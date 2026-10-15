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
