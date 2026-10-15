"""Tests for docflow_agent.config."""

import os
import pathlib
import textwrap

import pytest

from docflow_agent.config import AgentConfig, ConfigError, load_config


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
            log_level = "WARNING"
        """)
        config_file = tmp_path / "agent.toml"
        config_file.write_text(toml_content, encoding="utf-8")
        env = {"log_level": "ERROR"}
        config = load_config(config_file=config_file, env=env)
        assert config.log_level == "ERROR"


# ---------------------------------------------------------------------------
# Missing required values
# ---------------------------------------------------------------------------


class TestMissingRequired:
    """Test that missing required values produce clear errors."""

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
# Invalid configuration
# ---------------------------------------------------------------------------


class TestInvalidConfig:
    """Test that invalid configurations are rejected."""

    def test_bad_url_scheme(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["api_base_url"] = "ftp://not-http.example.com"
        with pytest.raises(ConfigError, match="http://.*https://"):
            load_config(env=env)

    def test_nonexistent_watch_folder(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["watch_folder"] = str(tmp_path / "nonexistent")
        with pytest.raises(ConfigError, match="does not exist"):
            load_config(env=env)

    def test_non_integer_stability(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["stability_sample_seconds"] = "not_a_number"
        with pytest.raises(ConfigError, match="integer"):
            load_config(env=env)

    def test_zero_stability_samples(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["stability_required_samples"] = "0"
        with pytest.raises(ConfigError, match="stability_required_samples"):
            load_config(env=env)

    def test_failed_retention_days_out_of_range(
        self, tmp_path: pathlib.Path
    ) -> None:
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

    def test_negative_max_pdf_size(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["max_pdf_size_bytes"] = "-1"
        with pytest.raises(ConfigError, match="max_pdf_size_bytes"):
            load_config(env=env)

    def test_prohibited_secret_in_config(self, tmp_path: pathlib.Path) -> None:
        env = _make_valid_env(tmp_path)
        env["wa_platform_developer_token"] = "EAAB..."
        with pytest.raises(ConfigError, match="Prohibited secret key"):
            load_config(env=env)

    def test_environment_aliases(self, tmp_path: pathlib.Path) -> None:
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
