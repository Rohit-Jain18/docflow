"""Tests for docflow_agent.watcher — folder watcher module."""

import pathlib
import threading
import time
import pytest

from docflow_agent.pdf import DEFAULT_MAX_PDF_SIZE_BYTES
from docflow_agent.watcher import Watcher, is_candidate_file, process_candidate_file


def _create_mock_pdf(content: bytes = b"mock content") -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n" + content + b"\ntrailer\n<<>>\n%%EOF\n"


class TestCandidateFiltering:
    """Test candidate file filtering rules."""

    def test_accepts_case_insensitive_pdf_files(self, tmp_path: pathlib.Path) -> None:
        for name in ["sample.pdf", "UPPER.PDF", "Mixed.Pdf"]:
            p = tmp_path / name
            p.write_bytes(b"dummy")
            assert is_candidate_file(p) is True

    def test_rejects_non_pdf_files(self, tmp_path: pathlib.Path) -> None:
        for name in ["sample.txt", "data.csv", "report.docx", "file"]:
            p = tmp_path / name
            p.write_bytes(b"dummy")
            assert is_candidate_file(p) is False

    def test_rejects_directories(self, tmp_path: pathlib.Path) -> None:
        d = tmp_path / "subdir.pdf"
        d.mkdir()
        assert is_candidate_file(d) is False

    def test_rejects_temporary_files_and_suffixes(self, tmp_path: pathlib.Path) -> None:
        bad_names = [
            ".hidden.pdf",
            "~lock.pdf",
            "report.tmp.pdf",
            "download.crdownload",
            "partial.part",
            "document.swp",
            "backup.bak",
        ]
        for name in bad_names:
            p = tmp_path / name
            p.write_bytes(b"dummy")
            assert is_candidate_file(p) is False


class TestWatcherLifecycleAndDeduplication:
    """Test watcher startup scan, deduplication, event handling, and clean shutdown."""

    def test_startup_scan_discovers_existing_files(self, tmp_path: pathlib.Path) -> None:
        watch = tmp_path / "watch"
        watch.mkdir()

        # Create candidate files before starting
        (watch / "9876543210.pdf").write_bytes(_create_mock_pdf())
        (watch / "9876543211.pdf").write_bytes(_create_mock_pdf())
        (watch / "ignored.txt").write_text("text")

        discovered: list[pathlib.Path] = []
        ready_event = threading.Event()

        def on_candidate(path: pathlib.Path) -> None:
            discovered.append(path)
            if len(discovered) == 2:
                ready_event.set()

        watcher = Watcher(
            watch_folder=watch,
            on_candidate=on_candidate,
            rescan_interval_seconds=0,  # disable auto rescan loop
        )

        try:
            watcher.start()
            # Wait for callback invocation on worker thread
            ready_event.wait(timeout=5.0)

            found_names = {p.name for p in discovered}
            assert "9876543210.pdf" in found_names
            assert "9876543211.pdf" in found_names
            assert "ignored.txt" not in found_names
        finally:
            watcher.stop()

    def test_in_process_deduplication_prevents_concurrent_processing(
        self, tmp_path: pathlib.Path,
    ) -> None:
        watch = tmp_path / "watch"
        watch.mkdir()
        file_path = watch / "9876543210.pdf"
        file_path.write_bytes(_create_mock_pdf())

        block_worker = threading.Event()
        worker_entered = threading.Event()
        call_count = 0

        def slow_worker(path: pathlib.Path) -> None:
            nonlocal call_count
            call_count += 1
            worker_entered.set()
            # Hold the worker active until released
            block_worker.wait(timeout=5.0)

        watcher = Watcher(
            watch_folder=watch,
            on_candidate=slow_worker,
            rescan_interval_seconds=0,
        )

        try:
            # 1. First schedule should succeed and enter worker
            scheduled1 = watcher.schedule_candidate(file_path)
            assert scheduled1 is True
            worker_entered.wait(timeout=3.0)

            # 2. Duplicate schedule attempt while worker is busy MUST be deduplicated
            scheduled2 = watcher.schedule_candidate(file_path)
            assert scheduled2 is False
            assert watcher.is_active(file_path) is True

            # Release worker
            block_worker.set()
        finally:
            watcher.stop()

        assert call_count == 1

    def test_manual_rescan_recovers_unseen_candidates(self, tmp_path: pathlib.Path) -> None:
        watch = tmp_path / "watch"
        watch.mkdir()

        discovered: list[pathlib.Path] = []

        def on_candidate(path: pathlib.Path) -> None:
            discovered.append(path)

        watcher = Watcher(
            watch_folder=watch,
            on_candidate=on_candidate,
            rescan_interval_seconds=0,
        )

        try:
            watcher.start()
            assert len(discovered) == 0

            # Add a file without relying on OS events
            new_file = watch / "9876543210.pdf"
            new_file.write_bytes(_create_mock_pdf())

            # Trigger rescan
            found = watcher.scan()
            assert len(found) == 1
            assert found[0].name == "9876543210.pdf"
        finally:
            watcher.stop()

    def test_offloads_stability_off_event_thread(self, tmp_path: pathlib.Path) -> None:
        watch = tmp_path / "watch"
        watch.mkdir()
        file_path = watch / "9876543210.pdf"
        file_path.write_bytes(_create_mock_pdf())

        worker_thread_name = ""
        done_event = threading.Event()

        def record_thread(path: pathlib.Path) -> None:
            nonlocal worker_thread_name
            worker_thread_name = threading.current_thread().name
            done_event.set()

        watcher = Watcher(
            watch_folder=watch,
            on_candidate=record_thread,
            rescan_interval_seconds=0,
        )

        try:
            watcher.start()
            done_event.wait(timeout=5.0)
            # The callback must run on a docflow-watcher-worker thread, NOT MainThread or Watchdog thread
            assert "docflow-watcher-worker" in worker_thread_name
        finally:
            watcher.stop()

    def test_clean_shutdown(self, tmp_path: pathlib.Path) -> None:
        watch = tmp_path / "watch"
        watch.mkdir()

        watcher = Watcher(
            watch_folder=watch,
            on_candidate=lambda p: None,
            rescan_interval_seconds=10.0,
        )
        watcher.start()
        assert watcher._running is True

        watcher.stop()
        assert watcher._running is False
        assert len(watcher._active_paths) == 0


