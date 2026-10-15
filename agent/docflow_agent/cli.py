"""
CLI for the Docflow Windows Agent.

Provides the ``activate``, ``health``, ``status``, and ``version`` subcommands.

Usage:
    python -m docflow_agent activate   Activate agent device with one-time code.
    python -m docflow_agent health     Validate config, permissions and readiness.
    python -m docflow_agent status     Alias for health check report.
    python -m docflow_agent version    Print agent version.
"""

from __future__ import annotations

import argparse
import logging
import sys

import docflow_agent
from docflow_agent.activation import ActivationError, activate_device
from docflow_agent.client import ApiClient
from docflow_agent.health import health_check
from docflow_agent.logging import setup_logging

logger = logging.getLogger(__name__)


def _cmd_health(args: argparse.Namespace) -> int:
    """Run health check and print results."""
    _ = args  # unused but required by argparse
    result = health_check()
    print(result.summary())
    return 0 if result.healthy else 1


def _cmd_version(args: argparse.Namespace) -> int:
    """Print agent version."""
    _ = args
    print(f"docflow-agent {docflow_agent.__version__}")
    return 0


def _cmd_activate(args: argparse.Namespace) -> int:
    """Activate agent device using a one-time activation code."""
    _ = args
    import getpass

    from docflow_agent.config import load_config
    from docflow_agent.queue import JobQueue

    try:
        code = getpass.getpass("Enter one-time activation code: ").strip()
    except Exception:
        print("Error: Secure prompting is unavailable. Cannot prompt for activation code.", file=sys.stderr)
        return 1

    if not code:
        print("Error: Activation code is required.", file=sys.stderr)
        return 1

    try:
        cfg = load_config()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    try:
        queue = JobQueue.from_config(cfg)
    except Exception as exc:
        logger.debug("JobQueue initialization failed (%s); proceeding without local queue persistence", exc)
        queue = None

    try:
        with ApiClient(base_url=cfg.api_base_url) as client:
            result = activate_device(
                client=client,
                activation_code=code,
                queue=queue,
            )
        print(f"Device successfully activated.")
        print(f"  Device ID: {result.device.id}")
        print(f"  Device Name: {result.device.name}")
        print(f"  Branch ID: {result.device.branch_id}")
        print(f"  Configuration Version: {result.configuration_version}")
        return 0
    except ActivationError as exc:
        print(f"Activation failed: {exc.code} - {exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Activation failed: {exc}", file=sys.stderr)
        return 1


def _cmd_run(args: argparse.Namespace) -> int:
    """Run the agent worker runtime."""
    from docflow_agent.config import load_config
    from docflow_agent.runtime import AgentRuntime
    from docflow_agent.service import ServiceRunner

    try:
        cfg = load_config()
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "once", False):
        runtime = AgentRuntime(cfg)
        runtime.startup_recovery()
        res = runtime.run_once()
        print(f"Sweep complete: {res['registered_jobs']} job(s) registered, {res['cleaned_jobs']} file(s) cleaned.")
        runtime.shutdown()
        return 0
    else:
        runner = ServiceRunner(cfg)
        return runner.run()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    parser = argparse.ArgumentParser(
        prog="docflow-agent",
        description="Docflow Windows Agent CLI",
    )
    subparsers = parser.add_subparsers(dest="command")

    # health
    health_parser = subparsers.add_parser(
        "health",
        help="Validate configuration, permissions, and report readiness.",
    )
    health_parser.set_defaults(func=_cmd_health)

    # status (alias for health)
    status_parser = subparsers.add_parser(
        "status",
        help="Report agent status and readiness checks (alias for health).",
    )
    status_parser.set_defaults(func=_cmd_health)

    # version
    version_parser = subparsers.add_parser(
        "version",
        help="Print agent version.",
    )
    version_parser.set_defaults(func=_cmd_version)

    # activate
    activate_parser = subparsers.add_parser(
        "activate",
        help="Activate agent device using a one-time activation code.",
    )
    activate_parser.set_defaults(func=_cmd_activate)

    # run
    run_parser = subparsers.add_parser(
        "run",
        help="Run the agent worker runtime.",
    )
    run_parser.add_argument(
        "--once",
        action="store_true",
        help="Perform a single sweep and exit.",
    )
    run_parser.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    # Initialize logging before running any command
    try:
        from docflow_agent.config import load_config
        cfg = load_config()
        setup_logging(level=cfg.log_level, log_file=cfg.log_file or None)
    except Exception:
        # If config loading fails, set up basic logging so the health
        # check can still run and report the config error
        setup_logging(level="INFO")

    return args.func(args)
