"""
CLI for the Docflow Windows Agent.

Provides the ``health``, ``status``, and ``version`` subcommands.

Usage:
    python -m docflow_agent health     Validate config, permissions and readiness.
    python -m docflow_agent status     Alias for health check report.
    python -m docflow_agent version    Print agent version.
"""

from __future__ import annotations

import argparse
import sys

import docflow_agent
from docflow_agent.health import health_check
from docflow_agent.logging import setup_logging


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
