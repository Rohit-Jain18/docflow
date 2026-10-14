"""
Docflow Report and Delivery models.

Implements report domain abstractions per DATA_MODEL.md §§ 4 and 6,
DELIVERY_STATE_MACHINE.md, and API_CONTRACTS.md:
  - Report: Core diagnostic report record with idempotency and canonical fingerprinting.
  - MediaReference: Ephemeral or provider-backed media locator (never stores PDF bytes).
  - DeliveryAttempt: Discrete external dispatch attempt history.
  - DeliveryEvent: Granular audit trail for delivery progression and provider callbacks.
  - DispatchOutbox: Transactionally safe queue table for reliable message dispatch.

Enforces:
  - Strict tenant consistency across all relationship paths.
  - Idempotency key and versioned canonical fingerprint uniqueness.
  - Media expiry requirements and protection of encrypted reference payloads.
  - Immutability of persisted identity relationships and attempt numbering.
"""

import hashlib
import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone as tz_utils

from apps.devices.models import Device
from apps.tenants.models import Branch, Lab, Organization
from apps.whatsapp.models import BranchWhatsAppAssignment


HEX_64_REGEX = re.compile(r"^[0-9a-f]{64}$")
E164_REGEX = re.compile(r"^\+[1-9]\d{6,14}$")
FORBIDDEN_PAYLOAD_KEYS = {
    "raw_payload",
    "payload",
    "access_token",
    "token",
    "secret",
    "authorization",
    "password",
}


class ReportStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    UPLOADED = "uploaded", "Document prepared"
    ACCEPTED = "accepted", "Accepted by WhatsApp platform"
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    READ = "read", "Read"
    FAILED = "failed", "Failed"
    QUARANTINED = "quarantined", "Needs review"
    RECONCILIATION_REQUIRED = (
        "reconciliation_required",
        "Checking send status — do not resend yet",
    )


class DocumentType(models.TextChoices):
    DIAGNOSTIC_REPORT = "diagnostic_report", "Diagnostic Report"


class MediaKind(models.TextChoices):
    DEVELOPMENT_DOWNLOAD_URL = (
        "development_download_url",
        "Development Download URL",
    )
    PROVIDER_MEDIA_ID = "provider_media_id", "Provider Media ID"
    PROVIDER_UPLOAD_REFERENCE = (
        "provider_upload_reference",
        "Provider Upload Reference",
    )


class ErrorCategory(models.TextChoices):
    TRANSIENT = "transient", "Transient"
    PERMANENT = "permanent", "Permanent"
    AMBIGUOUS = "ambiguous", "Ambiguous"
    CONFIGURATION = "configuration", "Configuration"


class EventSource(models.TextChoices):
    AGENT = "agent", "Agent"
    DOCFLOW = "docflow", "Docflow"
    PLATFORM = "platform", "Platform"
    META = "meta", "Meta"
    ADMIN = "admin", "Admin"


class OutboxState(models.TextChoices):
    PENDING = "pending", "Pending"
    CLAIMED = "claimed", "Claimed"
    COMPLETED = "completed", "Completed"
    RETRY_WAIT = "retry_wait", "Retry Wait"
    DEAD_LETTER = "dead_letter", "Dead Letter"


