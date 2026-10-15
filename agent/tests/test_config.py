"""Tests for docflow_agent.config."""

import os
import pathlib
import textwrap

import pytest

from docflow_agent.config import (
    AgentConfig,
    ConfigError,
    is_loopback_host,
    load_config,
    validate_api_base_url,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_env(tmp_path: pathlib.Path) -> dict[str, str]:
    """Return a minimal valid environment dict for testing."""
    watch = tmp_path / "watch"
    watch.mkdir(exist_ok=True)
    archive = tmp_path / "archive"
    quarantine = tmp_path / "quarantine"
    return {
        "api_base_url": "http://localhost:8000",
        "watch_folder": str(watch),
        "archive_folder": str(archive),
        "quarantine_folder": str(quarantine),
    }


# ---------------------------------------------------------------------------
# Valid configuration
# ---------------------------------------------------------------------------

class TestValidConfig:
    """Test that valid configurations load successfully."""

    def test_load_from_env(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        config = load_config(env=env)
        assert isinstance(config, AgentConfig)
        assert config.api_base_url == "http://localhost:8000"
        assert config.watch_folder == str(tmp_path / "watch")
        assert config.phone_default_region == "IN"

    def test_defaults_applied(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        config = load_config(env=env)
        assert config.stability_sample_seconds == 2
        assert config.stability_required_samples == 3
        assert config.stability_timeout_seconds == 120
        assert config.max_pdf_size_bytes == 52_428_800
        assert config.cleanup_retention_hours == 24
        assert config.failed_retention_days == 14
        assert config.log_level == "INFO"

    def test_env_overrides_defaults(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["stability_sample_seconds"] = "5"
        env["log_level"] = "DEBUG"
        config = load_config(env=env)
        assert config.stability_sample_seconds == 5
        assert config.log_level == "DEBUG"

    def test_https_url_accepted(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["api_base_url"] = "https://docflow.example.com"
        config = load_config(env=env)
        assert config.api_base_url == "https://docflow.example.com"

    def test_loopback_http_urls_accepted(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        for loopback in ("http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000"):
            env["api_base_url"] = loopback
            config = load_config(env=env)
            assert config.api_base_url == loopback

    def test_config_is_frozen(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        config = load_config(env=env)
        with pytest.raises(AttributeError):
            config.api_base_url = "http://evil.com"  # type: ignore[misc]

    def test_load_from_toml(self, tmp_path: pathlib.Path) -> None:
        watch = tmp_path / "watch"
        watch.mkdir()
        archive = tmp_path / "archive"
        quarantine = tmp_path / "quarantine"
        toml_content = textwrap.dedent(f"""\
            [agent]
            api_base_url = "http://localhost:8000"
            watch_folder = "{watch.as_posix()}"
            archive_folder = "{archive.as_posix()}"
            quarantine_folder = "{quarantine.as_posix()}"
            stability_sample_seconds = 4
        """)
        config_file = tmp_path / "agent.toml"
        config_file.write_text(toml_content, encoding="utf-8")
        config = load_config(config_file=config_file, env={})
        assert config.api_base_url == "http://localhost:8000"
        assert config.stability_sample_seconds == 4

    def test_env_overrides_toml(self, tmp_path: pathlib.Path) -> None:
        watch = tmp_path / "watch"
        watch.mkdir()
        archive = tmp_path / "archive"
        quarantine = tmp_path / "quarantine"
        toml_content = textwrap.dedent(f"""\
            [agent]
            api_base_url = "http://localhost:8000"
            watch_folder = "{watch.as_posix()}"
            archive_folder = "{archive.as_posix()}"
            quarantine_folder = "{quarantine.as_posix()}"
            stability_sample_seconds = 4
        """)
        config_file = tmp_path / "agent.toml"
        config_file.write_text(toml_content, encoding="utf-8")
        config = load_config(
            config_file=config_file,
            env={"stability_sample_seconds": "9"},
        )
        assert config.stability_sample_seconds == 9


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------

class TestMissingRequired:
    """Test that missing required fields raise ConfigError."""

    def test_missing_api_base_url(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        del env["api_base_url"]
        with pytest.raises(ConfigError, match="api_base_url"):
            load_config(env=env)

    def test_missing_watch_folder(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        del env["watch_folder"]
        with pytest.raises(ConfigError, match="watch_folder"):
            load_config(env=env)

    def test_empty_api_base_url(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["api_base_url"] = ""
        with pytest.raises(ConfigError, match="api_base_url"):
            load_config(env=env)


# ---------------------------------------------------------------------------
# URL Validation
# ---------------------------------------------------------------------------

class TestUrlValidation:
    """Detailed URL parser validation tests."""

    def test_plain_http_non_loopback_rejected(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["api_base_url"] = "http://api.docflow.example.com"
        with pytest.raises(ConfigError, match="Plain HTTP is only permitted for loopback"):
            load_config(env=env)

    def test_plain_http_lan_ip_rejected(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["api_base_url"] = "http://192.168.1.50:8000"
        with pytest.raises(ConfigError, match="Plain HTTP is only permitted for loopback"):
            load_config(env=env)

    def test_url_userinfo_rejected(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["api_base_url"] = "https://user:password@docflow.example.com"
        with pytest.raises(ConfigError, match="userinfo"):
            load_config(env=env)

    def test_url_query_string_rejected(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["api_base_url"] = "https://docflow.example.com?key=value"
        with pytest.raises(ConfigError, match="query parameters"):
            load_config(env=env)

    def test_url_fragment_rejected(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["api_base_url"] = "https://docflow.example.com#section"
        with pytest.raises(ConfigError, match="fragment"):
            load_config(env=env)

    def test_url_missing_hostname(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["api_base_url"] = "https:///api"
        with pytest.raises(ConfigError, match="valid hostname"):
            load_config(env=env)

    def test_url_invalid_scheme(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["api_base_url"] = "ftp://localhost:8000"
        with pytest.raises(ConfigError, match="scheme must be http or https"):
            load_config(env=env)


# ---------------------------------------------------------------------------
# Invalid configuration & Secrets detection
# ---------------------------------------------------------------------------

class TestInvalidConfig:
    """Test that invalid configuration values raise ConfigError."""

    def test_nonexistent_watch_folder(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["watch_folder"] = str(tmp_path / "does_not_exist")
        with pytest.raises(ConfigError, match="does not exist"):
            load_config(env=env)

    def test_non_integer_stability(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["stability_sample_seconds"] = "abc"
        with pytest.raises(ConfigError, match="must be an integer"):
            load_config(env=env)

    def test_zero_stability_samples(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["stability_required_samples"] = "0"
        with pytest.raises(ConfigError, match="stability_required_samples"):
            load_config(env=env)

    def test_failed_retention_days_out_of_range(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["failed_retention_days"] = "100"
        with pytest.raises(ConfigError, match="failed_retention_days"):
            load_config(env=env)

    def test_archive_inside_watch_folder(self, tmp_path: pathlib.Path) -> None:
        watch = tmp_path / "watch"
        watch.mkdir()
        inside = watch / "archive"
        env = _make_valid_env(tmp_path)
        env["watch_folder"] = str(watch)
        env["archive_folder"] = str(inside)
        with pytest.raises(ConfigError, match="must not be inside"):
            load_config(env=env)

    def test_quarantine_inside_watch_folder(self, tmp_path: pathlib.Path) -> None:
        watch = tmp_path / "watch"
        watch.mkdir()
        inside = watch / "quarantine"
        env = _make_valid_env(tmp_path)
        env["watch_folder"] = str(watch)
        env["quarantine_folder"] = str(inside)
        with pytest.raises(ConfigError, match="must not be inside"):
            load_config(env=env)

    def test_config_file_not_found(self) -> None:
        with pytest.raises(ConfigError, match="not found"):
            load_config(config_file="nonexistent.toml", env={})

    def test_toml_decode_error_raises_config_error(self, tmp_path: pathlib.Path) -> None:
        bad_toml = tmp_path / "bad.toml"
        bad_toml.write_text("this is not = [valid toml", encoding="utf-8")
        with pytest.raises(ConfigError, match="Failed to read or parse config file"):
            load_config(config_file=bad_toml, env={})

    def test_negative_max_pdf_size(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["max_pdf_size_bytes"] = "-1"
        with pytest.raises(ConfigError, match="max_pdf_size_bytes"):
            load_config(env=env)


# ---------------------------------------------------------------------------
# Prohibited secrets tests
# ---------------------------------------------------------------------------

class TestProhibitedSecrets:
    """Verify that prohibited secret keys are detected in TOML and environment without value leakage."""

    @pytest.mark.parametrize(
        "env_key",
        [
            "DOCFLOW_AGENT_REFRESH_TOKEN",
            "DOCFLOW_AGENT_refreshToken",
            "DOCFLOW_AGENT_refresh-token",
            "docflow_agent_deviceToken",
            "DOCFLOW_AGENT_DEVICE_TOKEN",
            "DOCFLOW_AGENT_DEVICE-TOKEN",
            "DOCFLOW_AGENT_PASSWORD",
            "DOCFLOW_AGENT_SECRET_KEY",
            "WA_PLATFORM_DEVELOPER_TOKEN",
            "wa_platform_developer_token",
            "DEVICE_TOKEN",
            "REFRESH_TOKEN",
        ],
    )
    def test_environment_secret_keys_rejected(self, tmp_path: pathlib.Path, env_key: str) -> None:
        secret_val = "SUPER_SECRET_PAYLOAD_VALUE_9999"
        env = _make_valid_env(tmp_path)
        env[env_key] = secret_val

        with pytest.raises(ConfigError) as exc_info:
            load_config(env=env)

        err_msg = str(exc_info.value)
        assert "Prohibited secret key" in err_msg
        # Secret value must NEVER leak in the error message
        assert secret_val not in err_msg

    def test_nested_toml_secret_keys_rejected(self, tmp_path: pathlib.Path) -> None:
        watch = tmp_path / "watch"
        watch.mkdir(exist_ok=True)
        secret_val = "TOP_SECRET_TOML_VALUE_8888"

        toml_content = textwrap.dedent(f"""\
            [agent]
            api_base_url = "http://localhost:8000"
            watch_folder = "{watch.as_posix()}"

            [security.credentials]
            refreshToken = "{secret_val}"
        """)
        config_file = tmp_path / "secrets.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_file=config_file, env={})

        err_msg = str(exc_info.value)
        assert "Prohibited secret configuration detected" in err_msg
        assert "security.credentials.refreshToken" in err_msg
        # Secret value must NEVER leak in error message
        assert secret_val not in err_msg

    def test_camel_case_and_hyphen_in_toml_rejected(self, tmp_path: pathlib.Path) -> None:
        watch = tmp_path / "watch"
        watch.mkdir(exist_ok=True)

        toml_content = textwrap.dedent(f"""\
            [agent]
            api_base_url = "http://localhost:8000"
            watch_folder = "{watch.as_posix()}"
            device-token = "secret123"
        """)
        config_file = tmp_path / "hyphen_secret.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(ConfigError) as exc_info:
            load_config(config_file=config_file, env={})

        err_msg = str(exc_info.value)
        assert "device-token" in err_msg
        assert "secret123" not in err_msg

    def test_environment_aliases_preserved(self, tmp_path: pathlib.Path) -> None:
        watch = tmp_path / "watch"
        watch.mkdir(exist_ok=True)
        archive = tmp_path / "archive"
        quarantine = tmp_path / "quarantine"
        env = {
            "DOCFLOW_API_BASE_URL": "http://localhost:8000",
            "WATCH_FOLDER": str(watch),
            "ARCHIVE_FOLDER": str(archive),
            "QUARANTINE_FOLDER": str(quarantine),
            "AGENT_LOG_LEVEL": "WARNING",
            "AGENT_LOG_FILE": str(tmp_path / "agent.log"),
        }
        config = load_config(env=env)
        assert config.api_base_url == "http://localhost:8000"
        assert config.watch_folder == str(watch)
        assert config.log_level == "WARNING"
        assert config.log_file == str(tmp_path / "agent.log")
