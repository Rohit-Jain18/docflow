"""
Tests for Agent Device Activation and Secure Credential Storage.

Covers:
- Successful activation exchange and response validation.
- Secure storage of the rotating refresh token in CredentialStore.
- In-memory retention of short-lived access token (never persisted to disk/SQLite).
- Safe persistence of non-secret device metadata in SQLite agent_settings.
- Fails closed on invalid/expired activation code (400, 410, 429).
- Fails closed on malformed response, missing fields, or invalid field formats.
- Network connection and timeout failures.
- Secure credential storage failure fails closed.
- Repeated activation behavior (consumed code rejected, fresh code updates credential).
- Installation ID generation and persistent reuse.
- Strict prevention of secret leakage in logs, exceptions, representations, and CLI output.
- CLI activate command integration.
"""

from __future__ import annotations

from datetime import datetime, timezone
import copy
import json
import logging
import uuid
from typing import Any
import pytest
import httpx

from docflow_agent.activation import (
    ACTIVATION_EXCHANGE_ENDPOINT,
    REFRESH_TOKEN_KEY,
    ActivationCodeExpiredError,
    ActivationError,
    ActivationRateLimitedError,
    ActivationResult,
    ActivationService,
    ActivationStorageError,
    ActivationValidationError,
    DeviceInfo,
    activate_device,
)
from docflow_agent.cli import main as cli_main
from docflow_agent.client import ApiClient
from docflow_agent.credentials import CredentialStore, InMemoryCredentialStore
from docflow_agent.queue import JobQueue


# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
# ---------------------------------------------------------------------------

VALID_DEVICE_ID = "11111111-2222-3333-4444-555555555555"
VALID_BRANCH_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
VALID_INSTALLATION_ID = "f94fe6c0-bdbb-47ba-9f61-6d1c6ae5b1a2"

VALID_RESPONSE_DATA: dict[str, Any] = {
    "device": {
        "id": VALID_DEVICE_ID,
        "name": "Main Lab PC",
        "status": "active",
        "branch_id": VALID_BRANCH_ID,
    },
    "access_token": "signed.access.token.header.payload.sig",
    "access_token_expires_at": "2026-10-15T15:30:00Z",
    "refresh_token": "rotating-secret-refresh-credential-123",
    "refresh_token_expires_at": "2026-11-14T15:30:00Z",
    "configuration_version": 1,
}


def make_mock_client(
    handler: Any,
    base_url: str = "https://api.docflow.example.com",
) -> ApiClient:
    """Create an ApiClient backed by an httpx MockTransport."""
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(base_url=base_url, transport=transport)
    return ApiClient(base_url=base_url, http_client=http_client)


class FailingCredentialStore(CredentialStore):
    """Credential store double that always fails on store()."""

    def __init__(self) -> None:
        self.stored: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.stored.get(key)

    def store(self, key: str, value: str) -> None:
        raise RuntimeError("Windows Credential Manager / DPAPI write failure (Access Denied)")

    def delete(self, key: str) -> bool:
        return self.stored.pop(key, None) is not None

    def exists(self, key: str) -> bool:
        return key in self.stored


# ---------------------------------------------------------------------------
# Test Suites
# ---------------------------------------------------------------------------