class Report(models.Model):
    """
    Diagnostic report record registered by an authenticated agent or system service.

    Uniquely identified within an organization by idempotency_key and canonical fingerprint.
    Stores metadata only — PDF bytes are never stored in Django or PostgreSQL.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="reports",
        verbose_name="organization",
    )
    lab = models.ForeignKey(
        Lab,
        on_delete=models.CASCADE,
        related_name="reports",
        verbose_name="lab",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="reports",
        verbose_name="branch",
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name="device",
    )
    branch_assignment = models.ForeignKey(
        BranchWhatsAppAssignment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name="branch WhatsApp assignment",
    )
    recipient_phone_e164 = models.CharField(
        max_length=32,
        verbose_name="recipient phone (E.164)",
        help_text="Recipient phone number in E.164 format (e.g. +919876543210).",
    )
    source_file_label = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="source file label",
        help_text="Opaque client tracking label without phone numbers or patient PII.",
    )
    document_type = models.CharField(
        max_length=50,
        choices=DocumentType.choices,
        default=DocumentType.DIAGNOSTIC_REPORT,
        verbose_name="document type",
    )
    content_sha256 = models.CharField(
        max_length=64,
        verbose_name="content SHA-256",
        help_text="64-character lowercase hex digest of PDF content.",
    )
    file_size_bytes = models.PositiveBigIntegerField(
        verbose_name="file size in bytes",
    )
    idempotency_key = models.CharField(
        max_length=64,
        verbose_name="idempotency key",
        help_text="Agent-provided 64-character lowercase hex idempotency key.",
    )
    fingerprint = models.CharField(
        max_length=64,
        verbose_name="canonical fingerprint",
        help_text="Versioned canonical SHA-256 fingerprint: sha256('v1|branch_id|phone|content_sha256').",
    )
    status = models.CharField(
        max_length=30,
        choices=ReportStatus.choices,
        default=ReportStatus.QUEUED,
        verbose_name="status",
    )
    accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="accepted at",
    )
    delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="delivered at",
    )
    read_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="read at",
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="expires at",
    )
    quarantined_reason_code = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="quarantined reason code",
    )
    created_at = models.DateTimeField(default=tz_utils.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reports_report"
        verbose_name = "report"
        verbose_name_plural = "reports"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="unique_organization_report_idempotency_key",
            ),
            models.UniqueConstraint(
                fields=["organization", "fingerprint"],
                name="unique_organization_report_fingerprint",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "created_at"]),
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["branch", "status"]),
            models.Index(fields=["device", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Report {self.id} ({self.status})"

    @classmethod
    def compute_canonical_fingerprint(
        cls,
        branch_id: uuid.UUID | str,
        recipient_phone_e164: str,
        content_sha256: str,
    ) -> str:
        """
        Compute the versioned canonical fingerprint for a report request:
        sha256("v1|" + branch_id + "|" + recipient_phone_e164 + "|" + content_sha256)
        """
        canonical_str = f"v1|{branch_id}|{recipient_phone_e164}|{content_sha256}"
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def clean(self) -> None:
        """Perform comprehensive model validation."""
        super().clean()
        self._validate_field_formats()
        self._validate_immutability()
        self._validate_tenant_consistency()

    def _validate_field_formats(self) -> None:
        """Validate format requirements for keys, digests, and PII minimization."""
        errors = {}

        if self.idempotency_key:
            if not HEX_64_REGEX.match(self.idempotency_key):
                errors["idempotency_key"] = (
                    "Idempotency key must be a 64-character lowercase hex string."
                )

        if self.content_sha256:
            if not HEX_64_REGEX.match(self.content_sha256):
                errors["content_sha256"] = (
                    "Content SHA-256 must be a 64-character lowercase hex string."
                )

        if self.recipient_phone_e164:
            if not E164_REGEX.match(self.recipient_phone_e164):
                errors["recipient_phone_e164"] = (
                    "Recipient phone number must be in E.164 format (e.g. +919876543210)."
                )

        # Enforce data minimization: source_file_label must not leak raw phone numbers
        if self.source_file_label and self.recipient_phone_e164:
            phone_digits = self.recipient_phone_e164.lstrip("+")
            national_digits = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
            if (phone_digits in self.source_file_label) or (
                len(national_digits) >= 8 and national_digits in self.source_file_label
            ):
                errors["source_file_label"] = (
                    "Source file label must be opaque and must not contain the recipient phone number."
                )


        # Compute or validate fingerprint against canonical formula
        if self.branch_id and self.recipient_phone_e164 and self.content_sha256:
            expected_fp = self.compute_canonical_fingerprint(
                self.branch_id, self.recipient_phone_e164, self.content_sha256
            )
            if not self.fingerprint:
                self.fingerprint = expected_fp
            elif self.fingerprint != expected_fp:
                errors["fingerprint"] = (
                    f"Fingerprint does not match the canonical calculation. Expected {expected_fp}."
                )

        if errors:
            raise ValidationError(errors)

    def _validate_immutability(self) -> None:
        """Ensure persisted identity relationships and cryptographic keys cannot be altered."""
        if not self._state.adding and self.pk:
            original = (
                Report.objects.filter(pk=self.pk)
                .values(
                    "organization_id",
                    "lab_id",
                    "branch_id",
                    "idempotency_key",
                    "fingerprint",
                    "branch_assignment_id",
                )
                .first()
            )
            if original:
                errors = {}
                if original["organization_id"] != self.organization_id:
                    errors["organization"] = (
                        "The organization of a persisted report cannot be changed."
                    )
                if original["lab_id"] != self.lab_id:
                    errors["lab"] = (
                        "The lab of a persisted report cannot be changed."
                    )
                if original["branch_id"] != self.branch_id:
                    errors["branch"] = (
                        "The branch of a persisted report cannot be changed."
                    )
                if original["idempotency_key"] != self.idempotency_key:
                    errors["idempotency_key"] = (
                        "The idempotency key of a persisted report cannot be changed."
                    )
                if original["fingerprint"] != self.fingerprint:
                    errors["fingerprint"] = (
                        "The fingerprint of a persisted report cannot be changed."
                    )
                if (
                    original["branch_assignment_id"] is not None
                    and original["branch_assignment_id"] != self.branch_assignment_id
                ):
                    errors["branch_assignment"] = (
                        "The historical branch assignment of a persisted report cannot be changed."
                    )

                if errors:
                    raise ValidationError(errors)

    def _validate_tenant_consistency(self) -> None:
        """Ensure all referenced records belong to the same organization and branch hierarchy."""
        errors = {}

        # Branch must belong to report's organization and parent lab
        if self.branch_id:
            branch_data = (
                Branch.objects.filter(id=self.branch_id)
                .values("organization_id", "lab_id")
                .first()
            )
            if branch_data:
                if self.organization_id and branch_data["organization_id"] != self.organization_id:
                    errors["branch"] = "The report branch must belong to the report organization."
                if self.lab_id and branch_data["lab_id"] != self.lab_id:
                    errors["lab"] = "The report lab must match the branch's parent lab."

        # Device must match report's branch and organization
        if self.device_id:
            device_data = (
                Device.objects.filter(id=self.device_id)
                .values("organization_id", "branch_id")
                .first()
            )
            if device_data:
                if self.organization_id and device_data["organization_id"] != self.organization_id:
                    errors["device"] = "The device must belong to the report organization."
                if self.branch_id and device_data["branch_id"] != self.branch_id:
                    errors["device"] = "The device must belong to the report branch."

        # BranchWhatsAppAssignment must match report's branch and organization
        if self.branch_assignment_id:
            assignment_data = (
                BranchWhatsAppAssignment.objects.filter(id=self.branch_assignment_id)
                .values("organization_id", "branch_id")
                .first()
            )
            if assignment_data:
                if self.organization_id and assignment_data["organization_id"] != self.organization_id:
                    errors["branch_assignment"] = (
                        "The branch assignment must belong to the report organization."
                    )
                if self.branch_id and assignment_data["branch_id"] != self.branch_id:
                    errors["branch_assignment"] = (
                        "The branch assignment must belong to the report branch."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        """Enforce validation and canonical fingerprint calculation on normal saves."""
        if self.branch_id and self.recipient_phone_e164 and self.content_sha256 and not self.fingerprint:
            self.fingerprint = self.compute_canonical_fingerprint(
                self.branch_id, self.recipient_phone_e164, self.content_sha256
            )

        update_fields = kwargs.get("update_fields")
        if update_fields is None:
            self._validate_field_formats()
            self._validate_immutability()
            self._validate_tenant_consistency()
        else:
            checked_fields = {
                "organization",
                "organization_id",
                "lab",
                "lab_id",
                "branch",
                "branch_id",
                "device",
                "device_id",
                "branch_assignment",
                "branch_assignment_id",
                "recipient_phone_e164",
                "content_sha256",
                "idempotency_key",
                "fingerprint",
                "source_file_label",
            }
            if checked_fields.intersection(update_fields):
                self._validate_field_formats()
                self._validate_immutability()
                self._validate_tenant_consistency()

        super().save(*args, **kwargs)


class MediaReference(models.Model):
    """
    Ephemeral or provider-managed reference to a report's media file.

    PDF bytes are never stored in Django or PostgreSQL.
    Temporary development download URLs require an explicit expires_at timestamp
    and are restricted to allowlisted hosts in development environments only.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name="media_references",
        verbose_name="report",
    )
    kind = models.CharField(
        max_length=40,
        choices=MediaKind.choices,
        verbose_name="kind",
    )
    encrypted_reference = models.TextField(
        blank=True,
        default="",
        verbose_name="encrypted reference",
        help_text="Protected/encrypted ciphertext for provider references. Never store plaintext temporary URLs here.",
    )
    download_url = models.CharField(
        max_length=1000,
        blank=True,
        default="",
        verbose_name="download URL",
        help_text="Direct binary download URL for development_download_url kind only.",
    )
    provider_media_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="provider media ID",
        help_text="Optional opaque provider media ID reference.",
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="expires at",
        help_text="Mandatory expiration timestamp for temporary media.",
    )
    created_at = models.DateTimeField(default=tz_utils.now, editable=False)
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="deleted at",
    )

    class Meta:
        db_table = "reports_media_reference"
        verbose_name = "media reference"
        verbose_name_plural = "media references"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["report", "kind"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"MediaReference ({self.kind}) for Report {self.report_id}"

    def clean(self) -> None:
        """Validate media reference integrity, expiry rules, and security constraints."""
        super().clean()
        self._validate_media_reference()

    def _validate_media_reference(self) -> None:
        errors = {}

        # Rule: Never store PDF bytes in reference fields
        for field_name in ("encrypted_reference", "download_url", "provider_media_id"):
            val = getattr(self, field_name, "")
            if val and val.startswith("%PDF-"):
                errors[field_name] = "PDF bytes must never be stored in media reference records."

        # Rule: Do not store plaintext URLs in encrypted_reference
        if self.encrypted_reference:
            cleaned_ref = self.encrypted_reference.strip().lower()
            if cleaned_ref.startswith("http://") or cleaned_ref.startswith("https://"):
                errors["encrypted_reference"] = (
                    "Plaintext temporary URLs must not be stored in encrypted_reference."
                )

        # Temporary development media validation
        if self.kind == MediaKind.DEVELOPMENT_DOWNLOAD_URL:
            # 1. Explicit expiration is mandatory for temporary media
            if not self.expires_at:
                errors["expires_at"] = (
                    "Temporary media must have an explicit expiration timestamp."
                )

            # 2. Check development mode permissions
            temp_upload_mode = getattr(settings, "TEMP_UPLOAD_MODE", "disabled")
            if temp_upload_mode == "disabled":
                errors["kind"] = (
                    "development_download_url is prohibited when TEMP_UPLOAD_MODE is disabled."
                )

            # 3. Direct download binary URL validation
            if not self.download_url:
                errors["download_url"] = (
                    "A download URL is required for development download URLs."
                )
            else:
                expected_host = getattr(settings, "TEMP_UPLOAD_EXPECTED_HOST", "tmpfiles.org")
                expected_prefix = f"https://{expected_host}/dl/"
                if not self.download_url.startswith(expected_prefix):
                    errors["download_url"] = (
                        f"URL must be a direct binary download URL ({expected_prefix}...); "
                        f"HTML landing pages and untrusted hosts are prohibited."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        """Enforce validation rules on normal saves."""
        update_fields = kwargs.get("update_fields")
        if update_fields is None:
            self._validate_media_reference()
        else:
            checked = {
                "kind",
                "encrypted_reference",
                "download_url",
                "provider_media_id",
                "expires_at",
            }
            if checked.intersection(update_fields):
                self._validate_media_reference()

        super().save(*args, **kwargs)


class DeliveryAttempt(models.Model):
    """
    Individual external dispatch attempt for a report.

    Preserves full delivery history across resends.
    Unique constraint on (report, attempt_number) prevents attempt collision.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="delivery_attempts",
        verbose_name="organization",
    )
    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name="delivery_attempts",
        verbose_name="report",
    )
    attempt_number = models.PositiveIntegerField(
        verbose_name="attempt number",
    )
    status = models.CharField(
        max_length=30,
        choices=ReportStatus.choices,
        default=ReportStatus.QUEUED,
        verbose_name="status",
    )
    provider_key = models.CharField(
        max_length=50,
        default="kiziee",
        verbose_name="provider key",
    )
    provider_message_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="provider message ID",
        help_text="Upstream WhatsApp/provider message identifier (e.g. wamid).",
    )
    provider_request_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="provider request ID",
    )
    request_started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="request started at",
    )
    accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="accepted at",
    )
    finished_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="finished at",
    )
    error_code = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="error code",
    )
    error_category = models.CharField(
        max_length=30,
        blank=True,
        default="",
        choices=ErrorCategory.choices,
        verbose_name="error category",
    )
    retry_after = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="retry after",
    )
    created_at = models.DateTimeField(default=tz_utils.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reports_delivery_attempt"
        verbose_name = "delivery attempt"
        verbose_name_plural = "delivery attempts"
        ordering = ["report", "attempt_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["report", "attempt_number"],
                name="unique_report_attempt_number",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["report", "-attempt_number"]),
            models.Index(fields=["provider_key", "provider_message_id"]),
            models.Index(fields=["provider_message_id"]),
        ]

    def __str__(self) -> str:
        return f"Attempt {self.attempt_number} for Report {self.report_id} ({self.status})"

    def clean(self) -> None:
        """Validate attempt invariants and tenant consistency."""
        super().clean()
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        errors = {}

        if self.attempt_number < 1:
            errors["attempt_number"] = "Attempt number must be a positive integer starting at 1."

        # Tenant consistency: organization must match report's organization
        if self.report_id and self.organization_id:
            report_org_id = (
                Report.objects.filter(id=self.report_id)
                .values_list("organization_id", flat=True)
                .first()
            )
            if report_org_id and report_org_id != self.organization_id:
                errors["organization"] = "The attempt organization must match the report organization."

        # Immutability on persisted instances
        if not self._state.adding and self.pk:
            original = (
                DeliveryAttempt.objects.filter(pk=self.pk)
                .values("organization_id", "report_id", "attempt_number")
                .first()
            )
            if original:
                if original["organization_id"] != self.organization_id:
                    errors["organization"] = "The organization of a persisted attempt cannot be changed."
                if original["report_id"] != self.report_id:
                    errors["report"] = "The report of a persisted attempt cannot be changed."
                if original["attempt_number"] != self.attempt_number:
                    errors["attempt_number"] = (
                        "The attempt number of a persisted attempt cannot be changed."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        """Enforce invariants on normal saves."""
        update_fields = kwargs.get("update_fields")
        if update_fields is None:
            self._validate_invariants()
        else:
            checked = {
                "organization",
                "organization_id",
                "report",
                "report_id",
                "attempt_number",
            }
            if checked.intersection(update_fields):
                self._validate_invariants()

        super().save(*args, **kwargs)


class DeliveryEvent(models.Model):
    """
    Audit and lifecycle timeline event for report delivery.

    Captures status transitions, provider acknowledgements, and error signals.
    Raw webhook payloads are strictly prohibited.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="delivery_events",
        verbose_name="organization",
    )
    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name="delivery_events",
        verbose_name="report",
    )
    delivery_attempt = models.ForeignKey(
        DeliveryAttempt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delivery_events",
        verbose_name="delivery attempt",
    )
    event_type = models.CharField(
        max_length=50,
        verbose_name="event type",
    )
    source = models.CharField(
        max_length=30,
        choices=EventSource.choices,
        verbose_name="source",
    )
    provider_event_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="provider event ID",
    )
    provider_timestamp = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="provider timestamp",
    )
    received_at = models.DateTimeField(
        default=tz_utils.now,
        verbose_name="received at",
    )
    safe_payload_summary = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="safe payload summary",
        help_text="Allowlisted redacted summary. Never persist raw webhook payloads or secrets.",
    )
    error_code = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="error code",
    )
    created_at = models.DateTimeField(default=tz_utils.now, editable=False)

    class Meta:
        db_table = "reports_delivery_event"
        verbose_name = "delivery event"
        verbose_name_plural = "delivery events"
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["organization", "event_type"]),
            models.Index(fields=["report", "-received_at"]),
            models.Index(fields=["provider_event_id"]),
        ]

    def __str__(self) -> str:
        return f"Event {self.event_type} ({self.source}) for Report {self.report_id}"

    def clean(self) -> None:
        """Validate tenant consistency and payload security."""
        super().clean()
        self._validate_event()

    def _validate_event(self) -> None:
        errors = {}

        # Tenant consistency: organization must match report organization
        if self.report_id and self.organization_id:
            report_org_id = (
                Report.objects.filter(id=self.report_id)
                .values_list("organization_id", flat=True)
                .first()
            )
            if report_org_id and report_org_id != self.organization_id:
                errors["organization"] = "The event organization must match the report organization."

        # DeliveryAttempt consistency: must belong to the same report and organization
        if self.delivery_attempt_id:
            attempt_data = (
                DeliveryAttempt.objects.filter(id=self.delivery_attempt_id)
                .values("organization_id", "report_id")
                .first()
            )
            if attempt_data:
                if self.organization_id and attempt_data["organization_id"] != self.organization_id:
                    errors["delivery_attempt"] = (
                        "The delivery attempt must belong to the event organization."
                    )
                if self.report_id and attempt_data["report_id"] != self.report_id:
                    errors["delivery_attempt"] = (
                        "The delivery attempt must belong to the event report."
                    )

        # Payload security: ensure safe_payload_summary is a dict and free of raw payloads/secrets
        if self.safe_payload_summary:
            if not isinstance(self.safe_payload_summary, dict):
                errors["safe_payload_summary"] = "safe_payload_summary must be a dictionary."
            else:
                for k in self.safe_payload_summary.keys():
                    if str(k).lower() in FORBIDDEN_PAYLOAD_KEYS:
                        errors["safe_payload_summary"] = (
                            "Raw webhook payloads or secret credentials must not be stored in safe_payload_summary."
                        )
                        break

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        """Enforce validation on normal saves."""
        update_fields = kwargs.get("update_fields")
        if update_fields is None:
            self._validate_event()
        else:
            checked = {
                "organization",
                "organization_id",
                "report",
                "report_id",
                "delivery_attempt",
                "delivery_attempt_id",
                "safe_payload_summary",
            }
            if checked.intersection(update_fields):
                self._validate_event()

        super().save(*args, **kwargs)


