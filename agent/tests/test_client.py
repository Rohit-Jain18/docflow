"""Tests for docflow_agent.client — Authenticated HTTP client with origin validation and error handling."""

from __future__ import annotations

import logging
from typing import Any
import pytest
import httpx

from docflow_agent.client import (
    ApiClient,
    ApiClientError,
    ApiAuthenticationError,
    ApiConflictError,
    ApiConnectionError,
    ApiNotFoundError,
    ApiPayloadError,
    ApiPermissionError,
    ApiRateLimitError,
    ApiResponseError,
    ApiTimeoutError,
    UntrustedOriginError,
)


class TestClientInitializationAndOriginValidation:
    """Tests for base URL validation, origin trust, and client cleanup."""

    def test_valid_loopback_http_allowed(self) -> None:
        client = ApiClient("http://127.0.0.1:8000")
        assert client.base_url == "http://127.0.0.1:8000"
        assert client.is_trusted_origin("http://127.0.0.1:8000/api/v1/agent/config") is True
        client.close()

    def test_valid_https_allowed(self) -> None:
        client = ApiClient("https://api.docflow.example.com")
        assert client.base_url == "https://api.docflow.example.com"
        assert client.is_trusted_origin("https://api.docflow.example.com/api/v1") is True
        client.close()

    def test_invalid_base_url_fails_fast(self) -> None:
        # Non-loopback plain HTTP forbidden
        with pytest.raises(ApiClientError):
            ApiClient("http://insecure.example.com")

        # Userinfo in URL forbidden
        with pytest.raises(ApiClientError):
            ApiClient("https://user:pass@api.docflow.example.com")

        # Query parameters in base URL forbidden
        with pytest.raises(ApiClientError):
            ApiClient("https://api.docflow.example.com?token=123")

    def test_origin_validation_detects_untrusted_origins(self) -> None:
        client = ApiClient("https://api.docflow.example.com:8443")
        try:
            # Same origin
            assert client.is_trusted_origin("https://api.docflow.example.com:8443/api") is True
            assert client.is_trusted_origin("/relative/path") is True

            # Different port
            assert client.is_trusted_origin("https://api.docflow.example.com:443/api") is False
            # Different scheme
            assert client.is_trusted_origin("http://api.docflow.example.com:8443/api") is False
            # Different host
            assert client.is_trusted_origin("https://evil.example.com:8443/api") is False
        finally:
            client.close()

    def test_explicit_client_cleanup_and_context_manager(self) -> None:
        with ApiClient("https://api.docflow.example.com") as client:
            assert client._client.is_closed is False
        assert client._client.is_closed is True


