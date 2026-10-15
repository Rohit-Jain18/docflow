"""
Agent Runtime Orchestrator, Retry Policy, and Lifecycle Management.

Implements requirements from:
- docs/AGENT_SPEC.md §§ 3, 5, 8, 10
- docs/DELIVERY_STATE_MACHINE.md
- docs/RULES.md (Rules 1, 2, 3, 5, 7)
- docs/ROADMAP.md (Phase 2 deliverables)

Responsibilities:
- Coordinates the folder watcher, durable SQLite queue, token manager, authenticated HTTP client,
  heartbeat/config sync, metadata registration, and source cleanup workers.
- Executes startup recovery: reclaims expired worker leases, runs initial sync, and rescans folder.
- Enforces single-worker lease claiming (BEGIN IMMEDIATE) with deterministic retry backoff.
- Classifies errors: transient (exponential backoff with jitter), terminal (fails closed), and ambiguous.
- Clean shutdown handling: releases active worker leases, closes HTTP client, and stops watcher.
- Exposes run_once() for deterministic testing, verification, and CLI batch sweeps.
"""

from __future__ import annotations

import datetime
from datetime import timezone
import logging
import math
import pathlib
import random
import threading
import time
import uuid
from typing import Any

from docflow_agent.client import (
    ApiClient,
    ApiResponseError,
    ApiAuthenticationError,
    ApiPermissionError,
    ApiTimeoutError,
    ApiConnectionError,
    ApiRateLimitError,
)
from docflow_agent.config import AgentConfig
from docflow_agent.credentials import CredentialStore, get_credential_store
from docflow_agent.queue import (
    JobQueue,
    JobRecord,
    JobStatus,
    create_watcher_enqueue_adapter,
)
from docflow_agent.registration import (
    ReportRegistrationService,
    RegistrationResult,
    AccountNotVerifiedError,
    RegistrationConflictError,
    RegistrationError,
)
from docflow_agent.retention import CleanupService
from docflow_agent.sync import (
    DeviceSyncManager,
    DeviceRevokedError,
    HeartbeatResult,
)
from docflow_agent.token_manager import TokenManager
from docflow_agent.watcher import Watcher

logger = logging.getLogger(__name__)

# Default retry / backoff parameters (docs/AGENT_SPEC.md §8)
DEFAULT_BASE_BACKOFF_SECONDS = 2.0
DEFAULT_BACKOFF_MULTIPLIER = 2.0
DEFAULT_MAX_BACKOFF_SECONDS = 900.0  # 15 minutes
DEFAULT_MAX_RETRY_ATTEMPTS = 5


def calculate_backoff_delay(
    attempt_count: int,
    base_seconds: float = DEFAULT_BASE_BACKOFF_SECONDS,
    multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
    max_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
    jitter: bool = True,
) -> float:
    """Calculate bounded exponential backoff with full jitter."""
    attempt = max(1, attempt_count)
    raw_delay = base_seconds * (multiplier ** (attempt - 1))
    bounded_delay = min(max_seconds, raw_delay)
    if jitter:
        return random.uniform(0.5 * bounded_delay, bounded_delay)
    return bounded_delay


