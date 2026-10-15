"""Tests for docflow_agent.queue — Durable SQLite job queue, deduplication, and worker leases."""

from __future__ import annotations

import logging
import pathlib
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
import pytest

from docflow_agent.pdf import ValidationResult
from docflow_agent.quarantine import QuarantineResult
from docflow_agent.queue import (
    DatabaseCorruptedError,
    EnqueueResult,
    InvalidStateTransitionError,
    JobNotFoundError,
    JobQueue,
    JobRecord,
    JobStatus,
    MigrationError,
    ProhibitedSecretError,
    QueueStateError,
    compute_fingerprint,
    create_watcher_enqueue_adapter,
    handle_watcher_result,
)
from docflow_agent.stability import StabilityResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_validation_result(
    tmp_path: pathlib.Path,
    phone_number: str = "+919876543210",
    content_sha256: str = "a" * 64,
    size: int = 1024,
    mtime_ns: int = 1700000000000,
    is_valid: bool = True,
    reason_code: str | None = None,
) -> ValidationResult:
    stem = phone_number.replace("+", "")
    p = tmp_path / f"{stem}.pdf"
    if not p.exists():
        p.write_bytes(b"%PDF-1.4 dummy content %%EOF")
    return ValidationResult(
        source_path=p,
        source_basename=p.name,
        recipient_phone_e164=phone_number if is_valid else None,
        content_sha256=content_sha256 if is_valid else None,
        file_size_bytes=size,
        mtime_ns=mtime_ns,
        is_valid=is_valid,
        reason_code=reason_code,
    )


# ---------------------------------------------------------------------------
# Test Suites
# ---------------------------------------------------------------------------

class TestDatabaseInitialization:
    """Tests for database creation, integrity checks, and schema migrations."""

    def test_fresh_db_initialization_and_schema_version_tracking(
        self, tmp_path: pathlib.Path,
    ) -> None:
        db_path = tmp_path / "test_queue.db"
        queue = JobQueue(db_path)

        assert db_path.exists()
        assert queue.get_schema_version() == 1

        # Check tables exist
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cur.fetchall()}
        conn.close()

        expected = {
            "schema_migrations",
            "jobs",
            "job_events",
            "processed_fingerprints",
            "agent_settings",
        }
        assert expected.issubset(tables)

    def test_migration_upgrade(self, tmp_path: pathlib.Path) -> None:
        db_path = tmp_path / "test_upgrade.db"

        # Initialize with v1
        v1_migrations = [(1, "CREATE TABLE dummy_v1 (id INT PRIMARY KEY);")]
        queue = JobQueue(db_path, migrations=v1_migrations)
        assert queue.get_schema_version() == 1

        # Upgrade with v2
        v2_migrations = [
            (1, "CREATE TABLE dummy_v1 (id INT PRIMARY KEY);"),
            (2, "CREATE TABLE dummy_v2 (id INT PRIMARY KEY, name TEXT);"),
        ]
        queue2 = JobQueue(db_path, migrations=v2_migrations)
        assert queue2.get_schema_version() == 2

        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cur.fetchall()}
        conn.close()

        assert "dummy_v1" in tables
        assert "dummy_v2" in tables

    def test_corrupt_database_fails_closed_and_preserves_file(
        self, tmp_path: pathlib.Path,
    ) -> None:
        db_path = tmp_path / "corrupt.db"
        # Write corrupted content (not a valid SQLite header)
        corrupted_content = b"INVALID SQLITE FILE CONTENT FOR TEST"
        db_path.write_bytes(corrupted_content)

        with pytest.raises(DatabaseCorruptedError) as exc_info:
            JobQueue(db_path)

        assert "failed integrity check" in str(exc_info.value) or "corrupt" in str(exc_info.value)
        # Must preserve the file for diagnosis, NEVER delete or overwrite it
        assert db_path.exists()
        assert db_path.read_bytes() == corrupted_content

    def test_migration_failure_fails_closed_and_preserves_file(
        self, tmp_path: pathlib.Path,
    ) -> None:
        db_path = tmp_path / "mig_fail.db"
        bad_migrations = [
            (1, "INVALID SQL SYNTAX HERE THAT WILL FAIL;"),
        ]

        with pytest.raises(MigrationError):
            JobQueue(db_path, migrations=bad_migrations)

        assert db_path.exists()

    def test_foreign_key_enforcement(self, tmp_path: pathlib.Path) -> None:
        db_path = tmp_path / "fk.db"
        queue = JobQueue(db_path)

        conn = queue._connect()
        try:
            # Foreign keys must be enabled on every connection
            cur = conn.execute("PRAGMA foreign_keys;")
            assert cur.fetchone()[0] == 1

            # Inserting job_events with invalid job_id must fail foreign key constraint
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO job_events (job_id, event_type, occurred_at) VALUES (?, ?, ?);",
                    ("non-existent-uuid", "test_event", datetime.now(timezone.utc).isoformat()),
                )
        finally:
            conn.close()


