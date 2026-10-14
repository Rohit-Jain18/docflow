"""
Docflow Device Activation and Credential Services.

Implements core domain operations per API_CONTRACTS.md §3, SECURITY.md §3,
and DATA_MODEL.md §2:
  - Cryptographically random, hashed activation code issuance with replacement revocation.
  - Atomic single-use activation exchange enforcing expiry, limits, eligibility, and credential issuance.
  - Signed device access token generation and cryptographic verification.
  - Atomic refresh credential rotation with token reuse detection and immediate credential revocation.
  - Safe audit recording without exposing raw codes or secret tokens.
"""

import datetime
import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional, Tuple

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone as tz_utils

from apps.audit.models import AuditAction, AuditEvent
from .models import (
    Device,
    DeviceActivationCode,
    DeviceRefreshCredential,
    DeviceStatus,
)

# ---------------------------------------------------------------------------
# Policy Constants
# ---------------------------------------------------------------------------

DEFAULT_ACTIVATION_CODE_LIFETIME = datetime.timedelta(minutes=10)
MIN_ACTIVATION_CODE_LIFETIME = datetime.timedelta(minutes=1)
MAX_ACTIVATION_CODE_LIFETIME = datetime.timedelta(hours=1)
MAX_ACTIVATION_ATTEMPTS = 5

DEVICE_ACCESS_TOKEN_LIFETIME = datetime.timedelta(minutes=10)
DEVICE_REFRESH_TOKEN_LIFETIME = datetime.timedelta(days=30)

ACCESS_TOKEN_SALT = "docflow.device.access_token"
ACCESS_TOKEN_PURPOSE = "device_access"
ACCESS_TOKEN_VERSION = 1


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class DeviceServiceError(Exception):
    """Base exception for all device service domain errors."""
    pass


class InvalidActivationCodeError(DeviceServiceError):
    """Raised when an activation code is unknown, empty, or malformed."""
    pass


class ActivationCodeExpiredError(DeviceServiceError):
    """Raised when an activation code has passed its expiration time."""
    pass


class ActivationCodeRevokedError(DeviceServiceError):
    """Raised when an activation code has been explicitly revoked."""
    pass


class ActivationCodeConsumedError(DeviceServiceError):
    """Raised when an activation code has already been consumed."""
    pass


class ActivationAttemptLimitError(DeviceServiceError):
    """Raised when an activation code's maximum attempt limit is exceeded."""
    pass


class IneligibleDeviceError(DeviceServiceError):
    """Raised when a device is ineligible for activation (e.g. revoked or disabled)."""
    pass


class InvalidRefreshTokenError(DeviceServiceError):
    """Raised when a refresh token is invalid, expired, revoked, or the device is inactive."""
    pass


class RefreshTokenReuseError(DeviceServiceError):
    """Raised when an already-rotated refresh token is submitted (token reuse / theft attempt)."""
    pass


# ---------------------------------------------------------------------------
# Result Data Structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IssuedActivationCode:
    raw_code: str
    code_record: DeviceActivationCode
    expires_at: datetime.datetime


@dataclass(frozen=True)
class ActivationResult:
    device: Device
    access_token: str
    access_token_expires_at: datetime.datetime
    refresh_token: str
    refresh_token_expires_at: datetime.datetime
    configuration_version: int = 1


@dataclass(frozen=True)
class RefreshResult:
    access_token: str
    access_token_expires_at: datetime.datetime
    refresh_token: str
    refresh_token_expires_at: datetime.datetime


# ---------------------------------------------------------------------------
# Cryptographic and Token Helpers
# ---------------------------------------------------------------------------

def generate_activation_code() -> str:
    """Generate a high-entropy, cryptographically random activation code."""
    return secrets.token_urlsafe(32)


def generate_refresh_secret() -> str:
    """Generate a high-entropy, cryptographically random refresh secret."""
    return secrets.token_urlsafe(48)


def hash_token(raw_token: str) -> str:
    """Return the SHA-256 hexadecimal digest of a raw token string."""
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


