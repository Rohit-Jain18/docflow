"""
Views for Docflow Human User Authentication APIs (Phase 1, Task 3C).

Implements:
  - GET  /api/v1/auth/csrf: Minimal CSRF bootstrap endpoint setting the standard Django CSRF cookie.
  - POST /api/v1/auth/login: Session-establishing login with CSRF enforcement and IP throttling.
  - POST /api/v1/auth/logout: Session-terminating logout with CSRF enforcement.
  - GET  /api/v1/auth/me: Safe current authenticated user summary.

Conventions:
  - Base path /api/v1; UTF-8 JSON only.
  - Django server-side sessions with secure cookies.
  - Generic authentication failure (never reveals email existence or active status).
  - Explicit rejection of device bearer credentials on human user endpoints.
  - Audit failure logging using permitted platform actions and bounded safe metadata.
"""

import uuid
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.models import BaseUserManager
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction, AuditEvent
from apps.devices.ip_utils import get_client_ip
from apps.devices.throttling import UserLoginRateThrottle
from .authentication import CSRFEnforcedSessionAuthentication
from .serializers import LoginSerializer, LogoutSerializer, UserSummarySerializer


def _get_request_id(request) -> str:
    """Extract or generate request tracking identifier."""
    if request:
        req_id = getattr(request, "request_id", None) or getattr(request, "_request_id", None)
        if req_id:
            return str(req_id)
        header_val = request.headers.get("X-Request-ID") or request.META.get("HTTP_X_REQUEST_ID")
        if header_val:
            return str(header_val).strip()
    return f"req_{uuid.uuid4().hex[:16]}"


class CSRFBootstrapView(APIView):
    """
    GET /api/v1/auth/csrf

    Minimal, unauthenticated endpoint allowing browser clients to acquire
    the standard Django CSRF cookie. Never reveals sensitive data.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request, *args, **kwargs):
        # Force evaluation/setting of the CSRF cookie on response
        get_token(request)
        return Response({"detail": "CSRF cookie set"}, status=status.HTTP_200_OK)


class LoginView(APIView):
    """
    POST /api/v1/auth/login

    Browser human user authentication endpoint.
    Enforces:
      - Valid CSRF protection even for anonymous requests.
      - Hardened IP-based rate limiting via UserLoginRateThrottle.
      - Generic authentication error on unknown email, wrong password, or inactive user.
      - Zero secret/credential leakage in responses or audit logs.
      - Safe server-side session establishment with session fixation protection.
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [UserLoginRateThrottle]

    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        raw_email = serializer.validated_data["email"]
        password = serializer.validated_data["password"]

        # Authenticate with provided email, lowercase, or normalized variant
        user = authenticate(request, username=raw_email, password=password)
        if user is None and raw_email.lower() != raw_email:
            user = authenticate(request, username=raw_email.lower(), password=password)
        if user is None:
            normalized_email = BaseUserManager.normalize_email(raw_email)
            if normalized_email not in (raw_email, raw_email.lower()):
                user = authenticate(request, username=normalized_email, password=password)

        if not user or not user.is_active:
            client_ip = get_client_ip(request)
            request_id = _get_request_id(request)

            # Audit authentication failure as a platform security event
            # Never log raw email input, passwords, or tokens
            AuditEvent.objects.create(
                organization=None,
                action=AuditAction.PLATFORM_SECURITY_FAILURE,
                target_type="user",
                target_id="unknown",
                request_id=request_id,
                safe_metadata={
                    "error_code": "authentication_failed",
                    "failure_reason": "Invalid credentials or inactive user",
                    "ip_address": client_ip or "unknown",
                },
            )
            raise AuthenticationFailed("Invalid credentials.")

        # Establish server-side Django session
        login(request, user)

        summary = UserSummarySerializer(user).data
        return Response(summary, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout

    Invalidates the active human user session.
    Enforces:
      - Authenticated session requirement.
      - Valid CSRF protection.
      - Strict rejection of non-empty request body.
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """
    GET /api/v1/auth/me

    Returns safe user summary for the currently authenticated session user.
    Enforces:
      - Session authentication required.
      - Rejection of device bearer tokens.
      - Safe membership serialization.
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user_model = get_user_model()
        if not isinstance(request.user, user_model):
            raise AuthenticationFailed("Human user session authentication required.")


        summary = UserSummarySerializer(request.user).data
        return Response(summary, status=status.HTTP_200_OK)
