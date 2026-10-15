"""
Lifecycle and health module for the Docflow Windows Agent.

Provides the ``health_check`` function used by the CLI ``health`` command
to validate that the agent is correctly configured and ready to operate.

The health check inspects:
1. Configuration validity (syntax, ranges, required fields).
2. Watch-folder access (existence and read permissions).
3. Write permissions (archive folder, quarantine folder, database path).
4. Credential readiness (OS credential store accessibility, refresh token readiness).
5. API base URL and connection scheme (strict hostname, no userinfo/query/fragment, loopback HTTP vs HTTPS).
6. Log level validity.
7. Secret exposure safeguards (ensuring no plaintext secrets exist in config/env).

It does NOT:
- Contact production services or the Docflow API.
- Display or log any secret values.
- Modify any business state.
"""

from __future__ import annotations

import logging
import os
import pathlib
import urllib.parse
from dataclasses import dataclass

from docflow_agent.config import (
    AgentConfig,
    ConfigError,
    is_prohibited_key,
    load_config,
    normalize_key,
    validate_api_base_url,
)
from docflow_agent.credentials import CredentialStore, get_credential_store

logger = logging.getLogger(__name__)


@dataclass
class HealthResult:
    """Result of a health check."""

    healthy: bool
    checks: list[CheckItem]

    def summary(self) -> str:
        """Human-readable summary."""
        lines: list[str] = []
        for item in self.checks:
            icon = "[OK]" if item.passed else "[FAIL]"
            lines.append(f"  {icon} {item.name}: {item.detail}")
        status = "HEALTHY" if self.healthy else "UNHEALTHY"
        lines.insert(0, f"Agent Health: {status}")
        return "\n".join(lines)


@dataclass
class CheckItem:
    """Individual check result."""

    name: str
    passed: bool
    detail: str


def _check_watch_folder(path_str: str) -> CheckItem:
    """Validate watch folder existence and read access."""
    if not path_str:
        return CheckItem(name="Watch folder", passed=False, detail="Not configured.")
    path = pathlib.Path(path_str)
    if not path.is_dir():
        return CheckItem(name="Watch folder", passed=False, detail=f"Not found or not a directory: {path}")
    if not os.access(path, os.R_OK):
        return CheckItem(name="Watch folder", passed=False, detail=f"No read permission: {path}")
    return CheckItem(name="Watch folder", passed=True, detail=f"Accessible (read OK): {path}")


def _check_write_folder(label: str, path_str: str) -> CheckItem:
    """Validate that a folder exists or can be created, and has write permission."""
    if not path_str:
        return CheckItem(name=label, passed=False, detail="Not configured.")
    path = pathlib.Path(path_str)
    if path.is_dir():
        if os.access(path, os.W_OK):
            return CheckItem(name=label, passed=True, detail=f"Exists (write OK): {path}")
        return CheckItem(name=label, passed=False, detail=f"No write permission: {path}")

    # If it does not exist, check if parent directory exists and is writable
    parent = path.parent
    if parent.is_dir():
        if os.access(parent, os.W_OK):
            return CheckItem(name=label, passed=True, detail=f"Will be created in: {parent}")
        return CheckItem(name=label, passed=False, detail=f"Parent directory not writable: {parent}")
    return CheckItem(name=label, passed=False, detail=f"Parent directory missing: {parent}")


def _check_db_path(db_path_str: str) -> CheckItem:
    """Validate that the SQLite database directory is writable."""
    if not db_path_str:
        return CheckItem(name="Database path", passed=False, detail="Not configured.")
    db_file = pathlib.Path(db_path_str)
    if db_file.exists():
        if os.access(db_file, os.W_OK):
            return CheckItem(name="Database path", passed=True, detail=f"Writable: {db_file}")
        return CheckItem(name="Database path", passed=False, detail=f"Not writable: {db_file}")
    parent = db_file.parent if db_file.parent != pathlib.Path("") else pathlib.Path(".")
    if parent.is_dir() and os.access(parent, os.W_OK):
        return CheckItem(name="Database path", passed=True, detail=f"Will be created in: {parent.resolve()}")
    return CheckItem(name="Database path", passed=False, detail=f"Parent directory not writable: {parent}")