class TestEnqueueAndDeduplication:
    """Tests for canonical fingerprinting, atomic enqueue, and deduplication."""

    def test_canonical_fingerprint_formula(self) -> None:
        branch_id = "branch-uuid-1234"
        phone = "+919876543210"
        sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

        expected_input = f"v1|{branch_id}|{phone}|{sha}".encode("utf-8")
        import hashlib
        expected_hex = hashlib.sha256(expected_input).hexdigest().lower()

        fp = compute_fingerprint(branch_id, phone, sha)
        assert fp == expected_hex
        assert len(fp) == 64
        assert fp.islower()

    def test_missing_branch_identity_fails_closed(self) -> None:
        with pytest.raises(QueueStateError):
            compute_fingerprint("", "+919876543210", "a" * 64)

        with pytest.raises(QueueStateError):
            compute_fingerprint("   ", "+919876543210", "a" * 64)

    def test_enqueue_valid_job(self, tmp_path: pathlib.Path) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val = _mock_validation_result(tmp_path, phone_number="+919876543210", content_sha256="b" * 64)

        res = queue.enqueue(val, branch_id="branch-001")

        assert isinstance(res, EnqueueResult)
        assert res.is_duplicate is False
        assert res.job.status == JobStatus.VALIDATED.value
        assert res.job.recipient_phone_e164 == "+919876543210"
        assert res.job.content_sha256 == "b" * 64
        assert res.job.attempt_count == 0
        assert res.job.cleanup_status == "retained_in_flight"
        assert res.job.operator_hold is False

        # Verify event recorded
        events = queue.list_events(res.job.id)
        assert len(events) == 1
        assert events[0].event_type == "job_enqueued"

    def test_enqueue_invalid_validation_result_raises(self, tmp_path: pathlib.Path) -> None:
        queue = JobQueue(tmp_path / "q.db")
        invalid_val = _mock_validation_result(tmp_path, is_valid=False, reason_code="invalid_phone")

        with pytest.raises(QueueStateError):
            queue.enqueue(invalid_val, branch_id="branch-001")

    def test_duplicate_fingerprint_replay_returns_existing_job(
        self, tmp_path: pathlib.Path,
    ) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val = _mock_validation_result(tmp_path, phone_number="+919876543210", content_sha256="c" * 64)

        # First enqueue
        res1 = queue.enqueue(val, branch_id="branch-001")
        assert res1.is_duplicate is False

        # Second enqueue with identical content + recipient + branch
        res2 = queue.enqueue(val, branch_id="branch-001")
        assert res2.is_duplicate is True
        assert res2.job.id == res1.job.id

        # Total job count in database must remain exactly 1
        all_jobs = queue.list_jobs()
        assert len(all_jobs) == 1

        # Audit events include duplicate_fingerprint_observed
        events = queue.list_events(res1.job.id)
        event_types = [e.event_type for e in events]
        assert "duplicate_fingerprint_observed" in event_types

    def test_changed_file_content_enqueues_distinct_job(
        self, tmp_path: pathlib.Path,
    ) -> None:
        queue = JobQueue(tmp_path / "q.db")

        # Initial file
        val1 = _mock_validation_result(tmp_path, content_sha256="1" * 64)
        res1 = queue.enqueue(val1, branch_id="branch-001")
        assert res1.is_duplicate is False

        # Same path, but content hash changed
        val2 = _mock_validation_result(tmp_path, content_sha256="2" * 64)
        res2 = queue.enqueue(val2, branch_id="branch-001")
        assert res2.is_duplicate is False
        assert res2.job.id != res1.job.id

        all_jobs = queue.list_jobs()
        assert len(all_jobs) == 2


