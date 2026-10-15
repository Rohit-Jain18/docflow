"""
Agent configuration module.

Reads settings from environment variables and an optional TOML config file.
Validates all required values at startup.  Fails fast on invalid or missing
required configuration so errors are visible before any network operations.

Configuration sources (in priority order, highest wins):
1. Environment variables  (DOCFLOW_AGENT_* prefix and documented aliases)
2. TOML config file       (path in DOCFLOW_AGENT_CONFIG_FILE or agent.toml)
3. Built-in defaults

Secret material (device tokens, refresh credentials) is NEVER read from
environment variables or config files.  See `credentials.py` for the
secure-store interface.
"""

from __future__ import annotations

import logging
import os
import pathlib
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults from docs/AGENT_SPEC.md and docs/ENVIRONMENT.md
# ---------------------------------------------------------------------------
_DEFAULTS: dict[str, Any] = {
    "api_base_url": "",                      # Required, no default
    "watch_folder": "",                      # Required, no default
    "archive_folder": "",                    # Required, no default
    "quarantine_folder": "",                 # Required, no default
    "db_path": "docflow_agent.db",           # Local SQLite path
    "phone_default_region": "IN",
    "stability_sample_seconds": 2,
    "stability_required_samples": 3,
    "stability_timeout_seconds": 120,
    "max_pdf_size_bytes": 52_428_800,        # 50 MiB
    "cleanup_retention_hours": 24,
    "failed_retention_days": 14,
    "temp_upload_expected_host": "tmpfiles.org",
    "temp_upload_ttl_seconds": 3600,
    "temp_upload_expiry_buffer_seconds": 300,
    "log_level": "INFO",
    "log_file": "",                          # Optional file logging path
}

# Environment variable prefix
_ENV_PREFIX = "DOCFLOW_AGENT_"

# Documented aliases from docs/ENVIRONMENT.md §5
_ENV_ALIASES: dict[str, str] = {
    "DOCFLOW_API_BASE_URL": "api_base_url",
    "WATCH_FOLDER": "watch_folder",
    "ARCHIVE_FOLDER": "archive_folder",
    "QUARANTINE_FOLDER": "quarantine_folder",
    "AGENT_DB_PATH": "db_path",
    "PHONE_DEFAULT_REGION": "phone_default_region",
    "STABILITY_SAMPLE_SECONDS": "stability_sample_seconds",
    "STABILITY_REQUIRED_SAMPLES": "stability_required_samples",
    "STABILITY_TIMEOUT_SECONDS": "stability_timeout_seconds",
    "MAX_PDF_SIZE_BYTES": "max_pdf_size_bytes",
    "AGENT_CLEANUP_RETENTION_HOURS": "cleanup_retention_hours",
    "AGENT_FAILED_RETENTION_DAYS": "failed_retention_days",
    "TEMP_UPLOAD_EXPECTED_HOST": "temp_upload_expected_host",
    "TEMP_UPLOAD_TTL_SECONDS": "temp_upload_ttl_seconds",
    "TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS": "temp_upload_expiry_buffer_seconds",
    "AGENT_LOG_LEVEL": "log_level",
    "AGENT_LOG_FILE": "log_file",
}

# Fields that MUST be set to a non-empty value
_REQUIRED_FIELDS = frozenset({"api_base_url", "watch_folder"})

# Prohibited secret keys that must never be in configuration
_PROHIBITED_SECRET_KEYS = frozenset({
    "wa_platform_developer_token",
    "whatsapp_token",
    "device_token",
    "device_refresh_token",
    "refresh_token",
    "access_token",
    "secret_key",
    "password",
})


class ConfigError(Exception):
    """Raised when agent configuration is invalid or incomplete."""


# ---------------------------------------------------------------------------
# Parsed, validated configuration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AgentConfig:
    """Immutable, validated agent configuration."""

    api_base_url: str
    watch_folder: str
    archive_folder: str
    quarantine_folder: str
    db_path: str
    phone_default_region: str
    stability_sample_seconds: int
    stability_required_samples: int
    stability_timeout_seconds: int
    max_pdf_size_bytes: int
    cleanup_retention_hours: int
    failed_retention_days: int
    temp_upload_expected_host: str
    temp_upload_ttl_seconds: int
    temp_upload_expiry_buffer_seconds: int
    log_level: str
    log_file: str = ""
    # Populated during loading; never from user input
    _source: str = field(default="defaults", repr=False)


# ---------------------------------------------------------------------------
# TOML loading (stdlib tomllib, Python 3.11+)
# ---------------------------------------------------------------------------
def _load_toml(path: pathlib.Path) -> dict[str, Any]:
    """Load a TOML config file, returning the [agent] table or top-level."""
    import tomllib

    with path.open("rb") as fh:
        data = tomllib.load(fh)
    # Support both [agent] section and top-level keys
    return dict(data.get("agent", data))


# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------
def _load_env(raw_env: dict[str, str] | None = None) -> dict[str, str]:
    """Collect environment variables from aliases, DOCFLOW_AGENT_* prefix, and direct keys."""
    env_source = os.environ if raw_env is None else raw_env
    result: dict[str, str] = {}

    # Check documented aliases first
    for env_var, config_key in _ENV_ALIASES.items():
        if env_var in env_source:
            result[config_key] = env_source[env_var]

    # Check direct keys and DOCFLOW_AGENT_* prefix (higher priority)
    for key, value in env_source.items():
        upper = key.upper()
        if upper.startswith(_ENV_PREFIX):
            config_key = upper[len(_ENV_PREFIX):].lower()
            result[config_key] = value
        elif key in _DEFAULTS or key.lower() in _DEFAULTS or key in _PROHIBITED_SECRET_KEYS:
            result[key.lower()] = value

    return result


