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
        self.status_code = status_code
        self.code = code or "http_error"
        self.detail = detail or f"HTTP {status_code} error"
        self.request_id = request_id
        self.field_errors = field_errors or {}

        msg = f"HTTP {status_code} ({self.code}): {self.detail}"
        if request_id:
            msg += f" [request_id={request_id}]"
        super().__init__(msg)


class ApiAuthenticationError(ApiResponseError):
    """Raised when authentication fails (HTTP 401) or no access token is available."""

    def __init__(
        self,
        status_code: int = 401,
        code: str | None = "authentication_required",
        detail: str | None = "Authentication is required or credentials are missing/invalid.",
        request_id: str | None = None,
        field_errors: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            code=code,
            detail=detail,
            request_id=request_id,
            field_errors=field_errors,
        )


class ApiPermissionError(ApiResponseError):
    """Raised when authorization fails (HTTP 403 Forbidden)."""

    def __init__(
        self,
        status_code: int = 403,
        code: str | None = "permission_denied",
        detail: str | None = "Permission denied for this operation.",
        request_id: str | None = None,
        field_errors: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            code=code,
            detail=detail,
            request_id=request_id,
            field_errors=field_errors,
        )


class ApiNotFoundError(ApiResponseError):
    """Raised when a resource is not found (HTTP 404 Not Found)."""

    def __init__(
        self,
        status_code: int = 404,
        code: str | None = "not_found",
        detail: str | None = "The requested resource was not found.",
        request_id: str | None = None,
        field_errors: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            code=code,
            detail=detail,
            request_id=request_id,
            field_errors=field_errors,
        )


class ApiConflictError(ApiResponseError):
    """Raised on state or idempotency conflicts (HTTP 409 Conflict)."""

    def __init__(
        self,
        status_code: int = 409,
        code: str | None = "conflict",
        detail: str | None = "Resource conflict or idempotency conflict occurred.",
        request_id: str | None = None,
        field_errors: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            code=code,
            detail=detail,
            request_id=request_id,
            field_errors=field_errors,
        )


class ApiRateLimitError(ApiResponseError):
    """Raised when request is rate limited (HTTP 429 Too Many Requests)."""

    def __init__(
        self,
        status_code: int = 429,
        code: str | None = "rate_limited",
        detail: str | None = "Rate limit exceeded. Please back off.",
        request_id: str | None = None,
        retry_after: float | None = None,
        field_errors: dict[str, Any] | None = None,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(
            status_code=status_code,
            code=code,
            detail=detail,
            request_id=request_id,
            field_errors=field_errors,
        )


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
        if not path_or_url.startswith(("http://", "https://")):
            # Relative path
            cleaned = path_or_url.lstrip("/")
            return f"{self.base_url}/{cleaned}"
        return path_or_url

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

        req_headers = dict(self._default_headers)
        if headers:
            req_headers.update(headers)

        # Handle authentication
        if authenticated:
            if not is_trusted:
                raise UntrustedOriginError(
                    "Refusing to send authenticated request to untrusted origin."
                )

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
            # Predictable, sanitized timeout exception without echoing headers or raw URL query/userinfo
            logger.warning("API request timed out (%s %s): %s", method.upper(), path, type(exc).__name__)
            raise ApiTimeoutError(f"API request timed out: {type(exc).__name__}") from None
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            logger.warning("API connection failed (%s %s): %s", method.upper(), path, type(exc).__name__)
            raise ApiConnectionError(f"API connection failed: {type(exc).__name__}") from None
        except httpx.RequestError as exc:
            logger.warning("API request error (%s %s): %s", method.upper(), path, type(exc).__name__)
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
        """Parse structured error from Django API if available and raise typed exception."""
        status = response.status_code
        request_id = response.headers.get("x-request-id")
        code: str | None = None
        detail: str | None = None
        field_errors: dict[str, Any] | None = None

        with contextlib.suppress(Exception):
            payload = response.json()
            if isinstance(payload, dict):
                code = payload.get("code") or payload.get("error", {}).get("code")
                detail = (
                    payload.get("detail")
                    or payload.get("message")
                    or payload.get("error", {}).get("message")
                )
                request_id = request_id or payload.get("request_id")
                field_errors = payload.get("field_errors")

        if status == 401:
            raise ApiAuthenticationError(
                status_code=401,
                code=code or "authentication_required",
                detail=detail,
                request_id=request_id,
                field_errors=field_errors,
            )
        if status == 403:
            raise ApiPermissionError(
                status_code=403,
                code=code or "permission_denied",
                detail=detail,
                request_id=request_id,
                field_errors=field_errors,
            )
        if status == 404:
            raise ApiNotFoundError(
                status_code=404,
                code=code or "not_found",
                detail=detail,
                request_id=request_id,
                field_errors=field_errors,
            )
        if status == 409:
            raise ApiConflictError(
                status_code=409,
                code=code or "conflict",
                detail=detail,
                request_id=request_id,
                field_errors=field_errors,
            )
        if status == 429:
            retry_after: float | None = None
            if "retry-after" in response.headers:
                with contextlib.suppress(ValueError):
                    retry_after = float(response.headers["retry-after"])
            raise ApiRateLimitError(
                status_code=429,
                code=code or "rate_limited",
                detail=detail,
                request_id=request_id,
                retry_after=retry_after,
                field_errors=field_errors,
            )

        raise ApiResponseError(
            status_code=status,
            code=code or "http_error",
            detail=detail or f"Server returned error HTTP {status}",
            request_id=request_id,
            field_errors=field_errors,
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