class TestJobLifecycleAndTransitions:
    """Tests for validated state transitions, cleanup deadlines, and operator hold."""

    def test_valid_lifecycle_transitions(self, tmp_path: pathlib.Path) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val = _mock_validation_result(tmp_path)
        job = queue.enqueue(val, branch_id="b1").job

        # Walk through permitted transitions
        job = queue.update_status(job.id, JobStatus.METADATA_REGISTERING)
        assert job.status == JobStatus.METADATA_REGISTERING.value

        job = queue.update_status(job.id, JobStatus.METADATA_REGISTERED)
        assert job.status == JobStatus.METADATA_REGISTERED.value

        job = queue.update_status(job.id, JobStatus.UPLOADING)
        assert job.status == JobStatus.UPLOADING.value

        job = queue.update_status(job.id, JobStatus.MEDIA_UPLOADED)
        assert job.status == JobStatus.MEDIA_UPLOADED.value

        job = queue.update_status(job.id, JobStatus.MEDIA_REFERENCE_ATTACHING)
        assert job.status == JobStatus.MEDIA_REFERENCE_ATTACHING.value

        job = queue.update_status(job.id, JobStatus.REGISTERED)
        assert job.status == JobStatus.REGISTERED.value

        job = queue.update_status(job.id, JobStatus.ACCEPTED)
        assert job.status == JobStatus.ACCEPTED.value
        assert job.accepted_at is not None
        # Provider acceptance alone MUST NOT permit deletion or archiving
        assert job.cleanup_status == "retained_in_flight"
        assert job.cleanup_eligible_at is None

        job = queue.update_status(job.id, JobStatus.DELIVERED)
        assert job.status == JobStatus.DELIVERED.value
        assert job.terminal_confirmed_at is not None
        assert job.cleanup_status == "retention_active"
        assert job.cleanup_eligible_at is not None

        job = queue.update_status(job.id, JobStatus.READ)
        assert job.status == JobStatus.READ.value

        job = queue.update_status(job.id, JobStatus.ARCHIVED)
        assert job.status == JobStatus.ARCHIVED.value
        assert job.archived_at is not None

    def test_invalid_status_transition_raises_error(self, tmp_path: pathlib.Path) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val = _mock_validation_result(tmp_path)
        job = queue.enqueue(val, branch_id="b1").job

        # Validated directly to UPLOADING is illegal (must register metadata first)
        with pytest.raises(InvalidStateTransitionError):
            queue.update_status(job.id, JobStatus.UPLOADING)

        # Transitioning a non-existent job raises JobNotFoundError
        with pytest.raises(JobNotFoundError):
            queue.update_status("non-existent-uuid", JobStatus.UPLOADING)

    def test_retry_cancels_cleanup_eligibility(self, tmp_path: pathlib.Path) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val = _mock_validation_result(tmp_path)
        job = queue.enqueue(val, branch_id="b1").job

        # Move to failed
        job = queue.update_status(job.id, JobStatus.FAILED, error_code="timeout")
        assert job.status == JobStatus.FAILED.value
        assert job.cleanup_status == "retention_active"
        assert job.cleanup_eligible_at is not None

        # Re-try / authorized retry moves to retry_wait -> cancels cleanup eligibility
        job = queue.update_status(job.id, JobStatus.RETRY_WAIT, increment_attempt=True)
        assert job.status == JobStatus.RETRY_WAIT.value
        assert job.attempt_count == 1
        assert job.cleanup_eligible_at is None
        assert job.cleanup_status == "retained_in_flight"

    def test_operator_hold_suspends_and_resumes_cleanup(
        self, tmp_path: pathlib.Path,
    ) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val = _mock_validation_result(tmp_path)
        job = queue.enqueue(val, branch_id="b1").job

        # Transition to terminal delivered
        job = queue.update_status(job.id, JobStatus.METADATA_REGISTERING)
        job = queue.update_status(job.id, JobStatus.METADATA_REGISTERED)
        job = queue.update_status(job.id, JobStatus.UPLOADING)
        job = queue.update_status(job.id, JobStatus.MEDIA_UPLOADED)
        job = queue.update_status(job.id, JobStatus.MEDIA_REFERENCE_ATTACHING)
        job = queue.update_status(job.id, JobStatus.REGISTERED)
        job = queue.update_status(job.id, JobStatus.ACCEPTED)
        job = queue.update_status(job.id, JobStatus.DELIVERED)

        orig_cleanup = job.cleanup_eligible_at
        assert orig_cleanup is not None
        assert job.cleanup_status == "retention_active"

        # Set operator hold
        job = queue.set_operator_hold(job.id, hold=True)
        assert job.operator_hold is True
        assert job.cleanup_status == "operator_hold"

        # Release operator hold
        job = queue.set_operator_hold(job.id, hold=False)
        assert job.operator_hold is False
        assert job.cleanup_status == "retention_active"
        assert job.cleanup_eligible_at is not None


