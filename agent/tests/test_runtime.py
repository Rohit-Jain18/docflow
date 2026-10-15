"""
Tests for Agent Runtime Orchestrator, Retry Policy, and Lifecycle Management.

Covers:
- Startup recovery (expired worker lease reclamation and folder rescan).
- Single-worker lease claiming (BEGIN IMMEDIATE) and release.
- Successful registration processing and state progression.
- Transient failure handling with exponential backoff and retry scheduling.
- Retry budget exhaustion transitioning jobs to terminal FAILED.
- Device revocation (403) pausing active network operations.
- Graceful shutdown releasing all active worker leases.
- Deterministic run_once() sweep execution.
"""

from __future__ import annotations

import datetime
from datetime import timedelta, timezone
import json
import pathlib
import uuid
import pytest
import httpx

from docflow_agent.client import ApiClient
from docflow_agent.config import AgentConfig
from docflow_agent.credentials import InMemoryCredentialStore
from docflow_agent.pdf import ValidationResult
from docflow_agent.queue import JobQueue, JobStatus
from docflow_agent.runtime import (
    AgentRuntime,
    calculate_backoff_delay,
)
from docflow_agent.service import ServiceRunner
from docflow_agent.token_manager import TokenManager


@pytest.fixture
def temp_env(tmp_path: pathlib.Path):
    watch = tmp_path / "watch"
    archive = tmp_path / "archive"
    quarantine = tmp_path / "quarantine"
    watch.mkdir()
    archive.mkdir()
    quarantine.mkdir()

    config = AgentConfig(
        api_base_url="https://api.docflow.test",
        watch_folder=str(watch),
        archive_folder=str(archive),
        quarantine_folder=str(quarantine),
        db_path=str(tmp_path / "agent.db"),
        phone_default_region="IN",
        stability_sample_seconds=1,
        stability_required_samples=2,
        stability_timeout_seconds=10,
        max_pdf_size_bytes=52428800,
        cleanup_retention_hours=24,
        failed_retention_days=14,
        temp_upload_expected_host="tmpfiles.org",
        temp_upload_ttl_seconds=3600,
        temp_upload_expiry_buffer_seconds=300,
        log_level="INFO",
    )
    store = InMemoryCredentialStore()
    store.store("device_refresh_token", "test-refresh-token")
    return config, store, watch