def generate_access_token(
    device: Device,
    lifetime: Optional[datetime.timedelta] = None,
) -> Tuple[str, datetime.datetime]:
    """
    Generate a signed, time-bounded device access token using Django's TimestampSigner.

    Contains device identity, organization, branch, token purpose, and version.
    Does not require external JWT libraries.
    """
    now = tz_utils.now()
    token_lifetime = lifetime or DEVICE_ACCESS_TOKEN_LIFETIME
    expires_at = now + token_lifetime

    payload = {
        "device_id": str(device.id),
        "organization_id": str(device.organization_id),
        "branch_id": str(device.branch_id),
        "purpose": ACCESS_TOKEN_PURPOSE,
        "version": ACCESS_TOKEN_VERSION,
        "exp": int(expires_at.timestamp()),
    }

    signer = signing.TimestampSigner(salt=ACCESS_TOKEN_SALT)
    token = signer.sign_object(payload)
    return token, expires_at


def verify_access_token(token: str) -> dict:
    """
    Cryptographically verify and unsign a device access token.

    Validates HMAC signature, token purpose, version, and expiration.
    Raises ValidationError on signature tampering or expired tokens.
    """
    if not token or not isinstance(token, str):
        raise ValidationError("Device access token must be a non-empty string.")

    signer = signing.TimestampSigner(salt=ACCESS_TOKEN_SALT)
    max_age_seconds = int(DEVICE_ACCESS_TOKEN_LIFETIME.total_seconds()) + 60  # 60s clock skew tolerance

    try:
        payload = signer.unsign_object(token, max_age=max_age_seconds)
    except signing.SignatureExpired:
        raise ValidationError("Device access token has expired.")
    except signing.BadSignature:
        raise ValidationError("Invalid device access token signature.")
    except Exception as exc:
        raise ValidationError(f"Malformed device access token: {exc}")

    if not isinstance(payload, dict):
        raise ValidationError("Invalid device access token payload format.")

    if payload.get("purpose") != ACCESS_TOKEN_PURPOSE:
        raise ValidationError("Invalid device access token purpose.")

    if payload.get("version") != ACCESS_TOKEN_VERSION:
        raise ValidationError("Unsupported device access token version.")

    exp = payload.get("exp")
    if exp is not None and tz_utils.now().timestamp() > exp:
        raise ValidationError("Device access token has expired.")

    return payload


# ---------------------------------------------------------------------------
# Service Operations
# ---------------------------------------------------------------------------

def issue_activation_code(
    device: Device,
    created_by=None,
    lifetime: Optional[datetime.timedelta] = None,
    request_id: str = "",
) -> IssuedActivationCode:
    """
    Issue a new cryptographically random activation code for a device.

    Enforces:
      - Device eligibility: device must not be revoked or disabled.
      - Bounded code lifetime (default 10 minutes, bounded between 1 min and 60 min).
      - Stores only the SHA-256 hash in code_hash; raw code is returned once to caller.
      - Revocation of any previous unused activation codes for the same device.
      - Safe audit logging without storing raw codes or sensitive material.
    """
    if device.status in (DeviceStatus.REVOKED, DeviceStatus.DISABLED):
        raise IneligibleDeviceError(
            f"Cannot issue activation code for device '{device.name}' in status '{device.status}'."
        )

    # Bound lifetime
    effective_lifetime = lifetime or DEFAULT_ACTIVATION_CODE_LIFETIME
    if effective_lifetime < MIN_ACTIVATION_CODE_LIFETIME:
        effective_lifetime = MIN_ACTIVATION_CODE_LIFETIME
    elif effective_lifetime > MAX_ACTIVATION_CODE_LIFETIME:
        effective_lifetime = MAX_ACTIVATION_CODE_LIFETIME

    raw_code = generate_activation_code()
    code_hash = hash_token(raw_code)
    now = tz_utils.now()
    expires_at = now + effective_lifetime

    with transaction.atomic():
        # Revoke previous unused codes for this device to prevent parallel active codes
        DeviceActivationCode.objects.filter(
            device=device,
            consumed_at__isnull=True,
            revoked_at__isnull=True,
        ).update(revoked_at=now)

        code_record = DeviceActivationCode.objects.create(
            organization=device.organization,
            branch=device.branch,
            device=device,
            created_by=created_by,
            code_hash=code_hash,
            expires_at=expires_at,
        )

        AuditEvent.objects.create(
            organization=device.organization,
            actor_user=created_by,
            action=AuditAction.DEVICE_ACTIVATION_CODE_ISSUED,
            target_type="device",
            target_id=str(device.id),
            request_id=request_id,
            safe_metadata={
                "device_name": device.name,
                "device_id": str(device.id),
                "branch_id": str(device.branch_id),
                "reason": "Activation code issued",
            },
        )

    return IssuedActivationCode(
        raw_code=raw_code,
        code_record=code_record,
        expires_at=expires_at,
    )


