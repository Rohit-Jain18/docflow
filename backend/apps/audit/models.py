"""
Docflow Audit and Webhook Receipt models.

Implements audit and callback idempotency abstractions per DATA_MODEL.md §5,
SECURITY.md §§ 2, 7, 8, and OPEN_QUESTIONS.md:
  - AuditEvent: Strict, append-only audit record foundation with strict
    metadata allowlisting, bounded scalar values, actor-device tenant consistency,
    and platform-level organization gating.
  - WebhookReceipt: Minimal provider-scoped duplicate suppression record
    with immutable event identity and safe processing-state lifecycle updates.
"""

import re
from typing import Any
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone as tz_utils

from apps.devices.models import Device
from apps.tenants.models import Organization

# ---------------------------------------------------------------------------
# Constants and Validation Helpers
# ---------------------------------------------------------------------------

KEY_SNAKE_CASE_REGEX = re.compile(r"^[a-z][a-z0-9_]*$")
E164_PHONE_REGEX = re.compile(r"^\+[1-9]\d{6,14}$")
MAX_METADATA_VALUE_LENGTH = 255
MAX_METADATA_KEYS = 30

FORBIDDEN_AUDIT_KEY_PATTERNS = {
    "token",
    "secret",
    "password",
    "credential",
    "auth",
    "bearer",
    "cookie",
    "session",
    "jwt",
    "payload",
    "rawpayload",
    "rawbody",
    "body",
    "pdf",
    "url",
    "link",
    "http",
    "patient",
    "patientname",
    "patientdata",
    "phone",
    "phonenumber",
}

ALLOWED_AUDIT_METADATA_KEYS = {
    "action_by",
    "agent_version",
    "attempt_count",
    "attempt_number",
    "branch_code",
    "branch_id",
    "config_key",
    "config_version",
    "device_id",
    "device_name",
    "display_name",
    "error_code",
    "error_message",
    "failure_reason",
    "ip_address",
    "new_value",
    "override_reason",
    "platform",
    "previous_attempt_number",
    "previous_role",
    "previous_status",
    "previous_value",
    "provider_key",
    "reason",
    "reason_code",
    "recipient_id",
    "report_id",
    "resend_reason",
    "role",
    "setting_name",
    "source",
    "status",
    "target_resource",
    "user_agent",
    "user_id",
    "verification_status",
}


def normalize_audit_key(key: str) -> str:
    """Normalize a key string by removing non-alphanumeric characters and converting to lowercase."""
    return re.sub(r"[^a-zA-Z0-9]", "", str(key)).lower()


