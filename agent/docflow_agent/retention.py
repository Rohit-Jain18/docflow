"""
Source PDF Retention, Operator Hold, and Best-Effort Cleanup Worker.

Implements requirements from:
- docs/AGENT_SPEC.md §§ 5, 8, 9
- docs/DELIVERY_STATE_MACHINE.md § 4
- docs/RULES.md (Rule 7)
- docs/SECURITY.md § 3

Core rules:
1. Retain source PDF through all in-flight states (queued, uploading, retrying, awaiting delivery confirmation,
   or undergoing reconciliation).
2. Provider API acceptance alone (accepted) MUST NOT permit deletion of the local source PDF.
3. Finite configurable retention windows:
   - Confirmed delivered/read: AGENT_CLEANUP_RETENTION_HOURS (default 24h, clock starts upon delivery confirmation).
   - Failed/quarantined: AGENT_FAILED_RETENTION_DAYS (default 14d, clock starts upon entering terminal status).
4. Retries cancel previous cleanup eligibility (cleanup_eligible_at = None, cleanup_status = 'retained_in_flight').
5. Operator hold suspends cleanup indefinitely across restarts. Releasing hold re-evaluates eligibility (minimum 24h).
6. Pre-deletion verification checklist:
   - Allowed terminal state
   - No active worker lease
   - No active or scheduled retry
   - No operator hold
   - No pending reconciliation or in-flight dependency
   - Current time has reached or passed cleanup_eligible_at
7. Safe path verification:
   - Path must resolve strictly inside approved local folders (watch, archive, quarantine).
   - Refuse deletion if path is a symlink or reparse point.
   - Deletion is best-effort file deletion; never claim forensic erasure.
8. If local PDF is missing/corrupt when needed for re-upload: fail closed with code 'source_file_unavailable'.
"""

from __future__ import annotations

import dataclasses
import datetime
from datetime import timezone
import logging
import os
import pathlib
import stat
from typing import Any

from docflow_agent.queue import (
    JobQueue,
    JobRecord,
    JobStatus,
)

logger = logging.getLogger(__name__)

# Valid terminal states permitted to become eligible for deletion
ALLOWED_TERMINAL_CLEANUP_STATUSES = frozenset({
    JobStatus.DELIVERED.value,
    JobStatus.READ.value,
    JobStatus.FAILED.value,
    JobStatus.QUARANTINED.value,
    JobStatus.ARCHIVED.value,
})

# Statuses that represent in-flight or dependent operations blocking cleanup
BLOCKING_OPERATION_STATUSES = frozenset({
    JobStatus.DISCOVERED.value,
    JobStatus.WAITING_STABILITY.value,
    JobStatus.VALIDATED.value,
    JobStatus.METADATA_REGISTERING.value,
    JobStatus.METADATA_REGISTERED.value,
    JobStatus.UPLOADING.value,
    JobStatus.MEDIA_UPLOADED.value,
    JobStatus.MEDIA_REFERENCE_ATTACHING.value,
    JobStatus.REGISTERED.value,
    JobStatus.ACCEPTED.value,
    JobStatus.RETRY_WAIT.value,
    JobStatus.RECONCILIATION_REQUIRED.value,
})


@dataclasses.dataclass(frozen=True)
class CleanupChecklistResult:
    """Outcome of evaluating the pre-deletion verification checklist."""

    is_eligible: bool
    reason: str


def verify_cleanup_checklist(
    job: JobRecord,
    now_dt: datetime.datetime | None = None,
) -> CleanupChecklistResult:
    """Evaluate the 6-point pre-deletion verification checklist against SQLite job state.

    Checklist:
    1. The job is in a valid terminal state (delivered, read, failed, quarantined).
    2. No active worker lease exists.
    3. No active retry is in progress or pending.
    4. No operator hold is active (operator_hold == 0 and cleanup_status != 'operator_hold').
    5. No active or unresolved operation depends on the source (no in-flight states).
    6. Current time has reached or passed cleanup_eligible_at.
    """
    now = now_dt or datetime.datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # Checklist Item 1: Valid terminal state
    if job.status not in ALLOWED_TERMINAL_CLEANUP_STATUSES:
        return CleanupChecklistResult(
            is_eligible=False,
            reason=f"Status '{job.status}' is not an allowed terminal state for cleanup.",
        )

    # Checklist Item 2: No active worker lease
    if job.lease_owner is not None and job.lease_expires_at is not None:
        if job.lease_expires_at > now_iso:
            return CleanupChecklistResult(
                is_eligible=False,
                reason=f"Active worker lease held by '{job.lease_owner}' until {job.lease_expires_at}.",
            )

    # Checklist Item 3: No active or pending retry
    if job.status == JobStatus.RETRY_WAIT.value:
        return CleanupChecklistResult(
            is_eligible=False,
            reason="Job is currently in retry_wait status.",
        )
    if job.next_attempt_at is not None and job.next_attempt_at > now_iso:
        return CleanupChecklistResult(
            is_eligible=False,
            reason=f"Future retry scheduled at {job.next_attempt_at}.",
        )

    # Checklist Item 4: No operator hold
    if job.operator_hold or job.cleanup_status == "operator_hold":
        return CleanupChecklistResult(
            is_eligible=False,
            reason="Operator hold is active.",
        )

    # Checklist Item 5: No blocking in-flight operations
    if job.status in BLOCKING_OPERATION_STATUSES:
        return CleanupChecklistResult(
            is_eligible=False,
            reason=f"Job is in blocking in-flight status '{job.status}'.",
        )

    # Checklist Item 6: Elapsed retention timer
    if not job.cleanup_eligible_at:
        return CleanupChecklistResult(
            is_eligible=False,
            reason="No cleanup_eligible_at deadline recorded.",
        )
    if job.cleanup_eligible_at > now_iso:
        return CleanupChecklistResult(
            is_eligible=False,
            reason=f"Retention deadline {job.cleanup_eligible_at} has not elapsed yet.",
        )

    # Already deleted
    if job.cleanup_status == "deleted":
        return CleanupChecklistResult(
            is_eligible=False,
            reason="Source file is already marked deleted.",
        )

    return CleanupChecklistResult(is_eligible=True, reason="All checklist criteria satisfied.")