def _check_credential_store(credential_store: CredentialStore | None = None) -> CheckItem:
    """Inspect credential store readiness without exposing secrets."""
    try:
        store = credential_store or get_credential_store()
        store_type = type(store).__name__
        has_token = store.exists("device_refresh_token")
        status_note = "refresh token present" if has_token else "awaiting activation (no token stored yet)"
        return CheckItem(
            name="Credential store",
            passed=True,
            detail=f"Ready ({store_type}; {status_note})",
        )
    except Exception as exc:
        return CheckItem(
            name="Credential store",
            passed=False,
            detail=f"Initialization failed: {exc}",
        )


def _check_secrets_exposure() -> CheckItem:
    """Verify that dangerous plaintext secrets are not exposed in the environment."""
    exposed = []
    for key in os.environ:
        norm_k = normalize_key(key)
        is_agent_scoped = (
            norm_k.startswith("docflow_agent_")
            or norm_k.startswith("docflow_")
            or norm_k in (
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
            stripped = norm_k
            if stripped.startswith("docflow_agent_"):
                stripped = stripped[len("docflow_agent_"):]
            elif stripped.startswith("docflow_"):
                stripped = stripped[len("docflow_"):]
            if is_prohibited_key(stripped) or is_prohibited_key(norm_k):
                exposed.append(key)

    if exposed:
        return CheckItem(
            name="Secret safeguards",
            passed=False,
            detail=f"Forbidden secret variables detected in environment: {', '.join(sorted(exposed))}",
        )
    return CheckItem(
        name="Secret safeguards",
        passed=True,
        detail="No prohibited secret keys detected in environment.",
    )


def health_check(
    config: AgentConfig | None = None,
    credential_store: CredentialStore | None = None,
) -> HealthResult:
    """Run agent health checks and return results.

    Args:
        config:           Pre-loaded config (for testing). If None, loads from
                          standard sources.
        credential_store: Pre-configured credential store (for testing).

    Returns:
        HealthResult with individual check outcomes.
    """
    checks: list[CheckItem] = []

    # 1. Configuration loading
    if config is None:
        try:
            config = load_config()
            checks.append(CheckItem(
                name="Configuration",
                passed=True,
                detail="Loaded and validated successfully.",
            ))
        except ConfigError as exc:
            checks.append(CheckItem(
                name="Configuration",
                passed=False,
                detail=str(exc),
            ))
            return HealthResult(healthy=False, checks=checks)
    else:
        checks.append(CheckItem(
            name="Configuration",
            passed=True,
            detail="Provided directly.",
        ))

    # 2. Watch folder access (read permissions)
    checks.append(_check_watch_folder(config.watch_folder))

    # 3. Archive folder write permission
    checks.append(_check_write_folder("Archive folder", config.archive_folder))

    # 4. Quarantine folder write permission
    checks.append(_check_write_folder("Quarantine folder", config.quarantine_folder))

    # 5. Database write permission
    checks.append(_check_db_path(config.db_path))

    # 6. Credential readiness
    checks.append(_check_credential_store(credential_store))

    # 7. Secrets exposure safeguard
    checks.append(_check_secrets_exposure())

    # 8. API base URL
    url_errors = validate_api_base_url(config.api_base_url)
    if url_errors:
        checks.append(CheckItem(
            name="API base URL",
            passed=False,
            detail="; ".join(url_errors),
        ))
    else:
        try:
            parsed = urllib.parse.urlsplit(config.api_base_url)
            if parsed.scheme.lower() == "https":
                detail = "HTTPS configured."
            else:
                detail = f"HTTP configured on loopback host ({parsed.hostname}) for development."
        except Exception:
            detail = "Valid API base URL configured."
        checks.append(CheckItem(
            name="API base URL",
            passed=True,
            detail=detail,
        ))

    # 9. Log level validity
    numeric = getattr(logging, config.log_level.upper(), None)
    if isinstance(numeric, int):
        checks.append(CheckItem(
            name="Log level",
            passed=True,
            detail=config.log_level.upper(),
        ))
    else:
        checks.append(CheckItem(
            name="Log level",
            passed=False,
            detail=f"Unknown level: {config.log_level!r}",
        ))

    healthy = all(c.passed for c in checks)
    return HealthResult(healthy=healthy, checks=checks)