def validate_safe_metadata(metadata: dict) -> None:
    """
    Validate that metadata contains only allowlisted keys with bounded, scalar values.

    Enforces defense-in-depth:
      - Dictionary structure with bounded key count.
      - Lowercase snake_case keys from strict allowlist.
      - Rejection of unknown keys, unsafe key variants, and forbidden key patterns.
      - Rejection of nested arbitrary objects (dict, list, tuple, set) and null values.
      - Value content inspection to prevent storing tokens, URLs, PDF contents,
        raw payloads, or raw patient data (phone numbers).
    """
    if metadata is None:
        return

    if not isinstance(metadata, dict):
        raise ValidationError({"safe_metadata": "safe_metadata must be a dictionary."})

    if len(metadata) > MAX_METADATA_KEYS:
        raise ValidationError(
            {"safe_metadata": f"safe_metadata exceeds maximum of {MAX_METADATA_KEYS} keys."}
        )

    for k, v in metadata.items():
        if not isinstance(k, str):
            raise ValidationError(
                {"safe_metadata": f"Metadata key '{k}' must be a string."}
            )

        # Reject unsafe key formats / variants (must be lowercase snake_case)
        if not KEY_SNAKE_CASE_REGEX.match(k):
            raise ValidationError(
                {
                    "safe_metadata": (
                        f"Unsafe key variant or invalid format '{k}' in safe_metadata. "
                        "Keys must be lowercase alphanumeric snake_case."
                    )
                }
            )

        # Allowlist check
        if k not in ALLOWED_AUDIT_METADATA_KEYS:
            raise ValidationError(
                {"safe_metadata": f"Unknown metadata key '{k}' is not permitted in safe_metadata."}
            )

        # Forbidden patterns check in normalized key (defense-in-depth)
        norm_k = normalize_audit_key(k)
        for pattern in FORBIDDEN_AUDIT_KEY_PATTERNS:
            if pattern in norm_k:
                raise ValidationError(
                    {
                        "safe_metadata": (
                            f"Forbidden key pattern '{pattern}' detected in metadata key '{k}'."
                        )
                    }
                )

        # Value must be scalar
        if v is None:
            raise ValidationError(
                {"safe_metadata": f"Null value in metadata field '{k}' is not permitted."}
            )

        if isinstance(v, (dict, list, tuple, set)):
            raise ValidationError(
                {
                    "safe_metadata": (
                        f"Arbitrary nested object in field '{k}' is not permitted in safe_metadata."
                    )
                }
            )

        if not isinstance(v, (str, int, float, bool)):
            raise ValidationError(
                {"safe_metadata": f"Value for field '{k}' must be a scalar (str, int, float, bool)."}
            )

        # String value checks
        if isinstance(v, str):
            if len(v) > MAX_METADATA_VALUE_LENGTH:
                raise ValidationError(
                    {
                        "safe_metadata": (
                            f"Value for field '{k}' exceeds maximum length of "
                            f"{MAX_METADATA_VALUE_LENGTH} characters."
                        )
                    }
                )

            # Never store PDF contents
            if "%PDF-" in v:
                raise ValidationError(
                    {"safe_metadata": f"PDF contents must never be stored in safe_metadata field '{k}'."}
                )

            # Never store public URLs
            v_lower = v.lower()
            if "http://" in v_lower or "https://" in v_lower:
                raise ValidationError(
                    {"safe_metadata": f"URLs must never be stored in safe_metadata field '{k}'."}
                )

            # Never store tokens
            if "bearer " in v_lower or "token " in v_lower or v.startswith("eyJ"):
                raise ValidationError(
                    {"safe_metadata": f"Tokens must never be stored in safe_metadata field '{k}'."}
                )

            # Never store raw provider payloads or serialized JSON structures
            v_stripped = v.strip()
            if (v_stripped.startswith("{") and v_stripped.endswith("}")) or (
                v_stripped.startswith("[") and v_stripped.endswith("]")
            ):
                raise ValidationError(
                    {
                        "safe_metadata": (
                            f"Raw payloads or serialized structures must never be stored in "
                            f"safe_metadata field '{k}'."
                        )
                    }
                )

            # Never store raw patient phone numbers
            if E164_PHONE_REGEX.match(v_stripped):
                raise ValidationError(
                    {
                        "safe_metadata": (
                            f"Raw patient phone numbers must never be stored in "
                            f"safe_metadata field '{k}'."
                        )
                    }
                )


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------

class AuditAction(models.TextChoices):
    # Device lifecycle
    DEVICE_ACTIVATION_CODE_ISSUED = (
        "device_activation_code_issued",
        "Device activation code issued",
    )
    DEVICE_ACTIVATED = "device_activated", "Device activated"
    DEVICE_REVOKED = "device_revoked", "Device revoked"
    DEVICE_DISABLED = "device_disabled", "Device disabled"

    # WhatsApp account lifecycle and dev verification override
    WHATSAPP_ACCOUNT_ASSIGNED = (
        "whatsapp_account_assigned",
        "WhatsApp account assigned",
    )
    WHATSAPP_ACCOUNT_UNASSIGNED = (
        "whatsapp_account_unassigned",
        "WhatsApp account unassigned",
    )
    WHATSAPP_ACCOUNT_DEV_VERIFICATION_OVERRIDE = (
        "whatsapp_account_dev_verification_override",
        "WhatsApp account dev verification override",
    )

    # Tenancy, roles, and configuration
    ROLE_ASSIGNED = "role_assigned", "Role assigned"
    ROLE_REVOKED = "role_revoked", "Role revoked"
    CONFIG_CHANGED = "config_changed", "Config changed"
    ORGANIZATION_CREATED = "organization_created", "Organization created"
    ORGANIZATION_STATUS_CHANGED = (
        "organization_status_changed",
        "Organization status changed",
    )

    # Delivery operations
    REPORT_RESENT = "report_resent", "Report resent"
    REPORT_QUARANTINE_RELEASED = (
        "report_quarantine_released",
        "Report quarantine released",
    )

    # Security failure and alert actions
    SECURITY_FAILURE = "security_failure", "Security failure"
    AUTHENTICATION_FAILED = "authentication_failed", "Authentication failed"
    ACCESS_DENIED = "access_denied", "Access denied"
    TAMPERING_DETECTED = "tampering_detected", "Tampering detected"

    # Explicit platform-level actions
    PLATFORM_CONFIG_CHANGED = "platform_config_changed", "Platform config changed"
    PLATFORM_ADMIN_ACCESS = "platform_admin_access", "Platform admin access"
    PLATFORM_SECURITY_FAILURE = (
        "platform_security_failure",
        "Platform security failure",
    )
    PLATFORM_MAINTENANCE = "platform_maintenance", "Platform maintenance"
    PLATFORM_SYSTEM_EVENT = "platform_system_event", "Platform system event"


