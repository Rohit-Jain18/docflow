"""Tests for docflow_agent.logging — redaction and logger setup."""

import io
import logging
import pytest

from docflow_agent.logging import (
    RedactionFilter,
    is_sensitive_key,
    normalize_key,
    redact,
    redact_value,
    setup_logging,
)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

class TestRedaction:
    """Verify sensitive values are scrubbed from log messages."""

    def test_phone_number_redacted(self) -> None:
        msg = "Sending to +919876543210"
        result = redact(msg)
        assert "9876543210" not in result
        assert "3210" in result  # Last 4 preserved
        assert "******" in result

    def test_short_phone_redacted(self) -> None:
        msg = "Number: 9876543210"
        result = redact(msg)
        assert "98765" not in result

    def test_bearer_token_redacted(self) -> None:
        msg = "Authorization: Bearer eyJhbGciOiJ.super-secret-token"
        result = redact(msg)
        assert "eyJhbGciOiJ" not in result
        assert "[REDACTED]" in result

    def test_secret_key_value_redacted(self) -> None:
        msg = "token=abc123secret"
        result = redact(msg)
        assert "abc123secret" not in result
        assert "[REDACTED]" in result

    def test_password_redacted(self) -> None:
        msg = "password: hunter2"
        result = redact(msg)
        assert "hunter2" not in result

    def test_refresh_token_redacted(self) -> None:
        msg = "refresh_token=very-long-refresh-token-value"
        result = redact(msg)
        assert "very-long-refresh-token-value" not in result

    def test_tmpfiles_url_redacted(self) -> None:
        msg = "Uploaded to https://tmpfiles.org/dl/12345/test.pdf"
        result = redact(msg)
        assert "tmpfiles.org" not in result
        assert "[REDACTED_URL]" in result

    def test_windows_path_redacted(self) -> None:
        msg = r"Processing C:\Users\JohnDoe\Documents\patient_report.pdf"
        result = redact(msg)
        assert "JohnDoe" not in result
        assert "[REDACTED_PATH]" in result

    def test_safe_message_unchanged(self) -> None:
        msg = "Report abc123 registered successfully."
        result = redact(msg)
        assert result == msg


# ---------------------------------------------------------------------------
# Sensitive key normalization & detection
# ---------------------------------------------------------------------------

class TestKeyNormalization:
    """Verify key normalization and sensitive key detection."""

    @pytest.mark.parametrize(
        "key",
        [
            "access_token",
            "accessToken",
            "access-token",
            "ACCESS_TOKEN",
            "refresh_token",
            "refreshToken",
            "refresh-token",
            "REFRESH_TOKEN",
            "device_token",
            "deviceToken",
            "device-token",
            "DEVICE_TOKEN",
            "authorization",
            "Authorization",
            "AUTHORIZATION",
            "password",
            "userPassword",
            "secret",
            "clientSecret",
            "credential",
            "deviceCredential",
            "wa_platform_developer_token",
        ],
    )
    def test_sensitive_keys_detected(self, key: str) -> None:
        assert is_sensitive_key(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            "status",
            "report_id",
            "file_size_bytes",
            "mtime_ns",
            "watch_folder",
            "phone_default_region",
        ],
    )
    def test_safe_keys_not_flagged(self, key: str) -> None:
        assert is_sensitive_key(key) is False


# ---------------------------------------------------------------------------
# Recursive value redaction
# ---------------------------------------------------------------------------

class TestRecursiveRedaction:
    """Verify recursive redaction on nested dicts, lists, and tuples."""

    def test_nested_dictionary_redacted(self) -> None:
        data = {
            "meta": {"status": "ok", "version": 1},
            "auth": {
                "accessToken": "secret-access-token-123",
                "refresh-token": "secret-refresh-token-456",
                "nested": {
                    "deviceToken": "device-token-789",
                    "Password": "superpassword",
                    "safe": "visible",
                },
            },
        }
        redacted = redact_value(data)
        assert redacted["meta"]["status"] == "ok"
        assert redacted["auth"]["accessToken"] == "[REDACTED]"
        assert redacted["auth"]["refresh-token"] == "[REDACTED]"
        assert redacted["auth"]["nested"]["deviceToken"] == "[REDACTED]"
        assert redacted["auth"]["nested"]["Password"] == "[REDACTED]"
        assert redacted["auth"]["nested"]["safe"] == "visible"
        assert "secret-access-token-123" not in str(redacted)
        assert "secret-refresh-token-456" not in str(redacted)
        assert "superpassword" not in str(redacted)

    def test_list_and_tuple_nested_redacted(self) -> None:
        data = [
            {"name": "batch1", "secret": "shhh"},
            ({"item": "tuple_entry", "Authorization": "Bearer secret_jwt"},),
            "safe string with phone +919876543210",
        ]
        redacted = redact_value(data)
        assert redacted[0]["name"] == "batch1"
        assert redacted[0]["secret"] == "[REDACTED]"
        assert redacted[1][0]["Authorization"] == "[REDACTED]"
        assert "3210" in redacted[2]
        assert "******" in redacted[2]
        assert "shhh" not in str(redacted)
        assert "secret_jwt" not in str(redacted)


