"""
Quarantine handling module for the Docflow Windows Agent.

Implements quarantine rules specified in docs/AGENT_SPEC.md §9:
- Moves permanently invalid files into the configured quarantine folder safely.
- Reasons: invalid_filename, invalid_phone, invalid_pdf, empty_file, file_too_large.
- Stability timeout ('stability_timeout_after_policy') is retryable and NEVER quarantined.
- Uses collision-safe opaque UUID filenames (<uuid4>.pdf).
- Never uses patient phone numbers or original filenames for quarantined files.
- Never discards the source file if the move operation fails.
- Redacts/suppresses all paths and phone numbers in error logs.
"""

from __future__ import annotations

import logging
import os
import pathlib
import shutil
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Normalized reason codes that warrant quarantine
PERMANENT_QUARANTINE_REASONS = frozenset({
    "invalid_filename",
    "invalid_phone",
    "invalid_pdf",
    "empty_file",
    "file_too_large",
})


@dataclass(frozen=True)
class QuarantineResult:
    """Result of attempting to quarantine an invalid file."""

    success: bool
    quarantined_path: pathlib.Path | None
    quarantine_id: str
    reason_code: str
    error: str | None = None


def should_quarantine(reason_code: str | None) -> bool:
    """Return True if reason_code represents a permanently invalid input that must be quarantined."""
    return reason_code in PERMANENT_QUARANTINE_REASONS


def quarantine_file(
    source_path: pathlib.Path | str,
    quarantine_folder: pathlib.Path | str,
    reason_code: str,
) -> QuarantineResult:
    """Move an invalid candidate file into the quarantine folder with an opaque UUID name.

    Args:
        source_path: Path to the invalid source file.
        quarantine_folder: Directory where quarantined files are placed.
        reason_code: Normalized error reason code (e.g. 'invalid_pdf').

    Returns:
        QuarantineResult with success status, opaque target path, and error code if failed.
    """
    src = pathlib.Path(source_path)
    q_dir = pathlib.Path(quarantine_folder)

    # If source does not exist, fail safely without crash
    if not src.exists():
        logger.warning(
            "Cannot quarantine file: source not found (reason: %s)", reason_code
        )
        return QuarantineResult(
            success=False,
            quarantined_path=None,
            quarantine_id="",
            reason_code=reason_code,
            error="source_file_unavailable",
        )

    # Ensure quarantine directory exists
    try:
        q_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error(
            "Failed to create quarantine folder (reason: %s, error: %s)",
            reason_code,
            type(exc).__name__,
        )
        return QuarantineResult(
            success=False,
            quarantined_path=None,
            quarantine_id="",
            reason_code=reason_code,
            error=f"quarantine_move_failed: {type(exc).__name__}",
        )

    # Generate collision-safe opaque UUID filename
    max_attempts = 10
    quarantine_id = str(uuid.uuid4())
    target_path = q_dir / f"{quarantine_id}.pdf"
    attempt = 0
    while target_path.exists() and attempt < max_attempts:
        quarantine_id = str(uuid.uuid4())
        target_path = q_dir / f"{quarantine_id}.pdf"
        attempt += 1

    if target_path.exists():
        logger.error(
            "Quarantine collision safety failed after %d attempts (reason: %s)",
            max_attempts,
            reason_code,
        )
        return QuarantineResult(
            success=False,
            quarantined_path=None,
            quarantine_id=quarantine_id,
            reason_code=reason_code,
            error="quarantine_collision_error",
        )

    # Move file safely without discarding source on failure
    try:
        shutil.move(str(src), str(target_path))
        logger.info(
            "Successfully moved invalid file to quarantine (reason: %s, quarantine_id: %s)",
            reason_code,
            quarantine_id,
        )
        return QuarantineResult(
            success=True,
            quarantined_path=target_path,
            quarantine_id=quarantine_id,
            reason_code=reason_code,
        )
    except Exception as exc:
        # Never discard source file; report safe retryable outcome
        logger.error(
            "Failed to move file to quarantine (reason: %s, error: %s)",
            reason_code,
            type(exc).__name__,
        )
        return QuarantineResult(
            success=False,
            quarantined_path=None,
            quarantine_id=quarantine_id,
            reason_code=reason_code,
            error=f"quarantine_move_failed: {type(exc).__name__}",
        )
