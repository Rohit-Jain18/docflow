"""
Docflow WhatsApp Account and Assignment models.

Implements WhatsApp domain abstractions per DATA_MODEL.md §3, SECURITY.md §4,
and OPEN_QUESTIONS.md (OQ-003, OQ-004):
  - WhatsAppAccount: Provider account configuration and status.
  - BranchWhatsAppAssignment: Historical and active sender assignment linking
    a branch to a verified WhatsApp account under the same organization.

Enforces:
  - At most one active sender assignment per branch (partial unique constraint).
  - Cross-table tenant consistency: Branch and WhatsApp account must belong
    to the same organization.
  - No raw access tokens stored in credential_secret_ref.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone as tz_utils

from apps.tenants.models import Branch, Organization


class CredentialMode(models.TextChoices):
    PLATFORM_MANAGED = "platform_managed", "Platform Managed"
    BACKEND_SECRET = "backend_secret", "Backend Secret"
    PENDING_CONTRACT = "pending_contract", "Pending Contract"


class WhatsAppAccountStatus(models.TextChoices):
    PENDING_VERIFICATION = "pending_verification", "Pending Verification"
    VERIFIED = "verified", "Verified"
    DISABLED = "disabled", "Disabled"
    ERROR = "error", "Error"


class WhatsAppAccount(models.Model):
    """
    WhatsApp Cloud API or platform-managed account configuration.

    Represents an authorized sender identity mapped to an organization.
    Credentials stay platform-managed by default; credential_secret_ref holds
    an opaque reference, never a raw access token.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="whatsapp_accounts",
        verbose_name="organization",
    )
    provider_key = models.CharField(
        max_length=50,
        default="kiziee",
        verbose_name="provider key",
        help_text="Key identifying the provider adapter.",
    )
    provider_account_reference = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="provider account reference",
        help_text="Optional upstream reference or account ID from provider.",
    )
    phone_number_id = models.CharField(
        max_length=50,
        verbose_name="phone number ID",
        help_text="Provider phone number ID for WhatsApp Cloud API.",
    )
    display_phone_number = models.CharField(
        max_length=32,
        blank=True,
        default="",
        verbose_name="display phone number",
    )
    display_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="display name",
    )
    credential_mode = models.CharField(
        max_length=30,
        choices=CredentialMode.choices,
        default=CredentialMode.PLATFORM_MANAGED,
        verbose_name="credential mode",
    )
    credential_secret_ref = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="credential secret reference",
        help_text="Opaque reference to external secret manager. Never store raw tokens.",
    )
    status = models.CharField(
        max_length=30,
        choices=WhatsAppAccountStatus.choices,
        default=WhatsAppAccountStatus.PENDING_VERIFICATION,
        verbose_name="status",
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="verified at",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_whatsapp_accounts",
        verbose_name="created by",
    )
    created_at = models.DateTimeField(default=tz_utils.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "whatsapp_account"
        verbose_name = "WhatsApp account"
        verbose_name_plural = "WhatsApp accounts"
        ordering = ["organization", "display_name", "phone_number_id"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["provider_key", "phone_number_id"]),
        ]

    def __str__(self) -> str:
        label = self.display_name or self.phone_number_id
        return f"{label} ({self.get_status_display()})"

    def clean(self) -> None:
        """Validate model invariants including organization immutability."""
        super().clean()
        self._validate_immutability()

    def _validate_immutability(self) -> None:
        """Ensure a persisted WhatsApp account's organization cannot be changed."""
        if not self._state.adding and self.pk:
            original_org_id = (
                WhatsAppAccount.objects.filter(pk=self.pk)
                .values_list("organization_id", flat=True)
                .first()
            )
            if original_org_id and original_org_id != self.organization_id:
                raise ValidationError(
                    {"organization": "The organization of a persisted WhatsApp account cannot be changed."}
                )

    def save(self, *args, **kwargs) -> None:
        """Enforce organization immutability on normal saves."""
        update_fields = kwargs.get("update_fields")
        if update_fields is None:
            self._validate_immutability()
        else:
            tenant_fields = {"organization", "organization_id"}
            if tenant_fields.intersection(update_fields):
                self._validate_immutability()

        super().save(*args, **kwargs)


class AssignmentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class BranchWhatsAppAssignment(models.Model):
    """
    Branch-to-WhatsAppAccount sender assignment.

    Enforces at most one active sender assignment per branch, while preserving
    historical inactive assignments. Enforces that the branch and WhatsApp account
    share the exact same organization.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="whatsapp_assignments",
        verbose_name="organization",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="whatsapp_assignments",
        verbose_name="branch",
    )
    whatsapp_account = models.ForeignKey(
        WhatsAppAccount,
        on_delete=models.CASCADE,
        related_name="branch_assignments",
        verbose_name="WhatsApp account",
    )
    status = models.CharField(
        max_length=20,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.ACTIVE,
        verbose_name="status",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_branch_whatsapp",
        verbose_name="assigned by",
    )
    assigned_at = models.DateTimeField(
        default=tz_utils.now,
        verbose_name="assigned at",
    )
    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="ended at",
    )

    class Meta:
        db_table = "whatsapp_branch_assignment"
        verbose_name = "branch WhatsApp assignment"
        verbose_name_plural = "branch WhatsApp assignments"
        ordering = ["-assigned_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch"],
                condition=models.Q(status="active"),
                name="unique_active_branch_whatsapp_assignment",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["branch", "status"]),
            models.Index(fields=["whatsapp_account", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.branch.name} -> {self.whatsapp_account} ({self.status})"

    def clean(self) -> None:
        """Validate immutability of identity relationships and mutual tenant consistency."""
        super().clean()
        self._validate_immutability()
        self._validate_tenant_consistency()

    def _validate_immutability(self) -> None:
        """
        Ensure persisted BranchWhatsAppAssignment identity relationships
        (organization, branch, whatsapp_account) cannot be changed after creation.
        """
        if not self._state.adding and self.pk:
            original = (
                BranchWhatsAppAssignment.objects.filter(pk=self.pk)
                .values("organization_id", "branch_id", "whatsapp_account_id")
                .first()
            )
            if original:
                errors = {}
                if original["organization_id"] != self.organization_id:
                    errors["organization"] = (
                        "The organization of a persisted assignment cannot be changed."
                    )
                if original["branch_id"] != self.branch_id:
                    errors["branch"] = (
                        "The branch of a persisted assignment cannot be changed."
                    )
                if original["whatsapp_account_id"] != self.whatsapp_account_id:
                    errors["whatsapp_account"] = (
                        "The WhatsApp account of a persisted assignment cannot be changed."
                    )
                if errors:
                    raise ValidationError(errors)

    def _validate_tenant_consistency(self) -> None:
        """
        Validate that both the assigned branch and WhatsApp account belong to
        the assignment's organization.
        """
        errors = {}

        # Validate branch belongs to the assignment's organization
        if self.branch_id and self.organization_id:
            branch_org_id = None
            if hasattr(self, "_state") and "branch" in self._state.fields_cache:
                branch_org_id = self._state.fields_cache["branch"].organization_id
            else:
                branch_org_id = (
                    Branch.objects.filter(id=self.branch_id)
                    .values_list("organization_id", flat=True)
                    .first()
                )
            if branch_org_id and branch_org_id != self.organization_id:
                errors["branch"] = "The assigned branch must belong to the same organization."

        # Validate WhatsApp account belongs to the assignment's organization
        if self.whatsapp_account_id and self.organization_id:
            account_org_id = None
            if hasattr(self, "_state") and "whatsapp_account" in self._state.fields_cache:
                account_org_id = self._state.fields_cache["whatsapp_account"].organization_id
            else:
                account_org_id = (
                    WhatsAppAccount.objects.filter(id=self.whatsapp_account_id)
                    .values_list("organization_id", flat=True)
                    .first()
                )
            if account_org_id and account_org_id != self.organization_id:
                errors["whatsapp_account"] = "The WhatsApp account must belong to the same organization."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        """Enforce immutability and tenant consistency on normal saves."""
        update_fields = kwargs.get("update_fields")
        identity_fields = {
            "organization",
            "organization_id",
            "branch",
            "branch_id",
            "whatsapp_account",
            "whatsapp_account_id",
        }
        if update_fields is None:
            self._validate_immutability()
            self._validate_tenant_consistency()
        else:
            if identity_fields.intersection(update_fields):
                self._validate_immutability()
                self._validate_tenant_consistency()

        super().save(*args, **kwargs)

