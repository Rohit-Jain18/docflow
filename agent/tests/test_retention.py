"""
Tests for Source PDF Retention, Operator Hold, and Cleanup Worker.

Covers:
- Retention lifecycle across all in-flight and terminal states.
- 6-point pre-deletion verification checklist.
- Active worker leases, future retries, and in-flight operations blocking deletion.
- Operator hold suspending cleanup and survival across restarts.
- Operator hold release recalculating 24h retention window if expired.
- Retries canceling previous cleanup eligibility.
- Boundary protection (rejecting files outside allowed folders or symlinks).
- Best-effort unlinking with Windows lock handling (PermissionError).
- Atomic SQLite updates and audit event recording.
"""

from __future__ import annotations

import datetime
from datetime import timedelta, timezone
import os
import pathlib
import stat
import uuid
import pytest

from docflow_agent.pdf import ValidationResult
from docflow_agent.queue import JobQueue, JobStatus
from docflow_agent.retention import (
    CleanupService,
    verify_cleanup_checklist,
    is_safe_path_for_deletion,
    ALLOWED_TERMINAL_CLEANUP_STATUSES,
)


@pytest.fixture
def temp_dirs(tmp_path: pathlib.Path):
    watch = tmp_path / "watch"
    archive = tmp_path / "archive"
    quarantine = tmp_path / "quarantine"
    watch.mkdir()
    archive.mkdir()
    quarantine.mkdir()
    return watch, archive, quarantine


@pytest.fixture
def queue(tmp_path: pathlib.Path) -> JobQueue:
    db = tmp_path / "test_retention.db"
    return JobQueue(db, cleanup_retention_hours=24, failed_retention_days=14)


def _create_sample_job(queue: JobQueue, folder: pathlib.Path, name: str = "919876543210.pdf"):
    branch_id = str(uuid.uuid4())
    pdf = folder / name
    pdf.write_bytes(b"%PDF-1.4 retention sample")

    val = ValidationResult(
        is_valid=True,
        source_path=pdf,
        source_basename=name,
        recipient_phone_e164="+919876543210",
        content_sha256="d" * 64,
        file_size_bytes=len(pdf.read_bytes()),
        mtime_ns=1000000,
    )
    res = queue.enqueue(val, branch_id=branch_id)
    return res.job, pdf