PLATFORM_AUDIT_ACTIONS = {
    AuditAction.PLATFORM_CONFIG_CHANGED,
    AuditAction.PLATFORM_ADMIN_ACCESS,
    AuditAction.PLATFORM_SECURITY_FAILURE,
    AuditAction.PLATFORM_MAINTENANCE,
    AuditAction.PLATFORM_SYSTEM_EVENT,
}


class WebhookProcessingState(models.TextChoices):
    RECEIVED = "received", "Received"
    PROCESSED = "processed", "Processed"
    IGNORED = "ignored", "Ignored"
    DUPLICATE = "duplicate", "Duplicate"
    FAILED = "failed", "Failed"


# ---------------------------------------------------------------------------
# Custom QuerySet / Manager for Append-Only Audit Event
# ---------------------------------------------------------------------------

class AuditEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Audit records are immutable and cannot be updated.")

    def delete(self):
        raise ValidationError("Audit records cannot be deleted.")


class AuditEventManager(models.Manager):
    def get_queryset(self):
        return AuditEventQuerySet(self.model, using=self._db)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AuditEvent(models.Model):
    """
    Append-only audit record foundation for security-sensitive actions.

    Enforces:
      - Append-only immutability through model and QuerySet operations.
      - Strict actor-device tenant consistency.
      - Explicit platform-level gating for organization-less actions.
      - Strict allowlisted, bounded, scalar metadata.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization_id: uuid.UUID | None
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
        verbose_name="organization",
        help_text="Tenant boundary. Nullable only for explicit platform-level actions.",
    )
    actor_user_id: uuid.UUID | None
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
        verbose_name="actor user",
    )
    actor_device_id: uuid.UUID | None
    actor_device = models.ForeignKey(
        Device,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
        verbose_name="actor device",
    )
    action = models.CharField(
        max_length=100,
        choices=AuditAction.choices,
        verbose_name="action",
        db_index=True,
    )
    target_type = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="target type",
    )
    target_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="target ID",
    )
    request_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="request ID",
    )
    timestamp = models.DateTimeField(
        default=tz_utils.now,
        editable=False,
        db_index=True,
        verbose_name="timestamp",
    )
    safe_metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="safe metadata",
        help_text="Strictly allowlisted, bounded scalar metadata. Never store tokens, URLs, or patient data.",
    )

    objects = AuditEventManager()

    class Meta:
        db_table = "audit_event"
        verbose_name = "audit event"
        verbose_name_plural = "audit events"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["organization", "-timestamp"]),
            models.Index(fields=["action", "-timestamp"]),
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["request_id"]),
            models.Index(fields=["-timestamp"]),
        ]

    def __str__(self) -> str:
        org_label = self.organization.slug if self.organization else "platform"
        return f"AuditEvent {self.action} [{org_label}] at {self.timestamp}"

    def clean(self) -> None:
        """Enforce tenant rules, metadata security, and actor consistency."""
        super().clean()
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        errors: dict[str, Any] = {}

        # 1. Organization requirement: Nullable only for explicit platform-level actions
        is_platform_action = self.action in PLATFORM_AUDIT_ACTIONS
        if self.organization_id is None and not is_platform_action:
            errors["organization"] = (
                f"Organization is required for action '{self.action}'. "
                "Only explicit platform-level actions may omit organization."
            )

        # 2. Actor-device tenant consistency
        if self.actor_device_id:
            if self.organization_id is None:
                errors["actor_device"] = (
                    "A device cannot be the actor for a platform-level event without an organization."
                )
            else:
                device_org_id = (
                    Device.objects.filter(id=self.actor_device_id)
                    .values_list("organization_id", flat=True)
                    .first()
                )
                if device_org_id and device_org_id != self.organization_id:
                    errors["actor_device"] = (
                        "The actor device's organization must match the event organization."
                    )

        # 3. Validate safe metadata
        if self.safe_metadata is not None:
            try:
                validate_safe_metadata(self.safe_metadata)
            except ValidationError as e:
                errors.update(e.message_dict)

        # 4. Immutability check on existing instances
        if not self._state.adding and self.pk:
            if AuditEvent.objects.filter(pk=self.pk).exists():
                raise ValidationError("Audit records are immutable and append-only.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        """Enforce append-only semantics and validation on normal saves."""
        if not self._state.adding and self.pk:
            if AuditEvent.objects.filter(pk=self.pk).exists():
                raise ValidationError("Audit records are immutable and append-only.")

        self._validate_invariants()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Prohibit deletion of audit records."""
        raise ValidationError("Audit records cannot be deleted.")