class TestWorkerLeases:
    """Tests for exclusive claims, renewal, release, and restart recovery."""

    def test_exclusive_worker_claim(self, tmp_path: pathlib.Path) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val = _mock_validation_result(tmp_path)
        job = queue.enqueue(val, branch_id="b1").job

        # Worker 1 claims job
        claimed_w1 = queue.claim_job("worker-1", lease_duration_seconds=60.0)
        assert claimed_w1 is not None
        assert claimed_w1.id == job.id
        assert claimed_w1.lease_owner == "worker-1"
        assert claimed_w1.lease_expires_at is not None

        # Worker 2 attempts to claim while lease is active
        claimed_w2 = queue.claim_job("worker-2", lease_duration_seconds=60.0)
        assert claimed_w2 is None

    def test_lease_renewal(self, tmp_path: pathlib.Path) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val = _mock_validation_result(tmp_path)
        job = queue.enqueue(val, branch_id="b1").job

        queue.claim_job("worker-1", lease_duration_seconds=30.0)

        # Worker 1 can renew
        renewed = queue.renew_lease(job.id, "worker-1", extension_seconds=120.0)
        assert renewed is True

        # Non-owner cannot renew
        renewed_w2 = queue.renew_lease(job.id, "worker-2", extension_seconds=120.0)
        assert renewed_w2 is False

    def test_lease_release(self, tmp_path: pathlib.Path) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val = _mock_validation_result(tmp_path)
        job = queue.enqueue(val, branch_id="b1").job

        queue.claim_job("worker-1", lease_duration_seconds=60.0)

        # Worker 1 releases lease
        released = queue.release_lease(job.id, "worker-1")
        assert released is True

        # Worker 2 can now claim it
        claimed_w2 = queue.claim_job("worker-2", lease_duration_seconds=60.0)
        assert claimed_w2 is not None
        assert claimed_w2.id == job.id
        assert claimed_w2.lease_owner == "worker-2"

    def test_expired_lease_recovery(self, tmp_path: pathlib.Path) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val = _mock_validation_result(tmp_path)
        job = queue.enqueue(val, branch_id="b1").job

        # Claim with short lease
        queue.claim_job("worker-1", lease_duration_seconds=1.0)

        # Simulate time passing beyond expiry
        past_iso = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat()
        recovered_count = queue.recover_expired_leases(now_iso=past_iso)
        assert recovered_count == 1

        # Job is preserved, not deleted or marked failed
        job_after = queue.get_job(job.id)
        assert job_after is not None
        assert job_after.lease_owner is None
        assert job_after.lease_expires_at is None
        assert job_after.status == JobStatus.VALIDATED.value

        # Another worker can now claim it
        claimed = queue.claim_job("worker-2", lease_duration_seconds=60.0)
        assert claimed is not None
        assert claimed.id == job.id

    def test_retry_wait_delay_respected(self, tmp_path: pathlib.Path) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val = _mock_validation_result(tmp_path)
        job = queue.enqueue(val, branch_id="b1").job

        future_iso = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        queue.update_status(job.id, JobStatus.RETRY_WAIT, next_attempt_at=future_iso)

        # Cannot claim before retry deadline
        claimed = queue.claim_job("worker-1", eligible_statuses=[JobStatus.RETRY_WAIT.value])
        assert claimed is None


