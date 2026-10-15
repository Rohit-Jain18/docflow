"""
Tests for Report Metadata Registration Service.

Covers:
- Metadata-first registration with deterministic Idempotency-Key.
- Data minimization (zero PDF bytes, no file paths or phone filenames in request body).
- State transitions (VALIDATED -> METADATA_REGISTERING -> METADATA_REGISTERED).
- Persistence of server-returned docflow_report_id in SQLite.
- Handling of duplicate registration responses (duplicate: true).
- Handling of account unverified errors (HTTP 422 account_not_verified -> RETRY_WAIT).
- Handling of idempotency conflicts (HTTP 409 -> FAILED).
- Transient network error handling (timeout -> RETRY_WAIT).
- Malformed response validation (fails closed).
"""

from __future__ import annotations

import json
import pathlib
import uuid
import pytest
import httpx

from docflow_agent.client import (
    ApiClient,
    ApiTimeoutError,
    ApiPayloadError,
)
from docflow_agent.pdf import ValidationResult
from docflow_agent.queue import JobQueue, JobStatus, compute_fingerprint
from docflow_agent.registration import (
    ReportRegistrationService,
    RegistrationResult,
    AccountNotVerifiedError,
    RegistrationConflictError,
    RegistrationError,
    REPORT_REGISTRATION_ENDPOINT,
)


