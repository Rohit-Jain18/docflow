"""
Serializers for Docflow Human User Authentication APIs (Phase 1, Task 3C).

Enforces:
  - Strict input allowlists; rejects unknown fields and mass assignment.
  - Safe user summary representation with active memberships only.
  - Zero token or credential exposure in JSON responses.
"""

from rest_framework import serializers

from apps.tenants.models import MembershipStatus, OrganizationMembership, OrganizationStatus


class LoginSerializer(serializers.Serializer):
    """
    Validate POST /api/v1/auth/login request payload.
    Accepts ONLY: email, password.
    """

    email = serializers.EmailField(
        required=True,
        allow_blank=False,
        max_length=255,
        trim_whitespace=True,
    )
    password = serializers.CharField(
        required=True,
        allow_blank=False,
        write_only=True,
        trim_whitespace=False,
    )

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                {"detail": "Invalid request payload; expected JSON object."}
            )
        allowed = {"email", "password"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                {k: ["Unexpected field."] for k in sorted(unknown)}
            )
        return super().to_internal_value(data)


class LogoutSerializer(serializers.Serializer):
    """
    Validate POST /api/v1/auth/logout request payload.
    Accepts ONLY: empty dictionary {}.
    """

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                {"detail": "Invalid request payload; expected JSON object."}
            )
        if data:
            raise serializers.ValidationError(
                {k: ["Unexpected field."] for k in sorted(data.keys())}
            )
        return {}


class OrganizationMembershipSummarySerializer(serializers.ModelSerializer):
    """Safe read-only representation of an active organization membership."""

    organization_id = serializers.UUIDField(source="organization.id", read_only=True)
    organization_name = serializers.CharField(source="organization.name", read_only=True)
    role = serializers.CharField(read_only=True)

    class Meta:
        model = OrganizationMembership
        fields = ["organization_id", "organization_name", "role"]
        read_only_fields = fields


class UserSummarySerializer(serializers.Serializer):
    """
    Safe read-only representation of an authenticated human user.
    Exposes only safe identity fields and active organization memberships.
    """

    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    is_platform_admin = serializers.BooleanField(read_only=True)
    memberships = serializers.SerializerMethodField()

    def get_memberships(self, obj):
        active_memberships = (
            obj.organization_memberships
            .filter(
                status=MembershipStatus.ACTIVE,
                organization__status=OrganizationStatus.ACTIVE,
            )
            .select_related("organization")
            .order_by("organization__name")
        )
        return OrganizationMembershipSummarySerializer(active_memberships, many=True).data
