"""Tests for Windows Service Control Manager (SCM) lifecycle integration."""

from __future__ import annotations

import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest

from docflow_agent.service import (
    DocflowAgentService,
    HAS_WIN32_SERVICE,
    ServiceRunner,
    handle_service_command,
)


def test_service_metadata():
    """Verify Windows Service identification attributes."""
    assert DocflowAgentService._svc_name_ == "DocflowAgent"
    assert DocflowAgentService._svc_display_name_ == "Docflow Windows Agent"
    assert "Docflow Windows Agent" in DocflowAgentService._svc_description_


@pytest.mark.skipif(not HAS_WIN32_SERVICE, reason="Requires pywin32")
def test_service_initialization():
    """Verify DocflowAgentService initializes cleanly under pywin32."""
    svc = DocflowAgentService(["DocflowAgent"])
    assert svc.hWaitStop is not None
    assert svc.runner is None


@pytest.mark.skipif(not HAS_WIN32_SERVICE, reason="Requires pywin32")
def test_service_stop_flow():
    """Verify SvcStop reports stop pending and signals the runner to stop."""
    svc = DocflowAgentService(["DocflowAgent"])
    mock_runner = MagicMock(spec=ServiceRunner)
    svc.runner = mock_runner

    with patch.object(svc, "ReportServiceStatus") as mock_report:
        svc.SvcStop()
        assert mock_report.called
        assert mock_runner.stop.called


@pytest.mark.skipif(not HAS_WIN32_SERVICE, reason="Requires pywin32")
def test_service_do_run_success(tmp_path):
    """Verify SvcDoRun initializes runner from config and executes run loop."""
    svc = DocflowAgentService(["DocflowAgent"])

    mock_runner = MagicMock(spec=ServiceRunner)
    mock_runner.run.return_value = 0

    with (
        patch("docflow_agent.service.load_config") as mock_load,
        patch("docflow_agent.service.ServiceRunner", return_value=mock_runner),
        patch.object(svc, "ReportServiceStatus") as mock_report,
    ):
        ret = svc.SvcDoRun()
        assert ret == 0
        assert mock_runner.run.called
        assert mock_report.called


@pytest.mark.skipif(not HAS_WIN32_SERVICE, reason="Requires pywin32")
def test_service_do_run_fatal_error():
    """Verify SvcDoRun catches fatal startup errors safely and returns 1."""
    svc = DocflowAgentService(["DocflowAgent"])

    with (
        patch("docflow_agent.service.load_config", side_effect=RuntimeError("Config failure")),
        patch.object(svc, "ReportServiceStatus") as mock_report,
    ):
        ret = svc.SvcDoRun()
        assert ret == 1
        assert mock_report.called


def test_handle_service_command_access_denied(capsys):
    """Verify handle_service_command handles Access is Denied (5) gracefully."""
    if not HAS_WIN32_SERVICE:
        pytest.skip("Requires pywin32")

    import pywintypes

    err = pywintypes.error(5, "OpenSCManager", "Access is denied.")
    with patch("win32serviceutil.HandleCommandLine", side_effect=err):
        ret = handle_service_command(["docflow-agent", "install"])
        assert ret == 5
        captured = capsys.readouterr()
        assert "Access is denied" in captured.err
        assert "Administrator" in captured.err


def test_handle_service_command_success():
    """Verify handle_service_command delegates to win32serviceutil."""
    if not HAS_WIN32_SERVICE:
        pytest.skip("Requires pywin32")

    with patch("win32serviceutil.HandleCommandLine") as mock_cmd:
        ret = handle_service_command(["docflow-agent", "status"])
        assert ret == 0
        assert mock_cmd.called


def test_cli_service_subcommand_dispatch():
    """Verify CLI service subcommand routes to handle_service_command."""
    from docflow_agent.cli import main

    with patch("docflow_agent.service.handle_service_command", return_value=0) as mock_handle:
        ret = main(["service", "status"])
        assert ret == 0
        mock_handle.assert_called_once_with(argv=["docflow-agent", "status"])