class DispatchOutbox(models.Model):
    """
    Durable dispatch queue item for reliable external delivery.

    Enables reliable outbox dispatch pattern without making Redis or Celery
    the single source of truth.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="outbox_items",
        verbose_name="organization",
    )
    report = models.ForeignKey(
        Report,
        on_delete=models.CASCADE,
        related_name="outbox_items",
        verbose_name="report",
    )
    delivery_attempt = models.ForeignKey(
        DeliveryAttempt,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="outbox_items",
        verbose_name="delivery attempt",
    )
    event_type = models.CharField(
        max_length=50,
        default="send_message",
        verbose_name="event type",
    )
    state = models.CharField(
        max_length=30,
        choices=OutboxState.choices,
        default=OutboxState.PENDING,
        verbose_name="state",
    )
    available_at = models.DateTimeField(
        default=tz_utils.now,
        verbose_name="available at",
    )
    claimed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="claimed at",
    )
    claim_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="claim expires at",
    )
    attempt_count = models.PositiveIntegerField(
        default=0,
        verbose_name="attempt count",
    )
    last_error_code = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="last error code",
    )
    created_at = models.DateTimeField(default=tz_utils.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reports_dispatch_outbox"
        verbose_name = "dispatch outbox item"
        verbose_name_plural = "dispatch outbox items"
        ordering = ["available_at"]
        indexes = [
            models.Index(fields=["state", "available_at"]),
            models.Index(fields=["organization", "state"]),
            models.Index(fields=["report", "state"]),
        ]

    def __str__(self) -> str:
        return f"Outbox {self.id} for Report {self.report_id} ({self.state})"

    def clean(self) -> None:
        """Validate outbox invariants and tenant consistency."""
        super().clean()
        self._validate_outbox()

    def _validate_outbox(self) -> None:
        errors = {}

        # Tenant consistency: organization must match report organization
        if self.report_id and self.organization_id:
            report_org_id = (
                Report.objects.filter(id=self.report_id)
                .values_list("organization_id", flat=True)
                .first()
            )
            if report_org_id and report_org_id != self.organization_id:
                errors["organization"] = "The outbox organization must match the report organization."

        # DeliveryAttempt consistency: must belong to the same report and organization
        if self.delivery_attempt_id:
            attempt_data = (
                DeliveryAttempt.objects.filter(id=self.delivery_attempt_id)
                .values("organization_id", "report_id")
                .first()
            )
            if attempt_data:
                if self.organization_id and attempt_data["organization_id"] != self.organization_id:
                    errors["delivery_attempt"] = (
                        "The delivery attempt must belong to the outbox organization."
                    )
                if self.report_id and attempt_data["report_id"] != self.report_id:
                    errors["delivery_attempt"] = (
                        "The delivery attempt must belong to the outbox report."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        """Enforce validation on normal saves."""
        update_fields = kwargs.get("update_fields")
        if update_fields is None:
            self._validate_outbox()
        else:
            checked = {
                "organization",
                "organization_id",
                "report",
                "report_id",
                "delivery_attempt",
                "delivery_attempt_id",
            }
            if checked.intersection(update_fields):
                self._validate_outbox()

        super().save(*args, **kwargs)
