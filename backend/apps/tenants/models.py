"""
Docflow Tenancy models.

Implements core tenancy abstractions per DATA_MODEL.md §1:
  - Organization: Customer tenant boundary.
  - OrganizationMembership: User roles within an organization.
  - Lab: Diagnostic lab profile within an organization.
  - Branch: Physical or operational branch under a lab and organization.

Enforces cross-table tenant consistency:
  A branch's lab must belong to the same organization.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone as tz_utils


class OrganizationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    CLOSED = "closed", "Closed"


class Organization(models.Model):
    """
    Tenant boundary and customer account.

    All tenant-owned resources (labs, branches, devices, reports) belong to an
    organization.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, verbose_name="name")
    slug = models.SlugField(
        max_length=100,
        unique=True,
        verbose_name="slug",
        help_text="Unique URL-safe identifier for the organization.",
    )
    status = models.CharField(
        max_length=20,
        choices=OrganizationStatus.choices,
        default=OrganizationStatus.ACTIVE,
        verbose_name="status",
    )
    timezone = models.CharField(
        max_length=64,
        default="UTC",
        verbose_name="timezone",
        help_text="Primary timezone for the organization (e.g. UTC, Asia/Kolkata).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_organizations",
        verbose_name="created by",
        help_text="User who created this organization, if recorded.",
    )
    created_at = models.DateTimeField(default=tz_utils.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants_organization"
        verbose_name = "organization"
        verbose_name_plural = "organizations"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class MembershipRole(models.TextChoices):
    ORGANIZATION_ADMIN = "organization_admin", "Organization Admin"
    BRANCH_MANAGER = "branch_manager", "Branch Manager"
    OPERATOR = "operator", "Operator"
    VIEWER = "viewer", "Viewer"
    AUDITOR = "auditor", "Auditor"


class MembershipStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    INACTIVE = "inactive", "Inactive"


class OrganizationMembership(models.Model):
    """
    Explicit user membership and role assignment within an organization.

    Enforces that a user can have at most one membership per organization.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name="organization",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="organization_memberships",
        verbose_name="user",
    )
    role = models.CharField(
        max_length=30,
        choices=MembershipRole.choices,
        default=MembershipRole.OPERATOR,
        verbose_name="role",
    )
    status = models.CharField(
        max_length=20,
        choices=MembershipStatus.choices,
        default=MembershipStatus.ACTIVE,
        verbose_name="status",
    )
    created_at = models.DateTimeField(default=tz_utils.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants_organization_membership"
        verbose_name = "organization membership"
        verbose_name_plural = "organization memberships"
        ordering = ["organization", "user"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="unique_organization_user_membership",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} ({self.role}) @ {self.organization}"


class LabType(models.TextChoices):
    DIAGNOSTIC = "diagnostic", "Diagnostic"


class LabStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    INACTIVE = "inactive", "Inactive"


class Lab(models.Model):
    """
    Diagnostic lab profile belonging to an organization.

    A Lab is a diagnostic facility profile within an organization, not a
    separate tenant.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="labs",
        verbose_name="organization",
    )
    name = models.CharField(max_length=255, verbose_name="name")
    code = models.CharField(
        max_length=50,
        verbose_name="code",
        help_text="Facility code unique within the organization.",
    )
    lab_type = models.CharField(
        max_length=30,
        choices=LabType.choices,
        default=LabType.DIAGNOSTIC,
        verbose_name="lab type",
    )
    support_phone = models.CharField(
        max_length=32,
        blank=True,
        default="",
        verbose_name="support phone",
    )
    status = models.CharField(
        max_length=20,
        choices=LabStatus.choices,
        default=LabStatus.ACTIVE,
        verbose_name="status",
    )
    created_at = models.DateTimeField(default=tz_utils.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants_lab"
        verbose_name = "lab"
        verbose_name_plural = "labs"
        ordering = ["organization", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="unique_organization_lab_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    def clean(self) -> None:
        """Validate model invariants including organization immutability."""
        super().clean()
        self._validate_organization_immutability()

    def _validate_organization_immutability(self) -> None:
        """
        Ensure a persisted lab's organization cannot be changed.

        A lab's organization is its tenant boundary. Allowing it to change
        risks tenant isolation and can leave child branches inconsistent.
        """
        if not self._state.adding and self.pk:
            original_org_id = (
                Lab.objects.filter(pk=self.pk)
                .values_list("organization_id", flat=True)
                .first()
            )
            if original_org_id and original_org_id != self.organization_id:
                raise ValidationError(
                    {"organization": "The organization of a persisted lab cannot be changed."}
                )

    def save(self, *args, **kwargs) -> None:
        """
        Save the lab instance, enforcing organization immutability.

        Django models do not run clean() automatically on save(). We enforce
        immutability on normal saves and when update_fields touches organization.
        """
        update_fields = kwargs.get("update_fields")
        if update_fields is None:
            self._validate_organization_immutability()
        else:
            tenant_fields = {"organization", "organization_id"}
            if tenant_fields.intersection(update_fields):
                self._validate_organization_immutability()

        super().save(*args, **kwargs)


class BranchStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    INACTIVE = "inactive", "Inactive"


class Branch(models.Model):
    """
    Physical or operational branch of a diagnostic lab.

    Must belong to the same organization as its parent lab.
    Branch code is unique within its lab.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="branches",
        verbose_name="organization",
    )
    lab = models.ForeignKey(
        Lab,
        on_delete=models.CASCADE,
        related_name="branches",
        verbose_name="lab",
    )
    name = models.CharField(max_length=255, verbose_name="name")
    code = models.CharField(
        max_length=50,
        verbose_name="code",
        help_text="Branch code unique within its lab.",
    )
    address = models.TextField(blank=True, default="", verbose_name="address")
    support_phone = models.CharField(
        max_length=32,
        blank=True,
        default="",
        verbose_name="support phone",
    )
    timezone = models.CharField(
        max_length=64,
        default="UTC",
        verbose_name="timezone",
        help_text="Local timezone of the branch.",
    )
    status = models.CharField(
        max_length=20,
        choices=BranchStatus.choices,
        default=BranchStatus.ACTIVE,
        verbose_name="status",
    )
    created_at = models.DateTimeField(default=tz_utils.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants_branch"
        verbose_name = "branch"
        verbose_name_plural = "branches"
        ordering = ["organization", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["lab", "code"],
                name="unique_lab_branch_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    def clean(self) -> None:
        """Validate model invariants including cross-tenant consistency."""
        super().clean()
        self._validate_tenant_consistency()

    def _validate_tenant_consistency(self) -> None:
        """
        Ensure the branch's lab belongs to the same organization.

        Avoids unnecessary database queries by checking the cached lab instance
        if already resolved; otherwise queries only the organization_id.
        """
        if self.lab_id and self.organization_id:
            lab_org_id = None
            if hasattr(self, "_state") and "lab" in self._state.fields_cache:
                lab_org_id = self._state.fields_cache["lab"].organization_id
            else:
                lab_org_id = (
                    Lab.objects.filter(id=self.lab_id)
                    .values_list("organization_id", flat=True)
                    .first()
                )

            if lab_org_id and lab_org_id != self.organization_id:
                raise ValidationError(
                    {"lab": "The assigned lab must belong to the same organization as the branch."}
                )

    def save(self, *args, **kwargs) -> None:
        """
        Save the branch instance, enforcing tenant validation on normal saves.

        Django models do not run clean() automatically on save().  We enforce
        tenant consistency here while skipping the check when update_fields is
        used and neither organization nor lab is being updated.
        """
        update_fields = kwargs.get("update_fields")
        if update_fields is None:
            self._validate_tenant_consistency()
        else:
            tenant_fields = {"organization", "organization_id", "lab", "lab_id"}
            if tenant_fields.intersection(update_fields):
                self._validate_tenant_consistency()

        super().save(*args, **kwargs)
