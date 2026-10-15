"""Tests for Windows Agent PyInstaller packaging specification and frozen executable smoke tests."""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest


def test_spec_file_exists_and_configured():
    """Verify docflow_agent.spec exists and contains required packaging safeguards."""
    spec_path = pathlib.Path("agent/docflow_agent.spec")
    assert spec_path.is_file(), "agent/docflow_agent.spec must exist"

    content = spec_path.read_text(encoding="utf-8")

    # Entry point
    assert "docflow_agent/__main__.py" in content

    # Zero bundling of data/secrets
    assert "datas=[]" in content or "datas = []" in content

    # Console mode enabled for diagnostic and SCM logging
    assert "console=True" in content

    # Key modules included in hidden imports
    for mod in [
        "docflow_agent",
        "docflow_agent.service",
        "docflow_agent.config",
        "docflow_agent.runtime",
        "docflow_agent.registration",
        "docflow_agent.retention",
        "docflow_agent.credentials",
        "win32service",
        "win32serviceutil",
        "servicemanager",
    ]:
        assert mod in content

    # Test frameworks and Django excluded
    for exc in ["pytest", "unittest", "django"]:
        assert exc in content


def test_packaged_executable_smoke_checks():
    """Verify built docflow-agent.exe executes non-destructive CLI commands."""
    exe_path = pathlib.Path("agent/dist/docflow-agent/docflow-agent.exe")
    if not exe_path.is_file():
        pytest.skip("Packaged executable agent/dist/docflow-agent/docflow-agent.exe is not built.")

    # 1. Version smoke check
    proc_ver = subprocess.run(
        [str(exe_path), "version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc_ver.returncode == 0
    assert "docflow-agent 0.1.0" in proc_ver.stdout

    # 2. Help smoke check
    proc_help = subprocess.run(
        [str(exe_path), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc_help.returncode == 0
    assert "Docflow Windows Agent CLI" in proc_help.stdout
    assert "service" in proc_help.stdout
    assert "run" in proc_help.stdout
    assert "health" in proc_help.stdout

    # 3. Service help smoke check
    proc_svc_help = subprocess.run(
        [str(exe_path), "service", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc_svc_help.returncode == 0
    assert "install" in proc_svc_help.stdout
    assert "start" in proc_svc_help.stdout
    assert "stop" in proc_svc_help.stdout


def test_packaged_executable_different_cwd_and_health(tmp_path):
    """Verify built docflow-agent.exe executes health check from a different working directory."""
    exe_path = pathlib.Path("agent/dist/docflow-agent/docflow-agent.exe").resolve()
    if not exe_path.is_file():
        pytest.skip("Packaged executable agent/dist/docflow-agent/docflow-agent.exe is not built.")

    # Create isolated folders and config file
    watch_dir = tmp_path / "incoming"
    watch_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    cfg_file = tmp_path / "agent.toml"
    cfg_file.write_text(
        f'api_base_url = "http://127.0.0.1:8000"\n'
        f'watch_folder = "{str(watch_dir).replace(chr(92), "/")}"\n'
        f'data_dir = "{str(data_dir).replace(chr(92), "/")}"\n'
        f'quarantine_dir = "{str(quarantine_dir).replace(chr(92), "/")}"\n',
        encoding="utf-8",
    )

    empty_cwd = tmp_path / "other_cwd"
    empty_cwd.mkdir()

    # 1. Version from different cwd
    proc_ver = subprocess.run(
        [str(exe_path), "version"],
        cwd=str(empty_cwd),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc_ver.returncode == 0
    assert "docflow-agent 0.1.0" in proc_ver.stdout

    # 2. Health check from different cwd with DOCFLOW_AGENT_CONFIG_FILE
    import os
    env = dict(os.environ)
    env["DOCFLOW_AGENT_CONFIG_FILE"] = str(cfg_file)

    proc_health = subprocess.run(
        [str(exe_path), "health"],
        cwd=str(empty_cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    # The health check will run and report checks (readiness, watch folder, data dir)
    assert "Agent Health:" in proc_health.stdout
    assert "Configuration: Loaded and validated successfully" in proc_health.stdout
    assert "Watch folder: Accessible" in proc_health.stdout


def test_packaged_bundle_contains_no_secrets_or_tests():
    """Verify built distribution folder contains no databases, .env files, tests, or PDFs."""
    dist_dir = pathlib.Path("agent/dist/docflow-agent")
    if not dist_dir.is_dir():
        pytest.skip("Packaged dist folder does not exist.")

    for file_path in dist_dir.rglob("*"):
        if file_path.is_file():
            suffix = file_path.suffix.lower()
            assert suffix not in [".db", ".sqlite", ".sqlite3", ".env", ".pdf"]
            assert not file_path.name.startswith(".env")
            assert "test_" not in file_path.name
