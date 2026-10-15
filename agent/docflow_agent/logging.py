"""
Logging module for the Docflow Windows Agent.

Provides structured logging with:
- ISO-8601 timestamps
- Severity levels
- Operational context (agent version, component)
- Mandatory recursive redaction of sensitive values
- Console (stream) and file handler support

SECURITY: Logs must NEVER contain:
- Device tokens or refresh credentials
- Patient phone numbers (full)
- PDF file contents
- Raw filenames or absolute source paths
- Direct media URLs
- Provider payloads or access tokens
"""

from __future__ import annotations

import logging
import pathlib
import re
import sys
from collections.abc import Mapping
from typing import Any

# ---------------------------------------------------------------------------
# Sensitive-value redaction
# ---------------------------------------------------------------------------

# Patterns that match common sensitive data in log messages
_REDACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Phone numbers: +91XXXXXXXXXX or similar international formats
    # Redact to keep country code + last 4 digits
    (
        re.compile(r"(\+?\d{1,3})\d{4,}(\d{4})"),
        r"\1******\2",
    ),
    # Bearer tokens / Authorization headers
    (
        re.compile(r"(Bearer\s+)\S+", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
    # Generic token= or key= or secret= or password= values
    (
        re.compile(
            r"((?:token|key|secret|password|credential|refresh_token|access_token)"
            r"\s*[=:]\s*)\S+",
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
    # URLs that look like temporary media (tmpfiles.org or similar direct links)
    (
        re.compile(r"https?://tmpfiles\.org/\S+", re.IGNORECASE),
        "[REDACTED_URL]",
    ),
    # Windows absolute paths (e.g., C:\Users\...)
    (
        re.compile(r"[A-Za-z]:\\(?:Users|Documents|Downloads)\\\S+"),
        "[REDACTED_PATH]",
    ),
]


def redact(message: str) -> str:
    """Apply redaction patterns to a log message.

    Returns the message with sensitive values replaced by safe placeholders.
    """
    result = message
    for pattern, replacement in _REDACTION_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


# ---------------------------------------------------------------------------
# Key normalization and sensitive key detection
# ---------------------------------------------------------------------------

def normalize_key(key: Any) -> str:
    """Normalize a key by converting camelCase, hyphens, and spaces to snake_case."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
    s = re.sub(r"[-.\s]+", "_", s).lower()
    return s.strip("_")


_SENSITIVE_KEY_STEMS = frozenset({
    "access_token",
    "refresh_token",
    "device_token",
    "authorization",
    "password",
    "secret",
    "credential",
    "token",
    "secret_key",
    "wa_platform_developer_token",
    "whatsapp_token",
})

_SENSITIVE_SUBSTRINGS = (
    "access_token",
    "refresh_token",
    "device_token",
    "authorization",
    "password",
    "secret",
    "credential",
)


def is_sensitive_key(key: Any) -> bool:
    """Check if key matches sensitive key patterns across case/separator/camelCase variants."""
    norm = normalize_key(key)
    if norm in _SENSITIVE_KEY_STEMS:
        return True
    parts = norm.split("_")
    for part in parts:
        if part in ("password", "secret", "credential", "authorization"):
            return True
    for sub in _SENSITIVE_SUBSTRINGS:
        if sub in norm:
            return True
    if norm.endswith("_token") or norm.startswith("token_"):
        return True
    return False


def redact_value(value: Any) -> Any:
    """Recursively scrub sensitive data from strings, mappings, lists, tuples, and structures."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, Mapping):
        return {
            k: "[REDACTED]" if is_sensitive_key(k) else redact_value(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__") and not isinstance(value, type):
        try:
            return {
                k: "[REDACTED]" if is_sensitive_key(k) else redact_value(v)
                for k, v in vars(value).items()
            }
        except Exception:
            return redact(str(value))
    return redact(str(value))


# ---------------------------------------------------------------------------
# Redacting log filter & Formatter
# ---------------------------------------------------------------------------

class RedactionFilter(logging.Filter):
    """Logging filter that scrubs sensitive data recursively from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_value(record.msg)
        if record.args:
            if isinstance(record.args, Mapping):
                record.args = redact_value(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(redact_value(a) for a in record.args)
            elif isinstance(record.args, list):
                record.args = [redact_value(a) for a in record.args]
            else:
                record.args = redact_value(record.args)
        return True


class RedactingFormatter(logging.Formatter):
    """Logging formatter that guarantees final formatted record messages are completely scrubbed."""

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        return redact(formatted)


# ---------------------------------------------------------------------------
# Log formatter constants
# ---------------------------------------------------------------------------

_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_logging(
    level: str = "INFO",
    *,
    stream: Any = None,
    log_file: str | pathlib.Path | None = None,
) -> logging.Logger:
    """Configure the agent's root logger.

    Args:
        level:    Logging level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        stream:   Output stream; defaults to sys.stderr.
        log_file: Optional path to a log file. Both console and file handlers
                  enforce sensitive value redaction.

    Returns:
        The configured ``docflow_agent`` logger.
    """
    if stream is None:
        stream = sys.stderr

    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    root_logger = logging.getLogger("docflow_agent")
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers on repeated calls
    if not root_logger.handlers:
        # Console stream handler
        handler = logging.StreamHandler(stream)
        handler.setLevel(numeric_level)
        formatter = RedactingFormatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
        handler.setFormatter(formatter)
        handler.addFilter(RedactionFilter())
        root_logger.addHandler(handler)

        # File handler if requested
        if log_file:
            path = pathlib.Path(log_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(str(path), encoding="utf-8")
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)
            file_handler.addFilter(RedactionFilter())
            root_logger.addHandler(file_handler)

    return root_logger