def exchange_activation_code(
    activation_code: str,
    installation_id: str,
    agent_version: str = "",
    platform: str = "windows",
    ip_address: Optional[str] = None,
    request_id: str = "",
) -> ActivationResult:
    """
    Atomically exchange a valid activation code for initial device credentials.

    Enforces:
      - Database-level locking (select_for_update) inside transaction.atomic.
      - Checks for code existence, expiration, revocation, prior consumption, and attempt limits.
      - Tracks attempt_count for failed attempts on identifiable codes.
      - Single-use code consumption and device transition to ACTIVE.
      - Generation of rotating refresh credential and signed access token.
      - installation_id treated strictly as untrusted metadata (never proof of identity).
      - Audit recording with zero raw secret/token leakage.
    """
    if not activation_code or not isinstance(activation_code, str):
        raise InvalidActivationCodeError("Activation code is required.")

    code_hash = hash_token(activation_code)
    now = tz_utils.now()

    failure_error = None
    result = None

    with transaction.atomic():
        code = (
            DeviceActivationCode.objects.select_for_update()
            .filter(code_hash=code_hash)
            .first()
        )

        if not code:
            AuditEvent.objects.create(
                organization=None,
                action=AuditAction.PLATFORM_SECURITY_FAILURE,
                target_type="device_activation",
                target_id="unknown",
                request_id=request_id,
                safe_metadata={
                    "error_code": "activation_code_not_found",
                    "failure_reason": "Activation attempt with unknown activation code",
                    "ip_address": ip_address or "unknown",
                },
            )
            failure_error = InvalidActivationCodeError("Invalid activation code.")
        elif code.attempt_count >= MAX_ACTIVATION_ATTEMPTS:
            code.attempt_count += 1
            if not code.revoked_at:
                code.revoked_at = now
            code.save(update_fields=["attempt_count", "revoked_at"])

            AuditEvent.objects.create(
                organization=code.organization,
                action=AuditAction.SECURITY_FAILURE,
                target_type="device",
                target_id=str(code.device_id),
                request_id=request_id,
                safe_metadata={
                    "device_id": str(code.device_id),
                    "branch_id": str(code.branch_id),
                    "attempt_count": code.attempt_count,
                    "error_code": "activation_attempt_limit_exceeded",
                    "failure_reason": "Activation code attempt limit exceeded",
                },
            )
            failure_error = ActivationAttemptLimitError("Activation code attempt limit exceeded.")
        elif code.is_revoked:
            code.attempt_count += 1
            code.save(update_fields=["attempt_count"])

            AuditEvent.objects.create(
                organization=code.organization,
                action=AuditAction.SECURITY_FAILURE,
                target_type="device",
                target_id=str(code.device_id),
                request_id=request_id,
                safe_metadata={
                    "device_id": str(code.device_id),
                    "branch_id": str(code.branch_id),
                    "attempt_count": code.attempt_count,
                    "error_code": "activation_code_revoked",
                    "failure_reason": "Attempt to use revoked activation code",
                },
            )
            failure_error = ActivationCodeRevokedError("Activation code has been revoked.")
        elif code.is_consumed:
            code.attempt_count += 1
            code.save(update_fields=["attempt_count"])

            AuditEvent.objects.create(
                organization=code.organization,
                action=AuditAction.SECURITY_FAILURE,
                target_type="device",
                target_id=str(code.device_id),
                request_id=request_id,
                safe_metadata={
                    "device_id": str(code.device_id),
                    "branch_id": str(code.branch_id),
                    "attempt_count": code.attempt_count,
                    "error_code": "activation_code_already_consumed",
                    "failure_reason": "Attempt to reuse already consumed activation code",
                },
            )
            failure_error = ActivationCodeConsumedError("Activation code has already been consumed.")
        elif code.is_expired:
            code.attempt_count += 1
            code.save(update_fields=["attempt_count"])

            AuditEvent.objects.create(
                organization=code.organization,
                action=AuditAction.SECURITY_FAILURE,
                target_type="device",
                target_id=str(code.device_id),
                request_id=request_id,
                safe_metadata={
                    "device_id": str(code.device_id),
                    "branch_id": str(code.branch_id),
                    "attempt_count": code.attempt_count,
                    "error_code": "activation_code_expired",
                    "failure_reason": "Attempt to use expired activation code",
                },
            )
            failure_error = ActivationCodeExpiredError("Activation code has expired.")
        else:
            # Code is valid and unconsumed. Acquire lock on associated device to verify eligibility
            device = Device.objects.select_for_update().get(id=code.device_id)
            if device.status in (DeviceStatus.REVOKED, DeviceStatus.DISABLED):
                code.attempt_count += 1
                code.save(update_fields=["attempt_count"])

                AuditEvent.objects.create(
                    organization=code.organization,
                    action=AuditAction.SECURITY_FAILURE,
                    target_type="device",
                    target_id=str(code.device_id),
                    request_id=request_id,
                    safe_metadata={
                        "device_id": str(code.device_id),
                        "branch_id": str(code.branch_id),
                        "attempt_count": code.attempt_count,
                        "error_code": "device_ineligible",
                        "failure_reason": f"Device in status '{device.status}' cannot be activated",
                    },
                )
                failure_error = IneligibleDeviceError(
                    f"Device '{device.name}' cannot be activated in status '{device.status}'."
                )
            else:
                # All locks held, all state verified under lock. Execute success mutations atomically:
                # 1. Consume code atomically
                code.consumed_at = now
                code.attempt_count += 1
                code.save(update_fields=["consumed_at", "attempt_count"])

                # 2. Activate device and record metadata
                device.status = DeviceStatus.ACTIVE
                device.activated_at = now
                device.last_seen_at = now
                if agent_version:
                    device.agent_version = agent_version
                if platform:
                    device.platform = platform
                if ip_address:
                    device.last_ip = ip_address
                device.save(
                    update_fields=[
                        "status",
                        "activated_at",
                        "last_seen_at",
                        "agent_version",
                        "platform",
                        "last_ip",
                        "updated_at",
                    ]
                )

                # 3. Clean up any existing active refresh credentials for this device
                DeviceRefreshCredential.objects.filter(
                    device=device,
                    revoked_at__isnull=True,
                ).update(revoked_at=now)

                # 4. Create initial refresh credential
                raw_refresh_token = generate_refresh_secret()
                refresh_hash = hash_token(raw_refresh_token)
                refresh_expires_at = now + DEVICE_REFRESH_TOKEN_LIFETIME

                DeviceRefreshCredential.objects.create(
                    device=device,
                    credential_hash=refresh_hash,
                    issued_at=now,
                    expires_at=refresh_expires_at,
                )

                # 5. Generate short-lived signed access token
                access_token, access_token_expires_at = generate_access_token(device)

                # 6. Audit successful activation
                AuditEvent.objects.create(
                    organization=device.organization,
                    actor_device=device,
                    action=AuditAction.DEVICE_ACTIVATED,
                    target_type="device",
                    target_id=str(device.id),
                    request_id=request_id,
                    safe_metadata={
                        "device_name": device.name,
                        "device_id": str(device.id),
                        "branch_id": str(device.branch_id),
                        "agent_version": device.agent_version or "unknown",
                        "platform": device.platform,
                        "status": "active",
                    },
                )

                result = ActivationResult(
                    device=device,
                    access_token=access_token,
                    access_token_expires_at=access_token_expires_at,
                    refresh_token=raw_refresh_token,
                    refresh_token_expires_at=refresh_expires_at,
                    configuration_version=1,
                )

    if failure_error:
        raise failure_error

    return result


