"""
File stability checking module for the Docflow Windows Agent.

Implements the stability detection algorithm specified in docs/AGENT_SPEC.md §3:
- Configurable defaults: sample_interval = 2s, required_samples = 3, timeout = 120s.
- Verifies a file can be opened read-only without sharing violations.
- Samples size and mtime_ns across consecutive intervals.
- Resets count if size or mtime_ns changes, or if file is locked/inaccessible.
- Returns retryable 'stability_timeout_after_policy' on timeout without quarantining.
- Supports injected time/sleep dependencies for deterministic, fast testing.
"""

from __future__ import annotations

import logging
import os
import pathlib
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StabilityResult:
    """Result of file stability checking."""

    is_stable: bool
    file_size_bytes: int = 0
    mtime_ns: int = 0
    reason_code: str | None = None
    samples_collected: int = 0


def check_stability(
    path: pathlib.Path | str,
    *,
    sample_interval_seconds: float = 2.0,
    required_samples: int = 3,
    timeout_seconds: float = 120.0,
    time_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> StabilityResult:
    """Check whether a file is stable and ready for processing.

    A file is stable only when:
    1. It can be opened read-only in binary mode without sharing violation.
    2. Its size and mtime_ns remain unchanged for `required_samples` consecutive samples.

    Args:
        path: Path to the target file.
        sample_interval_seconds: Interval in seconds between samples (default: 2.0).
        required_samples: Number of consecutive unchanged samples required (default: 3).
        timeout_seconds: Maximum time allowed before giving up (default: 120.0).
        time_fn: Callable returning the current time in seconds (for test mocking).
        sleep_fn: Callable to sleep for specified seconds (for test mocking).

    Returns:
        StabilityResult with stability flag, metadata, and reason code if timed out.
    """
    file_path = pathlib.Path(path)
    start_time = time_fn()
    consecutive_samples = 0
    last_size: int | None = None
    last_mtime_ns: int | None = None

    while True:
        elapsed = time_fn() - start_time
        if elapsed >= timeout_seconds:
            logger.warning(
                "File stability timed out after %.1fs policy (samples: %d/%d)",
                elapsed,
                consecutive_samples,
                required_samples,
            )
            return StabilityResult(
                is_stable=False,
                file_size_bytes=last_size or 0,
                mtime_ns=last_mtime_ns or 0,
                reason_code="stability_timeout_after_policy",
                samples_collected=consecutive_samples,
            )

        # 1. Attempt to open read-only and read stat
        can_access = False
        current_size = 0
        current_mtime_ns = 0

        try:
            # Check for sharing violation / exclusive write lock
            with open(file_path, "rb") as f:
                f.read(1)
            stat = file_path.stat()
            current_size = stat.st_size
            current_mtime_ns = stat.st_mtime_ns
            can_access = True
        except (FileNotFoundError, PermissionError, OSError):
            can_access = False

        # 2. Evaluate sample
        if not can_access:
            # File is disappearing, locked, or inaccessible: reset baseline
            consecutive_samples = 0
            last_size = None
            last_mtime_ns = None
        else:
            if last_size is not None and last_mtime_ns is not None:
                if current_size == last_size and current_mtime_ns == last_mtime_ns:
                    consecutive_samples += 1
                else:
                    # File size or mtime changed: growing or being written
                    # Reset count to 1 with this sample as new baseline
                    consecutive_samples = 1
                    last_size = current_size
                    last_mtime_ns = current_mtime_ns
            else:
                # First successful sample
                consecutive_samples = 1
                last_size = current_size
                last_mtime_ns = current_mtime_ns

            if consecutive_samples >= required_samples:
                return StabilityResult(
                    is_stable=True,
                    file_size_bytes=current_size,
                    mtime_ns=current_mtime_ns,
                    reason_code=None,
                    samples_collected=consecutive_samples,
                )

        # 3. Wait before taking next sample
        sleep_fn(sample_interval_seconds)
