"""
Admin configurations for Report, MediaReference, Attempt, Event, and Outbox models.

Ensures sensitive material (such as media references and payloads) is excluded
from ordinary listings, while keeping audit fields inspectable and protected.
"""

from django.contrib import admin

from .models import (
    DeliveryAttempt,
    DeliveryEvent,
    DispatchOutbox,
    MediaReference,
    Report,
)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "organization",
        "branch",
        "recipient_phone_e164",
        "status",
        "document_type",
        "created_at",
    )
    list_filter = ("status", "document_type", "organization")
    search_fields = (
        "id",
        "idempotency_key",
        "fingerprint",
        "recipient_phone_e164",
        "organization__name",
        "branch__name",
    )
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return tuple(self.readonly_fields) + (
                "organization",
                "lab",
                "branch",
                "device",
                "branch_assignment",
                "idempotency_key",
                "fingerprint",
                "content_sha256",
            )
        return self.readonly_fields


@admin.register(MediaReference)
class MediaReferenceAdmin(admin.ModelAdmin):
    # Sensitive reference material is strictly excluded from list_display and form/detail presentation
    list_display = (
        "id",
        "report",
        "kind",
        "expires_at",
        "created_at",
        "deleted_at",
    )
    list_filter = ("kind",)
    search_fields = ("id", "report__id")
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at")
    exclude = ("encrypted_reference", "download_url", "provider_media_id")

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return tuple(self.readonly_fields) + ("report", "kind")
        return self.readonly_fields



@admin.register(DeliveryAttempt)
class DeliveryAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "report",
        "attempt_number",
        "status",
        "provider_key",
        "provider_message_id",
        "created_at",
    )
    list_filter = ("status", "error_category", "provider_key", "organization")
    search_fields = (
        "id",
        "report__id",
        "provider_message_id",
        "provider_request_id",
        "error_code",
    )
    ordering = ("report", "attempt_number")
    readonly_fields = ("id", "created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return tuple(self.readonly_fields) + ("organization", "report", "attempt_number")
        return self.readonly_fields


@admin.register(DeliveryEvent)
class DeliveryEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "report",
        "event_type",
        "source",
        "provider_event_id",
        "received_at",
    )
    list_filter = ("event_type", "source", "organization")
    search_fields = (
        "id",
        "report__id",
        "provider_event_id",
        "event_type",
        "error_code",
    )
    ordering = ("-received_at",)
    readonly_fields = ("id", "created_at", "received_at")


@admin.register(DispatchOutbox)
class DispatchOutboxAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "report",
        "event_type",
        "state",
        "available_at",
        "attempt_count",
    )
    list_filter = ("state", "event_type", "organization")
    search_fields = ("id", "report__id", "last_error_code")
    ordering = ("available_at",)
    readonly_fields = ("id", "created_at", "updated_at")