def _make_client(handler, token: str = "valid-token") -> ApiClient:
    return ApiClient(
        base_url="https://api.docflow.test",
        token_provider=lambda: token,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


class TestBackoffCalculation:
    def test_calculate_backoff_delay_exponential(self):
        d1 = calculate_backoff_delay(1, base_seconds=2.0, multiplier=2.0, jitter=False)
        d2 = calculate_backoff_delay(2, base_seconds=2.0, multiplier=2.0, jitter=False)
        d3 = calculate_backoff_delay(3, base_seconds=2.0, multiplier=2.0, jitter=False)

        assert d1 == 2.0
        assert d2 == 4.0
        assert d3 == 8.0

    def test_calculate_backoff_delay_capped(self):
        d = calculate_backoff_delay(20, base_seconds=2.0, max_seconds=100.0, jitter=False)
        assert d == 100.0

    def test_calculate_backoff_delay_with_jitter(self):
        d = calculate_backoff_delay(2, base_seconds=2.0, jitter=True)
        # Should be between 0.5 * 4.0 and 4.0
        assert 2.0 <= d <= 4.0


class TestAgentRuntime:
    def test_startup_recovery(self, temp_env):
        config, store, watch = temp_env
        queue = JobQueue.from_config(config)

        # Create an expired worker lease
        pdf = watch / "919876543210.pdf"
        pdf.write_bytes(b"%PDF-1.4 sample")
        val = ValidationResult(
            is_valid=True,
            source_path=pdf,
            source_basename="919876543210.pdf",
            recipient_phone_e164="+919876543210",
            content_sha256="1" * 64,
            file_size_bytes=100,
            mtime_ns=100,
        )
        enq = queue.enqueue(val, branch_id=str(uuid.uuid4()))
        past_time = (datetime.datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with queue._write_transaction() as conn:
            conn.execute(
                "UPDATE jobs SET lease_owner = 'dead-worker', lease_expires_at = ? WHERE id = ?;",
                (past_time, enq.job.id),
            )

        client = _make_client(lambda r: httpx.Response(200))
        runtime = AgentRuntime(config, credential_store=store, queue=queue, client=client)

        recovery = runtime.startup_recovery()
        assert recovery["recovered_leases"] == 1

        recovered_job = queue.get_job(enq.job.id)
        assert recovered_job.lease_owner is None
        assert recovered_job.lease_expires_at is None

    def test_process_next_registration_job_success(self, temp_env):
        config, store, watch = temp_env
        queue = JobQueue.from_config(config)

        pdf = watch / "919876543210.pdf"
        pdf.write_bytes(b"%PDF-1.4 sample")
        val = ValidationResult(
            is_valid=True,
            source_path=pdf,
            source_basename="919876543210.pdf",
            recipient_phone_e164="+919876543210",
            content_sha256="2" * 64,
            file_size_bytes=100,
            mtime_ns=100,
        )
        enq = queue.enqueue(val, branch_id=str(uuid.uuid4()))
        server_report_id = str(uuid.uuid4())

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                202,
                json={
                    "report_id": server_report_id,
                    "status": "queued",
                    "duplicate": False,
                    "created_at": "2026-10-15T12:00:00Z",
                },
            )

        client = _make_client(handler)
        runtime = AgentRuntime(config, credential_store=store, queue=queue, client=client)

        processed = runtime.process_next_registration_job()
        assert processed is True

        updated = queue.get_job(enq.job.id)
        assert updated.status == JobStatus.METADATA_REGISTERED.value
        assert updated.docflow_report_id == server_report_id
        # Lease must be cleanly released!
        assert updated.lease_owner is None

    def test_process_next_registration_job_transient_error_schedules_backoff(self, temp_env):
        config, store, watch = temp_env
        queue = JobQueue.from_config(config)

        pdf = watch / "919876543210.pdf"
        pdf.write_bytes(b"%PDF-1.4 sample")
        val = ValidationResult(
            is_valid=True,
            source_path=pdf,
            source_basename="919876543210.pdf",
            recipient_phone_e164="+919876543210",
            content_sha256="3" * 64,
            file_size_bytes=100,
            mtime_ns=100,
        )
        enq = queue.enqueue(val, branch_id=str(uuid.uuid4()))

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Timeout")

        client = _make_client(handler)
        runtime = AgentRuntime(config, credential_store=store, queue=queue, client=client)

        processed = runtime.process_next_registration_job()
        assert processed is False

        updated = queue.get_job(enq.job.id)
        assert updated.status == JobStatus.RETRY_WAIT.value
        assert updated.attempt_count == 1
        assert updated.next_attempt_at is not None
        assert updated.lease_owner is None

    def test_process_next_registration_job_retry_budget_exhaustion(self, temp_env):
        config, store, watch = temp_env
        queue = JobQueue.from_config(config)

        pdf = watch / "919876543210.pdf"
        pdf.write_bytes(b"%PDF-1.4 sample")
        val = ValidationResult(
            is_valid=True,
            source_path=pdf,
            source_basename="919876543210.pdf",
            recipient_phone_e164="+919876543210",
            content_sha256="4" * 64,
            file_size_bytes=100,
            mtime_ns=100,
        )
        enq = queue.enqueue(val, branch_id=str(uuid.uuid4()))
        # Simulate 2 prior attempts, with max_retry_attempts=3
        with queue._write_transaction() as conn:
            conn.execute("UPDATE jobs SET attempt_count = 2 WHERE id = ?;", (enq.job.id,))

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Timeout")

        client = _make_client(handler)
        runtime = AgentRuntime(
            config,
            credential_store=store,
            queue=queue,
            client=client,
            max_retry_attempts=3,
        )

        processed = runtime.process_next_registration_job()
        assert processed is False

        updated = queue.get_job(enq.job.id)
        # Attempt count reached 3 -> marked FAILED
        assert updated.status == JobStatus.FAILED.value
        assert updated.last_error_code == "retry_budget_exhausted"

    def test_runtime_pause_on_device_revocation(self, temp_env):
        config, store, watch = temp_env
        queue = JobQueue.from_config(config)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                json={
                    "type": "about:blank",
                    "title": "Forbidden",
                    "status": 403,
                    "code": "permission_denied",
                    "detail": "Device is revoked.",
                },
            )

        client = _make_client(handler)
        runtime = AgentRuntime(config, credential_store=store, queue=queue, client=client)

        assert runtime.is_paused is False
        runtime.run_once()
        assert runtime.is_paused is True

    def test_runtime_shutdown_releases_active_leases(self, temp_env):
        config, store, watch = temp_env
        queue = JobQueue.from_config(config)

        pdf = watch / "919876543210.pdf"
        pdf.write_bytes(b"%PDF-1.4 sample")
        val = ValidationResult(
            is_valid=True,
            source_path=pdf,
            source_basename="919876543210.pdf",
            recipient_phone_e164="+919876543210",
            content_sha256="5" * 64,
            file_size_bytes=100,
            mtime_ns=100,
        )
        enq = queue.enqueue(val, branch_id=str(uuid.uuid4()))

        claimed = queue.claim_job("test-worker")
        assert claimed is not None

        client = _make_client(lambda r: httpx.Response(200))
        runtime = AgentRuntime(
            config,
            credential_store=store,
            queue=queue,
            client=client,
            worker_id="test-worker",
        )
        runtime._active_leases.add(enq.job.id)

        runtime.shutdown()
        released_job = queue.get_job(enq.job.id)
        assert released_job.lease_owner is None
        assert released_job.lease_expires_at is None