class TestDeviceActivationSuccess:
    """Tests for successful device activation flows."""

    def test_successful_activation_exchange_and_token_storage(self, tmp_path: Any) -> None:
        """Successful activation validates response, stores refresh token, and keeps access token in memory."""
        captured_request: dict[str, Any] = {}

        def mock_handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == ACTIVATION_EXCHANGE_ENDPOINT
            assert "Authorization" not in request.headers
            captured_request["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(201, json=VALID_RESPONSE_DATA)

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        db_path = tmp_path / "test_queue.db"
        queue = JobQueue(db_path=db_path)

        result = activate_device(
            client=client,
            activation_code="valid-one-time-code-123",
            credential_store=store,
            queue=queue,
            installation_id=VALID_INSTALLATION_ID,
            agent_version="0.1.0",
            platform="windows",
        )

        # 1. Request payload checks
        req_body = captured_request["body"]
        assert req_body["activation_code"] == "valid-one-time-code-123"
        assert req_body["installation_id"] == VALID_INSTALLATION_ID
        assert req_body["agent_version"] == "0.1.0"
        assert req_body["platform"] == "windows"
        assert set(req_body.keys()) == {"activation_code", "installation_id", "agent_version", "platform"}

        # 2. Returned result checks
        assert isinstance(result, ActivationResult)
        assert result.device.id == VALID_DEVICE_ID
        assert result.device.name == "Main Lab PC"
        assert result.device.status == "active"
        assert result.device.branch_id == VALID_BRANCH_ID
        assert result.access_token == "signed.access.token.header.payload.sig"
        assert result.access_token_expires_at == datetime(2026, 10, 15, 15, 30, tzinfo=timezone.utc)
        assert result.refresh_token_expires_at == datetime(2026, 11, 14, 15, 30, tzinfo=timezone.utc)
        assert result.configuration_version == 1
        assert result.installation_id == VALID_INSTALLATION_ID

        # 3. Secure Credential Store checks
        assert store.exists(REFRESH_TOKEN_KEY)
        assert store.get(REFRESH_TOKEN_KEY) == "rotating-secret-refresh-credential-123"

        # 4. SQLite settings checks (non-secret metadata stored, secrets strictly absent)
        settings = queue.list_settings()
        assert settings["device_id"] == VALID_DEVICE_ID
        assert settings["branch_id"] == VALID_BRANCH_ID
        assert settings["device_name"] == "Main Lab PC"
        assert settings["configuration_version"] == "1"
        assert settings["installation_id"] == VALID_INSTALLATION_ID

        for key, val in settings.items():
            assert "access_token" not in key
            assert "refresh_token" not in key
            assert "token" not in key
            assert "signed.access.token" not in val
            assert "rotating-secret" not in val
            assert "valid-one-time-code" not in val

    def test_activation_without_queue_succeeds(self) -> None:
        """Activation works when queue is None (e.g. standalone or pre-queue setup)."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json=VALID_RESPONSE_DATA)

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()

        service = ActivationService(
            client=client,
            credential_store=store,
            queue=None,
        )

        assert not service.is_activated()
        result = service.activate("code-abc")
        assert result.device.id == VALID_DEVICE_ID
        assert service.is_activated()
        assert store.get(REFRESH_TOKEN_KEY) == "rotating-secret-refresh-credential-123"

    def test_installation_id_generation_and_persistence(self, tmp_path: Any) -> None:
        """When no installation_id is provided, generate a valid UUID and persist in queue."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            # Validate that generated installation_id is a valid UUID
            uuid.UUID(body["installation_id"])
            return httpx.Response(201, json=VALID_RESPONSE_DATA)

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        queue = JobQueue(db_path=tmp_path / "queue.db")

        service1 = ActivationService(client=client, credential_store=store, queue=queue)
        result1 = service1.activate("code-1")
        gen_id = result1.installation_id
        assert uuid.UUID(gen_id)
        assert queue.get_setting("installation_id") == gen_id

        # Second service instance reuses the persisted installation_id
        service2 = ActivationService(client=client, credential_store=store, queue=queue)
        assert service2.get_or_create_installation_id() == gen_id


class TestDeviceActivationFailures:
    """Tests for activation failures and fail-closed behaviors."""

    def test_empty_or_whitespace_code_fails_fast(self) -> None:
        """Empty or whitespace activation codes fail validation before any network request."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            pytest.fail("Network call should not occur for empty activation code")

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        service = ActivationService(client=client, credential_store=store)

        for empty_code in ("", "   ", "\t\n"):
            with pytest.raises(ActivationValidationError) as exc_info:
                service.activate(empty_code)
            assert exc_info.value.code == "validation_error"
            assert not store.exists(REFRESH_TOKEN_KEY)

    def test_invalid_code_returns_400_validation_error(self) -> None:
        """Unknown or invalid code returning 400 raises ActivationValidationError."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                headers={"X-Request-ID": "req-val-fail"},
                json={
                    "type": "about:blank",
                    "title": "Validation failed",
                    "status": 400,
                    "code": "validation_error",
                    "detail": "Invalid activation code.",
                    "request_id": "req-val-fail",
                },
            )

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        service = ActivationService(client=client, credential_store=store)

        with pytest.raises(ActivationValidationError) as exc_info:
            service.activate("bad-code")

        err = exc_info.value
        assert err.code == "validation_error"
        assert err.request_id == "req-val-fail"
        assert not store.exists(REFRESH_TOKEN_KEY)

    def test_expired_or_consumed_code_returns_410_activation_expired(self) -> None:
        """Expired or already-consumed code returning 410 raises ActivationCodeExpiredError."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                410,
                headers={"X-Request-ID": "req-exp-fail"},
                json={
                    "type": "about:blank",
                    "title": "Activation expired",
                    "status": 410,
                    "code": "activation_expired",
                    "detail": "The activation code has expired, been revoked, or already consumed.",
                    "request_id": "req-exp-fail",
                },
            )

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        service = ActivationService(client=client, credential_store=store)

        with pytest.raises(ActivationCodeExpiredError) as exc_info:
            service.activate("expired-code")

        err = exc_info.value
        assert err.code == "activation_expired"
        assert err.request_id == "req-exp-fail"
        assert not store.exists(REFRESH_TOKEN_KEY)

    def test_rate_limited_returns_429(self) -> None:
        """Throttled requests returning 429 raise ActivationRateLimitedError."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                headers={"X-Request-ID": "req-rate-fail"},
                json={
                    "type": "about:blank",
                    "status": 429,
                    "code": "rate_limited",
                    "detail": "Activation rate limit exceeded.",
                    "request_id": "req-rate-fail",
                },
            )

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        service = ActivationService(client=client, credential_store=store)

        with pytest.raises(ActivationRateLimitedError) as exc_info:
            service.activate("throttled-code")

        err = exc_info.value
        assert err.code == "rate_limited"
        assert not store.exists(REFRESH_TOKEN_KEY)

    def test_network_connection_and_timeout_failures(self) -> None:
        """Network disconnects or timeouts raise ActivationError and do not store tokens."""
        def mock_connect_error(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused by peer")

        client = make_mock_client(mock_connect_error)
        store = InMemoryCredentialStore()
        service = ActivationService(client=client, credential_store=store)

        with pytest.raises(ActivationError) as exc_info:
            service.activate("code-123")
        assert exc_info.value.code == "network_error"
        assert not store.exists(REFRESH_TOKEN_KEY)

        def mock_timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Socket read timed out")

        client_timeout = make_mock_client(mock_timeout)
        service_timeout = ActivationService(client=client_timeout, credential_store=store)
        with pytest.raises(ActivationError) as exc_timeout:
            service_timeout.activate("code-123")
        assert exc_timeout.value.code == "network_error"
        assert not store.exists(REFRESH_TOKEN_KEY)

    def test_malformed_non_json_response(self) -> None:
        """Non-JSON response from backend raises ActivationError and fails closed."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, content=b"<html>Bad Gateway</html>", headers={"Content-Type": "text/html"})

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        service = ActivationService(client=client, credential_store=store)

        with pytest.raises(ActivationError) as exc_info:
            service.activate("code-123")
        assert not store.exists(REFRESH_TOKEN_KEY)

    @pytest.mark.parametrize(
        "corrupt_field_mutator",
        [
            lambda d: d.pop("device"),
            lambda d: d["device"].pop("id"),
            lambda d: d["device"].update({"id": "not-a-valid-uuid"}),
            lambda d: d["device"].pop("name"),
            lambda d: d["device"].update({"name": ""}),
            lambda d: d["device"].update({"status": "pending_activation"}),
            lambda d: d["device"].pop("branch_id"),
            lambda d: d["device"].update({"branch_id": "bad-branch-uuid"}),
            lambda d: d.pop("access_token"),
            lambda d: d.update({"access_token": ""}),
            lambda d: d.pop("access_token_expires_at"),
            lambda d: d.update({"access_token_expires_at": "not-a-date"}),
            lambda d: d.pop("refresh_token"),
            lambda d: d.update({"refresh_token": ""}),
            lambda d: d.pop("refresh_token_expires_at"),
            lambda d: d.update({"refresh_token_expires_at": "invalid-timestamp"}),
            lambda d: d.pop("configuration_version"),
            lambda d: d.update({"configuration_version": 0}),
            lambda d: d.update({"configuration_version": "not-an-int"}),
        ],
    )
    def test_missing_or_malformed_response_fields_fail_closed(
        self,
        corrupt_field_mutator: Any,
    ) -> None:
        """Any missing or malformed response field raises ActivationValidationError and stores nothing."""
        import copy
        payload = copy.deepcopy(VALID_RESPONSE_DATA)
        corrupt_field_mutator(payload)

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json=payload)

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        service = ActivationService(client=client, credential_store=store)

        with pytest.raises(ActivationValidationError):
            service.activate("valid-code")

        assert not store.exists(REFRESH_TOKEN_KEY)

    def test_invalid_device_status_uses_generic_safe_message_and_does_not_leak(self) -> None:
        """Invalid device status raises generic safe error message without interpolating raw status."""
        canary_status = "CANARY_SENSITIVE_STATUS_PATIENT_SSN_12345"
        payload = copy.deepcopy(VALID_RESPONSE_DATA)
        payload["device"]["status"] = canary_status

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json=payload)

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        service = ActivationService(client=client, credential_store=store)

        with pytest.raises(ActivationValidationError) as exc_info:
            service.activate("valid-code")

        err = exc_info.value
        assert err.code == "device_not_active"
        assert err.message == "Device status is invalid; expected 'active'."
        assert canary_status not in str(err)
        assert canary_status not in repr(err)
        assert not store.exists(REFRESH_TOKEN_KEY)

    @pytest.mark.parametrize(
        "field_name",
        ["access_token_expires_at", "refresh_token_expires_at"],
    )
    @pytest.mark.parametrize(
        "valid_ts",
        [
            "2026-10-15T15:30:00Z",
            "2026-10-15T15:30:00.000Z",
            "2026-10-15T15:30:00.123456Z",
        ],
    )
    def test_valid_utc_timestamps_accepted(self, field_name: str, valid_ts: str) -> None:
        """ISO 8601 UTC timestamps ending in 'Z' are accepted."""
        payload = copy.deepcopy(VALID_RESPONSE_DATA)
        payload[field_name] = valid_ts

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json=payload)

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        service = ActivationService(client=client, credential_store=store)

        result = service.activate("valid-code")
        dt_val = getattr(result, field_name)
        assert dt_val.tzinfo is not None
        assert dt_val.utcoffset() == timezone.utc.utcoffset(dt_val)

    @pytest.mark.parametrize(
        "field_name",
        ["access_token_expires_at", "refresh_token_expires_at"],
    )
    @pytest.mark.parametrize(
        "invalid_ts",
        [
            "2026-10-15T15:30:00",  # Naive (no timezone)
            "2026-10-15T15:30:00+05:30",  # Non-UTC positive offset
            "2026-10-15T15:30:00-04:00",  # Non-UTC negative offset
            "2026-10-15T15:30:00+00:00",  # Non-Z UTC offset
            "2026-10-15 15:30:00Z",  # Space instead of T
            "2026-10-15T15:30:00z",  # Lowercase z (API_CONTRACTS requires Z)
            "not-a-timestampZ",  # Malformed
            "2026-99-99T99:99:99Z",  # Out of range date/time
            "",  # Empty
            "   ",  # Whitespace
            None,  # None
            1234567890,  # Numeric
            "CANARY_SENSITIVE_EXPIRY_TOKEN_12345Z",  # Fake sensitive text ending in Z
        ],
    )
    def test_invalid_and_non_utc_timestamps_rejected(self, field_name: str, invalid_ts: Any) -> None:
        """Naive, non-UTC offset, malformed, missing, and non-Z timestamps are rejected without leaking data."""
        payload = copy.deepcopy(VALID_RESPONSE_DATA)
        payload[field_name] = invalid_ts

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json=payload)

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        service = ActivationService(client=client, credential_store=store)

        with pytest.raises(ActivationValidationError) as exc_info:
            service.activate("valid-code")

        err = exc_info.value
        assert err.code in ("invalid_timestamp", "missing_timestamp")
        if isinstance(invalid_ts, str) and invalid_ts.strip():
            assert invalid_ts not in str(err)
            assert invalid_ts not in repr(err)
        assert not store.exists(REFRESH_TOKEN_KEY)

    def test_secure_storage_failure_fails_closed(self, tmp_path: Any) -> None:
        """When CredentialStore.store() raises, activation fails closed without returning result."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json=VALID_RESPONSE_DATA)

        client = make_mock_client(mock_handler)
        failing_store = FailingCredentialStore()
        queue = JobQueue(db_path=tmp_path / "queue.db")

        service = ActivationService(
            client=client,
            credential_store=failing_store,
            queue=queue,
        )

        with pytest.raises(ActivationStorageError) as exc_info:
            service.activate("valid-code")

        err = exc_info.value
        assert err.code == "storage_error"
        assert "Secure credential storage failed" in err.message
        assert not failing_store.exists(REFRESH_TOKEN_KEY)


class TestRepeatedActivationBehavior:
    """Tests covering repeated activation scenarios."""

    def test_repeated_activation_with_consumed_code_fails(self) -> None:
        """Attempting to activate again with the already-consumed code raises 410 expired."""
        call_count = 0

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(201, json=VALID_RESPONSE_DATA)
            return httpx.Response(
                410,
                json={
                    "code": "activation_expired",
                    "detail": "The activation code has expired, been revoked, or already consumed.",
                },
            )

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        service = ActivationService(client=client, credential_store=store)

        # First activation succeeds
        res1 = service.activate("one-time-code")
        assert res1.device.id == VALID_DEVICE_ID
        assert store.get(REFRESH_TOKEN_KEY) == "rotating-secret-refresh-credential-123"

        # Second activation with same code fails
        with pytest.raises(ActivationCodeExpiredError):
            service.activate("one-time-code")

        # Original credential remains intact
        assert store.get(REFRESH_TOKEN_KEY) == "rotating-secret-refresh-credential-123"

    def test_repeated_activation_with_fresh_code_replaces_credential(self) -> None:
        """Admin re-activating a device with a new valid code replaces the stored refresh credential."""
        call_count = 0

        def mock_handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(201, json=VALID_RESPONSE_DATA)
            data2 = dict(VALID_RESPONSE_DATA)
            data2["refresh_token"] = "new-rotated-refresh-credential-456"
            return httpx.Response(201, json=data2)

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        service = ActivationService(client=client, credential_store=store)

        service.activate("code-1")
        assert store.get(REFRESH_TOKEN_KEY) == "rotating-secret-refresh-credential-123"

        service.activate("code-2")
        assert store.get(REFRESH_TOKEN_KEY) == "new-rotated-refresh-credential-456"


class TestSecretLeakagePrevention:
    """Tests ensuring no secrets appear in logs, exceptions, representations, or SQLite."""

    def test_no_secret_leakage_in_logs_and_exceptions(
        self,
        caplog: pytest.LogCaptureFixture,
        tmp_path: Any,
    ) -> None:
        """Activation codes, access tokens, and refresh tokens are never logged or exposed in repr/str."""
        SECRET_CODE = "CANARY_ACTIVATION_CODE_998877"
        SECRET_REFRESH = "CANARY_REFRESH_TOKEN_112233"
        SECRET_ACCESS = "CANARY_ACCESS_TOKEN_445566"

        response_data = {
            "device": {
                "id": VALID_DEVICE_ID,
                "name": "Secret Lab",
                "status": "active",
                "branch_id": VALID_BRANCH_ID,
            },
            "access_token": SECRET_ACCESS,
            "access_token_expires_at": "2026-10-15T15:30:00Z",
            "refresh_token": SECRET_REFRESH,
            "refresh_token_expires_at": "2026-11-14T15:30:00Z",
            "configuration_version": 1,
        }

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json=response_data)

        client = make_mock_client(mock_handler)
        store = InMemoryCredentialStore()
        queue = JobQueue(db_path=tmp_path / "queue.db")
        service = ActivationService(client=client, credential_store=store, queue=queue)

        with caplog.at_level(logging.DEBUG):
            result = service.activate(SECRET_CODE)

        # Check logs
        all_logs = caplog.text
        assert SECRET_CODE not in all_logs
        assert SECRET_REFRESH not in all_logs
        assert SECRET_ACCESS not in all_logs

        # Check result repr and str
        result_repr = repr(result)
        result_str = str(result)
        assert SECRET_CODE not in result_repr
        assert SECRET_REFRESH not in result_repr
        assert SECRET_ACCESS not in result_repr
        assert SECRET_CODE not in result_str
        assert SECRET_REFRESH not in result_str
        assert SECRET_ACCESS not in result_str

        # Check SQLite
        settings = queue.list_settings()
        for k, v in settings.items():
            assert SECRET_CODE not in k and SECRET_CODE not in v
            assert SECRET_REFRESH not in k and SECRET_REFRESH not in v
            assert SECRET_ACCESS not in k and SECRET_ACCESS not in v

    def test_exception_representation_does_not_leak_secrets(self) -> None:
        """ActivationError str and repr contain only safe error codes, never raw input."""
        SECRET_CODE = "CANARY_SUPER_SECRET_CODE"

        err = ActivationValidationError("Invalid activation code.", code="validation_error")
        assert SECRET_CODE not in repr(err)
        assert SECRET_CODE not in str(err)
        assert "code='validation_error'" in repr(err)

        err_expired = ActivationCodeExpiredError("Code expired.", code="activation_expired", request_id="req-123")
        assert "code='activation_expired'" in repr(err_expired)
        assert "request_id='req-123'" in repr(err_expired)


