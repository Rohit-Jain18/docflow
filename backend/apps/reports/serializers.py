"""
Serializers for Docflow Report APIs (Phase 1, Task 3G).

Enforces:
  - Strict input allowlists and rejection of unknown/forbidden fields.
  - Rejection of file_name, local disk paths, media URLs, and PDF bytes.
  - Rejection of client-supplied tenant, device, or WhatsApp account identities.
  - PII data minimization (client_tracking_label must not leak recipient phone number).
"""

import datetime
import re
import urllib.parse

from django.conf import settings
from django.utils import timezone as tz_utils
from rest_framework import serializers

from .models import DocumentType, MediaKind, ReportStatus

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


class MediaReferenceDataSerializer(serializers.Serializer):
    """Validate media_reference object inside PUT /api/v1/agent/reports/{id}/media-reference."""

    kind = serializers.CharField(
        max_length=50,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
    )
    url = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )
    expires_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        default=None,
    )
    provider_media_id = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                {"detail": "media_reference must be a JSON object."}
            )
        allowed = {"kind", "url", "expires_at", "provider_media_id"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                {k: ["Unexpected field in media_reference."] for k in sorted(unknown)}
            )

        raw_expiry = data.get("expires_at")
        if raw_expiry is not None and isinstance(raw_expiry, str):
            trimmed = raw_expiry.strip()
            if not (trimmed.endswith("Z") or re.search(r"[+-]\d{2}:?\d{2}$", trimmed)):
                raise serializers.ValidationError(
                    {"expires_at": ["expires_at must be timezone-aware (e.g. ISO 8601 ending in 'Z')."]}
                )

        return super().to_internal_value(data)

    def validate(self, attrs):
        kind = attrs.get("kind", "").strip()

        if kind == MediaKind.DEVELOPMENT_DOWNLOAD_URL:
            # 1. Mode check
            mode = getattr(settings, "TEMP_UPLOAD_MODE", "disabled")
            is_prod = getattr(settings, "DOCFLOW_ENV", "") == "production"
            if mode == "disabled" or is_prod:
                raise serializers.ValidationError(
                    {"kind": ["development_download_url is prohibited when TEMP_UPLOAD_MODE is disabled or in production."]}
                )

            # 2. Expiry check
            expires_at = attrs.get("expires_at")
            if not expires_at:
                raise serializers.ValidationError(
                    {"expires_at": ["expires_at is mandatory for development_download_url."]}
                )

            if tz_utils.is_naive(expires_at):
                raise serializers.ValidationError(
                    {"expires_at": ["expires_at must be timezone-aware (e.g. ISO 8601 ending in 'Z')."]}
                )

            now = tz_utils.now()
            buffer_seconds = getattr(settings, "TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS", 300)
            safety_threshold = now + datetime.timedelta(seconds=buffer_seconds)

            if expires_at <= now:
                raise serializers.ValidationError(
                    {"expires_at": ["expires_at must be in the future."]}
                )

            if expires_at <= safety_threshold:
                raise serializers.ValidationError(
                    {"expires_at": [f"expires_at must be outside the {buffer_seconds}s expiry safety buffer."]}
                )

            # 3. URL check
            url = attrs.get("url", "").strip()
            if not url:
                raise serializers.ValidationError(
                    {"url": ["A valid download URL is required for development_download_url."]}
                )

            try:
                parsed = urllib.parse.urlsplit(url)
            except Exception:
                raise serializers.ValidationError({"url": ["Malformed URL."]})

            if parsed.scheme.lower() != "https":
                raise serializers.ValidationError({"url": ["URL must use HTTPS protocol."]})

            expected_host = getattr(settings, "TEMP_UPLOAD_EXPECTED_HOST", "tmpfiles.org")
            if parsed.hostname != expected_host:
                raise serializers.ValidationError(
                    {"url": [f"URL host '{parsed.hostname}' does not match expected host '{expected_host}'."]}
                )

            if parsed.username or parsed.password:
                raise serializers.ValidationError({"url": ["Userinfo in URL is prohibited."]})

            if parsed.port and parsed.port != 443:
                raise serializers.ValidationError(
                    {"url": [f"Unapproved port '{parsed.port}' is prohibited."]}
                )

            if not parsed.path.startswith("/dl/") or len(parsed.path) <= 4:
                raise serializers.ValidationError(
                    {"url": ["URL must be a direct binary download URL with path starting with /dl/ (HTML landing pages are prohibited)."]}
                )

        elif kind in (MediaKind.PROVIDER_MEDIA_ID, MediaKind.PROVIDER_UPLOAD_REFERENCE):
            # Blocked per contract until external contract is confirmed
            pass
        else:
            raise serializers.ValidationError(
                {"kind": [f"Unknown media reference kind '{kind}'."]}
            )

        return attrs


class MediaReferenceAttachmentSerializer(serializers.Serializer):
    """
    Validate PUT /api/v1/agent/reports/{id}/media-reference request payload.
    Accepts exactly: media_reference.
    """

    media_reference = MediaReferenceDataSerializer(required=True)

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                {"detail": "Invalid request payload; expected JSON object."}
            )
        allowed = {"media_reference"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                {k: ["Unexpected field."] for k in sorted(unknown)}
            )
        return super().to_internal_value(data)


class AgentReportListQuerySerializer(serializers.Serializer):
    """Validate query parameters for GET /api/v1/agent/reports."""

    status = serializers.ChoiceField(
        choices=ReportStatus.choices,
        required=False,
    )
    since = serializers.DateTimeField(
        required=False,
    )
    page = serializers.IntegerField(
        required=False,
        min_value=1,
    )
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
    )

    def to_internal_value(self, data):
        allowed = {"status", "since", "page", "page_size"}
        unknown = set(data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                {k: ["Unexpected query parameter."] for k in sorted(unknown)}
            )
        return super().to_internal_value(data)