class WebhookReceipt(models.Model):
    """
    Provider-scoped receipt for duplicate callback suppression.

    Preserves external event identity while allowing legitimate processing-state
    lifecycle updates. Does not store raw payloads, secrets, or signatures.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_key = models.CharField(
        max_length=50,
        default="kiziee",
        verbose_name="provider key",
        help_text="Normalized provider identifier.",
    )
    external_event_key = models.CharField(
        max_length=255,
        verbose_name="external event key",
        help_text="External provider event ID or stable compound key for duplicate suppression.",
    )
    received_at = models.DateTimeField(
        default=tz_utils.now,
        editable=False,
        verbose_name="received at",
    )
    processed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="processed at",
    )
    processing_state = models.CharField(
        max_length=30,
        choices=WebhookProcessingState.choices,
        default=WebhookProcessingState.RECEIVED,
        verbose_name="processing state",
    )
    safe_error_code = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="safe error code",
        help_text="Normalized non-sensitive error code if processing failed.",
    )

    class Meta:
        db_table = "audit_webhook_receipt"
        verbose_name = "webhook receipt"
        verbose_name_plural = "webhook receipts"
        ordering = ["-received_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider_key", "external_event_key"],
                name="unique_webhook_receipt_provider_event",
            ),
        ]
        indexes = [
            models.Index(fields=["processing_state", "received_at"]),
            models.Index(fields=["provider_key", "processing_state"]),
            models.Index(fields=["-received_at"]),
        ]

    def __str__(self) -> str:
        return (
            f"WebhookReceipt [{self.provider_key}:{self.external_event_key}] "
            f"state={self.processing_state}"
        )

    def clean(self) -> None:
        """Validate receipt fields and enforce event identity immutability."""
        super().clean()
        self._validate_receipt()

    def _validate_receipt(self) -> None:
        errors = {}

        if not self.provider_key or not self.provider_key.strip():
            errors["provider_key"] = "Provider key cannot be blank."

        if not self.external_event_key or not self.external_event_key.strip():
            errors["external_event_key"] = "External event key cannot be blank."

        # Keep provider event identity immutable after creation
        if not self._state.adding and self.pk:
            original = (
                WebhookReceipt.objects.filter(pk=self.pk)
                .values("provider_key", "external_event_key", "received_at")
                .first()
            )
            if original:
                if original["provider_key"] != self.provider_key:
                    errors["provider_key"] = (
                        "The provider key of a persisted webhook receipt cannot be changed."
                    )
                if original["external_event_key"] != self.external_event_key:
                    errors["external_event_key"] = (
                        "The external event key of a persisted webhook receipt cannot be changed."
                    )
                if original["received_at"] != self.received_at:
                    errors["received_at"] = (
                        "The received_at timestamp of a persisted webhook receipt cannot be changed."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        """Enforce receipt validation and immutability on saves."""
        update_fields = kwargs.get("update_fields")
        if update_fields is None:
            self._validate_receipt()
        else:
            checked = {"provider_key", "external_event_key", "received_at"}
            if checked.intersection(update_fields):
                self._validate_receipt()

        super().save(*args, **kwargs)