class TestPipelineCandidateProcessing:
    """Test end-to-end processing: stability -> validation -> quarantine."""

    def test_pipeline_valid_pdf_remains_intact_and_not_archived(
        self, tmp_path: pathlib.Path,
    ) -> None:
        watch = tmp_path / "watch"
        quarantine = tmp_path / "quarantine"
        watch.mkdir()
        quarantine.mkdir()

        file_path = watch / "9876543210.pdf"
        pdf_data = _create_mock_pdf()
        file_path.write_bytes(pdf_data)

        # Process with instantaneous mock timing
        stab, val, quar = process_candidate_file(
            file_path,
            quarantine_folder=quarantine,
            sample_interval_seconds=0.01,
            required_samples=2,
            timeout_seconds=5.0,
            sleep_fn=lambda s: None,
        )

        assert stab.is_stable is True
        assert val is not None
        assert val.is_valid is True
        assert val.recipient_phone_e164 == "+919876543210"
        # Not quarantined
        assert quar is None
        # File must remain available for upload in later tasks (not archived or deleted)
        assert file_path.exists()
        assert file_path.read_bytes() == pdf_data

    def test_pipeline_invalid_filename_is_quarantined_safely(
        self, tmp_path: pathlib.Path,
    ) -> None:
        watch = tmp_path / "watch"
        quarantine = tmp_path / "quarantine"
        watch.mkdir()
        quarantine.mkdir()

        # Suffix like _report is permanently invalid
        file_path = watch / "9876543210_report.pdf"
        file_path.write_bytes(_create_mock_pdf())

        stab, val, quar = process_candidate_file(
            file_path,
            quarantine_folder=quarantine,
            sample_interval_seconds=0.01,
            required_samples=2,
            timeout_seconds=5.0,
            sleep_fn=lambda s: None,
        )

        assert stab.is_stable is True
        assert val is not None
        assert val.is_valid is False
        assert val.reason_code == "invalid_filename"

        assert quar is not None
        assert quar.success is True
        assert quar.quarantined_path is not None
        assert quar.quarantined_path.exists()
        # Original moved into quarantine
        assert not file_path.exists()
        # Quarantined filename must be opaque UUID, never containing phone
        assert "9876543210" not in quar.quarantined_path.name
        assert quar.quarantined_path.suffix.lower() == ".pdf"

    def test_pipeline_stability_timeout_is_never_quarantined(
        self, tmp_path: pathlib.Path,
    ) -> None:
        watch = tmp_path / "watch"
        quarantine = tmp_path / "quarantine"
        watch.mkdir()
        quarantine.mkdir()

        file_path = watch / "9876543210.pdf"
        file_path.write_bytes(_create_mock_pdf())

        # Simulate timeout by injecting zero-second timeout
        stab, val, quar = process_candidate_file(
            file_path,
            quarantine_folder=quarantine,
            sample_interval_seconds=1.0,
            required_samples=3,
            timeout_seconds=0.0,  # immediate timeout
            sleep_fn=lambda s: None,
        )

        assert stab.is_stable is False
        assert stab.reason_code == "stability_timeout_after_policy"
        # Must NOT quarantine
        assert quar is None
        assert file_path.exists()
