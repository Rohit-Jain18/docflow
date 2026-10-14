"""
Docflow Device and Credential models.

Implements device domain abstractions per DATA_MODEL.md §2 and SECURITY.md §3:
  - Device: Monitored Windows client instance assigned to an organization and branch.
  - DeviceActivationCode: Short-lived, single-use, hashed one-time activation code.
  - DeviceRefreshCredential: Rotating refresh secret hash for device API authentication.

Enforces cross-table tenant consistency:
  - A device's branch must belong to the device's organization.
  - Activation code organization, branch, and device must be mutually consistent.
  - Replacement refresh credentials must belong to the same device.
Never stores raw secrets or activation codes.
"""

import datetime
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone as tz_utils

from apps.tenants.models import Branch, Organization


def get_default_activation_code_expiry() -> datetime.datetime:
    """Return initial 10-minute expiry timestamp for activation codes."""
    return tz_utils.now() + datetime.timedelta(minutes=10)


class DeviceStatus(models.TextChoices):
    PENDING_ACTIVATION = "pending_activation", "Pending Activation"
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"
    DISABLED = "disabled", "Disabled"


class Device(models.Model):
    """
    Client PC running the Docflow Windows Agent.

    Server derives tenant and branch authority from the authenticated device.
    Never holds or returns secret material directly.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="devices",
        verbose_name="organization",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="devices",
        verbose_name="branch",
    )
    name = models.CharField(max_length=255, verbose_name="name")
    status = models.CharField(
        max_length=30,
        choices=DeviceStatus.choices,
        default=DeviceStatus.PENDING_ACTIVATION,
        verbose_name="status",
    )
    agent_version = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name="agent version",
    )
    platform = models.CharField(
        max_length=30,
        default="windows",
        verbose_name="platform",
    )
    last_seen_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="last seen at",
    )
    last_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name="last IP address",
    )
    activated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="activated at",
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="revoked at",
    )
    created_at = models.DateTimeField(default=tz_utils.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "devices_device"
        verbose_name = "device"
        verbose_name_plural = "devices"
        ordering = ["organization", "name"]
        indexes = [
            models.Index(fields=["organization", "status"]),
            models.Index(fields=["branch", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_status_display()})"

    def clean(self) -> None:
        """Validate tenant consistency and immutability."""
        super().clean()
        self._validate_tenant_consistency()

    def _validate_tenant_consistency(self) -> None:
        """
        Ensure the assigned branch belongs to the same organization as the device,
        and that a persisted device's organization cannot be altered.
        """
        errors = {}

        # Enforce organization immutability on persisted devices
        if not self._state.adding and self.pk:
            original_org_id = (
                Device.objects.filter(pk=self.pk)
                .values_list("organization_id", flat=True)
                .first()
            )
            if original_org_id and original_org_id != self.organization_id:
                errors["organization"] = "The organization of a persisted device cannot be changed."

        # Validate branch belongs to device's organization
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
                errors["branch"] = "The assigned branch must belong to the same organization as the device."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        """
        Save the device instance, enforcing tenant validation on normal saves.

        Skips tenant check when update_fields is provided and neither organization
        nor branch is being updated.
        """
        update_fields = kwargs.get("update_fields")
        if update_fields is None:
            self._validate_tenant_consistency()
        else:
            tenant_fields = {"organization", "organization_id", "branch", "branch_id"}
            if tenant_fields.intersection(update_fields):
                self._validate_tenant_consistency()

        super().save(*args, **kwargs)


class DeviceActivationCode(models.Model):
    """
    Single-use, short-lived, hashed activation code for binding an Agent to a Device.

    Stores ONLY code_hash; the raw activation code is never stored in plaintext
    or logged. Initial default expiry is 10 minutes.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="activation_codes",
        verbose_name="organization",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="activation_codes",
        verbose_name="branch",
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="activation_codes",
        verbose_name="device",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_activation_codes",
        verbose_name="created by",
    )
    code_hash = models.CharField(
        max_length=128,
        unique=True,
        verbose_name="code hash",
        help_text="Cryptographic hash of the one-time activation code. Raw code is never stored.",
    )
    expires_at = models.DateTimeField(
        default=get_default_activation_code_expiry,
        verbose_name="expires at",
    )
    consumed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="consumed at",
    )
    attempt_count = models.PositiveIntegerField(
        default=0,
        verbose_name="attempt count",
    )
    created_at = models.DateTimeField(default=tz_utils.now, editable=False)
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="revoked at",
    )

    class Meta:
        db_table = "devices_device_activation_code"
        verbose_name = "device activation code"
        verbose_name_plural = "device activation codes"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["device", "consumed_at"]),
            models.Index(fields=["code_hash"]),
            models.Index(fields=["organization", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"ActivationCode({self.device_id}, expires={self.expires_at})"

    @property
    def is_expired(self) -> bool:
        """Return True if the activation code has passed its expiration time."""
        return tz_utils.now() >= self.expires_at

    @property
    def is_consumed(self) -> bool:
        """Return True if the activation code has already been consumed."""
        return self.consumed_at is not None

    @property
    def is_revoked(self) -> bool:
        """Return True if the activation code was explicitly revoked."""
        return self.revoked_at is not None

    @property
    def is_valid(self) -> bool:
        """Return True if the code is unconsumed, unrevoked, and unexpired."""
        return not self.is_consumed and not self.is_revoked and not self.is_expired

    def clean(self) -> None:
        """Validate organization, branch, and device consistency."""
        super().clean()
        self._validate_tenant_consistency()

    def _validate_tenant_consistency(self) -> None:
        """
        Verify that organization, branch, and device mutually agree on tenancy.
        """
        errors = {}

        # Validate branch belongs to activation code's organization
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
                errors["branch"] = "The activation code branch must belong to the same organization."

        # Validate device belongs to the same organization and branch
        if self.device_id:
            device_org_id = None
            device_branch_id = None
            if hasattr(self, "_state") and "device" in self._state.fields_cache:
                dev = self._state.fields_cache["device"]
                device_org_id = dev.organization_id
                device_branch_id = dev.branch_id
            else:
                row = (
                    Device.objects.filter(id=self.device_id)
                    .values_list("organization_id", "branch_id")
                    .first()
                )
                if row:
                    device_org_id, device_branch_id = row

            if device_org_id and self.organization_id and device_org_id != self.organization_id:
                errors["device"] = "The device must belong to the same organization as the activation code."
            elif device_branch_id and self.branch_id and device_branch_id != self.branch_id:
                errors["device"] = "The device must belong to the same branch as the activation code."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        """Enforce tenant consistency on normal saves."""
        update_fields = kwargs.get("update_fields")
        if update_fields is None:
            self._validate_tenant_consistency()
        else:
            tenant_fields = {
                "organization",
                "organization_id",
                "branch",
                "branch_id",
                "device",
                "device_id",
            }
            if tenant_fields.intersection(update_fields):
                self._validate_tenant_consistency()

        super().save(*args, **kwargs)


class DeviceRefreshCredential(models.Model):
    """
    Rotating refresh credential for an authenticated Device.

    Stores ONLY credential_hash, never the raw rotating secret.
    Supports single-use rotation chaining via replaced_by self-reference.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="refresh_credentials",
        verbose_name="device",
    )
    credential_hash = models.CharField(
        max_length=128,
        unique=True,
        verbose_name="credential hash",
        help_text="Cryptographic hash of the rotating refresh secret. Raw secret is never stored.",
    )
    issued_at = models.DateTimeField(default=tz_utils.now, verbose_name="issued at")
    expires_at = models.DateTimeField(verbose_name="expires at")
    rotated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="rotated at",
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="revoked at",
    )
    replaced_by = models.OneToOneField(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replaces",
        verbose_name="replaced by",
    )

    class Meta:
        db_table = "devices_device_refresh_credential"
        verbose_name = "device refresh credential"
        verbose_name_plural = "device refresh credentials"
        ordering = ["-issued_at"]
        indexes = [
            models.Index(fields=["device", "revoked_at"]),
            models.Index(fields=["credential_hash"]),
            models.Index(fields=["device", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"RefreshCredential({self.device_id}, issued={self.issued_at})"

    @property
    def is_expired(self) -> bool:
        """Return True if the credential has expired."""
        return tz_utils.now() >= self.expires_at

    @property
    def is_revoked(self) -> bool:
        """Return True if the credential was explicitly revoked."""
        return self.revoked_at is not None

    @property
    def is_rotated(self) -> bool:
        """Return True if the credential has been rotated."""
        return self.rotated_at is not None

    @property
    def is_active(self) -> bool:
        """Return True if the credential is unexpired, unrevoked, and unrotated."""
        return not self.is_expired and not self.is_revoked and not self.is_rotated

    def clean(self) -> None:
        """Validate rotation device consistency."""
        super().clean()
        self._validate_device_consistency()

    def _validate_device_consistency(self) -> None:
        """
        Ensure that the replacement credential belongs to the exact same device.
        """
        if self.replaced_by_id and self.device_id:
            replaced_by_device_id = None
            if hasattr(self, "_state") and "replaced_by" in self._state.fields_cache:
                replaced_by_device_id = self._state.fields_cache["replaced_by"].device_id
            else:
                replaced_by_device_id = (
                    DeviceRefreshCredential.objects.filter(id=self.replaced_by_id)
                    .values_list("device_id", flat=True)
                    .first()
                )

            if replaced_by_device_id and replaced_by_device_id != self.device_id:
                raise ValidationError(
                    {"replaced_by": "The replacement credential must belong to the same device."}
                )

    def save(self, *args, **kwargs) -> None:
        """Enforce device consistency on normal saves."""
        self._validate_device_consistency()
        super().save(*args, **kwargs)
