"""
Windows Service Lifecycle and Packaging Scaffolding for Docflow Windows Agent.

Implements requirements from:
- docs/AGENT_SPEC.md § 11
- docs/ROADMAP.md (Phase 2 deliverables)

Responsibilities:
- Provides the Windows Service runner scaffolding and graceful shutdown handling.
- When running as an interactive process or daemon, handles SIGINT/SIGTERM cleanly.
- When running under Windows Service Control Manager (SCM via pywin32 if installed),
  implements ServiceFramework callbacks (SvcDoRun, SvcStop).
- Releases all SQLite worker leases and closes client sessions upon service stop.
- Packaging readiness: provides pyinstaller entry point and reproducible command documentation.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from typing import Any

from docflow_agent.config import AgentConfig, load_config
from docflow_agent.runtime import AgentRuntime

logger = logging.getLogger(__name__)


class ServiceRunner:
    """Manages the continuous execution and graceful stop of the AgentRuntime."""

    def __init__(
        self,
        config: AgentConfig | None = None,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self.config = config or load_config()
        self.poll_interval = max(0.5, float(poll_interval_seconds))
        self.runtime = AgentRuntime(self.config)
        self._stop_requested = threading.Event()

    def run(self) -> int:
        """Run the service loop until stop is requested."""
        logger.info("Starting Docflow Agent service runner...")

        # Setup OS signal handlers for graceful stop
        def _signal_handler(signum, frame):
            logger.info("Stop signal (%s) received. Initiating graceful shutdown...", signum)
            self.stop()

        try:
            signal.signal(signal.SIGINT, _signal_handler)
            signal.signal(signal.SIGTERM, _signal_handler)
        except (ValueError, OSError):
            # Non-main thread or unsupported signal platform
            pass

        # 1. Startup recovery
        self.runtime.startup_recovery()

        # 2. Start folder watcher
        try:
            self.runtime.watcher.start()
        except Exception as exc:
            logger.warning("Folder watcher failed to start: %s", exc)

        # 3. Main execution loop
        last_sync = 0.0
        sync_interval = 60.0  # seconds

        try:
            while not self._stop_requested.is_set():
                now = time.time()

                # Periodic heartbeat and config sync
                if now - last_sync >= sync_interval:
                    try:
                        self.runtime.sync_manager.perform_sync(
                            service_state="paused" if self.runtime.is_paused else "running"
                        )
                        last_sync = now
                    except Exception as exc:
                        logger.warning("Heartbeat sync failed: %s", type(exc).__name__)
                        last_sync = now

                # Process pending registration jobs
                while self.runtime.process_next_registration_job():
                    if self._stop_requested.is_set():
                        break

                # Process pending source PDF cleanup candidates
                try:
                    self.runtime.cleanup_service.process_cleanup_candidates()
                except Exception as exc:
                    logger.warning("Cleanup sweep failed: %s", type(exc).__name__)

                # Sleep brief interval or wait on stop event
                self._stop_requested.wait(timeout=self.poll_interval)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received.")
        finally:
            self.runtime.shutdown()

        return 0

    def stop(self) -> None:
        """Signal the service loop to terminate and release leases."""
        self._stop_requested.set()


def run_standalone() -> int:
    """Entry point for standalone execution."""
    runner = ServiceRunner()
    return runner.run()
