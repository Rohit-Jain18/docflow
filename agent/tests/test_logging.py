"""Tests for docflow_agent.logging — redaction and logger setup."""

import logging

import pytest

from docflow_agent.logging import RedactionFilter, redact, setup_logging


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
        # Set dict args after construction to avoid Python 3.13
        # LogRecord.__init__ indexing issue with Mapping detection.
        record.args = {"token": "secret=mysecretvalue"}
        filt.filter(record)
        assert isinstance(record.args, dict)
        assert "mysecretvalue" not in str(record.args["token"])


# ---------------------------------------------------------------------------
# Logger initialization
# ---------------------------------------------------------------------------


class TestSetupLogging:
    """Verify logger initialization."""

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

    @pytest.fixture(autouse=True)
    def _cleanup_logger(self) -> None:  # type: ignore[misc]
        """Remove handlers between tests to avoid accumulation."""
        yield  # type: ignore[misc]
        logger = logging.getLogger("docflow_agent")
        for h in list(logger.handlers):
            h.close()
        logger.handlers.clear()