def is_safe_path_for_deletion(
    candidate_path: pathlib.Path | str,
    allowed_folders: list[pathlib.Path | str],
) -> tuple[bool, str]:
    """Verify that a candidate file path is safe to delete.

    Rules:
    - Path metadata is inspected via lstat BEFORE any path resolution.
    - Symlinks and Windows reparse points are strictly rejected to prevent traversal.
    - Candidate must be a regular file.
    - Candidate must resolve strictly inside an approved folder (watch, archive, quarantine).
    - Fails closed with static reason codes if metadata inspection or resolution fails.
    - Never interpolates raw paths into error codes or exception text.
    """
    p = pathlib.Path(candidate_path)

    # 1. Inspect original un-resolved path metadata using lstat
    try:
        st = os.lstat(p)
    except (OSError, ValueError):
        return False, "path_inspection_failed"

    # 2. Reject symbolic links on original un-resolved path
    if stat.S_ISLNK(st.st_mode) or p.is_symlink():
        return False, "symlink_rejected"

    # 3. Reject Windows reparse points on un-resolved path
    attrs = getattr(st, "st_file_attributes", 0)
    reparse_attr = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if attrs and (attrs & reparse_attr):
        return False, "reparse_point_rejected"

    # 4. Must be a regular file
    if not stat.S_ISREG(st.st_mode):
        return False, "not_regular_file"

    # 5. Resolve path and verify boundaries
    try:
        resolved_path = p.resolve(strict=False)
    except (OSError, ValueError):
        return False, "path_resolution_failed"

    # 6. Re-check resolved path metadata
    try:
        res_st = os.lstat(resolved_path)
    except (OSError, ValueError):
        return False, "path_inspection_failed"

    if stat.S_ISLNK(res_st.st_mode) or resolved_path.is_symlink():
        return False, "symlink_rejected"

    res_attrs = getattr(res_st, "st_file_attributes", 0)
    if res_attrs and (res_attrs & reparse_attr):
        return False, "reparse_point_rejected"

    if not stat.S_ISREG(res_st.st_mode):
        return False, "not_regular_file"

    # 7. Boundary verification: must be strictly inside an allowed directory
    is_inside_allowed = False
    for folder in allowed_folders:
        try:
            resolved_folder = pathlib.Path(folder).resolve()
            if resolved_folder in resolved_path.parents:
                is_inside_allowed = True
                break
        except (OSError, ValueError):
            continue

    if not is_inside_allowed:
        return False, "outside_allowed_boundaries"

    return True, "safe"


class CleanupService:
    """Worker service that executes verified best-effort source PDF deletion."""

    def __init__(
        self,
        queue: JobQueue,
        allowed_folders: list[pathlib.Path | str],
    ) -> None:
        self.queue = queue
        self.allowed_folders = [pathlib.Path(f).resolve() for f in allowed_folders if f]

        if not self.allowed_folders:
            raise ValueError("allowed_folders must contain at least one valid folder path.")

    def process_cleanup_candidates(
        self,
        now_dt: datetime.datetime | None = None,
        limit: int = 50,
    ) -> int:
        """Scan SQLite queue for eligible jobs, verify checklist, and safely delete local source PDFs.

        Returns:
            Number of jobs whose source PDFs were successfully verified and marked deleted.
        """
        now = now_dt or datetime.datetime.now(timezone.utc)
        now_iso = now.isoformat()

        candidates = self.queue.get_cleanup_candidates(now_iso=now_iso, limit=limit)
        deleted_count = 0

        for job in candidates:
            # 1. Checklist verification against active SQLite record
            check = verify_cleanup_checklist(job, now_dt=now)
            if not check.is_eligible:
                logger.debug("Skipping job %s cleanup: %s", job.id, check.reason)
                continue

            # 2. Safe path validation (returns static reason code without paths)
            is_safe, reason_code = is_safe_path_for_deletion(job.source_path, self.allowed_folders)
            if not is_safe:
                logger.error("Job %s path failed safety check: %s. Preserving file.", job.id, reason_code)
                continue

            source_file = pathlib.Path(job.source_path)

            # 3. Best-effort deletion with immediate pre-deletion safety re-check (TOCTOU mitigation)
            try:
                if source_file.exists():
                    re_safe, re_reason = is_safe_path_for_deletion(job.source_path, self.allowed_folders)
                    if not re_safe:
                        logger.error(
                            "Job %s path failed TOCTOU safety recheck: %s. Preserving file.",
                            job.id,
                            re_reason,
                        )
                        continue
                    source_file.unlink()
                    logger.info("Deleted source PDF for job %s (terminal status: %s)", job.id, job.status)
                else:
                    logger.debug("Source PDF for job %s was already absent on disk", job.id)

                # 4. Record safe outcome in SQLite
                self.queue.mark_source_deleted(job.id, deletion_verified_at=now_iso)
                deleted_count += 1

            except PermissionError:
                # File is currently locked by another process (e.g. LIS or antivirus)
                logger.warning(
                    "Source PDF for job %s is locked; will retry next cleanup cycle.",
                    job.id,
                )
            except OSError:
                logger.warning(
                    "Failed to delete source PDF for job %s; preserving record.",
                    job.id,
                )

        return deleted_count
