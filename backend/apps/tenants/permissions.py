"""
Permissions for Docflow Tenant APIs (Phase 1, Task 3D).

Enforces:
  - Active human user session authentication only.
  - Explicit rejection of device bearer tokens.
  - Platform administrator authorization checks.
"""

from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission


class IsAuthenticatedHumanUser(BasePermission):
    """
    Ensures the request is authenticated via an active human user session.
    Explicitly rejects device bearer tokens or non-human user representations.
    """

    def has_permission(self, request, view):
        auth_header = (
            request.headers.get("Authorization")
            or request.META.get("HTTP_AUTHORIZATION", "")
        )
        if auth_header.strip().startswith("Bearer "):
            raise AuthenticationFailed("Device bearer tokens are not accepted for human user endpoints.")

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        user_model = get_user_model()
        if not isinstance(user, user_model):
            return False

        if not user.is_active:
            return False

        return True


class IsPlatformAdmin(BasePermission):
    """
    Requires the authenticated user to be a platform administrator.
    """

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "is_platform_admin", False)
        )
