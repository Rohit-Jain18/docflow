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

import ipaddress
import logging
import os
import pathlib
import re
import urllib.parse
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


class ConfigError(Exception):
    """Raised when agent configuration is invalid or incomplete."""


# ---------------------------------------------------------------------------
# Key normalization & Prohibited secret detection
# ---------------------------------------------------------------------------

def normalize_key(key: Any) -> str:
    """Normalize a key by converting camelCase, hyphens, and spaces to snake_case."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key))
    s = re.sub(r"[-.\s]+", "_", s).lower()
    return s.strip("_")


_PROHIBITED_KEY_STEMS = frozenset({
    "wa_platform_developer_token",
    "whatsapp_token",
    "device_token",
    "device_refresh_token",
    "refresh_token",
    "access_token",
    "secret_key",
    "password",
    "secret",
    "credential",
    "token",
    "authorization",
})

_PROHIBITED_SUBSTRINGS = (
    "wa_platform_developer_token",
    "whatsapp_token",
    "device_token",
    "device_refresh_token",
    "refresh_token",
    "access_token",
    "secret_key",
    "password",
    "secret",
    "credential",
    "authorization",
)


def is_prohibited_key(key: Any) -> bool:
    """Check if normalized key represents a prohibited secret key."""
    norm = normalize_key(key)
    if norm in _PROHIBITED_KEY_STEMS:
        return True
    parts = norm.split("_")
    for part in parts:
        if part in ("password", "secret", "credential", "authorization"):
            return True
    for sub in _PROHIBITED_SUBSTRINGS:
        if sub in norm:
            return True
    if norm.endswith("_token") or norm.startswith("token_"):
        return True
    return False


def _inspect_toml_for_secrets(data: Any, path_prefix: str = "") -> list[str]:
    """Recursively search a parsed TOML structure for prohibited secret keys.

    Returns the list of matching key paths (e.g. 'security.password').
    Never includes values.
    """
    prohibited: list[str] = []
    if isinstance(data, dict):
        for k, v in data.items():
            current_path = f"{path_prefix}.{k}" if path_prefix else str(k)
            if is_prohibited_key(str(k)):
                prohibited.append(current_path)
            if isinstance(v, (dict, list)):
                prohibited.extend(_inspect_toml_for_secrets(v, current_path))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            current_path = f"{path_prefix}[{idx}]"
            prohibited.extend(_inspect_toml_for_secrets(item, current_path))
    return prohibited


# ---------------------------------------------------------------------------
# URL Validation
# ---------------------------------------------------------------------------

def is_loopback_host(hostname: str) -> bool:
    """Return True if hostname is a loopback destination."""
    if not hostname:
        return False
    clean = hostname.strip("[]").lower()
    if clean == "localhost":
        return True
    try:
        return ipaddress.ip_address(clean).is_loopback
    except ValueError:
        return False


def validate_api_base_url(url: str) -> list[str]:
    """Validate API base URL according to security rules without echoing sensitive input.

    Rules:
    - Must be a non-empty string.
    - Scheme must be http or https.
    - Valid hostname is required.
    - Userinfo (username/password) is prohibited and must never be echoed.
    - Query strings and URL fragments are prohibited and must never be echoed.
    - Port must be a valid integer between 1 and 65535.
    - IPv6 authorities must be properly formatted.
    - Plain HTTP is permitted ONLY for loopback development destinations (localhost, 127.0.0.1, ::1).
    - Non-loopback destinations MUST use HTTPS.
    - Error messages MUST NEVER echo the raw URL, userinfo, query values, or fragments.
    """
    if not url or not isinstance(url, str) or not url.strip():
        return ["API base URL is missing or empty."]

    raw_url = url.strip()
    try:
        parsed = urllib.parse.urlsplit(raw_url)
    except Exception:
        return ["API base URL is malformed or contains an invalid host authority."]

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return ["API base URL scheme must be http or https."]

    # Userinfo check without echoing values
    has_userinfo = False
    try:
        if parsed.username is not None or parsed.password is not None:
            has_userinfo = True
    except Exception:
        has_userinfo = True

    if not has_userinfo and "@" in parsed.netloc:
        has_userinfo = True

    if has_userinfo:
        return ["API base URL must not contain userinfo (username or password)."]

    # Query strings must never be echoed
    if parsed.query:
        return ["API base URL must not contain query parameters."]

    # Fragments must never be echoed
    if parsed.fragment:
        return ["API base URL must not contain URL fragments."]

    # Safely extract and validate hostname
    try:
        hostname = parsed.hostname
    except Exception:
        return ["API base URL is malformed or contains an invalid host authority."]

    if not hostname:
        return ["API base URL must include a valid hostname."]

    # Validate port range safely (1 to 65535)
    try:
        port = parsed.port
        if port is not None and not (1 <= port <= 65535):
            return ["API base URL contains a malformed or out-of-range port (must be between 1 and 65535)."]
    except Exception:
        return ["API base URL contains a malformed or out-of-range port (must be between 1 and 65535)."]

    # Enforce HTTPS for non-loopback destinations
    if scheme == "http":
        try:
            is_loopback = is_loopback_host(hostname)
        except Exception:
            return ["API base URL contains an invalid host address."]

        if not is_loopback:
            return [
                "API base URL uses unencrypted HTTP for a non-loopback destination. "
                "Plain HTTP is only permitted for loopback development destinations (localhost, 127.0.0.1); "
                "non-loopback destinations require HTTPS."
            ]

    return []


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
    """Load a TOML config file, inspecting the entire document for secrets."""
    import tomllib

    try:
        with path.open("rb") as fh:
            raw_data = tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"Failed to read or parse config file '{path}': {exc}") from exc

    # Recursively check the entire TOML structure before selecting settings
    prohibited_keys = _inspect_toml_for_secrets(raw_data)
    if prohibited_keys:
        formatted = ", ".join(f"'{k}'" for k in sorted(prohibited_keys))
        raise ConfigError(
            f"Prohibited secret configuration detected in '{path}': {formatted}. "
            "Secret material must never be placed in configuration files."
        )

    # Support both [agent] section and top-level keys
    return dict(raw_data.get("agent", raw_data))


# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------
def _load_env(raw_env: dict[str, str] | None = None) -> dict[str, str]:
    """Collect environment variables from aliases and DOCFLOW_AGENT_* prefix,
    detecting and rejecting any prohibited secret variables."""
    env_source = os.environ if raw_env is None else raw_env

    # Detect prohibited secret keys without case or separator bypasses
    for key in env_source:
        norm_key = normalize_key(key)
        is_agent_scoped = (
            raw_env is not None
            or norm_key.startswith("docflow_agent_")
            or norm_key.startswith("docflow_")
            or norm_key in (
                "wa_platform_developer_token",
                "whatsapp_token",
                "device_token",
                "device_refresh_token",
                "refresh_token",
                "access_token",
                "secret_key",
                "password",
            )
        )
        if is_agent_scoped:
            stripped = norm_key
            if stripped.startswith("docflow_agent_"):
                stripped = stripped[len("docflow_agent_"):]
            elif stripped.startswith("docflow_"):
                stripped = stripped[len("docflow_"):]
            if is_prohibited_key(stripped) or is_prohibited_key(norm_key):
                raise ConfigError(
                    f"Prohibited secret key '{key}' detected in environment. "
                    "Secrets must be stored in secure credential storage, never environment variables."
                )

    result: dict[str, str] = {}

    # Check documented aliases first (case-insensitive)
    normalized_env = {normalize_key(k): v for k, v in env_source.items()}
    for env_var, config_key in _ENV_ALIASES.items():
        norm_alias = normalize_key(env_var)
        if norm_alias in normalized_env:
            result[config_key] = normalized_env[norm_alias]

    # Prefix DOCFLOW_AGENT_* has higher priority over aliases
    for key, value in env_source.items():
        norm_k = normalize_key(key)
        if norm_k.startswith("docflow_agent_"):
            config_key = norm_k[len("docflow_agent_"):]
            result[config_key] = value
        elif raw_env is not None:
            # If explicit env dict was passed (testing), support direct keys
            if norm_k in _DEFAULTS or key in _DEFAULTS:
                result[norm_k] = value

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

    # Prohibited secret keys check in merged values
    for secret_key in values:
        if is_prohibited_key(secret_key):
            errors.append(
                f"Prohibited secret configuration '{secret_key}' detected. "
                "Secrets must be stored in secure credential storage, never plaintext config."
            )

    # Required fields
    for name in _REQUIRED_FIELDS:
        if not values.get(name):
            errors.append(f"Required configuration '{name}' is missing or empty.")

    # API base URL validation
    url_val = values.get("api_base_url", "")
    if url_val:
        errors.extend(validate_api_base_url(url_val))

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