# ---------------------------------------------------------------------------
# Type coercion helpers
# ---------------------------------------------------------------------------
_INT_FIELDS = frozenset({
    "stability_sample_seconds",
    "stability_required_samples",
    "stability_timeout_seconds",
    "max_pdf_size_bytes",
    "cleanup_retention_hours",
    "failed_retention_days",
    "temp_upload_ttl_seconds",
    "temp_upload_expiry_buffer_seconds",
})


def _coerce(key: str, raw: Any) -> Any:
    """Coerce a raw config value to the expected type."""
    if key in _INT_FIELDS:
        try:
            return int(raw)
        except (ValueError, TypeError) as exc:
            raise ConfigError(
                f"Configuration '{key}' must be an integer, got {type(raw).__name__}: {raw!r}"
            ) from exc
    return raw


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _validate(values: dict[str, Any]) -> list[str]:
    """Return a list of human-readable validation errors (empty = valid)."""
    errors: list[str] = []

    # Prohibited secret keys check
    for secret_key in _PROHIBITED_SECRET_KEYS:
        if secret_key in values:
            errors.append(
                f"Prohibited secret key '{secret_key}' found in configuration. "
                "Secrets must be stored in secure credential storage, never plaintext config."
            )

    # Required fields
    for name in _REQUIRED_FIELDS:
        if not values.get(name):
            errors.append(f"Required configuration '{name}' is missing or empty.")

    # API URL must look like a URL
    url = values.get("api_base_url", "")
    if url and not (url.startswith("http://") or url.startswith("https://")):
        errors.append(
            f"'api_base_url' must start with http:// or https://, got: {url!r}"
        )

    # Watch folder must be an existing directory (when provided)
    watch = values.get("watch_folder", "")
    if watch:
        wp = pathlib.Path(watch)
        if not wp.is_dir():
            errors.append(
                f"'watch_folder' does not exist or is not a directory: {watch!r}"
            )

    # Numeric range checks
    if values.get("stability_sample_seconds", 0) < 1:
        errors.append("'stability_sample_seconds' must be >= 1.")
    if values.get("stability_required_samples", 0) < 1:
        errors.append("'stability_required_samples' must be >= 1.")
    if values.get("stability_timeout_seconds", 0) < 1:
        errors.append("'stability_timeout_seconds' must be >= 1.")
    if values.get("max_pdf_size_bytes", 0) < 1:
        errors.append("'max_pdf_size_bytes' must be >= 1.")
    retention_hours = values.get("cleanup_retention_hours", 0)
    if retention_hours < 1:
        errors.append("'cleanup_retention_hours' must be >= 1.")
    failed_days = values.get("failed_retention_days", 0)
    if not (1 <= failed_days <= 90):
        errors.append("'failed_retention_days' must be between 1 and 90.")

    # Archive/quarantine must not be inside watch folder (recursive overlap)
    if watch:
        watch_resolved = pathlib.Path(watch).resolve()
        for folder_key in ("archive_folder", "quarantine_folder"):
            folder_val = values.get(folder_key, "")
            if folder_val:
                folder_resolved = pathlib.Path(folder_val).resolve()
                try:
                    folder_resolved.relative_to(watch_resolved)
                    errors.append(
                        f"'{folder_key}' ({folder_val!r}) must not be inside "
                        f"'watch_folder' ({watch!r}) to prevent recursive watching."
                    )
                except ValueError:
                    pass  # Not inside watch folder — correct

    return errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def load_config(
    config_file: str | pathlib.Path | None = None,
    env: dict[str, str] | None = None,
) -> AgentConfig:
    """Load, merge and validate agent configuration.

    Args:
        config_file: Explicit path to a TOML file.  If None, checks the
                     DOCFLOW_AGENT_CONFIG_FILE env var, then ``agent.toml``
                     in the current directory.
        env:         Override for environment variables (used in testing).

    Returns:
        A validated, immutable ``AgentConfig``.

    Raises:
        ConfigError: On missing required values or invalid configuration.
    """
    # 1. Start with defaults
    merged: dict[str, Any] = dict(_DEFAULTS)
    source = "defaults"

    # 2. Layer TOML config file (if present)
    if config_file is None:
        config_file_str = os.environ.get("DOCFLOW_AGENT_CONFIG_FILE", "")
        if config_file_str:
            config_file = pathlib.Path(config_file_str)
        else:
            candidate = pathlib.Path("agent.toml")
            if candidate.is_file():
                config_file = candidate

    if config_file is not None:
        path = pathlib.Path(config_file)
        if not path.is_file():
            raise ConfigError(f"Config file not found: {path}")
        toml_values = _load_toml(path)
        merged.update(toml_values)
        source = f"toml:{path}"

    # 3. Layer environment variables (highest priority)
    env_values = _load_env(env) if env is not None else _load_env()
    if env_values:
        merged.update(env_values)
        source = "env" if not config_file else f"env+toml:{config_file}"

    # 4. Coerce types
    for key in list(merged.keys()):
        merged[key] = _coerce(key, merged[key])

    # 5. Validate
    errors = _validate(merged)
    if errors:
        msg = "Agent configuration is invalid:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ConfigError(msg)

    # 6. Build immutable config
    config_fields = {f.name for f in AgentConfig.__dataclass_fields__.values() if f.name != "_source"}
    filtered = {k: v for k, v in merged.items() if k in config_fields}
    return AgentConfig(**filtered, _source=source)
