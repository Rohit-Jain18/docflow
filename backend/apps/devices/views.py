"""
DRF Views for Docflow Agent Authentication APIs.

Implements:
  - POST /api/v1/agent/activation/exchange: Initial activation code exchange.
  - POST /api/v1/agent/auth/refresh: Rotating refresh credential exchange.
  - POST /api/v1/agent/auth/revoke-self: Authenticated device self-revocation.

Conventions per API_CONTRACTS.md §§ 1, 2, and 3:
  - Base path /api/v1; UTF-8 JSON only.
  - Device bearer authentication for agent auth endpoints.
  - Zero raw secret/token logging or leakage in errors.
  - Standard error envelope and X-Request-ID propagation.
"""

from typing import Optional

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import DeviceBearerAuthentication
from .serializers import (
    ActivationExchangeSerializer,
    RefreshTokenSerializer,
    RevokeSelfSerializer,
)
from .services import exchange_activation_code, revoke_device, rotate_refresh_token
from .throttling import ActivationRateThrottle, RefreshRateThrottle


def get_client_ip(request) -> Optional[str]:
    """Extract client IP address safely from request metadata."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
        if ip:
            return ip
    return request.META.get("REMOTE_ADDR")


class ActivationExchangeView(APIView):
    """
    POST /api/v1/agent/activation/exchange

    Unauthenticated, rate-limited endpoint for one-time activation code exchange.
    Consumes activation code atomically, activates device, issues signed access token
    and initial rotating refresh credential.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ActivationRateThrottle]

    def post(self, request, *args, **kwargs):
        serializer = ActivationExchangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        client_ip = get_client_ip(request)
        request_id = getattr(request, "request_id", "")

        result = exchange_activation_code(
            activation_code=serializer.validated_data["activation_code"],
            installation_id=serializer.validated_data["installation_id"],
            agent_version=serializer.validated_data.get("agent_version", ""),
            platform=serializer.validated_data.get("platform", "windows"),
            ip_address=client_ip,
            request_id=request_id,
        )

        response_data = {
            "device": {
                "id": str(result.device.id),
                "name": result.device.name,
                "status": result.device.status,
                "branch_id": str(result.device.branch_id),
            },
            "access_token": result.access_token,
            "access_token_expires_at": result.access_token_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "refresh_token": result.refresh_token,
            "refresh_token_expires_at": result.refresh_token_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "configuration_version": result.configuration_version,
        }
        return Response(response_data, status=status.HTTP_201_CREATED)


class RefreshTokenView(APIView):
    """
    POST /api/v1/agent/auth/refresh

    Rate-limited endpoint to rotate an active refresh token and obtain a fresh
    signed access token. Atomically invalidates old token and detects token reuse.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [RefreshRateThrottle]

    def post(self, request, *args, **kwargs):
        serializer = RefreshTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        client_ip = get_client_ip(request)
        request_id = getattr(request, "request_id", "")

        result = rotate_refresh_token(
            refresh_token=serializer.validated_data["refresh_token"],
            ip_address=client_ip,
            request_id=request_id,
        )

        response_data = {
            "access_token": result.access_token,
            "access_token_expires_at": result.access_token_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "refresh_token": result.refresh_token,
            "refresh_token_expires_at": result.refresh_token_expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        return Response(response_data, status=status.HTTP_200_OK)


class RevokeSelfView(APIView):
    """
    POST /api/v1/agent/auth/revoke-self

    Authenticated endpoint allowing an active Device to self-revoke.
    Revokes all outstanding refresh credentials, transitions device to REVOKED,
    and writes safe audit log.
    """

    authentication_classes = [DeviceBearerAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = RevokeSelfSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        client_ip = get_client_ip(request)
        request_id = getattr(request, "request_id", "")

        # request.user is set to the authenticated Device instance by DeviceBearerAuthentication
        revoke_device(
            device=request.user,
            request_id=request_id,
            ip_address=client_ip,
            reason="Device self-revoked",
        )

        return Response(status=status.HTTP_204_NO_CONTENT)