class TestAuthenticatedRequests:
    """Tests for token attachment, headers, and request execution."""

    def test_successful_authenticated_json_request(self) -> None:
        captured_request: httpx.Request | None = None

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(
                status_code=200,
                headers={"Content-Type": "application/json"},
                json={"device_id": "dev-123", "status": "active"},
            )

        mock_transport = httpx.MockTransport(mock_handler)
        mock_http_client = httpx.Client(
            base_url="https://api.docflow.example.com",
            transport=mock_transport,
        )

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            token_provider=lambda: "secret_access_token_xyz",
            http_client=mock_http_client,
        )

        resp = client.get("/api/v1/agent/config")

        assert resp == {"device_id": "dev-123", "status": "active"}
        assert captured_request is not None
        assert captured_request.method == "GET"
        assert captured_request.headers["Authorization"] == "Bearer secret_access_token_xyz"
        assert captured_request.headers["Accept"] == "application/json"
        assert "DocflowAgent/" in captured_request.headers["User-Agent"]

    def test_authenticated_request_with_json_body(self) -> None:
        captured_request: httpx.Request | None = None

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(
                status_code=202,
                json={"report_id": "rep-001", "status": "queued"},
            )

        mock_transport = httpx.MockTransport(mock_handler)
        mock_http_client = httpx.Client(
            base_url="https://api.docflow.example.com",
            transport=mock_transport,
        )

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            token_provider=lambda: "token_123",
            http_client=mock_http_client,
        )

        payload = {"recipient_phone_e164": "+919876543210", "file_size_bytes": 1024}
        resp = client.post("/api/v1/agent/reports", json=payload)

        assert resp == {"report_id": "rep-001", "status": "queued"}
        assert captured_request is not None
        assert captured_request.method == "POST"
        assert b"+919876543210" in captured_request.content

    def test_unauthenticated_request_does_not_attach_credentials(self) -> None:
        captured_request: httpx.Request | None = None

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(status_code=200, json={"status": "ok"})

        mock_transport = httpx.MockTransport(mock_handler)
        mock_http_client = httpx.Client(
            base_url="https://api.docflow.example.com",
            transport=mock_transport,
        )

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            token_provider=lambda: "should_not_be_attached",
            http_client=mock_http_client,
        )

        resp = client.post(
            "/api/v1/agent/activation/exchange",
            json={"activation_code": "one-time-code"},
            authenticated=False,
        )

        assert resp == {"status": "ok"}
        assert captured_request is not None
        assert "Authorization" not in captured_request.headers

    def test_missing_or_empty_token_raises_authentication_error(self) -> None:
        # Case 1: No token provider supplied
        client_no_provider = ApiClient("https://api.docflow.example.com")
        with pytest.raises(ApiAuthenticationError) as exc_info:
            client_no_provider.get("/api/v1/agent/config")
        assert "No token provider configured" in str(exc_info.value)
        client_no_provider.close()

        # Case 2: Token provider returns None
        client_none_token = ApiClient(
            "https://api.docflow.example.com",
            token_provider=lambda: None,
        )
        with pytest.raises(ApiAuthenticationError) as exc_info2:
            client_none_token.get("/api/v1/agent/config")
        assert "No access token available" in str(exc_info2.value)
        client_none_token.close()

        # Case 3: Token provider returns empty string
        client_empty_token = ApiClient(
            "https://api.docflow.example.com",
            token_provider=lambda: "   ",
        )
        with pytest.raises(ApiAuthenticationError):
            client_empty_token.get("/api/v1/agent/config")
        client_empty_token.close()

    def test_blocking_credential_forwarding_to_untrusted_origin(self) -> None:
        client = ApiClient(
            base_url="https://api.docflow.example.com",
            token_provider=lambda: "sensitive_token_999",
        )
        try:
            with pytest.raises(UntrustedOriginError):
                client.get("https://untrusted-host.example.com/api/data", authenticated=True)
        finally:
            client.close()


