"""
Logging module for the Docflow Windows Agent.

Provides structured logging with:
- ISO-8601 timestamps
- Severity levels
- Operational context (agent version, component)
- Mandatory redaction of sensitive values
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
# Redacting log filter
# ---------------------------------------------------------------------------

class RedactionFilter(logging.Filter):
    """Logging filter that scrubs sensitive data from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact(str(a)) if isinstance(a, str) else a for a in record.args
                )
        return True


# ---------------------------------------------------------------------------
# Log formatter
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
        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
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
