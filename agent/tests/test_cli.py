"""Tests for docflow_agent.cli — CLI commands."""

import logging
import pathlib
import textwrap

import pytest

from docflow_agent.cli import main


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove DOCFLOW_AGENT_* env vars to isolate tests."""
    import os

    for key in list(os.environ):
        if key.upper().startswith("DOCFLOW_AGENT_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _cleanup_logger() -> None:  # type: ignore[misc]
    """Remove handlers between tests."""
    yield  # type: ignore[misc]
    logger = logging.getLogger("docflow_agent")
    logger.handlers.clear()


class TestCLIHealth:
    """Test the 'health' CLI command."""

    def test_health_success(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
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
        """)
        config_file = tmp_path / "agent.toml"
        config_file.write_text(toml_content, encoding="utf-8")
        monkeypatch.setenv("DOCFLOW_AGENT_CONFIG_FILE", str(config_file))

        exit_code = main(["health"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "HEALTHY" in captured.out

    def test_status_command_alias(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
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
        """)
        config_file = tmp_path / "agent.toml"
        config_file.write_text(toml_content, encoding="utf-8")
        monkeypatch.setenv("DOCFLOW_AGENT_CONFIG_FILE", str(config_file))

        exit_code = main(["status"])

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "HEALTHY" in captured.out

    def test_health_failure_bad_config(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        # No config at all — should fail with missing required values
        exit_code = main(["health"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "UNHEALTHY" in captured.out

    def test_health_cli_sanitizes_url_errors(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        watch = tmp_path / "watch"
        watch.mkdir()
        archive = tmp_path / "archive"
        quarantine = tmp_path / "quarantine"
        secret_token = "CLI_LEAK_TEST_TOKEN_9999"
        toml_content = textwrap.dedent(f"""\
            [agent]
            api_base_url = "https://admin:super_secret_pwd@docflow.example.com?token={secret_token}"
            watch_folder = "{watch.as_posix()}"
            archive_folder = "{archive.as_posix()}"
            quarantine_folder = "{quarantine.as_posix()}"
        """)
        config_file = tmp_path / "agent.toml"
        config_file.write_text(toml_content, encoding="utf-8")
        monkeypatch.setenv("DOCFLOW_AGENT_CONFIG_FILE", str(config_file))

        exit_code = main(["health"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "UNHEALTHY" in captured.out
        assert secret_token not in captured.out
        assert "super_secret_pwd" not in captured.out
        assert "admin" not in captured.out
        assert "API base URL must not contain" in captured.out


class TestCLIVersion:
    """Test the 'version' CLI command."""

    def test_version_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["version"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "docflow-agent" in captured.out
        assert "0.1.0" in captured.out


class TestCLINoCommand:
    """Test CLI with no subcommand."""

    def test_no_command_shows_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main([])
        assert exit_code == 1


class TestCLIRun:
    """Test the 'run' CLI command."""

    def test_run_once(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
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
            db_path = "{(tmp_path / 'cli_run.db').as_posix()}"
        """)
        config_file = tmp_path / "agent.toml"
        config_file.write_text(toml_content, encoding="utf-8")
        monkeypatch.setenv("DOCFLOW_AGENT_CONFIG_FILE", str(config_file))

        exit_code = main(["run", "--once"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Sweep complete:" in captured.out
