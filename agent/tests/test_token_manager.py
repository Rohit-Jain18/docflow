"""
Tests for In-Memory Access Token Management and Rotating Refresh Token Lifecycle (Task 2D-3).

Verifies:
1. Successful refresh token rotation with atomic CredentialStore update and in-memory access token publication.
2. In-memory access token validity, expiry tracking, and proactive early refresh within the safety window.
3. Thread safety: concurrent callers share a single rotation request without duplicate HTTP exchanges.
4. Terminal rejection handling: HTTP 401 invalid/revoked, HTTP 409 token reuse conflict, HTTP 429 rate limit.
5. Strict ISO 8601 UTC Z timestamp validation and malformed payload rejection.
6. Fail-closed behavior on storage write failures (new access token never published).
7. Old access token is never exposed after a failed refresh.
8. Timeouts and network connection errors mark state as ambiguous and block automatic retries.
9. Zero leakage of access tokens or refresh secrets in logs, exceptions, representations, or string outputs.
10. Integration with ApiClient as token_provider.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import logging
import threading
from typing import Any
import pytest
import httpx

from docflow_agent.client import (
    ApiClient,
    ApiConnectionError,
    ApiTimeoutError,
)
from docflow_agent.credentials import CredentialStore, InMemoryCredentialStore
from docflow_agent.token_manager import (
    DEFAULT_SAFETY_WINDOW_SECONDS,
    REFRESH_ENDPOINT,
    REFRESH_TOKEN_KEY,
    TokenAuthenticationError,
    TokenError,
    TokenManager,
    TokenMissingError,
    TokenRateLimitedError,
    TokenReuseConflictError,
    TokenRotationAmbiguousError,
    TokenStatus,
    TokenStorageError,
    TokenValidationError,
)

# ---------------------------------------------------------------------------
# Test Fixtures and Helpers
# ---------------------------------------------------------------------------

API_BASE_URL = "https://api.docflow.example.com"
INITIAL_REFRESH = "secret-initial-refresh-token-111"
ROTATED_REFRESH = "secret-rotated-refresh-token-222"
ACCESS_TOKEN = "signed.jwt.access.token.333"

VALID_REFRESH_RESPONSE = {
    "access_token": ACCESS_TOKEN,
    "access_token_expires_at": "2026-10-15T16:10:00Z",
    "refresh_token": ROTATED_REFRESH,
    "refresh_token_expires_at": "2026-11-14T16:00:00Z",
}


class FailingCredentialStore(CredentialStore):
    """Credential store test double that simulates write failures."""

    def __init__(self, initial_data: dict[str, str] | None = None) -> None:
        self._data = dict(initial_data or {})

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def store(self, key: str, secret: str) -> None:
        raise OSError("Simulated DPAPI / Windows Credential Manager hardware fault")

    def delete(self, key: str) -> bool:
        return self._data.pop(key, None) is not None

    def exists(self, key: str) -> bool:
        return key in self._data


def make_mock_client(handler: Any) -> ApiClient:
    """Create an ApiClient backed by an in-memory httpx.MockTransport."""
    transport = httpx.MockTransport(handler)
    mock_http_client = httpx.Client(
        base_url=API_BASE_URL,
        transport=transport,
        follow_redirects=False,
    )
    return ApiClient(base_url=API_BASE_URL, http_client=mock_http_client)


def make_store(initial_refresh: str | None = None) -> InMemoryCredentialStore:
    """Create InMemoryCredentialStore with optional initial refresh token."""
    store = InMemoryCredentialStore()
    if initial_refresh:
        store.store(REFRESH_TOKEN_KEY, initial_refresh)
    return store


# ---------------------------------------------------------------------------
# Test Suites
# ---------------------------------------------------------------------------

class TestTokenManagerRotationSuccess:
    """Tests for successful rotation and proactive refresh lifecycle."""

    def test_rotate_token_success(self) -> None:
        """Successful rotation updates CredentialStore and in-memory access token."""
        recorded_requests: list[httpx.Request] = []

        def mock_handler(request: httpx.Request) -> httpx.Response:
            recorded_requests.append(request)
            return httpx.Response(200, json=VALID_REFRESH_RESPONSE)

        client = make_mock_client(mock_handler)
        store = make_store(INITIAL_REFRESH)
        manager = TokenManager(client=client, credential_store=store)

        token = manager.get_access_token()

        assert token == ACCESS_TOKEN
        assert len(recorded_requests) == 1
        req = recorded_requests[0]
        assert req.method == "POST"
        assert req.url.path == REFRESH_ENDPOINT
        # Must NOT send Authorization header
        assert "authorization" not in req.headers
        # Body contains initial refresh token
        import json
        body = json.loads(req.content.decode("utf-8"))
        assert body == {"refresh_token": INITIAL_REFRESH}

        # Verify new rotated refresh token was persisted to CredentialStore
        assert store.get(REFRESH_TOKEN_KEY) == ROTATED_REFRESH

        # Verify expiry metadata
        assert manager.get_access_token_expires_at() == datetime(2026, 10, 15, 16, 10, 0, tzinfo=timezone.utc)
        assert manager.get_refresh_token_expires_at() == datetime(2026, 11, 14, 16, 0, 0, tzinfo=timezone.utc)

    def test_set_initial_tokens_skips_refresh_while_valid(self) -> None:
        """When pre-populated with valid tokens (e.g. from activation), no refresh request is sent."""
        call_count = 0

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=VALID_REFRESH_RESPONSE)

        client = make_mock_client(mock_handler)
        store = make_store(INITIAL_REFRESH)

        now = datetime(2026, 10, 15, 16, 0, 0, tzinfo=timezone.utc)
        manager = TokenManager(
            client=client,
            credential_store=store,
            initial_access_token="initial-access-tok",
            initial_access_token_expires_at=now + timedelta(minutes=10),
            time_provider=lambda: now,
        )

        assert manager.is_access_token_valid() is True
        token = manager.get_access_token()
        assert token == "initial-access-tok"
        assert call_count == 0  # No HTTP call made

    def test_proactive_refresh_within_safety_window(self) -> None:
        """Token within the safety buffer triggers proactive refresh before actual expiry."""
        call_count = 0

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=VALID_REFRESH_RESPONSE)

        client = make_mock_client(mock_handler)
        store = make_store(INITIAL_REFRESH)

        now = datetime(2026, 10, 15, 16, 0, 0, tzinfo=timezone.utc)
        token_expires_at = now + timedelta(seconds=600)  # 10 minutes from now

        current_time = now

        manager = TokenManager(
            client=client,
            credential_store=store,
            initial_access_token="initial-tok",
            initial_access_token_expires_at=token_expires_at,
            safety_window_seconds=60.0,
            time_provider=lambda: current_time,
        )

        # 1. At t0 + 530s (70s left before expiry, safety window is 60s) -> Valid, no refresh
        current_time = now + timedelta(seconds=530)
        assert manager.is_access_token_valid() is True
        assert manager.get_access_token() == "initial-tok"
        assert call_count == 0

        # 2. At t0 + 545s (55s left before expiry, inside 60s safety buffer) -> Invalid, triggers refresh
        current_time = now + timedelta(seconds=545)
        assert manager.is_access_token_valid() is False
        new_token = manager.get_access_token()
        assert new_token == ACCESS_TOKEN
        assert call_count == 1
        assert store.get(REFRESH_TOKEN_KEY) == ROTATED_REFRESH

    def test_force_refresh_bypasses_cache(self) -> None:
        """force_refresh=True rotates credentials even if current token is unexpired."""
        call_count = 0

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=VALID_REFRESH_RESPONSE)

        client = make_mock_client(mock_handler)
        store = make_store(INITIAL_REFRESH)

        now = datetime(2026, 10, 15, 16, 0, 0, tzinfo=timezone.utc)
        manager = TokenManager(
            client=client,
            credential_store=store,
            initial_access_token="cached-tok",
            initial_access_token_expires_at=now + timedelta(minutes=10),
            time_provider=lambda: now,
        )

        new_token = manager.get_access_token(force_refresh=True)
        assert new_token == ACCESS_TOKEN
        assert call_count == 1

    def test_get_token_status_reflects_state(self) -> None:
        """get_token_status() returns non-secret diagnostics."""
        client = make_mock_client(lambda r: httpx.Response(200, json=VALID_REFRESH_RESPONSE))
        store = make_store(INITIAL_REFRESH)
        now = datetime(2026, 10, 15, 16, 0, 0, tzinfo=timezone.utc)
        exp = now + timedelta(minutes=10)

        canary_tok = "CANARY_ACCESS_SECRET_XYZ"
        manager = TokenManager(
            client=client,
            credential_store=store,
            initial_access_token=canary_tok,
            initial_access_token_expires_at=exp,
            time_provider=lambda: now,
        )

        status = manager.get_token_status()
        assert status.has_access_token is True
        assert status.is_valid is True
        assert status.is_ambiguous is False
        assert status.access_token_expires_at == exp
        assert canary_tok not in repr(status)
        assert canary_tok not in str(status)


class TestTokenManagerConcurrency:
    """Tests for thread safety and locking during rotation."""

    def test_concurrent_get_access_token_uses_single_rotation(self) -> None:
        """Multiple concurrent callers trigger only one network rotation exchange."""
        call_count = 0
        lock = threading.Lock()

        def slow_mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            with lock:
                call_count += 1
            # Small delay to simulate network latency
            import time
            time.sleep(0.05)
            return httpx.Response(200, json=VALID_REFRESH_RESPONSE)

        client = make_mock_client(slow_mock_handler)
        store = make_store(INITIAL_REFRESH)
        manager = TokenManager(client=client, credential_store=store)

        results: list[str] = []
        errors: list[Exception] = []

        def worker() -> None:
            try:
                tok = manager.get_access_token()
                results.append(tok)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10
        # All threads received the exact same token
        assert all(tok == ACCESS_TOKEN for tok in results)
        # Exactly one refresh request was performed!
        assert call_count == 1


class TestTokenManagerFailureModes:
    """Tests covering error statuses, revoked credentials, rate limiting, and fail-closed security."""

    def test_missing_refresh_token_raises_token_missing_error(self) -> None:
        """Unactivated device without refresh token in CredentialStore raises TokenMissingError."""
        client = make_mock_client(lambda r: httpx.Response(200, json=VALID_REFRESH_RESPONSE))
        store = InMemoryCredentialStore()  # empty
        manager = TokenManager(client=client, credential_store=store)

        with pytest.raises(TokenMissingError) as exc_info:
            manager.get_access_token()

        err = exc_info.value
        assert err.code == "refresh_token_missing"
        assert err.recoverable is False
        assert "Device must be activated first" in err.message

    def test_rejected_or_revoked_token_raises_authentication_error(self) -> None:
        """HTTP 401 authentication_required raises TokenAuthenticationError and clears token."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                json={
                    "type": "about:blank",
                    "title": "Authentication required",
                    "status": 401,
                    "code": "authentication_required",
                    "detail": "Invalid or revoked refresh credential.",
                    "request_id": "req-auth-fail",
                },
            )

        client = make_mock_client(mock_handler)
        store = make_store(INITIAL_REFRESH)
        manager = TokenManager(
            client=client,
            credential_store=store,
            initial_access_token="old-token-to-invalidate",
            initial_access_token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        with pytest.raises(TokenAuthenticationError) as exc_info:
            manager.get_access_token()

        err = exc_info.value
        assert err.code == "authentication_required"
        assert err.recoverable is False
        assert err.request_id == "req-auth-fail"

        # In-memory access token must be invalidated
        assert manager.is_access_token_valid() is False
        assert manager.get_access_token_expires_at() is None

    def test_token_reuse_conflict_raises_reuse_conflict_error(self) -> None:
        """HTTP 409 state_conflict (token reuse detected) raises TokenReuseConflictError."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                409,
                json={
                    "type": "about:blank",
                    "title": "State conflict",
                    "status": 409,
                    "code": "state_conflict",
                    "detail": "Rotated refresh token reuse detected. All active credentials have been revoked.",
                    "request_id": "req-reuse-fail",
                },
            )

        client = make_mock_client(mock_handler)
        store = make_store(INITIAL_REFRESH)
        manager = TokenManager(client=client, credential_store=store)

        with pytest.raises(TokenReuseConflictError) as exc_info:
            manager.get_access_token()

        err = exc_info.value
        assert err.code == "state_conflict"
        assert err.recoverable is False
        assert err.request_id == "req-reuse-fail"

    def test_rate_limited_raises_rate_limited_error_with_retry_after(self) -> None:
        """HTTP 429 rate_limited raises TokenRateLimitedError and preserves recoverable state."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                headers={"Retry-After": "45"},
                json={
                    "type": "about:blank",
                    "title": "Rate limited",
                    "status": 429,
                    "code": "rate_limited",
                    "detail": "Request was throttled. Expected available in 45 seconds.",
                    "request_id": "req-throttled",
                },
            )

        client = make_mock_client(mock_handler)
        store = make_store(INITIAL_REFRESH)
        manager = TokenManager(client=client, credential_store=store)

        with pytest.raises(TokenRateLimitedError) as exc_info:
            manager.get_access_token()

        err = exc_info.value
        assert err.code == "rate_limited"
        assert err.recoverable is True
        assert err.retry_after == 45
        assert err.request_id == "req-throttled"
        # Since it was rate limited, the refresh token in CredentialStore was NOT consumed
        assert store.get(REFRESH_TOKEN_KEY) == INITIAL_REFRESH

    @pytest.mark.parametrize(
        "corrupt_field_mutator",
        [
            lambda d: d.pop("access_token"),
            lambda d: d.update({"access_token": ""}),
            lambda d: d.update({"access_token": "   "}),
            lambda d: d.update({"access_token": 12345}),
            lambda d: d.pop("refresh_token"),
            lambda d: d.update({"refresh_token": ""}),
            lambda d: d.update({"refresh_token": None}),
            lambda d: d.pop("access_token_expires_at"),
            lambda d: d.update({"access_token_expires_at": "not-a-timestamp"}),
            lambda d: d.update({"access_token_expires_at": "2026-10-15T16:00:00+05:30"}),  # non-UTC
            lambda d: d.update({"access_token_expires_at": "2026-10-15 16:00:00Z"}),  # missing T
            lambda d: d.pop("refresh_token_expires_at"),
            lambda d: d.update({"refresh_token_expires_at": "2026-10-15T16:00:00"}),  # naive
            lambda d: d.update({"refresh_token_expires_at": "CANARY_SENSITIVE_TEXT"}),
        ],
    )
    def test_malformed_response_fields_fail_closed(self, corrupt_field_mutator: Any) -> None:
        """Any malformed or missing response field raises TokenValidationError and fails closed."""
        payload = copy.deepcopy(VALID_REFRESH_RESPONSE)
        corrupt_field_mutator(payload)

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        client = make_mock_client(mock_handler)
        store = make_store(INITIAL_REFRESH)
        manager = TokenManager(client=client, credential_store=store)

        with pytest.raises(TokenValidationError):
            manager.get_access_token()

        # Store remains on original refresh credential
        assert store.get(REFRESH_TOKEN_KEY) == INITIAL_REFRESH
        # No access token is published
        assert manager.is_access_token_valid() is False
        assert manager.get_access_token_expires_at() is None

    def test_storage_failure_fails_closed_and_does_not_publish_access_token(self) -> None:
        """When CredentialStore.store() raises, the new access token must NOT be published."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=VALID_REFRESH_RESPONSE)

        client = make_mock_client(mock_handler)
        failing_store = FailingCredentialStore({REFRESH_TOKEN_KEY: INITIAL_REFRESH})
        manager = TokenManager(client=client, credential_store=failing_store)

        with pytest.raises(TokenStorageError) as exc_info:
            manager.get_access_token()

        err = exc_info.value
        assert err.code == "storage_write_error"
        assert err.recoverable is False

        # Crucial security guarantee: new access token must NOT be published
        assert manager.is_access_token_valid() is False
        assert manager.get_access_token_expires_at() is None

    def test_old_access_token_not_exposed_after_failed_refresh(self) -> None:
        """Old access token is invalidated and never exposed if a refresh attempt fails."""
        OLD_TOKEN = "stale-access-token-999"

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"code": "server_error", "detail": "Internal error."})

        client = make_mock_client(mock_handler)
        store = make_store(INITIAL_REFRESH)
        now = datetime(2026, 10, 15, 16, 0, 0, tzinfo=timezone.utc)

        manager = TokenManager(
            client=client,
            credential_store=store,
            initial_access_token=OLD_TOKEN,
            initial_access_token_expires_at=now + timedelta(seconds=30),  # inside safety buffer
            safety_window_seconds=60.0,
            time_provider=lambda: now,
        )

        with pytest.raises(TokenError):
            manager.get_access_token()

        # Old access token must NOT be retained in manager
        assert manager.is_access_token_valid() is False
        assert manager.get_access_token_expires_at() is None


class TestTokenManagerAmbiguousTimeoutAndNetworkErrors:
    """Tests covering non-retryable behavior after timeouts or ambiguous network errors."""

    def test_timeout_after_rotation_request_marks_ambiguous_and_blocks_automatic_retry(self) -> None:
        """Timeout during rotation marks state as ambiguous; subsequent calls fail closed without retrying."""
        call_count = 0

        def timeout_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ReadTimeout("Server took too long to respond")

        client = make_mock_client(timeout_handler)
        store = make_store(INITIAL_REFRESH)
        manager = TokenManager(client=client, credential_store=store)

        # First call triggers timeout
        with pytest.raises(TokenRotationAmbiguousError) as exc_info:
            manager.get_access_token()

        err = exc_info.value
        assert err.code == "rotation_timeout"
        assert err.recoverable is False
        assert call_count == 1
        assert manager.get_token_status().is_ambiguous is True

        # Second call must NOT attempt another network request (blind reuse would trigger theft revocation)
        with pytest.raises(TokenRotationAmbiguousError) as exc_info2:
            manager.get_access_token()

        err2 = exc_info2.value
        assert err2.code == "ambiguous_rotation_state"
        assert call_count == 1  # No additional network call was made!

    def test_network_connection_error_during_refresh_marks_ambiguous(self) -> None:
        """Connection failure during refresh exchange marks state as ambiguous."""
        call_count = 0

        def conn_error_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("Connection refused / network reset")

        client = make_mock_client(conn_error_handler)
        store = make_store(INITIAL_REFRESH)
        manager = TokenManager(client=client, credential_store=store)

        with pytest.raises(TokenRotationAmbiguousError) as exc_info:
            manager.get_access_token()

        assert exc_info.value.code == "rotation_network_error"
        assert call_count == 1
        assert manager.get_token_status().is_ambiguous is True

    def test_reset_ambiguity_allows_retry_after_operator_intervention(self) -> None:
        """Calling reset_ambiguity() clears the ambiguous lock and allows new rotation attempts."""
        call_count = 0

        def alternating_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ReadTimeout("Timeout on first try")
            return httpx.Response(200, json=VALID_REFRESH_RESPONSE)

        client = make_mock_client(alternating_handler)
        store = make_store(INITIAL_REFRESH)
        manager = TokenManager(client=client, credential_store=store)

        # 1. First call fails with ambiguous timeout
        with pytest.raises(TokenRotationAmbiguousError):
            manager.get_access_token()

        assert manager.get_token_status().is_ambiguous is True

        # 2. Operator clears ambiguity
        manager.reset_ambiguity()
        assert manager.get_token_status().is_ambiguous is False

        # 3. Next call proceeds with rotation
        token = manager.get_access_token()
        assert token == ACCESS_TOKEN
        assert call_count == 2


class TestTokenManagerPrivacyAndSecretLeakage:
    """Tests ensuring no secrets appear in logs, exceptions, representations, or SQLite."""

    def test_secrets_never_appear_in_logs_repr_or_exceptions(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Access tokens and refresh secrets are never leaked into logs, str, or repr."""
        CANARY_REFRESH = "CANARY_SECRET_REFRESH_999888777"
        CANARY_ACCESS = "CANARY_SECRET_ACCESS_111222333"

        response_payload = {
            "access_token": CANARY_ACCESS,
            "access_token_expires_at": "2026-10-15T16:10:00Z",
            "refresh_token": CANARY_REFRESH,
            "refresh_token_expires_at": "2026-11-14T16:00:00Z",
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=response_payload)

        client = make_mock_client(mock_handler)
        store = make_store("canary-input-refresh-code")
        manager = TokenManager(client=client, credential_store=store)

        with caplog.at_level(logging.DEBUG):
            token = manager.get_access_token()

        assert token == CANARY_ACCESS

        # 1. Logs must not contain secrets
        all_logs = caplog.text
        assert CANARY_ACCESS not in all_logs
        assert CANARY_REFRESH not in all_logs
        assert "canary-input-refresh-code" not in all_logs

        # 2. TokenManager repr and str must not contain secrets
        mgr_repr = repr(manager)
        mgr_str = str(manager)
        assert CANARY_ACCESS not in mgr_repr
        assert CANARY_REFRESH not in mgr_repr
        assert CANARY_ACCESS not in mgr_str
        assert CANARY_REFRESH not in mgr_str

        # 3. TokenStatus repr must not contain secrets
        status = manager.get_token_status()
        status_repr = repr(status)
        assert CANARY_ACCESS not in status_repr
        assert CANARY_REFRESH not in status_repr

    def test_exception_representation_does_not_leak_secrets(self) -> None:
        """TokenError str and repr contain only safe error codes."""
        SECRET = "CANARY_FORBIDDEN_TOKEN_VALUE"

        err = TokenValidationError("Validation failed for response.", code="validation_error", request_id="req-123")
        assert SECRET not in repr(err)
        assert SECRET not in str(err)
        assert "code='validation_error'" in repr(err)
        assert "request_id='req-123'" in repr(err)

        err_throttled = TokenRateLimitedError("Throttled", code="rate_limited", retry_after=30)
        assert "retry_after=30" in repr(err_throttled)


