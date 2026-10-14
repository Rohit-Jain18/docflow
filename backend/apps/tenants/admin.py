"""Admin registrations for tenancy models."""
from django.contrib import admin

from .models import Branch, Lab, Organization, OrganizationMembership


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "status", "timezone", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "slug")
    ordering = ("name",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(OrganizationMembership)
class OrganizationMembershipAdmin(admin.ModelAdmin):
    list_display = ("organization", "user", "role", "status", "created_at")
    list_filter = ("role", "status")
    search_fields = ("organization__name", "user__email")
    ordering = ("organization", "user")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Lab)
class LabAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "organization", "lab_type", "status", "created_at")
    list_filter = ("lab_type", "status", "organization")
    search_fields = ("name", "code", "organization__name")
    ordering = ("organization", "name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "lab", "organization", "status", "timezone", "created_at")
    list_filter = ("status", "organization")
    search_fields = ("name", "code", "lab__name", "organization__name")
    ordering = ("organization", "name")
    readonly_fields = ("id", "created_at", "updated_at")