class TestQueriesAndSettings:
    """Tests for bounded queries, persistence across restart, and settings."""

    def test_bounded_list_jobs(self, tmp_path: pathlib.Path) -> None:
        queue = JobQueue(tmp_path / "q.db")
        for i in range(5):
            val = _mock_validation_result(
                tmp_path,
                phone_number=f"+91987654321{i}",
                content_sha256=f"{i}" * 64,
            )
            queue.enqueue(val, branch_id="b1")

        # Bound check: requested 2
        jobs = queue.list_jobs(limit=2)
        assert len(jobs) == 2

        # Offset check
        jobs_offset = queue.list_jobs(limit=2, offset=2)
        assert len(jobs_offset) == 2
        assert jobs_offset[0].id != jobs[0].id

    def test_restart_and_reopen_persistence(self, tmp_path: pathlib.Path) -> None:
        db_path = tmp_path / "persist.db"
        q1 = JobQueue(db_path)
        val = _mock_validation_result(tmp_path)
        job = q1.enqueue(val, branch_id="b1").job
        q1.set_setting("sync_mode", "auto")

        # Simulate service restart: create new queue instance pointing to same file
        q2 = JobQueue(db_path)
        restored_job = q2.get_job(job.id)
        assert restored_job is not None
        assert restored_job.id == job.id
        assert restored_job.content_sha256 == job.content_sha256
        assert q2.get_setting("sync_mode") == "auto"

    def test_agent_settings_storage(self, tmp_path: pathlib.Path) -> None:
        queue = JobQueue(tmp_path / "q.db")

        # Normal non-secret settings
        queue.set_setting("poll_interval_seconds", "15")
        assert queue.get_setting("poll_interval_seconds") == "15"

        all_settings = queue.list_settings()
        assert all_settings.get("poll_interval_seconds") == "15"

        # Attempting to store prohibited credentials/tokens must raise ProhibitedSecretError
        with pytest.raises(ProhibitedSecretError):
            queue.set_setting("access_token", "secret_val")

        with pytest.raises(ProhibitedSecretError):
            queue.set_setting("device_token", "secret_val")

        with pytest.raises(ProhibitedSecretError):
            queue.set_setting("wa_platform_developer_token", "secret_val")

        with pytest.raises(ProhibitedSecretError):
            queue.set_setting("auth_password", "secret_val")

    def test_no_pdf_bytes_or_credentials_in_sqlite(
        self, tmp_path: pathlib.Path,
    ) -> None:
        db_path = tmp_path / "clean.db"
        queue = JobQueue(db_path)
        val = _mock_validation_result(tmp_path)
        queue.enqueue(val, branch_id="b1")

        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # Check all table columns
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cur.fetchall() if not r[0].startswith("sqlite_")]

        for table in tables:
            cur.execute(f"PRAGMA table_info({table});")
            cols = [r[1] for r in cur.fetchall()]
            # No table should have a blob or pdf_bytes column
            assert "pdf_bytes" not in cols
            assert "file_bytes" not in cols

            # Inspect actual values
            cur.execute(f"SELECT * FROM {table};")
            for row in cur.fetchall():
                for val_cell in row:
                    assert not isinstance(val_cell, (bytes, bytearray)), (
                        f"Found binary data in table {table}"
                    )
                    if isinstance(val_cell, str):
                        # Verify no tokens or PDF magic header %PDF-
                        assert "%PDF-" not in val_cell
                        assert "wa_platform_developer_token" not in val_cell.lower()

        conn.close()