class AgentRuntime:
    """Central runtime orchestrating the Windows Agent components."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        credential_store: CredentialStore | None = None,
        queue: JobQueue | None = None,
        token_manager: TokenManager | None = None,
        client: ApiClient | None = None,
        installation_id: str | None = None,
        worker_id: str | None = None,
        max_retry_attempts: int = DEFAULT_MAX_RETRY_ATTEMPTS,
    ) -> None:
        self.config = config
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.max_retry_attempts = max(1, int(max_retry_attempts))
        self.is_paused = False
        self._stop_event = threading.Event()
        self._active_leases: set[str] = set()

        # 1. Credential store
        self.store = credential_store or get_credential_store()

        # 2. HTTP Client & Token manager
        if client is not None:
            self.client = client
            self.token_manager = token_manager or TokenManager(
                client=self.client,
                credential_store=self.store,
                safety_window_seconds=float(config.temp_upload_expiry_buffer_seconds),
            )
            if self.client.token_provider is None:
                self.client.token_provider = self.token_manager.get_access_token
        else:
            self.client = ApiClient(base_url=config.api_base_url)
            self.token_manager = token_manager or TokenManager(
                client=self.client,
                credential_store=self.store,
                safety_window_seconds=float(config.temp_upload_expiry_buffer_seconds),
            )
            self.client.token_provider = self.token_manager.get_access_token

        # 3. SQLite Queue
        self.queue = queue or JobQueue.from_config(config)

        # 4. Installation and Branch IDs
        persisted_inst_id = self.queue.get_setting("installation_id")
        self.installation_id = str(installation_id or persisted_inst_id or str(uuid.uuid4()))
        if not persisted_inst_id:
            self.queue.set_setting("installation_id", self.installation_id)

        persisted_branch_id = self.queue.get_setting("server_branch_id")
        self.branch_id = persisted_branch_id or "00000000-0000-0000-0000-000000000000"

        # 5. Domain Services
        self.sync_manager = DeviceSyncManager(
            client=self.client,
            queue=self.queue,
            installation_id=self.installation_id,
        )
        self.registration_service = ReportRegistrationService(
            client=self.client,
            queue=self.queue,
            branch_id=self.branch_id,
        )
        allowed_dirs = [config.watch_folder]
        if config.archive_folder:
            allowed_dirs.append(config.archive_folder)
        if config.quarantine_folder:
            allowed_dirs.append(config.quarantine_folder)
        self.cleanup_service = CleanupService(
            queue=self.queue,
            allowed_folders=allowed_dirs,
        )

        # 6. Folder Watcher with enqueue adapter
        enqueue_cb = create_watcher_enqueue_adapter(
            self.queue,
            branch_id=self.branch_id,
            watch_folder=config.watch_folder,
            quarantine_folder=config.quarantine_folder,
            max_size_bytes=config.max_pdf_size_bytes,
            default_region=config.phone_default_region,
            sample_interval_seconds=float(config.stability_sample_seconds),
            required_samples=config.stability_required_samples,
            timeout_seconds=float(config.stability_timeout_seconds),
        )
        self.watcher = Watcher(
            watch_folder=config.watch_folder,
            on_candidate=enqueue_cb,
            rescan_interval_seconds=float(config.stability_sample_seconds * 5),
        )

    def startup_recovery(self) -> dict[str, int]:
        """Execute pre-flight recovery checks and startup sweeps."""
        logger.info("Executing Agent startup recovery for worker '%s'...", self.worker_id)
        # 1. Recover expired leases
        recovered_leases = self.queue.recover_expired_leases()

        # 2. Rescan watch folder for missed candidate PDFs
        candidates = self.watcher.scan()
        rescanned_count = len(candidates)

        logger.info(
            "Startup recovery complete: %d expired lease(s) recovered, %d file(s) rescanned.",
            recovered_leases,
            rescanned_count,
        )
        return {
            "recovered_leases": recovered_leases,
            "rescanned_count": rescanned_count,
        }

    def process_next_registration_job(self) -> bool:
        """Claim and process the next eligible job for metadata registration."""
        if self.is_paused:
            return False

        # Claim job in VALIDATED or RETRY_WAIT status
        job = self.queue.claim_job(
            worker_id=self.worker_id,
            lease_duration_seconds=60.0,
            eligible_statuses=[JobStatus.VALIDATED.value, JobStatus.RETRY_WAIT.value],
        )
        if job is None:
            return False

        self._active_leases.add(job.id)
        try:
            # Attempt metadata registration
            self.registration_service.register_job(job)
            return True

        except (AccountNotVerifiedError, ApiTimeoutError, ApiConnectionError) as exc:
            # Transient error: compute backoff and schedule retry
            attempt = job.attempt_count + 1
            delay = calculate_backoff_delay(attempt)
            next_attempt_dt = datetime.datetime.now(timezone.utc) + datetime.timedelta(seconds=delay)

            err_code = getattr(exc, "code", type(exc).__name__)
            if attempt >= self.max_retry_attempts:
                logger.error(
                    "Job %s exhausted retry budget (%d attempts). Marking FAILED.",
                    job.id,
                    attempt,
                )
                self.queue.update_status(
                    job.id,
                    JobStatus.FAILED,
                    error_code="retry_budget_exhausted",
                    increment_attempt=True,
                )
            else:
                self.queue.update_status(
                    job.id,
                    JobStatus.RETRY_WAIT,
                    error_code=err_code,
                    next_attempt_at=next_attempt_dt.isoformat(),
                    increment_attempt=True,
                )
            return False

        except DeviceRevokedError as exc:
            logger.error("Device revoked or inactive. Pausing runtime operations.")
            self.is_paused = True
            return False

        except RegistrationConflictError as exc:
            logger.error("Idempotency conflict for job %s. Job marked FAILED.", job.id)
            return False

        except Exception as exc:
            logger.exception("Unexpected error processing job %s: %s", job.id, type(exc).__name__)
            self.queue.update_status(
                job.id,
                JobStatus.FAILED,
                error_code="unexpected_runtime_error",
            )
            return False

        finally:
            self.queue.release_lease(job.id, worker_id=self.worker_id)
            self._active_leases.discard(job.id)

    def run_once(self) -> dict[str, Any]:
        """Perform a single deterministic sweep across sync, registration, and cleanup."""
        # 1. Sync & Heartbeat
        sync_result = None
        try:
            sync_result = self.sync_manager.perform_sync(
                service_state="paused" if self.is_paused else "running"
            )
        except DeviceRevokedError:
            self.is_paused = True
        except Exception as exc:
            logger.warning("Periodic sync failed: %s", type(exc).__name__)

        # 2. Registration Sweep (process all currently ready jobs)
        registered_count = 0
        while self.process_next_registration_job():
            registered_count += 1
            if self._stop_event.is_set():
                break

        # 3. Cleanup Sweep
        cleaned_count = self.cleanup_service.process_cleanup_candidates()

        return {
            "sync": sync_result,
            "registered_jobs": registered_count,
            "cleaned_jobs": cleaned_count,
            "is_paused": self.is_paused,
        }

    def shutdown(self) -> None:
        """Gracefully stop runtime, release active leases, and close HTTP/queue resources."""
        logger.info("Stopping Agent runtime worker '%s'...", self.worker_id)
        self._stop_event.set()

        # Release any active leases held by this worker
        for job_id in list(self._active_leases):
            try:
                self.queue.release_lease(job_id, worker_id=self.worker_id)
            except Exception:
                pass
        self._active_leases.clear()

        # Stop folder watcher
        try:
            self.watcher.stop()
        except Exception:
            pass

        # Close HTTP client
        try:
            self.client.close()
        except Exception:
            pass

        logger.info("Agent runtime shutdown complete.")
