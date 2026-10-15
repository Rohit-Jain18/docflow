"""
Authenticated HTTP client for the Docflow Windows Agent.

Implements the client requirements specified in docs/AGENT_SPEC.md and docs/API_CONTRACTS.md:
- Uses httpx.Client with finite connect, read, write, and pool timeouts.
- Validates configured API base URL and enforces trusted-origin boundaries.
- Transmits bearer credentials ONLY to the trusted API origin and prevents credential forwarding.
- Handles timeouts, connection failures, HTTP errors, and malformed JSON with predictable sanitized exceptions.
- Zero credential, token, or sensitive data leakage in exception messages, reprs, or logs.
- Supports reliable cleanup and context manager protocol.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import urllib.parse
from collections.abc import Callable
from typing import Any

import httpx

from docflow_agent.config import validate_api_base_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default Timeouts (docs/AGENT_SPEC.md §2 & §8)
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = httpx.Timeout(
    connect=5.0,
    read=15.0,
    write=10.0,
    pool=5.0,
)

# Type alias for token provider function
TokenProvider = Callable[[], str | None]

# ---------------------------------------------------------------------------
# Security and Sanitization Helpers (Task 2D-1a & 2D-1b)
# ---------------------------------------------------------------------------

RECOGNIZED_SAFE_ERROR_CODES: frozenset[str] = frozenset({
    # Documented API contracts (docs/API_CONTRACTS.md §§ 2 & 5)
    "validation_error",
    "authentication_required",
    "permission_denied",
    "not_found",
    "method_not_allowed",
    "conflict",
    "idempotency_conflict",
    "state_conflict",
    "fingerprint_key_mismatch",
    "activation_expired",
    "payload_too_large",
    "unsupported_media_type",
    "account_not_verified",
    "unprocessable_entity",
    "rate_limited",
    "internal_error",
    "server_error",
    "provider_error",
    "provider_unavailable",
    "provider_timeout_ambiguous",
    "reconciliation_required",
    # Documented Agent error/reason codes (docs/AGENT_SPEC.md §§ 5 & 10)
    "source_file_unavailable",
    # General fallback
    "http_error",
})

DEFAULT_STATUS_ERROR_CODES: dict[int, str] = {
    400: "validation_error",
    401: "authentication_required",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "activation_expired",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "account_not_verified",
    429: "rate_limited",
    500: "server_error",
    502: "provider_error",
    503: "provider_unavailable",
    504: "provider_timeout_ambiguous",
}

SAFE_REQUEST_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
SAFE_FIELD_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

SAFE_FIELD_ERROR_TOKENS: frozenset[str] = frozenset({
    "invalid",
    "required",
    "null",
    "blank",
    "unique",
    "max_length",
    "min_length",
    "invalid_choice",
    "invalid_format",
    "not_found",
    "already_exists",
})

GENERIC_SAFE_DETAILS: dict[int, str] = {
    400: "Request failed validation or was malformed.",
    401: "Authentication is required or credentials are missing/invalid.",
    403: "Permission denied for this operation.",
    404: "The requested resource was not found.",
    409: "Resource conflict or idempotency conflict occurred.",
    429: "Rate limit exceeded. Please back off.",
}


def _is_authorization_header(key: Any) -> bool:
    """Check if header key represents an Authorization header case-insensitively."""
    if isinstance(key, bytes):
        try:
            key = key.decode("utf-8", errors="ignore")
        except Exception:
            return False
    return str(key).strip().lower() == "authorization"


def _get_generic_detail(status_code: int) -> str:
    """Return a generic safe detail message for an HTTP status code."""
    if status_code in GENERIC_SAFE_DETAILS:
        return GENERIC_SAFE_DETAILS[status_code]
    if 500 <= status_code <= 599:
        return "Docflow server encountered an internal error."
    return f"Docflow server returned HTTP {status_code} error."


def _get_default_error_code(status_code: int) -> str:
    """Return a safe default error code for an HTTP status code."""
    if status_code in DEFAULT_STATUS_ERROR_CODES:
        return DEFAULT_STATUS_ERROR_CODES[status_code]
    if 500 <= status_code <= 599:
        return "server_error"
    return "http_error"


def _sanitize_error_code(raw_code: Any, default: str) -> str:
    """Validate that error code is a recognized, documented safe code; otherwise return default."""
    if isinstance(raw_code, str):
        cleaned = raw_code.strip().lower()
        if cleaned in RECOGNIZED_SAFE_ERROR_CODES:
            return cleaned
    return default


def _sanitize_request_id(raw_id: Any) -> str | None:
    """Validate and bound request ID to safe alphanumeric tokens."""
    if isinstance(raw_id, str):
        cleaned = raw_id.strip()
        if SAFE_REQUEST_ID_PATTERN.fullmatch(cleaned):
            return cleaned
    return None


def _sanitize_field_errors(raw_field_errors: Any) -> dict[str, list[str]]:
    """Sanitize structured field errors so arbitrary strings or PII cannot leak."""
    if not isinstance(raw_field_errors, dict):
        return {}

    sanitized: dict[str, list[str]] = {}
    for raw_key, raw_val in raw_field_errors.items():
        if not isinstance(raw_key, str) or not SAFE_FIELD_NAME_PATTERN.fullmatch(raw_key.strip()):
            continue
        field_name = raw_key.strip()

        tokens: list[str] = []
        if isinstance(raw_val, (list, tuple)):
            for item in raw_val:
                item_str = str(item).strip().lower() if item is not None else ""
                if item_str in SAFE_FIELD_ERROR_TOKENS:
                    tokens.append(item_str)
                else:
                    tokens.append("invalid")
        elif isinstance(raw_val, str):
            item_str = raw_val.strip().lower()
            if item_str in SAFE_FIELD_ERROR_TOKENS:
                tokens.append(item_str)
            else:
                tokens.append("invalid")
        else:
            tokens.append("invalid")

        sanitized[field_name] = tokens or ["invalid"]

    return sanitized


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ApiClientError(Exception):
    """Base exception for all Docflow API client errors."""


class ApiConnectionError(ApiClientError):
    """Raised when a network connection failure or DNS error occurs."""


class ApiTimeoutError(ApiClientError):
    """Raised when an HTTP operation times out (connect, read, write)."""


class ApiPayloadError(ApiClientError):
    """Raised when a server response contains malformed or non-JSON content."""


class UntrustedOriginError(ApiClientError):
    """Raised when an authenticated request is directed to an untrusted origin."""


class ApiResponseError(ApiClientError):
    """Raised when the Docflow server returns an HTTP error status code (4xx, 5xx)."""

    def __init__(
        self,
        status_code: int,
        code: str | None = None,
        detail: str | None = None,
        request_id: str | None = None,
        field_errors: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = int(status_code)
        default_code = _get_default_error_code(self.status_code)
        self.code = _sanitize_error_code(code, default=default_code)
        self.detail = detail or _get_generic_detail(self.status_code)
        self.request_id = _sanitize_request_id(request_id)
        self.field_errors = _sanitize_field_errors(field_errors)

        msg = f"HTTP {self.status_code} ({self.code}): {self.detail}"
        if self.request_id:
            msg += f" [request_id={self.request_id}]"
        super().__init__(msg)

    def __repr__(self) -> str:
        parts = [f"status_code={self.status_code}", f"code={self.code!r}"]
        if self.request_id:
            parts.append(f"request_id={self.request_id!r}")
        return f"{self.__class__.__name__}({', '.join(parts)})"


class ApiAuthenticationError(ApiResponseError):
    """Raised when authentication fails (HTTP 401) or no access token is available."""

    def __init__(
        self,
        status_code: int = 401,
        code: str | None = "authentication_required",
        detail: str | None = None,
        request_id: str | None = None,
        field_errors: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            code=code or "authentication_required",
            detail=detail or _get_generic_detail(401),
            request_id=request_id,
            field_errors=field_errors,
        )


class ApiPermissionError(ApiResponseError):
    """Raised when authorization fails (HTTP 403 Forbidden)."""

    def __init__(
        self,
        status_code: int = 403,
        code: str | None = "permission_denied",
        detail: str | None = None,
        request_id: str | None = None,
        field_errors: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            code=code or "permission_denied",
            detail=detail or _get_generic_detail(403),
            request_id=request_id,
            field_errors=field_errors,
        )


class ApiNotFoundError(ApiResponseError):
    """Raised when a resource is not found (HTTP 404 Not Found)."""

    def __init__(
        self,
        status_code: int = 404,
        code: str | None = "not_found",
        detail: str | None = None,
        request_id: str | None = None,
        field_errors: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            code=code or "not_found",
            detail=detail or _get_generic_detail(404),
            request_id=request_id,
            field_errors=field_errors,
        )


class ApiConflictError(ApiResponseError):
    """Raised on state or idempotency conflicts (HTTP 409 Conflict)."""

    def __init__(
        self,
        status_code: int = 409,
        code: str | None = "conflict",
        detail: str | None = None,
        request_id: str | None = None,
        field_errors: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            code=code or "conflict",
            detail=detail or _get_generic_detail(409),
            request_id=request_id,
            field_errors=field_errors,
        )


class ApiRateLimitError(ApiResponseError):
    """Raised when request is rate limited (HTTP 429 Too Many Requests)."""

    def __init__(
        self,
        status_code: int = 429,
        code: str | None = "rate_limited",
        detail: str | None = None,
        request_id: str | None = None,
        retry_after: float | None = None,
        field_errors: dict[str, Any] | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(
            status_code=status_code,
            code=code or "rate_limited",
            detail=detail or _get_generic_detail(429),
            request_id=request_id,
            field_errors=field_errors,
        )

    def __repr__(self) -> str:
        parts = [f"status_code={self.status_code}", f"code={self.code!r}"]
        if self.request_id:
            parts.append(f"request_id={self.request_id!r}")
        if self.retry_after is not None:
            parts.append(f"retry_after={self.retry_after!r}")
        return f"{self.__class__.__name__}({', '.join(parts)})"


# ---------------------------------------------------------------------------
# Authenticated API Client
# ---------------------------------------------------------------------------

class ApiClient:
    """HTTP client communicating with the Docflow API using finite timeouts,
    trusted-origin enforcement, and strict secret protection."""

    def __init__(
        self,
        base_url: str,
        *,
        token_provider: TokenProvider | None = None,
        timeout: httpx.Timeout | float | None = None,
        http_client: httpx.Client | None = None,
        agent_version: str = "0.1.0",
    ) -> None:
        # Validate base URL using existing security rules
        errors = validate_api_base_url(base_url)
        if errors:
            raise ApiClientError(f"Invalid API base URL: {errors[0]}")

        self.base_url = base_url.strip().rstrip("/")
        self.token_provider = token_provider
        self.agent_version = agent_version

        # Compute trusted origin tuple (scheme, hostname, port)
        parsed = urllib.parse.urlsplit(self.base_url)
        self.trusted_origin: tuple[str, str, int | None] = (
            parsed.scheme.lower(),
            (parsed.hostname or "").lower(),
            parsed.port,
        )

        # Timeout configuration
        if timeout is None:
            self._timeout = DEFAULT_TIMEOUT
        elif isinstance(timeout, (int, float)):
            self._timeout = httpx.Timeout(timeout)
        else:
            self._timeout = timeout

        # Shared default headers (never include tokens by default here)
        self._default_headers = {
            "Accept": "application/json",
            "User-Agent": f"DocflowAgent/{self.agent_version}",
        }

        # Underlying HTTP client
        self._owns_http_client = http_client is None
        if http_client is not None:
            self._client = http_client
        else:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=self._timeout,
                headers=self._default_headers,
                follow_redirects=False,  # Security: prevent automatic cross-origin credential leaks
            )

    def is_trusted_origin(self, url: str) -> bool:
        """Check whether a target URL belongs to the configured trusted API origin."""
        if not url:
            return False
        parsed = urllib.parse.urlsplit(url)
        # If relative URL, it belongs to the base origin
        if not parsed.scheme and not parsed.netloc:
            return True
        target_origin = (
            parsed.scheme.lower(),
            (parsed.hostname or "").lower(),
            parsed.port,
        )
        return target_origin == self.trusted_origin

    def _resolve_url(self, path_or_url: str) -> str:
        """Resolve a path or URL, ensuring no query/userinfo injection on relative paths."""
        parsed = urllib.parse.urlsplit(path_or_url)
        if parsed.scheme.lower() in ("http", "https"):
            return path_or_url
        cleaned = path_or_url.lstrip("/")
        return f"{self.base_url}/{cleaned}"

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> Any:
        """Execute an HTTP request, handle errors safely, and parse JSON response.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH).
            path: Target endpoint path (relative to base_url) or full URL.
            json: Optional JSON body.
            params: Optional query parameters.
            headers: Optional additional headers.
            authenticated: Whether to attach Bearer credentials.

        Returns:
            Parsed JSON object/array from response, or None on 204 No Content.
        """
        target_url = self._resolve_url(path)
        is_trusted = self.is_trusted_origin(target_url)

        # Detect caller-supplied Authorization header (case-insensitive)
        has_caller_auth = bool(headers) and any(
            _is_authorization_header(k) for k in headers
        )

        # Security (Task 2D-1a Requirement 1): Never send an Authorization header to an origin
        # other than the configured trusted API origin, regardless of authenticated=True/False.
        # Prevent callers from bypassing origin validation by supplying their own Authorization header.
        # Reject unsafe requests before making any network call.
        if (authenticated or has_caller_auth) and not is_trusted:
            raise UntrustedOriginError(
                "Refusing to send credentials or authorization headers to untrusted origin."
            )

        req_headers = dict(self._default_headers)
        if headers:
            req_headers.update(headers)

        # Handle authentication
        if authenticated:
            if self.token_provider is None:
                raise ApiAuthenticationError(
                    status_code=401,
                    code="authentication_required",
                    detail="No token provider configured for authenticated request.",
                )

            token = self.token_provider()
            if not token or not str(token).strip():
                raise ApiAuthenticationError(
                    status_code=401,
                    code="authentication_required",
                    detail="No access token available for authenticated request.",
                )

            # Strip any manual authorization headers to prevent duplicate/conflicting headers
            for k in list(req_headers.keys()):
                if _is_authorization_header(k):
                    del req_headers[k]

            req_headers["Authorization"] = f"Bearer {str(token).strip()}"

        try:
            response = self._client.request(
                method=method.upper(),
                url=target_url,
                json=json,
                params=params,
                headers=req_headers,
            )
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
            # Security (Task 2D-1a Requirement 2): Never log caller-supplied path or full URL.
            # Log only safe metadata: HTTP method, fixed event label, and exception type.
            logger.warning("API request timed out (%s): %s", method.upper(), type(exc).__name__)
            raise ApiTimeoutError(f"API request timed out: {type(exc).__name__}") from None
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            logger.warning("API connection failed (%s): %s", method.upper(), type(exc).__name__)
            raise ApiConnectionError(f"API connection failed: {type(exc).__name__}") from None
        except httpx.RequestError as exc:
            logger.warning("API request error (%s): %s", method.upper(), type(exc).__name__)
            raise ApiConnectionError(f"API request error: {type(exc).__name__}") from None

        # Handle HTTP error responses
        if response.is_error:
            self._handle_error_response(response)

        # Handle successful response
        if response.status_code == 204 or not response.content:
            return None

        try:
            return response.json()
        except Exception:
            raise ApiPayloadError(
                f"Server returned non-JSON response with HTTP {response.status_code}."
            ) from None

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Parse structured error from Django API if available and raise typed exception.

        Security (Task 2D-1a Requirement 3):
        - Do not copy raw server response details or arbitrary field-error values into
          exception messages, representations, or logs.
        - Keep safe, useful metadata: HTTP status, validated bounded error code, and request ID.
        - Use generic safe details for exceptions.
        - Structured field errors values are sanitized to generic safe tokens.
        - Do not log response bodies.
        """
        status = response.status_code
        request_id = response.headers.get("x-request-id")
        raw_code: Any = None
        raw_field_errors: Any = None

        with contextlib.suppress(Exception):
            payload = response.json()
            if isinstance(payload, dict):
                raw_code = payload.get("code") or payload.get("error", {}).get("code")
                request_id = request_id or payload.get("request_id")
                raw_field_errors = payload.get("field_errors")

        safe_detail = _get_generic_detail(status)
        safe_req_id = _sanitize_request_id(request_id)
        sanitized_fields = _sanitize_field_errors(raw_field_errors)

        if status == 401:
            safe_code = _sanitize_error_code(raw_code, default="authentication_required")
            raise ApiAuthenticationError(
                status_code=401,
                code=safe_code,
                detail=safe_detail,
                request_id=safe_req_id,
                field_errors=sanitized_fields,
            )
        if status == 403:
            safe_code = _sanitize_error_code(raw_code, default="permission_denied")
            raise ApiPermissionError(
                status_code=403,
                code=safe_code,
                detail=safe_detail,
                request_id=safe_req_id,
                field_errors=sanitized_fields,
            )
        if status == 404:
            safe_code = _sanitize_error_code(raw_code, default="not_found")
            raise ApiNotFoundError(
                status_code=404,
                code=safe_code,
                detail=safe_detail,
                request_id=safe_req_id,
                field_errors=sanitized_fields,
            )
        if status == 409:
            safe_code = _sanitize_error_code(raw_code, default="conflict")
            raise ApiConflictError(
                status_code=409,
                code=safe_code,
                detail=safe_detail,
                request_id=safe_req_id,
                field_errors=sanitized_fields,
            )
        if status == 429:
            safe_code = _sanitize_error_code(raw_code, default="rate_limited")
            retry_after: float | None = None
            if "retry-after" in response.headers:
                with contextlib.suppress(ValueError):
                    retry_after = float(response.headers["retry-after"])
            raise ApiRateLimitError(
                status_code=429,
                code=safe_code,
                detail=safe_detail,
                request_id=safe_req_id,
                retry_after=retry_after,
                field_errors=sanitized_fields,
            )

        default_code = _get_default_error_code(status)
        safe_code = _sanitize_error_code(raw_code, default=default_code)
        raise ApiResponseError(
            status_code=status,
            code=safe_code,
            detail=safe_detail,
            request_id=safe_req_id,
            field_errors=sanitized_fields,
        )

    # Convenience HTTP methods
    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> Any:
        """Perform a GET request."""
        return self.request("GET", path, params=params, headers=headers, authenticated=authenticated)

    def post(
        self,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> Any:
        """Perform a POST request."""
        return self.request("POST", path, json=json, params=params, headers=headers, authenticated=authenticated)

    def put(
        self,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> Any:
        """Perform a PUT request."""
        return self.request("PUT", path, json=json, params=params, headers=headers, authenticated=authenticated)

    def patch(
        self,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> Any:
        """Perform a PATCH request."""
        return self.request("PATCH", path, json=json, params=params, headers=headers, authenticated=authenticated)

    def delete(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> Any:
        """Perform a DELETE request."""
        return self.request("DELETE", path, params=params, headers=headers, authenticated=authenticated)

    def close(self) -> None:
        """Close the underlying HTTP client if owned."""
        if self._owns_http_client:
            self._client.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
