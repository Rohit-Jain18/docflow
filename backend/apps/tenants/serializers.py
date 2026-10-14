"""
Serializers for Docflow Tenant APIs (Phase 1, Task 3D).

Enforces:
  - Explicit field allowlists and strict unknown-field rejection.
  - Safe representation of organizations, labs, and branches.
  - Organization immutability and reparenting prevention.
  - Status transition authorization rules.
"""

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from .models import (
    Branch,
    BranchStatus,
    Lab,
    LabStatus,
    LabType,
    Organization,
    OrganizationStatus,
)


def _reject_unknown_fields(serializer_instance, data, allowed_fields):
    """Ensure data dictionary contains only allowed field names."""
    if not isinstance(data, dict):
        raise serializers.ValidationError(
            {"detail": "Invalid request payload; expected JSON object."}
        )
    unknown = set(data.keys()) - allowed_fields
    if unknown:
        raise serializers.ValidationError(
            {k: ["Unexpected field."] for k in sorted(unknown)}
        )


# ===========================================================================
# Organization Serializers
# ===========================================================================


class OrganizationSerializer(serializers.ModelSerializer):
    """Safe read-only representation of an Organization."""

    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "status", "timezone", "created_at"]
        read_only_fields = fields


class OrganizationCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating an Organization.
    Platform-admin only.
    """

    name = serializers.CharField(
        max_length=255,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )
    slug = serializers.SlugField(
        max_length=100,
        required=True,
        allow_blank=False,
    )
    timezone = serializers.CharField(
        max_length=64,
        required=False,
        default="UTC",
    )

    class Meta:
        model = Organization
        fields = ["name", "slug", "timezone"]

    def to_internal_value(self, data):
        _reject_unknown_fields(self, data, {"name", "slug", "timezone"})
        return super().to_internal_value(data)

    def validate_slug(self, value):
        if Organization.objects.filter(slug=value).exists():
            raise serializers.ValidationError("An organization with this slug already exists.")
        return value


class OrganizationUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating an Organization (PATCH).
    Allows name, timezone, and status-transitions only.
    Rejects tenant re-assignment or slug modification.
    """

    name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=False,
        trim_whitespace=True,
    )
    timezone = serializers.CharField(
        max_length=64,
        required=False,
    )
    status = serializers.ChoiceField(
        choices=OrganizationStatus.choices,
        required=False,
    )

    class Meta:
        model = Organization
        fields = ["name", "timezone", "status"]

    def to_internal_value(self, data):
        _reject_unknown_fields(self, data, {"name", "timezone", "status"})
        return super().to_internal_value(data)

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None

        if "status" in attrs:
            new_status = attrs["status"]
            # Status changes affecting tenant access are platform-admin only
            if not user or not getattr(user, "is_platform_admin", False):
                raise PermissionDenied("Only platform administrators can change organization status.")

            # Closed organizations cannot transition to any other status
            if self.instance and self.instance.status == OrganizationStatus.CLOSED and new_status != OrganizationStatus.CLOSED:
                raise serializers.ValidationError({"status": ["Closed organizations cannot change status."]})

        return attrs


# ===========================================================================
# Lab Serializers
# ===========================================================================


