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
