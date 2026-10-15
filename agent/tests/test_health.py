"""Tests for docflow_agent.health — health check module."""

import pathlib

import pytest

from docflow_agent.config import AgentConfig
from docflow_agent.health import HealthResult, health_check


def _make_config(tmp_path: pathlib.Path, **overrides: str | int) -> AgentConfig:
    """Create a valid AgentConfig for testing."""
    watch = tmp_path / "watch"
    watch.mkdir(exist_ok=True)
    archive = tmp_path / "archive"
    quarantine = tmp_path / "quarantine"
    defaults: dict[str, str | int] = {
        "api_base_url": "http://localhost:8000",
        "watch_folder": str(watch),
        "archive_folder": str(archive),
        "quarantine_folder": str(quarantine),
        "db_path": str(tmp_path / "agent.db"),
        "phone_default_region": "IN",
        "stability_sample_seconds": 2,
        "stability_required_samples": 3,
        "stability_timeout_seconds": 120,
        "max_pdf_size_bytes": 52_428_800,
        "cleanup_retention_hours": 24,
        "failed_retention_days": 14,
        "temp_upload_expected_host": "tmpfiles.org",
        "temp_upload_ttl_seconds": 3600,
        "temp_upload_expiry_buffer_seconds": 300,
        "log_level": "INFO",
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)  # type: ignore[arg-type]


class TestHealthCheckSuccess:
    """Verify health check reports healthy when config is valid."""

    def test_healthy_with_valid_config(self, tmp_path: pathlib.Path) -> None:
        config = _make_config(tmp_path)
        result = health_check(config=config)
        assert isinstance(result, HealthResult)
        assert result.healthy is True
        assert all(c.passed for c in result.checks)

    def test_summary_contains_healthy(self, tmp_path: pathlib.Path) -> None:
        config = _make_config(tmp_path)
        result = health_check(config=config)
        summary = result.summary()
        assert "HEALTHY" in summary

    def test_https_url_shows_https(self, tmp_path: pathlib.Path) -> None:
        config = _make_config(tmp_path, api_base_url="https://docflow.example.com")
        result = health_check(config=config)
        assert result.healthy is True
        url_check = [c for c in result.checks if c.name == "API base URL"][0]
        assert "HTTPS" in url_check.detail

    def test_archive_will_be_created(self, tmp_path: pathlib.Path) -> None:
        config = _make_config(tmp_path)
        result = health_check(config=config)
        archive_check = [c for c in result.checks if c.name == "Archive folder"][0]
        assert archive_check.passed is True
        assert "Will be created" in archive_check.detail


class TestHealthCheckFailure:
    """Verify health check detects problems."""

    def test_missing_watch_folder(self, tmp_path: pathlib.Path) -> None:
        config = _make_config(
            tmp_path, watch_folder=str(tmp_path / "nonexistent"),
        )
        result = health_check(config=config)
        assert result.healthy is False
        watch_check = [c for c in result.checks if c.name == "Watch folder"][0]
        assert watch_check.passed is False

    def test_summary_contains_unhealthy(self, tmp_path: pathlib.Path) -> None:
        config = _make_config(
            tmp_path, watch_folder=str(tmp_path / "nonexistent"),
        )
        result = health_check(config=config)
        summary = result.summary()
        assert "UNHEALTHY" in summary

    def test_invalid_log_level(self, tmp_path: pathlib.Path) -> None:
        config = _make_config(tmp_path, log_level="NONEXISTENT")
        result = health_check(config=config)
        assert result.healthy is False
        log_check = [c for c in result.checks if c.name == "Log level"][0]
        assert log_check.passed is False

    def test_forbidden_secret_environment_variable(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WA_PLATFORM_DEVELOPER_TOKEN", "EAAB_test_token")
        config = _make_config(tmp_path)
        result = health_check(config=config)
        assert result.healthy is False
        secret_check = [c for c in result.checks if c.name == "Secret safeguards"][0]
        assert secret_check.passed is False
        assert "Forbidden secret variables" in secret_check.detail

    def test_credential_store_readiness(self, tmp_path: pathlib.Path) -> None:
        from docflow_agent.credentials import InMemoryCredentialStore
        store = InMemoryCredentialStore()
        config = _make_config(tmp_path)
        res1 = health_check(config=config, credential_store=store)
        cred_check1 = [c for c in res1.checks if c.name == "Credential store"][0]
        assert cred_check1.passed is True
        assert "awaiting activation" in cred_check1.detail

        store.store("device_refresh_token", "sample_secret")
        res2 = health_check(config=config, credential_store=store)
        cred_check2 = [c for c in res2.checks if c.name == "Credential store"][0]
        assert cred_check2.passed is True
        assert "refresh token present" in cred_check2.detail
        # Ensure secret value is never in detail
        assert "sample_secret" not in cred_check2.detail