class TestErrorAndTimeoutHandling:
    """Tests for connection failures, timeouts, HTTP status errors, and malformed responses."""

    def test_connect_timeout_raises_api_timeout_error(self) -> None:
        def mock_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("Connect timeout error")

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            http_client=httpx.Client(
                base_url="https://api.docflow.example.com",
                transport=httpx.MockTransport(mock_handler),
            ),
        )
        with pytest.raises(ApiTimeoutError):
            client.get("/api/test", authenticated=False)

    def test_read_timeout_raises_api_timeout_error(self) -> None:
        def mock_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Read timeout error")

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            http_client=httpx.Client(
                base_url="https://api.docflow.example.com",
                transport=httpx.MockTransport(mock_handler),
            ),
        )
        with pytest.raises(ApiTimeoutError):
            client.get("/api/test", authenticated=False)

    def test_connection_error_raises_api_connection_error(self) -> None:
        def mock_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Failed to resolve hostname")

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            http_client=httpx.Client(
                base_url="https://api.docflow.example.com",
                transport=httpx.MockTransport(mock_handler),
            ),
        )
        with pytest.raises(ApiConnectionError):
            client.get("/api/test", authenticated=False)

    def test_http_400_validation_error_parsing(self) -> None:
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=400,
                headers={"X-Request-ID": "req-12345"},
                json={
                    "code": "validation_error",
                    "detail": "One or more fields are invalid.",
                    "field_errors": {"content_sha256": ["Invalid hash format."]},
                },
            )

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            http_client=httpx.Client(
                base_url="https://api.docflow.example.com",
                transport=httpx.MockTransport(mock_handler),
            ),
        )
        with pytest.raises(ApiResponseError) as exc_info:
            client.post("/api/test", json={}, authenticated=False)

        err = exc_info.value
        assert err.status_code == 400
        assert err.code == "validation_error"
        assert "One or more fields are invalid." in err.detail
        assert err.request_id == "req-12345"
        assert "content_sha256" in err.field_errors

    def test_http_401_raises_api_authentication_error(self) -> None:
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=401,
                json={"code": "authentication_required", "detail": "Token expired."},
            )

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            token_provider=lambda: "expired_token",
            http_client=httpx.Client(
                base_url="https://api.docflow.example.com",
                transport=httpx.MockTransport(mock_handler),
            ),
        )
        with pytest.raises(ApiAuthenticationError) as exc_info:
            client.get("/api/test")
        assert exc_info.value.status_code == 401
        assert exc_info.value.code == "authentication_required"

    def test_http_403_raises_api_permission_error(self) -> None:
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=403,
                json={"code": "permission_denied", "detail": "Device is revoked."},
            )

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            token_provider=lambda: "revoked_token",
            http_client=httpx.Client(
                base_url="https://api.docflow.example.com",
                transport=httpx.MockTransport(mock_handler),
            ),
        )
        with pytest.raises(ApiPermissionError) as exc_info:
            client.get("/api/test")
        assert exc_info.value.status_code == 403

    def test_http_404_raises_api_not_found_error(self) -> None:
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=404,
                json={"code": "not_found", "detail": "Report missing."},
            )

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            token_provider=lambda: "valid_token",
            http_client=httpx.Client(
                base_url="https://api.docflow.example.com",
                transport=httpx.MockTransport(mock_handler),
            ),
        )
        with pytest.raises(ApiNotFoundError) as exc_info:
            client.get("/api/reports/123")
        assert exc_info.value.status_code == 404

    def test_http_409_raises_api_conflict_error(self) -> None:
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=409,
                json={"code": "idempotency_conflict", "detail": "Key reused with different body."},
            )

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            token_provider=lambda: "valid_token",
            http_client=httpx.Client(
                base_url="https://api.docflow.example.com",
                transport=httpx.MockTransport(mock_handler),
            ),
        )
        with pytest.raises(ApiConflictError) as exc_info:
            client.post("/api/reports", json={})
        assert exc_info.value.status_code == 409
        assert exc_info.value.code == "idempotency_conflict"

    def test_http_429_rate_limited_with_retry_after(self) -> None:
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=429,
                headers={"Retry-After": "45.0"},
                json={"code": "rate_limited", "detail": "Too many requests."},
            )

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            token_provider=lambda: "valid_token",
            http_client=httpx.Client(
                base_url="https://api.docflow.example.com",
                transport=httpx.MockTransport(mock_handler),
            ),
        )
        with pytest.raises(ApiRateLimitError) as exc_info:
            client.post("/api/reports", json={})
        assert exc_info.value.status_code == 429
        assert exc_info.value.retry_after == 45.0

    def test_malformed_json_response_raises_api_payload_error(self) -> None:
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=200,
                headers={"Content-Type": "text/html"},
                content=b"<html><body>502 Bad Gateway</body></html>",
            )

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            token_provider=lambda: "valid_token",
            http_client=httpx.Client(
                base_url="https://api.docflow.example.com",
                transport=httpx.MockTransport(mock_handler),
            ),
        )
        with pytest.raises(ApiPayloadError) as exc_info:
            client.get("/api/data")
        assert "non-JSON" in str(exc_info.value) or "invalid JSON" in str(exc_info.value)

    def test_http_204_returns_none(self) -> None:
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=204)

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            token_provider=lambda: "valid_token",
            http_client=httpx.Client(
                base_url="https://api.docflow.example.com",
                transport=httpx.MockTransport(mock_handler),
            ),
        )
        result = client.delete("/api/resource/1")
        assert result is None


class TestLogAndExceptionSanitization:
    """Tests ensuring no tokens, authorization headers, or sensitive strings leak in logs or errors."""

    def test_no_token_leakage_in_exceptions(self) -> None:
        secret_token = "ultra_secret_device_bearer_token_xyz999"

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=401,
                json={"code": "authentication_required", "detail": "Invalid token."},
            )

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            token_provider=lambda: secret_token,
            http_client=httpx.Client(
                base_url="https://api.docflow.example.com",
                transport=httpx.MockTransport(mock_handler),
            ),
        )

        with pytest.raises(ApiAuthenticationError) as exc_info:
            client.get("/api/test")

        error_str = str(exc_info.value)
        assert secret_token not in error_str
        assert "ultra_secret" not in error_str

    def test_no_token_leakage_in_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        secret_token = "sensitive_bearer_token_abc123"

        def mock_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Timeout occurred")

        client = ApiClient(
            base_url="https://api.docflow.example.com",
            token_provider=lambda: secret_token,
            http_client=httpx.Client(
                base_url="https://api.docflow.example.com",
                transport=httpx.MockTransport(mock_handler),
            ),
        )

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(ApiTimeoutError):
                client.get("/api/test")

        for record in caplog.records:
            msg = record.getMessage()
            assert secret_token not in msg
            assert "Authorization" not in msg
            assert "sensitive_bearer_token" not in msg