def rotate_refresh_token(
    refresh_token: str,
    ip_address: Optional[str] = None,
    request_id: str = "",
) -> RefreshResult:
    """
    Atomically rotate an unexpired, unrevoked refresh token.

    Enforces:
      - Single transaction.atomic() for validation and rotation.
      - Database-level locking (select_for_update) on the refresh credential and device.
      - Detection of rotated token reuse: immediately revokes all outstanding
        refresh credentials for the device and logs TAMPERING_DETECTED.
      - Rejection of unknown, expired, or revoked tokens.
      - Rechecks state under lock: competing requests cannot independently rotate.
      - Creation of replacement credential linked via replaced_by.
      - Issuance of fresh signed access token.
      - Zero raw credential logging or metadata storage.
    """
    if not refresh_token or not isinstance(refresh_token, str):
        raise InvalidRefreshTokenError("Refresh token is required.")

    cred_hash = hash_token(refresh_token)
    now = tz_utils.now()

    failure_error = None
    result = None

    with transaction.atomic():
        cred = (
            DeviceRefreshCredential.objects.select_for_update()
            .filter(credential_hash=cred_hash)
            .first()
        )

        if not cred:
            AuditEvent.objects.create(
                organization=None,
                action=AuditAction.PLATFORM_SECURITY_FAILURE,
                target_type="device_refresh",
                target_id="unknown",
                request_id=request_id,
                safe_metadata={
                    "error_code": "refresh_credential_not_found",
                    "failure_reason": "Refresh attempt with unknown credential",
                    "ip_address": ip_address or "unknown",
                },
            )
            failure_error = InvalidRefreshTokenError("Invalid refresh credential.")
        elif cred.is_rotated:
            # Reuse detection: if this token has already been rotated, revoke all device credentials
            DeviceRefreshCredential.objects.filter(
                device=cred.device,
                revoked_at__isnull=True,
            ).update(revoked_at=now)

            AuditEvent.objects.create(
                organization=cred.device.organization,
                actor_device=cred.device,
                action=AuditAction.TAMPERING_DETECTED,
                target_type="device",
                target_id=str(cred.device_id),
                request_id=request_id,
                safe_metadata={
                    "device_name": cred.device.name,
                    "device_id": str(cred.device_id),
                    "branch_id": str(cred.device.branch_id),
                    "error_code": "refresh_token_reuse_detected",
                    "failure_reason": "Rotated refresh credential reuse detected; all credentials revoked",
                },
            )
            failure_error = RefreshTokenReuseError(
                "Rotated refresh token reuse detected. All active credentials have been revoked."
            )
        elif cred.is_revoked:
            AuditEvent.objects.create(
                organization=cred.device.organization,
                actor_device=cred.device,
                action=AuditAction.SECURITY_FAILURE,
                target_type="device",
                target_id=str(cred.device_id),
                request_id=request_id,
                safe_metadata={
                    "device_name": cred.device.name,
                    "device_id": str(cred.device_id),
                    "branch_id": str(cred.device.branch_id),
                    "error_code": "refresh_credential_revoked",
                    "failure_reason": "Attempt to use revoked refresh credential",
                },
            )
            failure_error = InvalidRefreshTokenError("Refresh credential has been revoked.")
        elif cred.is_expired:
            AuditEvent.objects.create(
                organization=cred.device.organization,
                actor_device=cred.device,
                action=AuditAction.SECURITY_FAILURE,
                target_type="device",
                target_id=str(cred.device_id),
                request_id=request_id,
                safe_metadata={
                    "device_name": cred.device.name,
                    "device_id": str(cred.device_id),
                    "branch_id": str(cred.device.branch_id),
                    "error_code": "refresh_credential_expired",
                    "failure_reason": "Attempt to use expired refresh credential",
                },
            )
            failure_error = InvalidRefreshTokenError("Refresh credential has expired.")
        else:
            device = Device.objects.select_for_update().get(id=cred.device_id)
            if device.status != DeviceStatus.ACTIVE:
                failure_error = InvalidRefreshTokenError(
                    f"Device '{device.name}' is in status '{device.status}' and cannot refresh credentials."
                )
            else:
                new_raw_refresh = generate_refresh_secret()
                new_hash = hash_token(new_raw_refresh)
                new_expires_at = now + DEVICE_REFRESH_TOKEN_LIFETIME

                new_cred = DeviceRefreshCredential.objects.create(
                    device=device,
                    credential_hash=new_hash,
                    issued_at=now,
                    expires_at=new_expires_at,
                )

                cred.rotated_at = now
                cred.replaced_by = new_cred
                cred.save(update_fields=["rotated_at", "replaced_by"])

                # Update device telemetry
                device.last_seen_at = now
                if ip_address:
                    device.last_ip = ip_address
                device.save(update_fields=["last_seen_at", "last_ip", "updated_at"])

                # Fresh signed access token
                access_token, access_token_expires_at = generate_access_token(device)

                result = RefreshResult(
                    access_token=access_token,
                    access_token_expires_at=access_token_expires_at,
                    refresh_token=new_raw_refresh,
                    refresh_token_expires_at=new_expires_at,
                )

    if failure_error:
        raise failure_error

    return result