@pytest.fixture
def temp_db(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "test_registration.db"


@pytest.fixture
def queue(temp_db: pathlib.Path) -> JobQueue:
    return JobQueue(temp_db)


def _make_client(handler, token: str = "valid-device-token") -> ApiClient:
    return ApiClient(
        base_url="https://api.docflow.test",
        token_provider=lambda: token,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.fixture
def sample_job(queue: JobQueue, tmp_path: pathlib.Path):
    branch_id = str(uuid.uuid4())
    pdf_file = tmp_path / "919876543210.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 sample content")

    val = ValidationResult(
        is_valid=True,
        source_path=pdf_file,
        source_basename="919876543210.pdf",
        recipient_phone_e164="+919876543210",
        content_sha256="e" * 64,
        file_size_bytes=1024,
        mtime_ns=5000000,
    )
    res = queue.enqueue(val, branch_id=branch_id)
    return res.job, branch_id


class TestReportRegistrationService:
    def test_registration_success(self, queue: JobQueue, sample_job):
        job, branch_id = sample_job
        server_report_id = str(uuid.uuid4())
        recorded_req = {}

        def handler(request: httpx.Request) -> httpx.Response:
            recorded_req["method"] = request.method
            recorded_req["path"] = request.url.path
            recorded_req["idempotency_key"] = request.headers.get("Idempotency-Key")
            recorded_req["auth"] = request.headers.get("Authorization")
            recorded_req["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                202,
                json={
                    "report_id": server_report_id,
                    "status": "queued",
                    "duplicate": False,
                    "created_at": "2026-10-15T12:30:00Z",
                },
                headers={"X-Request-ID": "req_reg_01"},
            )

        client = _make_client(handler)
        service = ReportRegistrationService(
            client=client,
            queue=queue,
            branch_id=branch_id,
        )

        res = service.register_job(job)

        assert isinstance(res, RegistrationResult)
        assert res.report_id == server_report_id
        assert res.status == "queued"
        assert res.is_duplicate is False
        assert res.created_at == "2026-10-15T12:30:00Z"

        # Verify request protocol and headers
        assert recorded_req["method"] == "POST"
        assert recorded_req["path"] == REPORT_REGISTRATION_ENDPOINT
        assert recorded_req["auth"] == "Bearer valid-device-token"

        expected_fp = compute_fingerprint(branch_id, job.recipient_phone_e164, job.content_sha256)
        assert recorded_req["idempotency_key"] == expected_fp

        # Data minimization: verify no filenames, local paths, or PDF bytes in payload
        body = recorded_req["body"]
        assert body["recipient_phone_e164"] == "+919876543210"
        assert body["content_sha256"] == "e" * 64
        assert body["file_size_bytes"] == 1024
        assert body["document_type"] == "diagnostic_report"
        assert "source_path" not in body
        assert "source_basename" not in body
        assert "file_name" not in body
        assert "bytes" not in body

        # Verify database state after registration
        updated_job = queue.get_job(job.id)
        assert updated_job is not None
        assert updated_job.status == JobStatus.METADATA_REGISTERED.value
        assert updated_job.docflow_report_id == server_report_id

    def test_registration_duplicate_replay(self, queue: JobQueue, sample_job):
        job, branch_id = sample_job
        server_report_id = str(uuid.uuid4())

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                202,
                json={
                    "report_id": server_report_id,
                    "status": "queued",
                    "duplicate": True,
                    "created_at": "2026-10-15T12:00:00Z",
                },
            )

        client = _make_client(handler)
        service = ReportRegistrationService(client=client, queue=queue, branch_id=branch_id)
        res = service.register_job(job)

        assert res.is_duplicate is True
        assert res.report_id == server_report_id

        updated = queue.get_job(job.id)
        assert updated is not None
        assert updated.status == JobStatus.METADATA_REGISTERED.value
        assert updated.docflow_report_id == server_report_id

    def test_registration_account_not_verified_422(self, queue: JobQueue, sample_job):
        job, branch_id = sample_job

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                json={
                    "type": "about:blank",
                    "title": "Account not verified",
                    "status": 422,
                    "code": "account_not_verified",
                    "detail": "No active WhatsApp sender assignment found for branch.",
                },
            )

        client = _make_client(handler)
        service = ReportRegistrationService(client=client, queue=queue, branch_id=branch_id)

        with pytest.raises(AccountNotVerifiedError):
            service.register_job(job)

        updated = queue.get_job(job.id)
        assert updated is not None
        assert updated.status == JobStatus.RETRY_WAIT.value
        assert updated.last_error_code == "account_not_verified"

    def test_registration_idempotency_conflict_409(self, queue: JobQueue, sample_job):
        job, branch_id = sample_job

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                409,
                json={
                    "type": "about:blank",
                    "title": "State conflict",
                    "status": 409,
                    "code": "idempotency_conflict",
                    "detail": "Supplied Idempotency-Key does not match the canonical fingerprint.",
                },
            )

        client = _make_client(handler)
        service = ReportRegistrationService(client=client, queue=queue, branch_id=branch_id)

        with pytest.raises(RegistrationConflictError):
            service.register_job(job)

        updated = queue.get_job(job.id)
        assert updated is not None
        assert updated.status == JobStatus.FAILED.value
        assert updated.last_error_code == "idempotency_conflict"

    def test_registration_network_timeout(self, queue: JobQueue, sample_job):
        job, branch_id = sample_job

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Connection dropped")

        client = _make_client(handler)
        service = ReportRegistrationService(client=client, queue=queue, branch_id=branch_id)

        with pytest.raises(ApiTimeoutError):
            service.register_job(job)

        updated = queue.get_job(job.id)
        assert updated is not None
        assert updated.status == JobStatus.RETRY_WAIT.value
        assert updated.last_error_code == "network_timeout"

    def test_registration_malformed_response_missing_report_id(self, queue: JobQueue, sample_job):
        job, branch_id = sample_job

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                202,
                json={
                    "status": "queued",
                    "created_at": "2026-10-15T12:00:00Z",
                    # Missing report_id
                },
            )

        client = _make_client(handler)
        service = ReportRegistrationService(client=client, queue=queue, branch_id=branch_id)

        with pytest.raises(ApiPayloadError):
            service.register_job(job)

    def test_registration_invalid_starting_state(self, queue: JobQueue, sample_job):
        job, branch_id = sample_job
        # Move job to terminal failed
        queue.update_status(job.id, JobStatus.FAILED)
        failed_job = queue.get_job(job.id)
        assert failed_job is not None

        client = _make_client(lambda r: httpx.Response(200))
        service = ReportRegistrationService(client=client, queue=queue, branch_id=branch_id)

        with pytest.raises(RegistrationError):
            service.register_job(failed_job)

    def test_registration_from_queued_starting_state(self, queue: JobQueue, sample_job):
        job, branch_id = sample_job
        queue.update_status(job.id, JobStatus.QUEUED)
        queued_job = queue.get_job(job.id)
        assert queued_job is not None
        assert queued_job.status == JobStatus.QUEUED.value

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
        service = ReportRegistrationService(client=client, queue=queue, branch_id=branch_id)

        res = service.register_job(queued_job)
        assert res.report_id == server_report_id
        updated = queue.get_job(job.id)
        assert updated is not None
        assert updated.status == JobStatus.METADATA_REGISTERED.value


    @pytest.mark.parametrize(
        "invalid_body,error_substr",
        [
            (
                {"report_id": str(uuid.uuid4()), "status": "pending", "duplicate": False, "created_at": "2026-10-15T12:00:00Z"},
                "expected 'queued'",
            ),
            (
                {"report_id": "not-a-valid-uuid", "status": "queued", "duplicate": False, "created_at": "2026-10-15T12:00:00Z"},
                "valid UUID",
            ),
            (
                {"report_id": str(uuid.uuid4()), "status": "queued", "duplicate": 1, "created_at": "2026-10-15T12:00:00Z"},
                "valid boolean 'duplicate'",
            ),
            (
                {"report_id": str(uuid.uuid4()), "status": "queued", "duplicate": "true", "created_at": "2026-10-15T12:00:00Z"},
                "valid boolean 'duplicate'",
            ),
            (
                {"report_id": str(uuid.uuid4()), "status": "queued", "duplicate": False, "created_at": "2026-10-15T12:00:00+05:30"},
                "valid UTC Z 'created_at'",
            ),
            (
                {"report_id": str(uuid.uuid4()), "status": "queued", "duplicate": False, "created_at": "2026-02-31T12:00:00Z"},
                "calendar-valid UTC timestamp",
            ),
        ],
    )
    def test_registration_strict_validation_invalid_fields(
        self, queue: JobQueue, sample_job, invalid_body: dict, error_substr: str
    ):
        job, branch_id = sample_job

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(202, json=invalid_body)

        client = _make_client(handler)
        service = ReportRegistrationService(client=client, queue=queue, branch_id=branch_id)

        with pytest.raises(ApiPayloadError) as exc_info:
            service.register_job(job)

        assert error_substr in str(exc_info.value)
        # Job must be kept in RETRY_WAIT, NOT marked FAILED!
        updated = queue.get_job(job.id)
        assert updated is not None
        assert updated.status == JobStatus.RETRY_WAIT.value
        assert updated.last_error_code == "malformed_registration_response"

    def test_registration_canary_sanitization(
        self, queue: JobQueue, sample_job, caplog: pytest.LogCaptureFixture
    ):
        import logging
        job, branch_id = sample_job
        canary_report_id = "CANARY_REPORT_ID_SECRET_+919876543210"
        canary_status = "CANARY_STATUS_PATIENT_DO_NOT_LEAK"
        canary_created_at = "CANARY_CREATED_AT_CONFIDENTIAL"

        for field, canary_val in [
            ("report_id", canary_report_id),
            ("status", canary_status),
            ("created_at", canary_created_at),
        ]:
            body = {
                "report_id": str(uuid.uuid4()),
                "status": "queued",
                "duplicate": False,
                "created_at": "2026-10-15T12:00:00Z",
            }
            body[field] = canary_val

            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(202, json=body)

            client = _make_client(handler)
            service = ReportRegistrationService(client=client, queue=queue, branch_id=branch_id)

            caplog.clear()
            with caplog.at_level(logging.DEBUG):
                with pytest.raises(ApiPayloadError) as exc_info:
                    service.register_job(job)

            assert canary_val not in str(exc_info.value)
            assert canary_val not in repr(exc_info.value)
            assert canary_val not in caplog.text

    def test_registration_malformed_response_followed_by_duplicate_recovery(
        self, queue: JobQueue, sample_job
    ):
        job, branch_id = sample_job
        expected_report_id = str(uuid.uuid4())
        initial_key = job.idempotency_key

        responses = [
            # First attempt: backend registered the report, but returned malformed payload (missing duplicate)
            httpx.Response(
                202,
                json={
                    "report_id": expected_report_id,
                    "status": "queued",
                    "created_at": "2026-10-15T12:00:00Z",
                    # duplicate field missing entirely!
                },
            ),
            # Second attempt: resending exact same request returns duplicate: True with valid payload
            httpx.Response(
                202,
                json={
                    "report_id": expected_report_id,
                    "status": "queued",
                    "duplicate": True,
                    "created_at": "2026-10-15T12:00:00Z",
                },
            ),
        ]

        attempt = 0
        captured_keys = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempt
            captured_keys.append(request.headers.get("Idempotency-Key"))
            resp = responses[attempt]
            attempt += 1
            return resp

        client = _make_client(handler)
        service = ReportRegistrationService(client=client, queue=queue, branch_id=branch_id)

        # First call fails closed on malformed response
        with pytest.raises(ApiPayloadError):
            service.register_job(job)

        # Job is preserved in RETRY_WAIT, not FAILED
        job_after_fail = queue.get_job(job.id)
        assert job_after_fail is not None
        assert job_after_fail.status == JobStatus.RETRY_WAIT.value
        assert job_after_fail.idempotency_key == initial_key

        # Second call retries with the same job and succeeds!
        res = service.register_job(job_after_fail)
        assert res.report_id == expected_report_id
        assert res.is_duplicate is True

        # Job is now successfully METADATA_REGISTERED
        job_after_recovery = queue.get_job(job.id)
        assert job_after_recovery is not None
        assert job_after_recovery.status == JobStatus.METADATA_REGISTERED.value
        assert job_after_recovery.docflow_report_id == expected_report_id

        # Prove identical idempotency key was sent both times
        assert len(captured_keys) == 2
        assert captured_keys[0] == captured_keys[1] == initial_key

    def test_registration_403_raises_device_revoked_and_preserves_job(
        self, queue: JobQueue, sample_job
    ):
        from docflow_agent.sync import DeviceRevokedError
        job, branch_id = sample_job

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                json={
                    "type": "about:blank",
                    "title": "Forbidden",
                    "status": 403,
                    "code": "permission_denied",
                    "detail": "Device or branch is inactive.",
                },
            )

        client = _make_client(handler)
        service = ReportRegistrationService(client=client, queue=queue, branch_id=branch_id)

        with pytest.raises(DeviceRevokedError):
            service.register_job(job)

        updated = queue.get_job(job.id)
        assert updated is not None
        assert updated.status == JobStatus.RETRY_WAIT.value
        assert updated.last_error_code == "device_revoked"
        # Must not arm cleanup eligibility
        assert updated.cleanup_eligible_at is None

    def test_registration_token_errors_preserve_job(
        self, queue: JobQueue, sample_job
    ):
        from docflow_agent.token_manager import (
            TokenAuthenticationError,
            TokenReuseConflictError,
            TokenRotationAmbiguousError,
            TokenRateLimitedError,
        )
        job, branch_id = sample_job

        for exc_to_raise in [
            TokenAuthenticationError("token_authentication_failed"),
            TokenReuseConflictError("token_reuse_detected"),
            TokenRotationAmbiguousError("Ambiguous token rotation outcome"),
            TokenRateLimitedError("Rate limited", retry_after=45),
        ]:
            def handler(request: httpx.Request) -> httpx.Response:
                raise exc_to_raise

            client = _make_client(handler)
            service = ReportRegistrationService(client=client, queue=queue, branch_id=branch_id)

            # Move job back to VALIDATED
            queue.update_status(job.id, JobStatus.VALIDATED)
            current_job = queue.get_job(job.id)

            with pytest.raises(type(exc_to_raise)):
                service.register_job(current_job)

            updated = queue.get_job(job.id)
            assert updated is not None
            assert updated.status == JobStatus.RETRY_WAIT.value
            assert updated.cleanup_eligible_at is None
