"""
DRF Exception Handler for Docflow APIs.

Enforces:
  - Standard error envelope per API_CONTRACTS.md §§ 1 and 2.
  - Consistent X-Request-ID propagation on all error responses.
  - Safe error codes and messages with zero stack trace or secret leakage.
  - Mapping of domain service errors to HTTP status codes.
"""

import uuid
from typing import Any, Dict, Optional

from rest_framework import status
from rest_framework.exceptions import APIException, Throttled
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .services import (
    ActivationAttemptLimitError,
    ActivationCodeConsumedError,
    ActivationCodeExpiredError,
    ActivationCodeRevokedError,
    IneligibleDeviceError,
    InvalidActivationCodeError,
    InvalidRefreshTokenError,
    RefreshTokenReuseError,
)

ERROR_TITLES: Dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "Validation failed",
    status.HTTP_401_UNAUTHORIZED: "Authentication required",
    status.HTTP_403_FORBIDDEN: "Permission denied",
    status.HTTP_404_NOT_FOUND: "Not found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "Method not allowed",
    status.HTTP_409_CONFLICT: "State conflict",
    status.HTTP_410_GONE: "Activation expired",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "Unsupported media type",
    status.HTTP_422_UNPROCESSABLE_ENTITY: "Unprocessable entity",
    status.HTTP_429_TOO_MANY_REQUESTS: "Rate limited",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "Internal server error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "Provider unavailable",
}

DEFAULT_ERROR_CODES: Dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "validation_error",
    status.HTTP_401_UNAUTHORIZED: "authentication_required",
    status.HTTP_403_FORBIDDEN: "permission_denied",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "state_conflict",
    status.HTTP_410_GONE: "activation_expired",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
    status.HTTP_422_UNPROCESSABLE_ENTITY: "unprocessable_entity",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "internal_error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "provider_unavailable",
}


def _get_request_id(request) -> str:
    if request:
        req_id = getattr(request, "request_id", None) or getattr(request, "_request_id", None)
        if req_id:
            return str(req_id)
        header_val = request.headers.get("X-Request-ID") or request.META.get("HTTP_X_REQUEST_ID")
        if header_val:
            return str(header_val).strip()
    return f"req_{uuid.uuid4().hex[:16]}"


def api_exception_handler(exc: Exception, context: Dict[str, Any]) -> Optional[Response]:
    """
    Transform all view exceptions into the standard Docflow error envelope:
    {
      "type": "about:blank",
      "title": "<Safe title>",
      "status": <http_status_code>,
      "code": "<documented_code>",
      "detail": "<Safe human description>",
      "request_id": "<opaque_id>",
      "field_errors": { ... }  # optional
    }
    """
    request = context.get("request")
    request_id = _get_request_id(request)

    # 1. Handle device domain exceptions
    if isinstance(
        exc,
        (
            ActivationCodeExpiredError,
            ActivationCodeRevokedError,
            ActivationCodeConsumedError,
            ActivationAttemptLimitError,
        ),
    ):
        data = {
            "type": "about:blank",
            "title": "Activation expired",
            "status": status.HTTP_410_GONE,
            "code": "activation_expired",
            "detail": "The activation code has expired, been revoked, or already consumed.",
            "request_id": request_id,
        }
        res = Response(data, status=status.HTTP_410_GONE)
        res["X-Request-ID"] = request_id
        return res

    if isinstance(exc, InvalidActivationCodeError):
        data = {
            "type": "about:blank",
            "title": "Validation failed",
            "status": status.HTTP_400_BAD_REQUEST,
            "code": "validation_error",
            "detail": "Invalid activation code.",
            "request_id": request_id,
        }
        res = Response(data, status=status.HTTP_400_BAD_REQUEST)
        res["X-Request-ID"] = request_id
        return res

    if isinstance(exc, IneligibleDeviceError):
        data = {
            "type": "about:blank",
            "title": "Validation failed",
            "status": status.HTTP_400_BAD_REQUEST,
            "code": "validation_error",
            "detail": "Device is ineligible for activation.",
            "request_id": request_id,
        }
        res = Response(data, status=status.HTTP_400_BAD_REQUEST)
        res["X-Request-ID"] = request_id
        return res

    if isinstance(exc, RefreshTokenReuseError):
        data = {
            "type": "about:blank",
            "title": "State conflict",
            "status": status.HTTP_409_CONFLICT,
            "code": "state_conflict",
            "detail": "Rotated refresh token reuse detected. All active credentials have been revoked.",
            "request_id": request_id,
        }
        res = Response(data, status=status.HTTP_409_CONFLICT)
        res["X-Request-ID"] = request_id
        return res

    if isinstance(exc, InvalidRefreshTokenError):
        data = {
            "type": "about:blank",
            "title": "Authentication required",
            "status": status.HTTP_401_UNAUTHORIZED,
            "code": "authentication_required",
            "detail": "Invalid or revoked refresh credential.",
            "request_id": request_id,
        }
        res = Response(data, status=status.HTTP_401_UNAUTHORIZED)
        res["X-Request-ID"] = request_id
        return res

    # 2. Delegate to DRF default exception handler
    response = drf_exception_handler(exc, context)

    if response is not None:
        status_code = response.status_code
        title = ERROR_TITLES.get(status_code, "Error")
        code = DEFAULT_ERROR_CODES.get(status_code, "error")

        detail = "One or more fields are invalid."
        field_errors = None

        if isinstance(exc, Throttled):
            detail = str(exc.detail) if hasattr(exc, "detail") else "Request was throttled."
            if exc.wait:
                response["Retry-After"] = str(int(exc.wait))
        elif isinstance(response.data, dict):
            if "detail" in response.data and len(response.data) == 1:
                detail = str(response.data["detail"])
            else:
                field_errors = {}
                for k, v in response.data.items():
                    if k == "detail" and not field_errors:
                        detail = str(v)
                    elif isinstance(v, list):
                        field_errors[k] = [str(item) for item in v]
                    elif isinstance(v, dict):
                        field_errors[k] = [f"{subk}: {subv}" for subk, subv in v.items()]
                    else:
                        field_errors[k] = [str(v)]
        elif isinstance(response.data, list):
            detail = "; ".join(str(item) for item in response.data)

        envelope: Dict[str, Any] = {
            "type": "about:blank",
            "title": title,
            "status": status_code,
            "code": code,
            "detail": detail,
            "request_id": request_id,
        }
        if field_errors:
            envelope["field_errors"] = field_errors

        response.data = envelope
        response["X-Request-ID"] = request_id
        return response

    # 3. Handle unexpected internal exceptions safely without leaking stack traces or secrets
    data = {
        "type": "about:blank",
        "title": "Internal server error",
        "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
        "code": "internal_error",
        "detail": "An unexpected error occurred.",
        "request_id": request_id,
    }
    res = Response(data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    res["X-Request-ID"] = request_id
    return res
