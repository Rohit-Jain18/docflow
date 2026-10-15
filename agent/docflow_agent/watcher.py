"""
Folder watcher module for the Docflow Windows Agent.

Implements the folder watching requirements specified in docs/AGENT_SPEC.md §3:
- Uses watchdog to watch the configured watch folder non-recursively.
- Treats filesystem events as hints: scans on startup and rescans periodically.
- Filters candidate files: regular files with case-insensitive .pdf extension.
- Ignores temporary suffixes (.tmp, .crdownload, .part, ~*, .*) and inaccessible files.
- Deduplicates repeated events within the process so the same file is not processed concurrently.
- Offloads stability and processing off the filesystem event handler thread.
- Exposes a clean candidate callback/interface for subsequent pipeline / queue stages.
- Supports clean, graceful shutdown.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import pathlib
import stat
import threading
import time
from collections.abc import Callable
from typing import Any

from watchdog.events import (
    DirCreatedEvent,
    DirModifiedEvent,
    FileCreatedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from docflow_agent.pdf import DEFAULT_MAX_PDF_SIZE_BYTES, ValidationResult, validate_pdf
from docflow_agent.quarantine import QuarantineResult, quarantine_file, should_quarantine
from docflow_agent.recipient import mask_phone
from docflow_agent.stability import StabilityResult, check_stability

logger = logging.getLogger(__name__)

# Temporary suffixes and extensions to ignore
_IGNORED_EXTENSIONS = frozenset({
    ".tmp",
    ".crdownload",
    ".part",
    ".swp",
    ".bak",
    ".lock",
    ".aria2",
    ".download",
})

# Type alias for candidate callback
CandidateCallback = Callable[[pathlib.Path], None]


def is_candidate_file(
    path: pathlib.Path | str,
    watch_folder: pathlib.Path | str | None = None,
) -> bool:
    """Determine whether a path is a candidate PDF file for processing.

    Rules:
    - Must be a regular file (not directory).
    - Reject symbolic links and file reparse points.
    - Case-insensitive .pdf extension.
    - Not a temporary file (e.g. .tmp, .crdownload, .part, starting with ~ or .).
    - Must be accessible without fatal OS error.
    - If watch_folder is specified, resolved path must be within watch_folder at the top level only.
    """
    try:
        p = pathlib.Path(path)
        name = p.name

        # Ignore hidden and temp lock files
        if name.startswith(".") or name.startswith("~"):
            return False

        # Must end in .pdf (case-insensitive)
        if not name.lower().endswith(".pdf"):
            return False

        # Ignore compound temp extensions (e.g., sample.tmp.pdf)
        stem_lower = p.stem.lower()
        for ext in _IGNORED_EXTENSIONS:
            if stem_lower.endswith(ext):
                return False

        # Reject symbolic links
        if p.is_symlink() or os.path.islink(p):
            return False

        # Reject file reparse points on Windows
        try:
            lstat = os.lstat(p)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if bool(getattr(lstat, "st_file_attributes", 0) & reparse_flag):
                return False
        except (OSError, AttributeError):
            return False

        # Must be a regular file
        if not p.is_file():
            return False

        # Verify resolution within configured watch folder at the top level only
        if watch_folder is not None:
            try:
                resolved_watch = pathlib.Path(watch_folder).resolve()
                resolved_p = p.resolve(strict=True)
            except Exception:
                # If resolution fails, ignore safely without logging path
                return False

            if resolved_p.parent != resolved_watch:
                # Escapes watch folder or is in a subdirectory (not top level)
                return False

        return True
    except (OSError, PermissionError, RuntimeError, ValueError):
        return False


class _WatchdogHandler(FileSystemEventHandler):
    """Internal watchdog event handler translating filesystem events to watcher hints."""

    def __init__(self, watcher: Watcher) -> None:
        super().__init__()
        self._watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        if isinstance(event, (DirCreatedEvent, DirModifiedEvent)):
            return
        self._handle_path(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if isinstance(event, (DirCreatedEvent, DirModifiedEvent)):
            return
        self._handle_path(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if isinstance(event, FileMovedEvent):
            # If renamed/moved into the watch folder as a .pdf
            self._handle_path(event.dest_path)

    def _handle_path(self, path_str: str) -> None:
        try:
            path = pathlib.Path(path_str)
            if self._watcher.is_candidate(path):
                self._watcher.schedule_candidate(path)
        except Exception:
            logger.debug("Error inspecting event path")


class Watcher:
    """Non-recursive folder watcher with deduplication and periodic rescan."""

    def __init__(
        self,
        watch_folder: pathlib.Path | str,
        on_candidate: CandidateCallback | None = None,
        *,
        rescan_interval_seconds: float = 30.0,
        max_workers: int = 4,
    ) -> None:
        """Initialize the Watcher.

        Args:
            watch_folder: Path to folder to watch (non-recursively).
            on_candidate: Optional callback invoked when a candidate PDF is ready.
            rescan_interval_seconds: Interval in seconds for periodic recovery rescan.
                                     Set <= 0 to disable automatic background rescan.
            max_workers: Concurrency limit for background candidate processing.
        """
        self.watch_folder = pathlib.Path(watch_folder)
        self.on_candidate = on_candidate
        self.rescan_interval_seconds = rescan_interval_seconds
        self.max_workers = max_workers

        self._observer = Observer()
        self._event_handler = _WatchdogHandler(self)
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="docflow-watcher-worker",
        )

        self._active_paths: set[str] = set()
        self._lock = threading.Lock()
        self._running = False
        self._rescan_thread: threading.Thread | None = None

    def is_candidate(self, path: pathlib.Path | str) -> bool:
        """Check whether path is a valid candidate strictly within this watcher's folder."""
        return is_candidate_file(path, watch_folder=self.watch_folder)

    def is_active(self, path: pathlib.Path | str) -> bool:
        """Check if a path is currently being processed by a worker."""
        try:
            key = str(pathlib.Path(path).resolve())
        except Exception:
            return False
        with self._lock:
            return key in self._active_paths

    def schedule_candidate(self, path: pathlib.Path | str) -> bool:
        """Schedule a candidate file for background processing if not already active.

        Returns:
            True if scheduled, False if already in-progress (deduplicated).
        """
        p = pathlib.Path(path)
        if not self.is_candidate(p):
            return False

        try:
            key = str(p.resolve(strict=True))
        except Exception:
            return False

        with self._lock:
            if not self._running and self._observer.is_alive():
                return False
            if key in self._active_paths:
                # Deduplicate: already actively in progress
                return False
            self._active_paths.add(key)

        self._executor.submit(self._dispatch_candidate, p, key)
        return True

    def _dispatch_candidate(self, path: pathlib.Path, key: str) -> None:
        """Worker thread entry point for candidate dispatch."""
        try:
            if self.on_candidate is not None:
                self.on_candidate(path)
        except Exception as exc:
            logger.error("Unhandled error in candidate callback: %s", type(exc).__name__)
        finally:
            with self._lock:
                self._active_paths.discard(key)

    def scan(self) -> list[pathlib.Path]:
        """Scan the watch folder non-recursively for candidate files.

        Returns:
            List of candidate paths found during this scan.
        """
        candidates: list[pathlib.Path] = []
        if not self.watch_folder.is_dir():
            return candidates

        try:
            for item in self.watch_folder.iterdir():
                if self.is_candidate(item):
                    candidates.append(item)
                    self.schedule_candidate(item)
        except (OSError, PermissionError) as exc:
            logger.warning("Error reading watch folder during scan: %s", type(exc).__name__)

        return candidates

    def _rescan_loop(self) -> None:
        """Background thread executing periodic rescan to recover missed events."""
        while self._running:
            time.sleep(self.rescan_interval_seconds)
            if self._running:
                try:
                    self.scan()
                except Exception as exc:
                    logger.debug("Rescan cycle error: %s", type(exc).__name__)

    def start(self) -> None:
        """Start watching the folder, run initial scan, and start rescan timer."""
        if self._running:
            return

        self.watch_folder.mkdir(parents=True, exist_ok=True)
        self._running = True

        # 1. Startup scan to process existing files
        self.scan()

        # 2. Start watchdog observer non-recursively
        self._observer.schedule(
            self._event_handler,
            str(self.watch_folder),
            recursive=False,
        )
        self._observer.start()

        # 3. Start periodic rescan thread if configured
        if self.rescan_interval_seconds > 0:
            self._rescan_thread = threading.Thread(
                target=self._rescan_loop,
                daemon=True,
                name="docflow-rescan-timer",
            )
            self._rescan_thread.start()

        logger.info("Folder watcher started (watch_folder configured, non-recursive)")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop watching and cleanly shut down workers."""
        if not self._running:
            return

        self._running = False

        # Stop observer
        try:
            if self._observer.is_alive():
                self._observer.stop()
                self._observer.join(timeout=timeout)
        except Exception as exc:
            logger.debug("Error stopping watchdog observer: %s", type(exc).__name__)

        # Shutdown executor
        self._executor.shutdown(wait=True, cancel_futures=True)

        with self._lock:
            self._active_paths.clear()

        logger.info("Folder watcher stopped cleanly")


def process_candidate_file(
    path: pathlib.Path | str,
    *,
    watch_folder: pathlib.Path | str | None = None,
    quarantine_folder: pathlib.Path | str | None = None,
    max_size_bytes: int = DEFAULT_MAX_PDF_SIZE_BYTES,
    default_region: str = "IN",
    sample_interval_seconds: float = 2.0,
    required_samples: int = 3,
    timeout_seconds: float = 120.0,
    time_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[StabilityResult, ValidationResult | None, QuarantineResult | None]:
    """Execute the stability check, PDF validation, and quarantine pipeline on a candidate.

    Args:
        path: Candidate PDF path.
        watch_folder: Optional watch folder to enforce top-level boundary.
        quarantine_folder: Directory to quarantine permanently invalid files.
        max_size_bytes: Configured maximum PDF size.
        default_region: Region code for phone number validation.
        sample_interval_seconds: Interval between stability samples.
        required_samples: Number of consecutive unchanged samples.
        timeout_seconds: Stability timeout.
        time_fn: Time source.
        sleep_fn: Sleep implementation.

    Returns:
        tuple of (StabilityResult, ValidationResult | None, QuarantineResult | None).
    """
    file_path = pathlib.Path(path)

    # 0. Candidate and boundary check (do not quarantine boundary failures)
    if not is_candidate_file(file_path, watch_folder=watch_folder):
        return (
            StabilityResult(is_stable=False, reason_code="outside_watch_folder"),
            None,
            None,
        )

    # 1. Stability check
    stab = check_stability(
        file_path,
        sample_interval_seconds=sample_interval_seconds,
        required_samples=required_samples,
        timeout_seconds=timeout_seconds,
        time_fn=time_fn,
        sleep_fn=sleep_fn,
    )
    if not stab.is_stable:
        # Retryable timeout: DO NOT quarantine!
        return stab, None, None

    # 2. PDF validation
    val = validate_pdf(
        file_path,
        max_size_bytes=max_size_bytes,
        default_region=default_region,
    )

    # 3. Quarantine if permanently invalid
    quarantine_res: QuarantineResult | None = None
    if not val.is_valid and val.reason_code and should_quarantine(val.reason_code):
        if quarantine_folder is not None:
            quarantine_res = quarantine_file(
                file_path,
                quarantine_folder,
                reason_code=val.reason_code,
            )

    return stab, val, quarantine_res
