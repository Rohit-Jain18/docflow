"""
Serializers for Docflow Report APIs (Phase 1, Task 3G).

Enforces:
  - Strict input allowlists and rejection of unknown/forbidden fields.
  - Rejection of file_name, local disk paths, media URLs, and PDF bytes.
  - Rejection of client-supplied tenant, device, or WhatsApp account identities.
  - PII data minimization (client_tracking_label must not leak recipient phone number).
"""

import re
from rest_framework import serializers

from .models import DocumentType

HEX_64_REGEX = re.compile(r"^[0-9a-f]{64}$")
E164_REGEX = re.compile(r"^\+[1-9]\d{6,14}$")

ALLOWED_REPORT_FIELDS = {
    "recipient_phone_e164",
    "content_sha256",
    "file_size_bytes",
    "document_type",
    "agent_created_at",
    "client_tracking_label",
}


def _reject_unknown_and_forbidden_fields(data, allowed_fields):
    if not isinstance(data, dict):
        raise serializers.ValidationError(
            {"detail": "Invalid request payload; expected JSON object."}
        )
    unknown = set(data.keys()) - allowed_fields
    if unknown:
        raise serializers.ValidationError(
            {k: ["Unexpected or forbidden field."] for k in sorted(unknown)}
        )


class AgentReportCreateSerializer(serializers.Serializer):
    """
    Validate POST /api/v1/agent/reports request payload.
    Accepts safe report metadata only.
    """

    recipient_phone_e164 = serializers.CharField(
        max_length=32,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )
    content_sha256 = serializers.CharField(
        max_length=64,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )
    file_size_bytes = serializers.IntegerField(
        min_value=1,
        max_value=52428800,  # 50MB
        required=True,
    )
    document_type = serializers.CharField(
        max_length=50,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )
    agent_created_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        default=None,
    )
    client_tracking_label = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        _reject_unknown_and_forbidden_fields(data, ALLOWED_REPORT_FIELDS)
        return super().to_internal_value(data)

    def validate_recipient_phone_e164(self, value):
        val = value.strip()
        if not E164_REGEX.match(val):
            raise serializers.ValidationError(
                "Recipient phone number must be in E.164 format (e.g. +919876543210)."
            )
        return val

    def validate_content_sha256(self, value):
        val = value.strip()
        if not HEX_64_REGEX.match(val):
            raise serializers.ValidationError(
                "Content SHA-256 must be a 64-character lowercase hex string."
            )
        return val

    def validate_document_type(self, value):
        val = value.strip()
        if val != DocumentType.DIAGNOSTIC_REPORT:
            raise serializers.ValidationError(
                f"Unsupported document type '{val}'. Supported type: '{DocumentType.DIAGNOSTIC_REPORT}'."
            )
        return val

    def validate(self, attrs):
        phone = attrs.get("recipient_phone_e164", "")
        label = attrs.get("client_tracking_label", "")
        if label and phone:
            phone_digits = phone.lstrip("+")
            national_digits = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
            if (phone_digits in label) or (len(national_digits) >= 8 and national_digits in label):
                raise serializers.ValidationError(
                    {"client_tracking_label": ["Client tracking label must not contain recipient phone number."]}
                )
        return attrs
