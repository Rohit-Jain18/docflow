"""
DRF Authentication backend for Docflow Agent devices.

Authenticates client requests via short-lived signed Bearer tokens per
API_CONTRACTS.md §1 and SECURITY.md §3.
"""

from django.core.exceptions import ValidationError
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from .models import Device, DeviceStatus
from .services import verify_access_token


class DeviceBearerAuthentication(BaseAuthentication):
    """
    Authenticate a Device via short-lived signed Bearer token.

    Validates:
      - Bearer token cryptographic signature and expiry via verify_access_token.
      - Device existence and active status (rejects pending, revoked, and disabled).
      - Cross-tenant consistency between token claims and persisted device record.

    Returns:
      (device, token) where device.is_authenticated is True.
    """

    keyword = "Bearer"

    def authenticate(self, request):
        auth_header = get_authorization_header(request).split()

        if not auth_header:
            return None

        if auth_header[0].lower() != self.keyword.lower().encode():
            return None

        if len(auth_header) == 1:
            raise AuthenticationFailed("Invalid authorization header: Bearer token missing.")
        elif len(auth_header) > 2:
            raise AuthenticationFailed("Invalid authorization header: extra fields present.")

        try:
            token = auth_header[1].decode("utf-8")
        except UnicodeDecodeError:
            raise AuthenticationFailed("Invalid authorization header: token contains invalid characters.")

        try:
            payload = verify_access_token(token)
        except ValidationError as e:
            error_msg = e.messages[0] if hasattr(e, "messages") and e.messages else str(e)
            raise AuthenticationFailed(error_msg)

        device_id = payload.get("device_id")
        if not device_id:
            raise AuthenticationFailed("Invalid token payload: missing device identity.")

        try:
            device = (
                Device.objects.select_related("organization", "branch")
                .filter(id=device_id)
                .first()
            )
        except Exception:
            raise AuthenticationFailed("Failed to query device record.")

        if not device:
            raise AuthenticationFailed("Device record not found.")

        if device.status != DeviceStatus.ACTIVE:
            raise AuthenticationFailed(f"Device is {device.status}.")

        # Enforce consistency between token claims and persisted device state
        if payload.get("organization_id") != str(device.organization_id):
            raise AuthenticationFailed("Device organization does not match token claim.")

        if payload.get("branch_id") != str(device.branch_id):
            raise AuthenticationFailed("Device branch does not match token claim.")

        return (device, token)

    def authenticate_header(self, request):
        return self.keyword