class LabSerializer(serializers.ModelSerializer):
    """Safe read-only representation of a Lab."""

    organization_id = serializers.UUIDField(source="organization.id", read_only=True)

    class Meta:
        model = Lab
        fields = [
            "id",
            "organization_id",
            "name",
            "code",
            "lab_type",
            "support_phone",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class LabCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a Lab.
    Accepts organization_id (optional for tenant admin, required for platform admin),
    name, code, lab_type, support_phone, status.
    """

    organization_id = serializers.UUIDField(required=False)
    name = serializers.CharField(
        max_length=255,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )
    code = serializers.CharField(
        max_length=50,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )
    lab_type = serializers.ChoiceField(
        choices=LabType.choices,
        required=False,
        default=LabType.DIAGNOSTIC,
    )
    support_phone = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
        default="",
    )
    status = serializers.ChoiceField(
        choices=LabStatus.choices,
        required=False,
        default=LabStatus.ACTIVE,
    )

    class Meta:
        model = Lab
        fields = [
            "organization_id",
            "name",
            "code",
            "lab_type",
            "support_phone",
            "status",
        ]

    def to_internal_value(self, data):
        _reject_unknown_fields(
            self,
            data,
            {"organization_id", "name", "code", "lab_type", "support_phone", "status"},
        )
        return super().to_internal_value(data)


class LabUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating a Lab (PATCH).
    Allows name, code, support_phone, status.
    Strictly forbids reparenting or changing organization.
    """

    name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=False,
        trim_whitespace=True,
    )
    code = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=False,
        trim_whitespace=True,
    )
    support_phone = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
    )
    status = serializers.ChoiceField(
        choices=LabStatus.choices,
        required=False,
    )

    class Meta:
        model = Lab
        fields = ["name", "code", "support_phone", "status"]

    def to_internal_value(self, data):
        _reject_unknown_fields(self, data, {"name", "code", "support_phone", "status"})
        return super().to_internal_value(data)

    def validate(self, attrs):
        if "code" in attrs and self.instance:
            new_code = attrs["code"]
            if (
                Lab.objects.filter(organization=self.instance.organization, code=new_code)
                .exclude(id=self.instance.id)
                .exists()
            ):
                raise serializers.ValidationError(
                    {"code": ["A lab with this code already exists in the organization."]}
                )
        return attrs


# ===========================================================================
# Branch Serializers
# ===========================================================================


class BranchSerializer(serializers.ModelSerializer):
    """Safe read-only representation of a Branch."""

    organization_id = serializers.UUIDField(source="organization.id", read_only=True)
    lab_id = serializers.UUIDField(source="lab.id", read_only=True)

    class Meta:
        model = Branch
        fields = [
            "id",
            "organization_id",
            "lab_id",
            "name",
            "code",
            "address",
            "support_phone",
            "timezone",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class BranchCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a Branch.
    Accepts lab_id, name, code, address, support_phone, timezone, status.
    Organization is derived server-side from the Lab.
    """

    lab_id = serializers.UUIDField(required=True)
    name = serializers.CharField(
        max_length=255,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )
    code = serializers.CharField(
        max_length=50,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )
    address = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    support_phone = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
        default="",
    )
    timezone = serializers.CharField(
        max_length=64,
        required=False,
        default="UTC",
    )
    status = serializers.ChoiceField(
        choices=BranchStatus.choices,
        required=False,
        default=BranchStatus.ACTIVE,
    )

    class Meta:
        model = Branch
        fields = [
            "lab_id",
            "name",
            "code",
            "address",
            "support_phone",
            "timezone",
            "status",
        ]

    def to_internal_value(self, data):
        _reject_unknown_fields(
            self,
            data,
            {"lab_id", "name", "code", "address", "support_phone", "timezone", "status"},
        )
        return super().to_internal_value(data)


class BranchUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for updating a Branch (PATCH).
    Allows name, code, address, support_phone, timezone, status.
    Strictly forbids reparenting to another lab or organization.
    """

    name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=False,
        trim_whitespace=True,
    )
    code = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=False,
        trim_whitespace=True,
    )
    address = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    support_phone = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
    )
    timezone = serializers.CharField(
        max_length=64,
        required=False,
    )
    status = serializers.ChoiceField(
        choices=BranchStatus.choices,
        required=False,
    )

    class Meta:
        model = Branch
        fields = ["name", "code", "address", "support_phone", "timezone", "status"]

    def to_internal_value(self, data):
        _reject_unknown_fields(
            self,
            data,
            {"name", "code", "address", "support_phone", "timezone", "status"},
        )
        return super().to_internal_value(data)

    def validate(self, attrs):
        if "code" in attrs and self.instance:
            new_code = attrs["code"]
            if (
                Branch.objects.filter(lab=self.instance.lab, code=new_code)
                .exclude(id=self.instance.id)
                .exists()
            ):
                raise serializers.ValidationError(
                    {"code": ["A branch with this code already exists in this lab."]}
                )
        return attrs