class TestCliActivationCommand:
    """Tests for the CLI activate subcommand."""

    @pytest.fixture(autouse=True)
    def _cleanup_logger(self) -> None:  # type: ignore[misc]
        """Remove handlers before and after tests to avoid stream accumulation."""
        logger = logging.getLogger("docflow_agent")
        for h in list(logger.handlers):
            h.close()
        logger.handlers.clear()
        yield  # type: ignore[misc]
        for h in list(logger.handlers):
            h.close()
        logger.handlers.clear()

    def test_cli_activate_success_with_getpass(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
        tmp_path: Any,
    ) -> None:
        """CLI activate command succeeds via getpass and prints only non-sensitive device info."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json=VALID_RESPONSE_DATA)

        mock_client = make_mock_client(mock_handler)

        watch_dir = tmp_path / "watch"
        watch_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("DOCFLOW_API_BASE_URL", "https://api.docflow.example.com")
        monkeypatch.setenv("WATCH_FOLDER", str(watch_dir))
        monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "agent.db"))

        monkeypatch.setattr("docflow_agent.cli.ApiClient", lambda **kwargs: mock_client)
        secret_code = "valid-getpass-code-123"
        prompt_called = False

        def mock_getpass(prompt: str = "") -> str:
            nonlocal prompt_called
            prompt_called = True
            return secret_code

        monkeypatch.setattr("getpass.getpass", mock_getpass)

        with caplog.at_level(logging.DEBUG):
            exit_code = cli_main(["activate"])
        assert exit_code == 0
        assert prompt_called is True

        captured = capsys.readouterr()
        assert "Device successfully activated." in captured.out
        assert f"Device ID: {VALID_DEVICE_ID}" in captured.out
        assert f"Branch ID: {VALID_BRANCH_ID}" in captured.out
        # Secrets must never be printed to stdout, stderr, or logs
        assert secret_code not in captured.out
        assert "rotating-secret" not in captured.out
        assert "signed.access.token" not in captured.out
        assert secret_code not in captured.err
        assert secret_code not in caplog.text
        assert "rotating-secret" not in caplog.text
        assert "signed.access.token" not in caplog.text

    def test_cli_activate_rejects_code_flag_as_unrecognized_argument(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--code flag is removed and rejected by CLI parser as unrecognized argument."""
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["activate", "--code", "secret-cli-argument-code"])

        # argparse exits with code 2 on unrecognized arguments
        assert exc_info.value.code != 0

        captured = capsys.readouterr()
        assert "unrecognized arguments: --code" in captured.err or "--code" in captured.err
        assert "secret-cli-argument-code" not in captured.out

    def test_cli_activate_secure_prompting_unavailable_fails_safe(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When getpass fails, the CLI fails with a safe message instead of falling back to input()."""
        def broken_getpass(prompt: str = "") -> str:
            raise OSError("Inappropriate ioctl for device")

        def forbidden_input(prompt: str = "") -> str:
            raise AssertionError("input() must NEVER be called when getpass fails!")

        monkeypatch.setattr("getpass.getpass", broken_getpass)
        monkeypatch.setattr("builtins.input", forbidden_input)

        exit_code = cli_main(["activate"])
        assert exit_code == 1

        captured = capsys.readouterr()
        assert "Error: Secure prompting is unavailable. Cannot prompt for activation code." in captured.err

    def test_cli_activate_empty_code_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """CLI activate command with empty code fails with exit code 1."""
        monkeypatch.setattr("getpass.getpass", lambda prompt="": "")
        exit_code = cli_main(["activate"])
        assert exit_code == 1

        captured = capsys.readouterr()
        assert "Activation code is required" in captured.err

    def test_cli_activate_backend_error_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
        tmp_path: Any,
    ) -> None:
        """CLI activate command prints safe error message on backend failure without leaking secrets."""
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(410, json={"code": "activation_expired", "detail": "Code expired."})

        mock_client = make_mock_client(mock_handler)

        watch_dir = tmp_path / "watch"
        watch_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("DOCFLOW_API_BASE_URL", "https://api.docflow.example.com")
        monkeypatch.setenv("WATCH_FOLDER", str(watch_dir))
        monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "agent.db"))
        monkeypatch.setattr("docflow_agent.cli.ApiClient", lambda **kwargs: mock_client)

        secret_expired_code = "CANARY_EXPIRED_CODE_778899"
        monkeypatch.setattr("getpass.getpass", lambda prompt="": secret_expired_code)

        with caplog.at_level(logging.DEBUG):
            exit_code = cli_main(["activate"])
        assert exit_code == 1

        captured = capsys.readouterr()
        assert "Activation failed: activation_expired" in captured.err
        assert secret_expired_code not in captured.err
        assert secret_expired_code not in captured.out
        assert secret_expired_code not in caplog.text
