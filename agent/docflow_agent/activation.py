"""
Device Activation and Secure Credential Storage for Docflow Windows Agent.

Coordinates:
- One-time activation code exchange against POST /api/v1/agent/activation/exchange.
- Validation of backend response schema (device metadata, token lifespans, config version).
- Secure storage of the rotating refresh token in Windows Credential Manager / DPAPI.
- Holding the short-lived access token in process memory only.
- Safe persistence of non-secret device metadata in SQLite agent_settings.

Security Rules:
- NEVER persist access tokens or activation codes in SQLite, config files, or plaintext files.
- NEVER log activation codes, access tokens, refresh tokens, or raw response bodies.
- Fail closed on malformed response, missing fields, or credential-store failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import sys
import uuid
from typing import TYPE_CHECKING, Any

import docflow_agent
from docflow_agent.client import (
    ApiClient,
    ApiClientError,
    ApiConnectionError,
    ApiPayloadError,
    ApiResponseError,
    ApiTimeoutError,
)
from docflow_agent.credentials import CredentialStore, get_credential_store

if TYPE_CHECKING:
    from docflow_agent.queue import JobQueue

logger = logging.getLogger(__name__)

# Standard key for storing the rotating refresh credential in CredentialStore
REFRESH_TOKEN_KEY = "device_refresh_token"

# Endpoint per API_CONTRACTS.md §3 and §5
ACTIVATION_EXCHANGE_ENDPOINT = "/api/v1/agent/activation/exchange"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ActivationError(Exception):
    """Base exception for all activation failures."""

    def __init__(
        self,
        message: str,
        code: str = "activation_failed",
        request_id: str | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.request_id = request_id
        super().__init__(message)

    def __repr__(self) -> str:
        parts = [f"code={self.code!r}"]
        if self.request_id:
            parts.append(f"request_id={self.request_id!r}")
        return f"{self.__class__.__name__}({', '.join(parts)})"


class ActivationCodeExpiredError(ActivationError):
    """Raised when an activation code has expired, been revoked, or already consumed (HTTP 410)."""


class ActivationValidationError(ActivationError):
    """Raised when an activation request or response fails schema validation (HTTP 400)."""


class ActivationRateLimitedError(ActivationError):
    """Raised when activation requests are throttled (HTTP 429)."""


class ActivationStorageError(ActivationError):
    """Raised when storing credentials in secure storage fails."""


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DeviceInfo:
    """Safe, non-secret device metadata returned upon successful activation."""

    id: str
    name: str
    status: str
    branch_id: str


@dataclass(frozen=True)
class ActivationResult:
    """Result of a successful agent device activation.

    Contains in-memory access token and safe device metadata.
    The rotating refresh token is stored securely in the CredentialStore.
    """

    device: DeviceInfo
    access_token: str
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime
    configuration_version: int
    installation_id: str

    def __repr__(self) -> str:
        # Privacy-preserving representation: NEVER exposes access_token or secrets
        return (
            f"ActivationResult(device_id={self.device.id!r}, "
            f"branch_id={self.device.branch_id!r}, "
            f"status={self.device.status!r}, "
            f"configuration_version={self.configuration_version})"
        )


def _parse_utc_iso_timestamp(raw_val: Any, field_name: str) -> datetime:
    """Parse and validate an ISO 8601 UTC timestamp ending in 'Z'.

    Per docs/API_CONTRACTS.md §1 & §3:
    Rejects:
      - None, non-strings, or empty/whitespace strings
      - Naive timestamps without timezone
      - Non-UTC offset strings (e.g. +05:30, -04:00, or non-Z UTC offsets)
      - Malformed or invalid ISO 8601 timestamp representations
    Never echoes raw server-controlled values in exception messages.
    """
    if not isinstance(raw_val, str) or not raw_val.strip():
        raise ActivationValidationError(
            f"Field '{field_name}' is missing or empty.",
            code="missing_timestamp",
        )
    cleaned = raw_val.strip()
    if not cleaned.endswith("Z") or "T" not in cleaned:
        raise ActivationValidationError(
            f"Field '{field_name}' must be an ISO 8601 UTC timestamp ending in 'Z'.",
            code="invalid_timestamp",
        )
    try:
        dt = datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        raise ActivationValidationError(
            f"Field '{field_name}' is not a valid ISO 8601 timestamp.",
            code="invalid_timestamp",
        ) from None

    if dt.tzinfo is None or dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise ActivationValidationError(
            f"Field '{field_name}' must be a UTC timestamp.",
            code="invalid_timestamp",
        )
    return dt


# ---------------------------------------------------------------------------
# Activation Service
# ---------------------------------------------------------------------------

class ActivationService:
    """Coordinates device activation exchange and secure credential storage."""

    def __init__(
        self,
        client: ApiClient,
        *,
        credential_store: CredentialStore | None = None,
        queue: JobQueue | None = None,
        installation_id: str | None = None,
        agent_version: str | None = None,
        platform: str = "windows",
    ) -> None:
        self._client = client
        self._credential_store = credential_store or get_credential_store()
        self._queue = queue
        self._installation_id = installation_id
        self._agent_version = agent_version or docflow_agent.__version__
        self._platform = platform or "windows"

    @property
    def credential_store(self) -> CredentialStore:
        """Return the configured credential store."""
        return self._credential_store

    def is_activated(self) -> bool:
        """Check whether the agent currently has a stored refresh credential."""
        try:
            return self._credential_store.exists(REFRESH_TOKEN_KEY)
        except Exception:
            return False

    def get_or_create_installation_id(self) -> str:
        """Get an existing installation UUID or generate and persist a new one.

        Resolution order:
        1. Explicitly configured installation_id passed to constructor
        2. Persisted installation_id in queue's agent_settings
        3. Freshly generated UUID4 (persisted to queue if queue is available)
        """
        if self._installation_id:
            return self._installation_id

        if self._queue is not None:
            try:
                stored = self._queue.get_setting("installation_id")
                if stored and stored.strip():
                    self._installation_id = stored.strip()
                    return self._installation_id
            except Exception as exc:
                logger.debug("Failed to read installation_id from queue: %s", exc)

        new_id = str(uuid.uuid4())
        self._installation_id = new_id

        if self._queue is not None:
            try:
                self._queue.set_setting("installation_id", new_id)
            except Exception as exc:
                logger.debug("Failed to persist installation_id to queue: %s", exc)

        return new_id

    def activate(self, activation_code: str) -> ActivationResult:
        """Perform first-time activation using a one-time activation code.

        Args:
            activation_code: One-time raw activation code.

        Returns:
            ActivationResult containing in-memory access token and device metadata.

        Raises:
            ActivationCodeExpiredError: If code is expired, revoked, or already consumed.
            ActivationValidationError: If code is invalid or response fails schema validation.
            ActivationRateLimitedError: If activation requests are throttled.
            ActivationStorageError: If storing the refresh credential in secure storage fails.
            ActivationError: For other network, payload, or backend errors.
        """
        if not activation_code or not isinstance(activation_code, str) or not activation_code.strip():
            raise ActivationValidationError(
                "Activation code is required and cannot be empty.",
                code="validation_error",
            )

        cleaned_code = activation_code.strip()
        installation_id = self.get_or_create_installation_id()

        payload = {
            "activation_code": cleaned_code,
            "installation_id": installation_id,
            "agent_version": self._agent_version,
            "platform": self._platform,
        }

        logger.info(
            "Initiating device activation exchange (installation_id=%s, platform=%s)",
            installation_id,
            self._platform,
        )

        try:
            # Unauthenticated POST to /api/v1/agent/activation/exchange
            raw_response = self._client.post(
                ACTIVATION_EXCHANGE_ENDPOINT,
                json=payload,
                authenticated=False,
            )
        except ApiResponseError as exc:
            logger.warning("Activation request failed with HTTP error (code=%s)", exc.code)
            if exc.status_code == 410 or exc.code == "activation_expired":
                raise ActivationCodeExpiredError(
                    exc.detail or "The activation code has expired, been revoked, or already consumed.",
                    code="activation_expired",
                    request_id=exc.request_id,
                ) from exc
            if exc.status_code == 400 or exc.code == "validation_error":
                raise ActivationValidationError(
                    exc.detail or "Invalid activation code or request payload.",
                    code="validation_error",
                    request_id=exc.request_id,
                ) from exc
            if exc.status_code == 429 or exc.code == "rate_limited":
                raise ActivationRateLimitedError(
                    exc.detail or "Activation rate limit exceeded.",
                    code="rate_limited",
                    request_id=exc.request_id,
                ) from exc
            raise ActivationError(
                exc.detail or "Activation request failed.",
                code=exc.code or "activation_failed",
                request_id=exc.request_id,
            ) from exc
        except (ApiConnectionError, ApiTimeoutError, ApiPayloadError, ApiClientError) as exc:
            logger.warning("Activation request failed with network/client error")
            raise ActivationError(
                str(exc),
                code="network_error",
            ) from exc
        except Exception as exc:
            logger.warning("Activation request failed with unexpected error")
            raise ActivationError(
                "Unexpected failure during activation exchange.",
                code="unexpected_error",
            ) from exc

        # Validate response payload thoroughly before trusting or storing tokens
        validated = self._validate_response_payload(raw_response, installation_id=installation_id)

        # Store rotating refresh token in secure CredentialStore
        refresh_token = raw_response["refresh_token"]
        try:
            self._credential_store.store(REFRESH_TOKEN_KEY, refresh_token)
        except Exception as exc:
            logger.error("Failed to persist refresh token to secure credential store")
            raise ActivationStorageError(
                "Secure credential storage failed. Activation failed closed.",
                code="storage_error",
            ) from exc

        # Persist non-secret device metadata in queue settings if queue is available
        if self._queue is not None:
            self._persist_device_settings(validated)

        logger.info(
            "Device activation successful (device_id=%s, branch_id=%s, config_version=%s)",
            validated.device.id,
            validated.device.branch_id,
            validated.configuration_version,
        )

        return validated

    def _validate_response_payload(
        self,
        data: Any,
        *,
        installation_id: str,
    ) -> ActivationResult:
        """Validate all required fields and types in the activation exchange response."""
        if not isinstance(data, dict):
            raise ActivationValidationError(
                "Activation response was not a valid JSON object.",
                code="invalid_response_format",
            )

        # 1. Validate device object
        raw_device = data.get("device")
        if not isinstance(raw_device, dict):
            raise ActivationValidationError(
                "Activation response missing required 'device' object.",
                code="missing_device_metadata",
            )

        raw_device_id = raw_device.get("id")
        if not isinstance(raw_device_id, str) or not raw_device_id.strip():
            raise ActivationValidationError(
                "Device metadata missing valid 'id'.",
                code="invalid_device_id",
            )
        try:
            device_uuid = str(uuid.UUID(raw_device_id.strip()))
        except (ValueError, AttributeError):
            raise ActivationValidationError(
                "Device 'id' is not a valid UUID.",
                code="invalid_device_id",
            ) from None

        raw_device_name = raw_device.get("name")
        if not isinstance(raw_device_name, str) or not raw_device_name.strip():
            raise ActivationValidationError(
                "Device metadata missing valid 'name'.",
                code="invalid_device_name",
            )

        raw_status = raw_device.get("status")
        if raw_status != "active":
            raise ActivationValidationError(
                "Device status is invalid; expected 'active'.",
                code="device_not_active",
            )

        raw_branch_id = raw_device.get("branch_id")
        if not isinstance(raw_branch_id, str) or not raw_branch_id.strip():
            raise ActivationValidationError(
                "Device metadata missing valid 'branch_id'.",
                code="invalid_branch_id",
            )
        try:
            branch_uuid = str(uuid.UUID(raw_branch_id.strip()))
        except (ValueError, AttributeError):
            raise ActivationValidationError(
                "Device 'branch_id' is not a valid UUID.",
                code="invalid_branch_id",
            ) from None

        device_info = DeviceInfo(
            id=device_uuid,
            name=raw_device_name.strip(),
            status="active",
            branch_id=branch_uuid,
        )

        # 2. Validate access token
        access_token = data.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise ActivationValidationError(
                "Activation response missing valid 'access_token'.",
                code="missing_access_token",
            )

        access_expires_dt = _parse_utc_iso_timestamp(
            data.get("access_token_expires_at"),
            "access_token_expires_at",
        )

        # 3. Validate refresh token
        refresh_token = data.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            raise ActivationValidationError(
                "Activation response missing valid 'refresh_token'.",
                code="missing_refresh_token",
            )

        refresh_expires_dt = _parse_utc_iso_timestamp(
            data.get("refresh_token_expires_at"),
            "refresh_token_expires_at",
        )

        # 4. Validate configuration_version
        raw_config_ver = data.get("configuration_version")
        try:
            config_ver = int(raw_config_ver)
            if config_ver < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise ActivationValidationError(
                "Field 'configuration_version' must be a positive integer.",
                code="invalid_configuration_version",
            ) from None

        return ActivationResult(
            device=device_info,
            access_token=access_token.strip(),
            access_token_expires_at=access_expires_dt,
            refresh_token_expires_at=refresh_expires_dt,
            configuration_version=config_ver,
            installation_id=installation_id,
        )

    def _persist_device_settings(self, result: ActivationResult) -> None:
        """Persist non-secret device metadata into SQLite agent_settings."""
        if self._queue is None:
            return

        settings_to_store = {
            "device_id": result.device.id,
            "branch_id": result.device.branch_id,
            "device_name": result.device.name,
            "configuration_version": str(result.configuration_version),
            "installation_id": result.installation_id,
        }

        for k, v in settings_to_store.items():
            try:
                self._queue.set_setting(k, v)
            except Exception:
                logger.debug("Failed to store setting '%s' in queue", k)


# ---------------------------------------------------------------------------
# Convenience Function
# ---------------------------------------------------------------------------

def activate_device(
    client: ApiClient,
    activation_code: str,
    *,
    credential_store: CredentialStore | None = None,
    queue: JobQueue | None = None,
    installation_id: str | None = None,
    agent_version: str | None = None,
    platform: str = "windows",
) -> ActivationResult:
    """Convenience function to activate a device using an ApiClient."""
    service = ActivationService(
        client=client,
        credential_store=credential_store,
        queue=queue,
        installation_id=installation_id,
        agent_version=agent_version,
        platform=platform,
    )
    return service.activate(activation_code)
