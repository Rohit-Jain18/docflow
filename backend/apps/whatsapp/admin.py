"""Admin registrations for WhatsApp models."""
from django.contrib import admin

from .models import BranchWhatsAppAssignment, WhatsAppAccount


@admin.register(WhatsAppAccount)
class WhatsAppAccountAdmin(admin.ModelAdmin):
    # credential_secret_ref is deliberately excluded from list_display for security
    list_display = (
        "display_name",
        "display_phone_number",
        "organization",
        "phone_number_id",
        "status",
        "credential_mode",
        "verified_at",
        "created_at",
    )
    list_filter = ("status", "credential_mode", "organization")
    search_fields = (
        "display_name",
        "display_phone_number",
        "phone_number_id",
        "organization__name",
    )
    ordering = ("organization", "display_name")
    readonly_fields = ("id", "created_at", "updated_at", "verified_at")

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ("organization",)
        return self.readonly_fields


@admin.register(BranchWhatsAppAssignment)
class BranchWhatsAppAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "branch",
        "whatsapp_account",
        "organization",
        "status",
        "assigned_at",
        "ended_at",
    )
    list_filter = ("status", "organization")
    search_fields = (
        "branch__name",
        "whatsapp_account__display_name",
        "organization__name",
    )
    ordering = ("-assigned_at",)
    readonly_fields = ("id", "assigned_at")
