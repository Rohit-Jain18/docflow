"""
Django Admin configurations for AuditEvent and WebhookReceipt models.

Enforces:
  - Strict append-only presentation for audit records (no add, no edit, no delete).
  - Safe, minimal field presentation.
  - Immutability of provider event identity for webhook receipts.
"""

from django.contrib import admin

from .models import AuditEvent, WebhookReceipt


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "timestamp",
        "action",
        "organization",
        "actor_user",
        "actor_device",
        "target_type",
        "target_id",
        "request_id",
    )
    list_filter = ("action", "target_type", "organization", "timestamp")
    search_fields = (
        "id",
        "target_id",
        "request_id",
        "action",
        "organization__name",
        "organization__slug",
    )
    ordering = ("-timestamp",)

    def has_add_permission(self, request):
        """Audit events cannot be manually created via Django Admin."""
        return False

    def has_change_permission(self, request, obj=None):
        """Audit events are append-only and cannot be edited."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Audit events cannot be deleted."""
        return False

    def get_readonly_fields(self, request, obj=None):
        """All fields on audit events are strictly read-only."""
        return [f.name for f in self.model._meta.fields]


@admin.register(WebhookReceipt)
class WebhookReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "provider_key",
        "external_event_key",
        "processing_state",
        "safe_error_code",
        "received_at",
        "processed_at",
    )
    list_filter = ("provider_key", "processing_state", "received_at")
    search_fields = (
        "id",
        "external_event_key",
        "safe_error_code",
    )
    ordering = ("-received_at",)
    readonly_fields = ("id", "received_at")

    def has_delete_permission(self, request, obj=None):
        """Webhook receipts cannot be deleted to maintain idempotency suppression history."""
        return False

    def get_readonly_fields(self, request, obj=None):
        if obj:
            # Identity fields are immutable on persisted instances
            return self.readonly_fields + ("provider_key", "external_event_key")
        return self.readonly_fields