class TestWatcherIntegrationAdapter:
    """Tests for handle_watcher_result and create_watcher_enqueue_adapter."""

    def test_valid_stable_candidate_enqueued(self, tmp_path: pathlib.Path) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val = _mock_validation_result(tmp_path)
        stab = StabilityResult(
            is_stable=True,
            file_size_bytes=1024,
            mtime_ns=1700000000000,
            samples_collected=3,
            reason_code=None,
        )

        res = handle_watcher_result(
            queue=queue,
            branch_id="b1",
            stability=stab,
            validation=val,
            quarantine=None,
        )

        assert res is not None
        assert res.is_duplicate is False
        assert res.job.recipient_phone_e164 == val.recipient_phone_e164

    def test_stability_timeout_is_never_enqueued_and_never_quarantined(
        self, tmp_path: pathlib.Path,
    ) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val = _mock_validation_result(tmp_path)
        stab_timeout = StabilityResult(
            is_stable=False,
            file_size_bytes=1024,
            mtime_ns=1700000000000,
            samples_collected=5,
            reason_code="stability_timeout_after_policy",
        )

        res = handle_watcher_result(
            queue=queue,
            branch_id="b1",
            stability=stab_timeout,
            validation=val,
            quarantine=None,
        )

        assert res is None
        assert len(queue.list_jobs()) == 0

    def test_invalid_candidate_quarantined_is_never_enqueued(
        self, tmp_path: pathlib.Path,
    ) -> None:
        queue = JobQueue(tmp_path / "q.db")
        val_invalid = _mock_validation_result(tmp_path, is_valid=False, reason_code="invalid_filename")
        stab = StabilityResult(
            is_stable=True,
            file_size_bytes=1024,
            mtime_ns=1700000000000,
            samples_collected=3,
        )
        quar = QuarantineResult(
            success=True,
            quarantined_path=tmp_path / "quar.pdf",
            quarantine_id="test-quarantine-id",
            reason_code="invalid_filename",
        )

        res = handle_watcher_result(
            queue=queue,
            branch_id="b1",
            stability=stab,
            validation=val_invalid,
            quarantine=quar,
        )

        assert res is None
        assert len(queue.list_jobs()) == 0


class TestLogPrivacy:
    """Tests ensuring no phones, absolute paths, or tokens leak into log output."""

    def test_no_phone_or_path_or_token_in_logs(
        self, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        queue = JobQueue(tmp_path / "q.db")
        phone = "+919876543210"
        val = _mock_validation_result(tmp_path, phone_number=phone)

        with caplog.at_level(logging.DEBUG):
            res = queue.enqueue(val, branch_id="b1")
            queue.update_status(res.job.id, JobStatus.METADATA_REGISTERING)
            queue.claim_job("worker-test")

        raw_phone = "9876543210"
        full_path = str(val.source_path)
        basename = val.source_basename

        for record in caplog.records:
            msg = record.getMessage()
            # Raw unmasked 10-digit number must never appear in logs
            assert raw_phone not in msg
            # Full absolute source path must never appear in logs
            assert full_path not in msg
            # Sensitive basename bearing phone must not appear in logs
            assert basename not in msg