def test_service_exe_args():
    """Verify service class configures --service as execution argument for SCM launch."""
    assert DocflowAgentService._exe_args_ == "--service"


@pytest.mark.skipif(not HAS_WIN32_SERVICE, reason="Requires pywin32")
def test_start_service_dispatcher_success():
    """Verify start_service_dispatcher initializes and connects to SCM."""
    from docflow_agent.service import start_service_dispatcher

    with (
        patch("servicemanager.Initialize") as mock_init,
        patch("servicemanager.PrepareToHostSingle") as mock_prep,
        patch("servicemanager.StartServiceCtrlDispatcher") as mock_start,
    ):
        ret = start_service_dispatcher()
        assert ret == 0
        assert mock_init.called
        assert mock_prep.called
        assert mock_start.called


@pytest.mark.skipif(not HAS_WIN32_SERVICE, reason="Requires pywin32")
def test_start_service_dispatcher_scm_error():
    """Verify start_service_dispatcher returns winerror when SCM connection fails."""
    import pywintypes
    from docflow_agent.service import start_service_dispatcher

    scm_err = pywintypes.error(1063, "StartServiceCtrlDispatcher", "The service process could not connect.")
    with (
        patch("servicemanager.Initialize"),
        patch("servicemanager.PrepareToHostSingle"),
        patch("servicemanager.StartServiceCtrlDispatcher", side_effect=scm_err),
    ):
        ret = start_service_dispatcher()
        assert ret == 1063


def test_cli_service_flag_dispatch():
    """Verify top-level --service flag invokes start_service_dispatcher."""
    from docflow_agent.cli import main

    with patch("docflow_agent.service.start_service_dispatcher", return_value=0) as mock_disp:
        ret = main(["--service"])
        assert ret == 0
        assert mock_disp.called


def test_cli_run_service_flag_dispatch():
    """Verify run --service invokes start_service_dispatcher."""
    from docflow_agent.cli import main

    with patch("docflow_agent.service.start_service_dispatcher", return_value=0) as mock_disp:
        ret = main(["run", "--service"])
        assert ret == 0
        assert mock_disp.called


def test_cli_running_as_service_dispatch():
    """Verify automatic SCM dispatch when launched directly by SCM without arguments."""
    from docflow_agent.cli import main

    with (
        patch("docflow_agent.service.HAS_WIN32_SERVICE", True),
        patch("docflow_agent.service.servicemanager") as mock_sm,
        patch("docflow_agent.service.start_service_dispatcher", return_value=0) as mock_disp,
    ):
        mock_sm.RunningAsService.return_value = True
        ret = main([])
        assert ret == 0
        assert mock_disp.called


def test_config_resolution_from_programdata(tmp_path, monkeypatch):
    """Verify load_config falls back to %PROGRAMDATA%/Docflow/agent.toml when CWD config is absent."""
    import os
    from docflow_agent.config import load_config

    watch_dir = tmp_path / "incoming"
    watch_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    program_data_dir = tmp_path / "ProgramData"
    docflow_dir = program_data_dir / "Docflow"
    docflow_dir.mkdir(parents=True)
    cfg_file = docflow_dir / "agent.toml"
    cfg_file.write_text(
        f'api_base_url = "http://127.0.0.1:8000"\n'
        f'watch_folder = "{str(watch_dir).replace(chr(92), "/")}"\n'
        f'data_dir = "{str(data_dir).replace(chr(92), "/")}"\n'
        f'quarantine_dir = "{str(quarantine_dir).replace(chr(92), "/")}"\n',
        encoding="utf-8",
    )

    empty_cwd = tmp_path / "empty_cwd"
    empty_cwd.mkdir()
    monkeypatch.chdir(empty_cwd)
    monkeypatch.setenv("PROGRAMDATA", str(program_data_dir))
    monkeypatch.delenv("DOCFLOW_CONFIG", raising=False)

    cfg = load_config()
    assert pathlib.Path(cfg.watch_folder) == watch_dir
