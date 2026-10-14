"""
Serializers for Docflow Agent Authentication APIs.

Enforces:
  - Strict input allowlists; rejects unknown fields and mass assignment.
  - Rejection of tenant, organization, branch, or device identity overrides.
  - Opaque handling of codes and tokens; never logs raw secrets.
"""

from rest_framework import serializers


class ActivationExchangeSerializer(serializers.Serializer):
    """
    Validate POST /api/v1/agent/activation/exchange request payload.
    Accepts ONLY: activation_code, installation_id, agent_version, platform.
    """

    activation_code = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=128,
        trim_whitespace=True,
    )
    installation_id = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=128,
        trim_whitespace=True,
    )
    agent_version = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
        max_length=50,
        trim_whitespace=True,
    )
    platform = serializers.CharField(
        required=False,
        default="windows",
        allow_blank=True,
        max_length=30,
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                {"detail": "Invalid request payload; expected JSON object."}
            )
        allowed = {"activation_code", "installation_id", "agent_version", "platform"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                {k: ["Unexpected field."] for k in sorted(unknown)}
            )
        return super().to_internal_value(data)


class RefreshTokenSerializer(serializers.Serializer):
    """
    Validate POST /api/v1/agent/auth/refresh request payload.
    Accepts ONLY: refresh_token.
    """

    refresh_token = serializers.CharField(
        required=True,
        allow_blank=False,
        max_length=256,
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                {"detail": "Invalid request payload; expected JSON object."}
            )
        allowed = {"refresh_token"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                {k: ["Unexpected field."] for k in sorted(unknown)}
            )
        return super().to_internal_value(data)


class RevokeSelfSerializer(serializers.Serializer):
    """
    Validate POST /api/v1/agent/auth/revoke-self request payload.
    Accepts an empty JSON object only: {}.
    """

    def to_internal_value(self, data):
        if not isinstance(data, dict) or len(data) > 0:
            raise serializers.ValidationError(
                {"detail": "Request body must be an empty JSON object."}
            )
        return {}


# ===========================================================================
# Human-facing Device Management Serializers (Phase 1, Task 3E)
# ===========================================================================

import re
from .models import Device

REASON_CODE_REGEX = re.compile(r"^[a-z][a-z0-9_]{2,49}$")


class DeviceSerializer(serializers.ModelSerializer):
    """Safe read-only representation of a Device for dashboard APIs."""

    organization_id = serializers.UUIDField(source="organization.id", read_only=True)
    branch_id = serializers.UUIDField(source="branch.id", read_only=True)

    class Meta:
        model = Device
        fields = [
            "id",
            "organization_id",
            "branch_id",
            "name",
            "status",
            "agent_version",
            "platform",
            "last_seen_at",
            "activated_at",
            "revoked_at",
            "created_at",
        ]
        read_only_fields = fields


class DeviceCreateSerializer(serializers.Serializer):
    """
    Validate POST /api/v1/devices request payload.
    Accepts exactly: branch_id, name.
    """

    branch_id = serializers.UUIDField(required=True)
    name = serializers.CharField(
        max_length=255,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                {"detail": "Invalid request payload; expected JSON object."}
            )
        allowed = {"branch_id", "name"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                {k: ["Unexpected field."] for k in sorted(unknown)}
            )
        return super().to_internal_value(data)


class DeviceUpdateSerializer(serializers.Serializer):
    """
    Validate PATCH /api/v1/devices/{device_id} request payload.
    Accepts only human-editable metadata: name.
    """

    name = serializers.CharField(
        max_length=255,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                {"detail": "Invalid request payload; expected JSON object."}
            )
        allowed = {"name"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                {k: ["Unexpected field."] for k in sorted(unknown)}
            )
        return super().to_internal_value(data)


class ActivationCodeIssueSerializer(serializers.Serializer):
    """
    Validate POST /api/v1/devices/{device_id}/activation-code request payload.
    Accepts exactly: expires_in_seconds (optional, bounded between 60 and 3600).
    """

    expires_in_seconds = serializers.IntegerField(
        required=False,
        default=600,
        min_value=60,
        max_value=3600,
    )

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                {"detail": "Invalid request payload; expected JSON object."}
            )
        allowed = {"expires_in_seconds"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                {k: ["Unexpected field."] for k in sorted(unknown)}
            )
        return super().to_internal_value(data)


class DeviceRevokeSerializer(serializers.Serializer):
    """
    Validate POST /api/v1/devices/{device_id}/revoke request payload.
    Accepts exactly: reason_code.
    """

    reason_code = serializers.CharField(
        max_length=50,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                {"detail": "Invalid request payload; expected JSON object."}
            )
        allowed = {"reason_code"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                {k: ["Unexpected field."] for k in sorted(unknown)}
            )
        return super().to_internal_value(data)

    def validate_reason_code(self, value):
        val = value.strip().lower()
        if not REASON_CODE_REGEX.match(val):
            raise serializers.ValidationError(
                "Must be a valid snake_case code between 3 and 50 characters (e.g. compromised, decommissioned)."
            )
        return val