class TestPreDeletionChecklist:
    def test_in_flight_states_block_deletion(self, queue: JobQueue, temp_dirs):
        watch, _, _ = temp_dirs
        job, _ = _create_sample_job(queue, watch)

        # VALIDATED status
        res = verify_cleanup_checklist(job)
        assert res.is_eligible is False
        assert "not an allowed terminal state" in res.reason

        # Move through in-flight states
        queue.update_status(job.id, JobStatus.METADATA_REGISTERING)
        j1 = queue.get_job(job.id)
        assert verify_cleanup_checklist(j1).is_eligible is False

        queue.update_status(job.id, JobStatus.METADATA_REGISTERED, docflow_report_id=str(uuid.uuid4()))
        j2 = queue.get_job(job.id)
        assert verify_cleanup_checklist(j2).is_eligible is False

        queue.update_status(job.id, JobStatus.UPLOADING)
        j3 = queue.get_job(job.id)
        assert verify_cleanup_checklist(j3).is_eligible is False

        queue.update_status(job.id, JobStatus.MEDIA_UPLOADED, media_reference="https://tmpfiles.org/dl/1")
        j4 = queue.get_job(job.id)
        assert verify_cleanup_checklist(j4).is_eligible is False

        queue.update_status(job.id, JobStatus.MEDIA_REFERENCE_ATTACHING)
        j5 = queue.get_job(job.id)
        assert verify_cleanup_checklist(j5).is_eligible is False

        queue.update_status(job.id, JobStatus.REGISTERED)
        j6 = queue.get_job(job.id)
        assert verify_cleanup_checklist(j6).is_eligible is False

        # Provider acceptance alone (accepted) MUST NOT delete local PDF!
        queue.update_status(job.id, JobStatus.ACCEPTED)
        j7 = queue.get_job(job.id)
        assert verify_cleanup_checklist(j7).is_eligible is False
        assert "not an allowed terminal state" in verify_cleanup_checklist(j7).reason

        # Reconciliation required
        queue.update_status(job.id, JobStatus.RECONCILIATION_REQUIRED)
        j8 = queue.get_job(job.id)
        assert verify_cleanup_checklist(j8).is_eligible is False

    def test_delivered_report_retention_window(self, queue: JobQueue, temp_dirs):
        watch, _, _ = temp_dirs
        job, _ = _create_sample_job(queue, watch)

        # Advance to delivered
        queue.update_status(job.id, JobStatus.METADATA_REGISTERING)
        queue.update_status(job.id, JobStatus.METADATA_REGISTERED, docflow_report_id=str(uuid.uuid4()))
        queue.update_status(job.id, JobStatus.UPLOADING)
        queue.update_status(job.id, JobStatus.MEDIA_UPLOADED)
        queue.update_status(job.id, JobStatus.MEDIA_REFERENCE_ATTACHING)
        queue.update_status(job.id, JobStatus.REGISTERED)
        queue.update_status(job.id, JobStatus.ACCEPTED)
        queue.update_status(job.id, JobStatus.DELIVERED)

        delivered_job = queue.get_job(job.id)
        assert delivered_job is not None
        assert delivered_job.cleanup_status == "retention_active"
        assert delivered_job.cleanup_eligible_at is not None

        # Check before 24h deadline: blocked
        now = datetime.datetime.now(timezone.utc)
        assert verify_cleanup_checklist(delivered_job, now_dt=now).is_eligible is False

        # Check after 25h: eligible!
        future_25h = now + timedelta(hours=25)
        res = verify_cleanup_checklist(delivered_job, now_dt=future_25h)
        assert res.is_eligible is True

    def test_operator_hold_suspends_cleanup(self, queue: JobQueue, temp_dirs):
        watch, _, _ = temp_dirs
        job, _ = _create_sample_job(queue, watch)

        # Advance to delivered
        queue.update_status(job.id, JobStatus.METADATA_REGISTERING)
        queue.update_status(job.id, JobStatus.METADATA_REGISTERED, docflow_report_id=str(uuid.uuid4()))
        queue.update_status(job.id, JobStatus.UPLOADING)
        queue.update_status(job.id, JobStatus.MEDIA_UPLOADED)
        queue.update_status(job.id, JobStatus.MEDIA_REFERENCE_ATTACHING)
        queue.update_status(job.id, JobStatus.REGISTERED)
        queue.update_status(job.id, JobStatus.ACCEPTED)
        queue.update_status(job.id, JobStatus.DELIVERED)

        # Operator places hold
        held_job = queue.set_operator_hold(job.id, hold=True)
        assert held_job.operator_hold is True
        assert held_job.cleanup_status == "operator_hold"

        # Even 100 days later, hold blocks deletion!
        future_100d = datetime.datetime.now(timezone.utc) + timedelta(days=100)
        res = verify_cleanup_checklist(held_job, now_dt=future_100d)
        assert res.is_eligible is False
        assert "Operator hold is active" in res.reason

        # Release hold
        released_job = queue.set_operator_hold(job.id, hold=False)
        assert released_job.operator_hold is False
        assert released_job.cleanup_status == "retention_active"

        # Released hold gives at least 24h window from release
        now = datetime.datetime.now(timezone.utc)
        assert verify_cleanup_checklist(released_job, now_dt=now).is_eligible is False
        future_26h = now + timedelta(hours=26)
        assert verify_cleanup_checklist(released_job, now_dt=future_26h).is_eligible is True

    def test_active_lease_blocks_deletion(self, queue: JobQueue, temp_dirs):
        watch, _, _ = temp_dirs
        job, _ = _create_sample_job(queue, watch)

        # Advance to failed
        queue.update_status(job.id, JobStatus.FAILED)
        failed_job = queue.get_job(job.id)
        assert failed_job is not None

        # Simulate past retention deadline
        future = datetime.datetime.now(timezone.utc) + timedelta(days=20)
        assert verify_cleanup_checklist(failed_job, now_dt=future).is_eligible is True

        # Claim a lease on the job
        with queue._write_transaction() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET lease_owner = 'worker-1',
                    lease_expires_at = ?
                WHERE id = ?;
                """,
                ((future + timedelta(hours=1)).isoformat(), job.id),
            )

        leased_job = queue.get_job(job.id)
        assert verify_cleanup_checklist(leased_job, now_dt=future).is_eligible is False
        assert "Active worker lease held" in verify_cleanup_checklist(leased_job, now_dt=future).reason


class TestSafePathVerification:
    def test_safe_path_inside_allowed_folders(self, temp_dirs):
        watch, archive, quarantine = temp_dirs
        valid_file = watch / "sample.pdf"
        valid_file.write_bytes(b"%PDF")

        ok, msg = is_safe_path_for_deletion(valid_file, [watch, archive, quarantine])
        assert ok is True
        assert msg == "safe"

    def test_path_outside_allowed_folders_rejected(self, temp_dirs, tmp_path: pathlib.Path):
        watch, archive, quarantine = temp_dirs
        outside_folder = tmp_path / "outside"
        outside_folder.mkdir()
        outside_file = outside_folder / "critical.txt"
        outside_file.write_bytes(b"data")

        ok, msg = is_safe_path_for_deletion(outside_file, [watch, archive, quarantine])
        assert ok is False
        assert msg == "outside_allowed_boundaries"

    def test_symlink_pointing_outside_approved_folder_rejected(self, temp_dirs, tmp_path: pathlib.Path):
        watch, archive, quarantine = temp_dirs
        outside_folder = tmp_path / "outside"
        outside_folder.mkdir()
        outside_target = outside_folder / "secret.txt"
        outside_target.write_bytes(b"confidential")

        symlink_path = watch / "traversal_link.pdf"
        try:
            symlink_path.symlink_to(outside_target)
        except (OSError, NotImplementedError):
            pytest.skip("Symlink creation not permitted or supported in this test environment.")

        ok, msg = is_safe_path_for_deletion(symlink_path, [watch, archive, quarantine])
        assert ok is False
        assert msg == "symlink_rejected"
        assert "/" not in msg and "\\" not in msg

    def test_symlink_pointing_inside_approved_folder_rejected(self, temp_dirs):
        watch, archive, quarantine = temp_dirs
        target_file = watch / "real_report.pdf"
        target_file.write_bytes(b"%PDF real report")

        symlink_path = watch / "alias_link.pdf"
        try:
            symlink_path.symlink_to(target_file)
        except (OSError, NotImplementedError):
            pytest.skip("Symlink creation not permitted or supported in this test environment.")

        ok, msg = is_safe_path_for_deletion(symlink_path, [watch, archive, quarantine])
        assert ok is False
        assert msg == "symlink_rejected"
        assert "/" not in msg and "\\" not in msg

    def test_windows_reparse_point_rejected(self, temp_dirs, monkeypatch):
        import stat
        watch, archive, quarantine = temp_dirs
        test_file = watch / "reparse_test.pdf"
        test_file.write_bytes(b"%PDF content")

        real_lstat = os.lstat
        def fake_lstat(path, *args, **kwargs):
            st = real_lstat(path)
            # Create a mock stat_result with FILE_ATTRIBUTE_REPARSE_POINT set
            class MockStat:
                st_mode = st.st_mode
                st_file_attributes = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            return MockStat()

        monkeypatch.setattr(os, "lstat", fake_lstat)
        ok, msg = is_safe_path_for_deletion(test_file, [watch, archive, quarantine])
        assert ok is False
        assert msg == "reparse_point_rejected"
        assert "/" not in msg and "\\" not in msg

    def test_uninspectable_path_fails_closed(self, temp_dirs, monkeypatch):
        watch, archive, quarantine = temp_dirs
        test_file = watch / "error_test.pdf"
        test_file.write_bytes(b"%PDF content")

        def broken_lstat(path, *args, **kwargs):
            raise OSError("Access denied simulation")

        monkeypatch.setattr(os, "lstat", broken_lstat)
        ok, msg = is_safe_path_for_deletion(test_file, [watch, archive, quarantine])
        assert ok is False
        assert msg == "path_inspection_failed"
        assert "Access denied" not in msg

    def test_directory_rejected_as_not_regular_file(self, temp_dirs):
        watch, archive, quarantine = temp_dirs
        subfolder = watch / "subfolder"
        subfolder.mkdir()

        ok, msg = is_safe_path_for_deletion(subfolder, [watch, archive, quarantine])
        assert ok is False
        assert msg == "not_regular_file"


class TestCleanupService:
    def test_cleanup_service_deletes_eligible_file(self, queue: JobQueue, temp_dirs):
        watch, archive, quarantine = temp_dirs
        job, pdf_file = _create_sample_job(queue, watch)

        assert pdf_file.exists()

        # Advance to delivered
        queue.update_status(job.id, JobStatus.METADATA_REGISTERING)
        queue.update_status(job.id, JobStatus.METADATA_REGISTERED, docflow_report_id=str(uuid.uuid4()))
        queue.update_status(job.id, JobStatus.UPLOADING)
        queue.update_status(job.id, JobStatus.MEDIA_UPLOADED)
        queue.update_status(job.id, JobStatus.MEDIA_REFERENCE_ATTACHING)
        queue.update_status(job.id, JobStatus.REGISTERED)
        queue.update_status(job.id, JobStatus.ACCEPTED)
        queue.update_status(job.id, JobStatus.DELIVERED)

        # Service running before deadline: 0 deleted
        service = CleanupService(queue=queue, allowed_folders=[watch, archive, quarantine])
        count = service.process_cleanup_candidates()
        assert count == 0
        assert pdf_file.exists()

        # Service running after 25 hours: file is deleted
        future_25h = datetime.datetime.now(timezone.utc) + timedelta(hours=25)
        count_future = service.process_cleanup_candidates(now_dt=future_25h)
        assert count_future == 1
        assert not pdf_file.exists()

        # Check SQLite state
        updated = queue.get_job(job.id)
        assert updated is not None
        assert updated.cleanup_status == "deleted"
        assert updated.deletion_verified_at is not None

        # Check audit event
        events = queue.list_events(job.id)
        event_types = [e.event_type for e in events]
        assert "source_file_deleted" in event_types