class TestApiClientIntegrationWithTokenManager:
    """Tests verifying ApiClient using TokenManager.get_access_token as its token provider."""

    def test_api_client_uses_token_manager_as_token_provider(self) -> None:
        """ApiClient automatically calls TokenManager to acquire valid bearer token."""
        auth_requests: list[httpx.Request] = []

        def mock_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == REFRESH_ENDPOINT:
                return httpx.Response(200, json=VALID_REFRESH_RESPONSE)
            if request.url.path == "/api/v1/agent/reports":
                auth_requests.append(request)
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(404)

        transport = httpx.MockTransport(mock_handler)
        mock_http = httpx.Client(base_url=API_BASE_URL, transport=transport)

        client = ApiClient(base_url=API_BASE_URL, http_client=mock_http)
        store = make_store(INITIAL_REFRESH)
        manager = TokenManager(client=client, credential_store=store)

        # Wire TokenManager into ApiClient as token_provider
        client.token_provider = manager.get_access_token

        # Perform authenticated request
        res = client.post("/api/v1/agent/reports", json={"file_size": 100}, authenticated=True)
        assert res == {"status": "ok"}

        assert len(auth_requests) == 1
        req = auth_requests[0]
        # Authorization header must contain the bearer token from TokenManager
        assert req.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"
