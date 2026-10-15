"""Admin registrations for device and credential models."""
from django.contrib import admin

from .models import Device, DeviceActivationCode, DeviceRefreshCredential


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "organization",
        "branch",
        "status",
        "platform",
        "agent_version",
        "last_seen_at",
        "created_at",
    )
    list_filter = ("status", "platform", "organization")
    search_fields = ("name", "organization__name", "branch__name")
    ordering = ("organization", "name")
    readonly_fields = (
        "id",
        "activated_at",
        "revoked_at",
        "last_seen_at",
        "last_ip",
        "created_at",
        "updated_at",
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return tuple(self.readonly_fields) + ("organization",)
        return self.readonly_fields


@admin.register(DeviceActivationCode)
class DeviceActivationCodeAdmin(admin.ModelAdmin):
    # code_hash is deliberately excluded from list_display for security
    list_display = (
        "device",
        "organization",
        "branch",
        "expires_at",
        "consumed_at",
        "revoked_at",
        "attempt_count",
        "created_at",
    )
    list_filter = ("organization",)
    search_fields = ("device__name", "organization__name", "branch__name")
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "code_hash",
        "created_at",
        "consumed_at",
        "attempt_count",
    )


@admin.register(DeviceRefreshCredential)
class DeviceRefreshCredentialAdmin(admin.ModelAdmin):
    # credential_hash is deliberately excluded from list_display for security
    list_display = (
        "device",
        "issued_at",
        "expires_at",
        "rotated_at",
        "revoked_at",
        "replaced_by",
    )
    list_filter = ("device__organization",)
    search_fields = ("device__name",)
    ordering = ("-issued_at",)
    readonly_fields = (
        "id",
        "credential_hash",
        "issued_at",
        "rotated_at",
        "revoked_at",
        "replaced_by",
    )
