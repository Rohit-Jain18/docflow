"""
CLI entry point for the Docflow Windows Agent.

Usage:
    python -m docflow_agent health      Validate configuration and report readiness.
    python -m docflow_agent version     Print agent version.
"""

import sys

from docflow_agent.cli import main

if __name__ == "__main__":
    sys.exit(main())