# ---------------------------------------------------------------------------
# RedactionFilter
# ---------------------------------------------------------------------------

class TestRedactionFilter:
    """Verify the logging filter applies redaction."""

    def test_filter_redacts_message(self) -> None:
        filt = RedactionFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Token: Bearer secret123",
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert "secret123" not in record.msg

    def test_filter_redacts_string_args(self) -> None:
        filt = RedactionFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="User %s connected",
            args=("+919876543210",),
            exc_info=None,
        )
        filt.filter(record)
        assert isinstance(record.args, tuple)
        assert "9876543210" not in str(record.args[0])

    def test_filter_redacts_dict_args(self) -> None:
        filt = RedactionFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Data: %(token)s",
            args=None,
            exc_info=None,
        )
        record.args = {"token": "secret=mysecretvalue"}
        filt.filter(record)
        assert isinstance(record.args, dict)
        assert "mysecretvalue" not in str(record.args["token"])

    def test_filter_redacts_nested_args(self) -> None:
        filt = RedactionFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Event: %s",
            args=None,
            exc_info=None,
        )
        record.args = ({"auth": {"accessToken": "top_secret_token_val", "safe": 123}},)
        filt.filter(record)
        assert isinstance(record.args, tuple)
        assert "top_secret_token_val" not in str(record.args)
        assert record.args[0]["auth"]["accessToken"] == "[REDACTED]"
        assert record.args[0]["auth"]["safe"] == 123

    def test_filter_redacts_structured_message(self) -> None:
        filt = RedactionFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg={"event": "login", "refreshToken": "secret_refresh_token_xyz"},
            args=(),
            exc_info=None,
        )
        filt.filter(record)
        assert isinstance(record.msg, dict)
        assert record.msg["refreshToken"] == "[REDACTED]"
        assert "secret_refresh_token_xyz" not in str(record.msg)


# ---------------------------------------------------------------------------
# Logger initialization
# ---------------------------------------------------------------------------

class TestSetupLogging:
    """Verify logger initialization and formatting scrub."""

    def test_returns_logger(self) -> None:
        logger = setup_logging(level="DEBUG")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "docflow_agent"

    def test_sets_level(self) -> None:
        logger = setup_logging(level="WARNING")
        assert logger.level == logging.WARNING

    def test_invalid_level_defaults_to_info(self) -> None:
        logger = setup_logging(level="NONEXISTENT")
        assert logger.level == logging.INFO

    def test_has_handler(self) -> None:
        logger = setup_logging(level="INFO")
        assert len(logger.handlers) >= 1

    def test_handler_has_redaction_filter(self) -> None:
        logger = setup_logging(level="INFO")
        handler = logger.handlers[0]
        filter_types = [type(f) for f in handler.filters]
        assert RedactionFilter in filter_types

    def test_file_logging_creates_file_and_redacts(self, tmp_path) -> None:
        log_path = tmp_path / "test_agent.log"
        logger = setup_logging(level="INFO", log_file=log_path)
        assert len(logger.handlers) == 2  # StreamHandler + FileHandler
        logger.info("Sensitive token: Bearer my-secret-jwt-token")
        for h in logger.handlers:
            h.flush()
        assert log_path.is_file()
        content = log_path.read_text(encoding="utf-8")
        assert "my-secret-jwt-token" not in content
        assert "[REDACTED]" in content

    def test_nested_dict_output_in_stream_and_file_redacted(self, tmp_path) -> None:
        stream = io.StringIO()
        log_path = tmp_path / "nested_test.log"
        logger = setup_logging(level="INFO", stream=stream, log_file=log_path)

        logger.info("Event payload: %s", {
            "credentials": {"accessToken": "exposed_secret_1234"},
            "user": "dr_smith",
        })
        for h in logger.handlers:
            h.flush()

        # Check console stream output
        stream_val = stream.getvalue()
        assert "exposed_secret_1234" not in stream_val
        assert "[REDACTED]" in stream_val
        assert "dr_smith" in stream_val

        # Check file output
        file_val = log_path.read_text(encoding="utf-8")
        assert "exposed_secret_1234" not in file_val
        assert "[REDACTED]" in file_val
        assert "dr_smith" in file_val

    @pytest.fixture(autouse=True)
    def _cleanup_logger(self) -> None:  # type: ignore[misc]
        """Remove handlers between tests to avoid accumulation."""
        yield  # type: ignore[misc]
        logger = logging.getLogger("docflow_agent")
        for h in list(logger.handlers):
            h.close()
        logger.handlers.clear()
