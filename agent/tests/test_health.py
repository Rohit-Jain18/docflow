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

    def test_loopback_http_shows_development(self, tmp_path: pathlib.Path) -> None:
        config = _make_config(tmp_path, api_base_url="http://127.0.0.1:8000")
        result = health_check(config=config)
        assert result.healthy is True
        url_check = [c for c in result.checks if c.name == "API base URL"][0]
        assert "development" in url_check.detail

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

    def test_malformed_url_reports_unhealthy(self, tmp_path: pathlib.Path) -> None:
        # Non-loopback HTTP
        config1 = _make_config(tmp_path, api_base_url="http://remote.example.com")
        res1 = health_check(config=config1)
        assert res1.healthy is False
        url_check1 = [c for c in res1.checks if c.name == "API base URL"][0]
        assert url_check1.passed is False
        assert "Plain HTTP is only permitted for loopback" in url_check1.detail

        # URL with query string
        config2 = _make_config(tmp_path, api_base_url="https://docflow.example.com?token=123")
        res2 = health_check(config=config2)
        assert res2.healthy is False
        url_check2 = [c for c in res2.checks if c.name == "API base URL"][0]
        assert url_check2.passed is False
        assert "API base URL must not contain query parameters" in url_check2.detail
        assert "123" not in url_check2.detail
        assert "token" not in url_check2.detail

    def test_tokens_in_query_and_fragment_never_echoed_in_health(self, tmp_path: pathlib.Path) -> None:
        query_token = "SECRET_HEALTH_QUERY_XYZ999"
        config_query = _make_config(tmp_path, api_base_url=f"https://docflow.example.com?token={query_token}")
        res_query = health_check(config=config_query)
        assert res_query.healthy is False
        summary_query = res_query.summary()
        assert query_token not in summary_query
        assert "API base URL must not contain query parameters" in summary_query

        frag_token = "SECRET_HEALTH_FRAG_ABC111"
        config_frag = _make_config(tmp_path, api_base_url=f"https://docflow.example.com#token={frag_token}")
        res_frag = health_check(config=config_frag)
        assert res_frag.healthy is False
        summary_frag = res_frag.summary()
        assert frag_token not in summary_frag
        assert "API base URL must not contain URL fragments" in summary_frag

    def test_userinfo_credentials_never_echoed_in_health(self, tmp_path: pathlib.Path) -> None:
        user = "admin_doctor"
        secret = "very_secret_pwd_99"
        config = _make_config(tmp_path, api_base_url=f"https://{user}:{secret}@docflow.example.com")
        res = health_check(config=config)
        assert res.healthy is False
        summary = res.summary()
        assert user not in summary
        assert secret not in summary
        assert "API base URL must not contain userinfo" in summary

    @pytest.mark.parametrize("bad_port", ["99999", "0", "70000", "-1", "abc"])
    def test_invalid_ports_rejected_cleanly_in_health(self, tmp_path: pathlib.Path, bad_port: str) -> None:
        config = _make_config(tmp_path, api_base_url=f"http://localhost:{bad_port}")
        res = health_check(config=config)
        assert res.healthy is False
        url_check = [c for c in res.checks if c.name == "API base URL"][0]
        assert url_check.passed is False
        assert "port" in url_check.detail
        assert bad_port not in url_check.detail

    @pytest.mark.parametrize("bad_ipv6", ["http://[::1:8000", "http://[invalid_ipv6_host]"])
    def test_malformed_ipv6_rejected_cleanly_in_health(self, tmp_path: pathlib.Path, bad_ipv6: str) -> None:
        config = _make_config(tmp_path, api_base_url=bad_ipv6)
        res = health_check(config=config)
        assert res.healthy is False
        summary = res.summary()
        assert ("invalid host authority" in summary or "malformed" in summary)

    def test_health_with_unloaded_config_sanitizes_errors(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        watch = tmp_path / "watch"
        watch.mkdir()
        archive = tmp_path / "archive"
        quarantine = tmp_path / "quarantine"
        secret_token = "HEALTH_CLI_SECRET_TOKEN_555"
        toml_content = (
            f'[agent]\n'
            f'api_base_url = "https://docflow.example.com?token={secret_token}"\n'
            f'watch_folder = "{watch.as_posix()}"\n'
            f'archive_folder = "{archive.as_posix()}"\n'
            f'quarantine_folder = "{quarantine.as_posix()}"\n'
        )
        bad_config_file = tmp_path / "agent.toml"
        bad_config_file.write_text(toml_content, encoding="utf-8")
        monkeypatch.setenv("DOCFLOW_AGENT_CONFIG_FILE", str(bad_config_file))

        result = health_check()
        assert result.healthy is False
        summary = result.summary()
        assert secret_token not in summary
        assert "API base URL must not contain query parameters" in summary

    def test_corrupt_toml_reports_controlled_failure(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bad_toml = tmp_path / "corrupt.toml"
        bad_toml.write_text("invalid [[ toml syntax", encoding="utf-8")
        monkeypatch.setenv("DOCFLOW_AGENT_CONFIG_FILE", str(bad_toml))

        result = health_check()
        assert result.healthy is False
        config_check = [c for c in result.checks if c.name == "Configuration"][0]
        assert config_check.passed is False
        assert "Failed to read or parse config file" in config_check.detail

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
