"""
Serializers for Docflow WhatsApp Account and Assignment APIs (Phase 1, Task 3F).

Enforces:
  - Explicit field allowlists and strict unknown-field rejection.
  - Safe representation of WhatsApp accounts without credential or secret leakage.
  - Safe assignment summaries for branch-account mappings.
"""

from rest_framework import serializers

from .models import BranchWhatsAppAssignment, WhatsAppAccount


def _reject_unknown_fields(data, allowed_fields):
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


class WhatsAppAccountSerializer(serializers.ModelSerializer):
    """Safe read-only representation of a WhatsApp Account."""

    organization_id = serializers.UUIDField(source="organization.id", read_only=True)

    class Meta:
        model = WhatsAppAccount
        fields = [
            "id",
            "organization_id",
            "provider_key",
            "provider_account_reference",
            "phone_number_id",
            "display_phone_number",
            "display_name",
            "status",
            "verified_at",
            "created_at",
        ]
        read_only_fields = fields


class WhatsAppAccountCreateSerializer(serializers.Serializer):
    """
    Validate POST /api/v1/whatsapp-accounts request payload.
    Accepts safe metadata and optional organization context only.
    """

    organization_id = serializers.UUIDField(required=False)
    display_name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )
    provider_key = serializers.CharField(
        max_length=50,
        required=False,
        default="kiziee",
        trim_whitespace=True,
    )
    provider_account_reference = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )
    phone_number_id = serializers.CharField(
        max_length=50,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )
    display_phone_number = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        _reject_unknown_fields(
            data,
            {
                "organization_id",
                "display_name",
                "provider_key",
                "provider_account_reference",
                "phone_number_id",
                "display_phone_number",
            },
        )
        return super().to_internal_value(data)


class WhatsAppAccountVerifySerializer(serializers.Serializer):
    """
    Validate POST /api/v1/whatsapp-accounts/{account_id}/verify request payload.
    Accepts strictly an empty JSON object: {}.
    """

    def to_internal_value(self, data):
        if not isinstance(data, dict) or len(data) > 0:
            raise serializers.ValidationError(
                {"detail": "Request body must be an empty JSON object."}
            )
        return {}


class BranchWhatsAppAssignmentCreateSerializer(serializers.Serializer):
    """
    Validate POST /api/v1/branches/{branch_id}/whatsapp-assignment request payload.
    Accepts exactly: whatsapp_account_id.
    """

    whatsapp_account_id = serializers.UUIDField(required=True)

    def to_internal_value(self, data):
        _reject_unknown_fields(data, {"whatsapp_account_id"})
        return super().to_internal_value(data)


class BranchWhatsAppAssignmentSummarySerializer(serializers.ModelSerializer):
    """Safe response summary for a Branch WhatsApp sender assignment."""

    branch_id = serializers.UUIDField(source="branch.id", read_only=True)
    whatsapp_account_id = serializers.UUIDField(source="whatsapp_account.id", read_only=True)

    class Meta:
        model = BranchWhatsAppAssignment
        fields = [
            "id",
            "branch_id",
            "whatsapp_account_id",
            "status",
            "assigned_at",
            "ended_at",
        ]
        read_only_fields = fields
