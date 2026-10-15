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

from docflow_agent.client import ApiRateLimitError
from docflow_agent.config import AgentConfig, load_config
from docflow_agent.runtime import AgentRuntime
from docflow_agent.sync import DeviceRevokedError
from docflow_agent.token_manager import (
    TokenError,
    TokenAuthenticationError,
    TokenReuseConflictError,
    TokenRotationAmbiguousError,
    TokenRateLimitedError,
)

logger = logging.getLogger(__name__)

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    import pywintypes
    HAS_WIN32_SERVICE = True
except ImportError:
    HAS_WIN32_SERVICE = False
    win32serviceutil = None
    win32service = None
    win32event = None
    servicemanager = None
    pywintypes = None

BaseServiceClass: type = win32serviceutil.ServiceFramework if HAS_WIN32_SERVICE else object



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
                    except DeviceRevokedError:
                        logger.error("Device revoked or inactive in heartbeat. Pausing runtime operations.")
                        self.runtime.is_paused = True
                        last_sync = now
                    except (TokenRateLimitedError, ApiRateLimitError) as exc:
                        retry_after = getattr(exc, "retry_after", None) or 60.0
                        logger.warning("Heartbeat rate limited; backing off for %s seconds.", retry_after)
                        last_sync = now + retry_after - sync_interval
                    except TokenRotationAmbiguousError:
                        logger.error("Token rotation ambiguous in heartbeat. Pausing runtime operations.")
                        self.runtime.is_paused = True
                        last_sync = now
                    except TokenError as exc:
                        code = getattr(exc, "code", type(exc).__name__)
                        logger.error("Authentication/token failure in heartbeat (%s). Pausing runtime operations.", code)
                        self.runtime.is_paused = True
                        last_sync = now
                    except Exception as exc:
                        logger.warning("Heartbeat sync failed: %s", type(exc).__name__)
                        last_sync = now

                # Process pending registration jobs ONLY if runtime is not paused
                if not self.runtime.is_paused:
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


class DocflowAgentService(BaseServiceClass):
    """Windows Service Control Manager (SCM) lifecycle integration.

    Inherits from win32serviceutil.ServiceFramework on Windows when pywin32 is present.
    Provides SvcDoRun and SvcStop callbacks executed by the Windows Service Control Manager.
    """

    _svc_name_ = "DocflowAgent"
    _svc_display_name_ = "Docflow Windows Agent"
    _svc_description_ = (
        "Docflow Windows Agent: automated diagnostic report folder monitoring and metadata registration."
    )

    def __init__(self, args: Any = None) -> None:
        if HAS_WIN32_SERVICE and BaseServiceClass is not object:
            try:
                super().__init__(args)
            except (ValueError, Exception):
                # When instantiated outside SCM hosting process (e.g. testing or CLI)
                self.ssh = None

            try:
                self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
            except Exception:
                self.hWaitStop = None
        else:
            self.ssh = None
            self.hWaitStop = None

        self.runner: ServiceRunner | None = None

    def report_service_status(self, status: int) -> None:
        """Safely report service status to SCM if registered with a valid handle."""
        if HAS_WIN32_SERVICE and hasattr(self, "ReportServiceStatus"):
            try:
                self.ReportServiceStatus(status)
            except (ValueError, Exception):
                pass


    def SvcStop(self) -> None:
        """Called by Windows SCM when service stop is requested."""
        logger.info("Windows SCM stop requested.")
        if HAS_WIN32_SERVICE and win32service:
            self.report_service_status(win32service.SERVICE_STOP_PENDING)
            if self.hWaitStop:
                try:
                    win32event.SetEvent(self.hWaitStop)
                except Exception:
                    pass

        if self.runner is not None:
            self.runner.stop()

    def SvcDoRun(self) -> int:
        """Called by Windows SCM when service starts execution."""
        if HAS_WIN32_SERVICE and servicemanager:
            try:
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_INFORMATION_TYPE,
                    servicemanager.PYS_SERVICE_STARTED,
                    (self._svc_name_, ""),
                )
            except Exception:
                pass

        if HAS_WIN32_SERVICE and win32service:
            self.report_service_status(win32service.SERVICE_RUNNING)

        try:
            config = load_config()
            self.runner = ServiceRunner(config=config)
            return self.runner.run()
        except Exception as exc:
            logger.critical("Fatal error running Docflow Windows Agent service: %s", type(exc).__name__)
            if HAS_WIN32_SERVICE and servicemanager:
                try:
                    servicemanager.LogErrorMsg(f"DocflowAgent fatal startup error: {type(exc).__name__}")
                except Exception:
                    pass
            return 1
        finally:
            if HAS_WIN32_SERVICE and win32service:
                self.report_service_status(win32service.SERVICE_STOPPED)



def handle_service_command(argv: list[str] | None = None) -> int:
    """Handle Windows Service management commands (install, start, stop, restart, remove, debug)."""
    if not HAS_WIN32_SERVICE:
        print(
            "Error: pywin32 is not installed or unavailable. Windows SCM integration requires pywin32.",
            file=sys.stderr,
        )
        return 1

    args = argv if argv is not None else sys.argv[1:]
    try:
        win32serviceutil.HandleCommandLine(DocflowAgentService, argv=args)
        return 0
    except pywintypes.error as exc:
        if exc.winerror == 5:
            print(
                "Error: Access is denied. Managing Windows services requires an elevated Administrator command prompt.",
                file=sys.stderr,
            )
            return 5
        print(
            f"Windows Service management error ({exc.winerror}): {exc.strerror}",
            file=sys.stderr,
        )
        return int(exc.winerror) if exc.winerror else 1
    except Exception as exc:
        print(f"Windows Service management failed: {exc}", file=sys.stderr)
        return 1
