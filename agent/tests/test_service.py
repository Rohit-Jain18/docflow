"""Tests for Windows Service Control Manager (SCM) lifecycle integration."""

from __future__ import annotations

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