class TestServiceRunner:
    def test_service_runner_stops_gracefully(self, temp_env):
        config, store, watch = temp_env
        runner = ServiceRunner(config=config, poll_interval_seconds=0.1)

        # Trigger stop immediately
        runner.stop()
        exit_code = runner.run()
        assert exit_code == 0

    def test_runtime_registration_403_pauses_and_preserves_job(self, temp_env):
        config, store, watch = temp_env
        queue = JobQueue.from_config(config)

        pdf = watch / "919876543210.pdf"
        pdf.write_bytes(b"%PDF-1.4 sample")
        val = ValidationResult(
            is_valid=True,
            source_path=pdf,
            source_basename="919876543210.pdf",
            recipient_phone_e164="+919876543210",
            content_sha256="6" * 64,
            file_size_bytes=100,
            mtime_ns=100,
        )
        enq = queue.enqueue(val, branch_id=str(uuid.uuid4()))

        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(
                403,
                json={
                    "type": "about:blank",
                    "title": "Forbidden",
                    "status": 403,
                    "code": "permission_denied",
                    "detail": "Device is revoked.",
                },
            )

        client = _make_client(handler)
        runtime = AgentRuntime(config, credential_store=store, queue=queue, client=client)

        assert runtime.is_paused is False
        processed = runtime.process_next_registration_job()
        assert processed is False
        assert call_count == 1

        # Runtime is paused
        assert runtime.is_paused is True

        # Job is preserved in RETRY_WAIT, not FAILED, no terminal cleanup armed
        job = queue.get_job(enq.job.id)
        assert job is not None
        assert job.status == JobStatus.RETRY_WAIT.value
        assert job.last_error_code == "device_revoked"
        assert job.cleanup_eligible_at is None
        assert job.lease_owner is None

        # Subsequent call must not send any network request
        processed2 = runtime.process_next_registration_job()
        assert processed2 is False
        assert call_count == 1

    def test_runtime_token_errors_pause_and_preserve_job(self, temp_env):
        import dataclasses
        from docflow_agent.token_manager import (
            TokenAuthenticationError,
            TokenReuseConflictError,
            TokenRotationAmbiguousError,
        )
        config, store, watch = temp_env

        for i, (exc_to_raise, expected_code) in enumerate([
            (TokenAuthenticationError("auth_failed"), "token_error"),
            (TokenReuseConflictError("reuse_conflict"), "token_error"),
            (TokenRotationAmbiguousError("Ambiguous token rotation outcome"), "token_rotation_ambiguous"),
        ]):
            db_path = watch.parent / f"token_err_{i}.db"
            iter_config = dataclasses.replace(config, db_path=str(db_path))
            queue = JobQueue.from_config(iter_config)
            pdf = watch / f"91987654321{i}.pdf"
            pdf.write_bytes(b"%PDF-1.4 sample")
            val = ValidationResult(
                is_valid=True,
                source_path=pdf,
                source_basename=f"91987654321{i}.pdf",
                recipient_phone_e164=f"+91987654321{i}",
                content_sha256=f"{i}" * 64,
                file_size_bytes=100,
                mtime_ns=100,
            )
            enq = queue.enqueue(val, branch_id=str(uuid.uuid4()))

            call_count = 0

            def handler(request: httpx.Request) -> httpx.Response:
                nonlocal call_count
                call_count += 1
                raise exc_to_raise

            client = _make_client(handler)
            runtime = AgentRuntime(iter_config, credential_store=store, queue=queue, client=client)

            assert runtime.is_paused is False
            processed = runtime.process_next_registration_job()
            assert processed is False
            assert call_count == 1
            assert runtime.is_paused is True

            job = queue.get_job(enq.job.id)
            assert job is not None
            assert job.status == JobStatus.RETRY_WAIT.value
            assert job.cleanup_eligible_at is None
            assert job.lease_owner is None

            # Subsequent call does nothing while paused
            assert runtime.process_next_registration_job() is False
            assert call_count == 1

    def test_runtime_rate_limiting_pauses_and_preserves_job(self, temp_env):
        from docflow_agent.token_manager import TokenRateLimitedError
        config, store, watch = temp_env
        queue = JobQueue.from_config(config)

        pdf = watch / "919876543210.pdf"
        pdf.write_bytes(b"%PDF-1.4 sample")
        val = ValidationResult(
            is_valid=True,
            source_path=pdf,
            source_basename="919876543210.pdf",
            recipient_phone_e164="+919876543210",
            content_sha256="8" * 64,
            file_size_bytes=100,
            mtime_ns=100,
        )
        enq = queue.enqueue(val, branch_id=str(uuid.uuid4()))

        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise TokenRateLimitedError("Rate limit reached", retry_after=30)

        client = _make_client(handler)
        runtime = AgentRuntime(config, credential_store=store, queue=queue, client=client)

        processed = runtime.process_next_registration_job()
        assert processed is False
        assert call_count == 1
        assert runtime.is_paused is True

        job = queue.get_job(enq.job.id)
        assert job is not None
        assert job.status == JobStatus.RETRY_WAIT.value
        assert job.next_attempt_at is not None
        assert job.cleanup_eligible_at is None
        assert job.lease_owner is None

        # Subsequent call does nothing while rate-limited
        assert runtime.process_next_registration_job() is False
        assert call_count == 1

    def test_service_runner_heartbeat_403_pauses_runtime(self, temp_env):
        config, store, watch = temp_env
        queue = JobQueue.from_config(config)

        pdf = watch / "919876543210.pdf"
        pdf.write_bytes(b"%PDF-1.4 sample")
        val = ValidationResult(
            is_valid=True,
            source_path=pdf,
            source_basename="919876543210.pdf",
            recipient_phone_e164="+919876543210",
            content_sha256="9" * 64,
            file_size_bytes=100,
            mtime_ns=100,
        )
        enq = queue.enqueue(val, branch_id=str(uuid.uuid4()))

        registration_called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal registration_called
            if request.url.path == "/api/v1/agent/heartbeat":
                return httpx.Response(
                    403,
                    json={
                        "type": "about:blank",
                        "title": "Forbidden",
                        "status": 403,
                        "code": "permission_denied",
                        "detail": "Device is revoked.",
                    },
                )
            elif request.url.path == "/api/v1/agent/reports":
                registration_called = True
                return httpx.Response(202, json={})
            return httpx.Response(404)

        client = _make_client(handler)
        runner = ServiceRunner(config=config, poll_interval_seconds=0.05)
        runner.runtime.client = client
        runner.runtime.sync_manager.client = client
        runner.runtime.registration_service.client = client

        # Stop after 1 iteration
        def delayed_stop():
            import time
            time.sleep(0.15)
            runner.stop()

        import threading
        t = threading.Thread(target=delayed_stop)
        t.start()

        runner.run()
        t.join()

        # Proves runtime was paused and registration was NEVER called!
        assert runner.runtime.is_paused is True
        assert registration_called is False

        # Job was preserved
        job = runner.runtime.queue.get_job(enq.job.id)
        assert job is not None
        assert job.status in (JobStatus.VALIDATED.value, JobStatus.RETRY_WAIT.value)

    def test_end_to_end_watcher_to_registration_and_duplicate_events(self, temp_env):
        config, store, watch = temp_env
        server_report_id = str(uuid.uuid4())
        recorded_requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/agent/reports":
                recorded_requests.append({
                    "method": request.method,
                    "path": request.url.path,
                    "idempotency_key": request.headers.get("Idempotency-Key"),
                    "body": json.loads(request.content.decode("utf-8")),
                })
                return httpx.Response(
                    202,
                    json={
                        "report_id": server_report_id,
                        "status": "queued",
                        "duplicate": False,
                        "created_at": "2026-10-15T12:00:00Z",
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        runtime = AgentRuntime(config, credential_store=store, client=client)

        # 1. Create a valid PDF in the watch folder
        pdf_file = watch / "919876543210.pdf"
        valid_pdf_content = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
        pdf_file.write_bytes(valid_pdf_content)

        # 2. Trigger candidate processing through the real runtime watcher candidate callback
        assert runtime.watcher.on_candidate is not None
        enq_res = runtime.watcher.on_candidate(pdf_file)

        assert enq_res is not None
        assert enq_res.is_duplicate is False
        job_id = enq_res.job.id

        # 3. Confirm newly accepted job reaches an eligible status in SQLite queue
        enqueued_job = runtime.queue.get_job(job_id)
        assert enqueued_job is not None
        assert enqueued_job.status in (JobStatus.VALIDATED.value, JobStatus.QUEUED.value)
        assert enqueued_job.status == JobStatus.VALIDATED.value
        assert enqueued_job.recipient_phone_e164 == "+919876543210"
        assert enqueued_job.lease_owner is None

        # 4. Process the job via AgentRuntime.process_next_registration_job()
        processed = runtime.process_next_registration_job()
        assert processed is True

        # 5. Verify the job was claimed and reached the mocked registration endpoint
        assert len(recorded_requests) == 1
        req = recorded_requests[0]
        assert req["body"]["recipient_phone_e164"] == "+919876543210"
        assert req["body"]["document_type"] == "diagnostic_report"
        assert req["idempotency_key"] == enqueued_job.idempotency_key

        # 6. Verify job progressed to METADATA_REGISTERED, stored docflow_report_id, released lease
        registered_job = runtime.queue.get_job(job_id)
        assert registered_job is not None
        assert registered_job.status == JobStatus.METADATA_REGISTERED.value
        assert registered_job.docflow_report_id == server_report_id
        assert registered_job.lease_owner is None
        assert registered_job.cleanup_eligible_at is None

        # 7. Duplicate watcher events: re-run candidate callback on same file
        dup_res = runtime.watcher.on_candidate(pdf_file)
        assert dup_res is not None
        assert dup_res.is_duplicate is True
        assert dup_res.job.id == job_id

        # Database still contains exactly 1 job
        all_jobs = runtime.queue.list_jobs()
        assert len(all_jobs) == 1

        # Audit event records duplicate observation
        events = runtime.queue.list_events(job_id)
        event_types = [e.event_type for e in events]
        assert "duplicate_fingerprint_observed" in event_types

        # 8. Restart / recovery test: simulate an unreleased/expired lease on a new job
        pdf2 = watch / "919876543211.pdf"
        pdf2.write_bytes(valid_pdf_content)
        enq2 = runtime.watcher.on_candidate(pdf2)
        assert enq2 is not None

        past_iso = (datetime.datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with runtime.queue._write_transaction() as conn:
            conn.execute(
                "UPDATE jobs SET lease_owner = 'crashed_worker', lease_expires_at = ? WHERE id = ?;",
                (past_iso, enq2.job.id),
            )

        # Simulate fresh runtime startup recovery
        fresh_runtime = AgentRuntime(config, credential_store=store, client=client)
        recovery_summary = fresh_runtime.startup_recovery()
        assert recovery_summary["recovered_leases"] >= 1

        recovered_job = fresh_runtime.queue.get_job(enq2.job.id)
        assert recovered_job is not None
        assert recovered_job.lease_owner is None

        # Fresh runtime can claim and register the recovered job
        assert fresh_runtime.process_next_registration_job() is True
        assert fresh_runtime.queue.get_job(enq2.job.id).status == JobStatus.METADATA_REGISTERED.value

    def test_runtime_all_token_error_variants_pause_and_preserve_job(self, temp_env):
        import dataclasses
        from docflow_agent.token_manager import (
            TokenError,
            TokenMissingError,
            TokenAuthenticationError,
            TokenReuseConflictError,
            TokenRotationAmbiguousError,
            TokenRateLimitedError,
            TokenValidationError,
            TokenStorageError,
        )
        config, store, watch = temp_env

        error_variants = [
            TokenMissingError("Missing refresh token in credential store", code="token_missing"),
            TokenAuthenticationError("Refresh token revoked", code="authentication_failed"),
            TokenReuseConflictError("Rotated token reuse conflict", code="token_reuse_conflict"),
            TokenRotationAmbiguousError("Ambiguous token rotation outcome"),
            TokenValidationError("Malformed refresh response from server", code="validation_error"),
            TokenStorageError("DPAPI access failed", code="storage_error"),
            TokenError("General token failure", code="token_error"),
        ]

        for i, exc_to_raise in enumerate(error_variants):
            db_path = watch.parent / f"token_hier_{i}.db"
            iter_config = dataclasses.replace(config, db_path=str(db_path))
            queue = JobQueue.from_config(iter_config)
            pdf = watch / f"91987654322{i}.pdf"
            pdf.write_bytes(b"%PDF-1.4 sample")
            val = ValidationResult(
                is_valid=True,
                source_path=pdf,
                source_basename=f"91987654322{i}.pdf",
                recipient_phone_e164=f"+91987654322{i}",
                content_sha256=f"{i:02d}" * 32,
                file_size_bytes=100,
                mtime_ns=100,
            )
            enq = queue.enqueue(val, branch_id=str(uuid.uuid4()))

            call_count = 0

            def handler(request: httpx.Request) -> httpx.Response:
                nonlocal call_count
                call_count += 1
                raise exc_to_raise

            client = _make_client(handler)
            runtime = AgentRuntime(iter_config, credential_store=store, queue=queue, client=client)

            assert runtime.is_paused is False
            processed = runtime.process_next_registration_job()
            assert processed is False
            assert call_count == 1

            # Runtime must be paused
            assert runtime.is_paused is True

            # Job must be preserved in RETRY_WAIT, not FAILED, no terminal cleanup
            job = queue.get_job(enq.job.id)
            assert job is not None
            assert job.status == JobStatus.RETRY_WAIT.value
            assert job.cleanup_eligible_at is None
            assert job.lease_owner is None

            # Subsequent calls do nothing while paused
            assert runtime.process_next_registration_job() is False
            assert call_count == 1

    def test_service_runner_heartbeat_token_missing_and_storage_errors(self, temp_env):
        from docflow_agent.token_manager import TokenMissingError, TokenStorageError
        config, store, watch = temp_env

        for i, exc_to_raise in enumerate([
            TokenMissingError("Missing credentials", code="token_missing"),
            TokenStorageError("Storage error", code="storage_error"),
        ]):
            db_path = watch.parent / f"hb_token_err_{i}.db"
            import dataclasses
            iter_config = dataclasses.replace(config, db_path=str(db_path))
            queue = JobQueue.from_config(iter_config)

            pdf = watch / f"91987654323{i}.pdf"
            pdf.write_bytes(b"%PDF-1.4 sample")
            val = ValidationResult(
                is_valid=True,
                source_path=pdf,
                source_basename=f"91987654323{i}.pdf",
                recipient_phone_e164=f"+91987654323{i}",
                content_sha256=f"{i:02d}" * 32,
                file_size_bytes=100,
                mtime_ns=100,
            )
            enq = queue.enqueue(val, branch_id=str(uuid.uuid4()))

            registration_called = False

            def handler(request: httpx.Request) -> httpx.Response:
                nonlocal registration_called
                if request.url.path == "/api/v1/agent/heartbeat":
                    raise exc_to_raise
                elif request.url.path == "/api/v1/agent/reports":
                    registration_called = True
                    return httpx.Response(202, json={})
                return httpx.Response(404)

            client = _make_client(handler)
            runner = ServiceRunner(config=iter_config, poll_interval_seconds=0.05)
            runner.runtime.client = client
            runner.runtime.sync_manager.client = client
            runner.runtime.registration_service.client = client

            def delayed_stop():
                import time
                time.sleep(0.15)
                runner.stop()

            import threading
            t = threading.Thread(target=delayed_stop)
            t.start()

            runner.run()
            t.join()

            assert runner.runtime.is_paused is True
            assert registration_called is False
            job = runner.runtime.queue.get_job(enq.job.id)
            assert job is not None
            assert job.status in (JobStatus.VALIDATED.value, JobStatus.RETRY_WAIT.value)
