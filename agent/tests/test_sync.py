"""
Tests for Heartbeat and Configuration Synchronization Service.

Covers:
- Heartbeat telemetry payload generation and queue counts.
- ISO 8601 UTC timestamp validation (strict 'Z' suffix).
- Device status checking and fail-closed handling of revoked/inactive devices (403).
- Remote configuration validation and rejection of dangerous/prohibited keys.
- Version-driven synchronization (skips redundant config fetches).
- Zero secret, token, or patient PII exposure in logs, error messages, and representations.
"""

from __future__ import annotations

import json
import logging
import pathlib
import uuid
import pytest
import httpx

from docflow_agent.client import (
    ApiClient,
    ApiPermissionError,
    ApiPayloadError,
)
from docflow_agent.pdf import ValidationResult
from docflow_agent.queue import JobQueue, JobStatus
from docflow_agent.sync import (
    HeartbeatService,
    ConfigSyncService,
    DeviceSyncManager,
    HeartbeatResult,
    RemoteConfig,
    DeviceRevokedError,
    ConfigValidationError,
    parse_remote_config,
)


@pytest.fixture
def temp_db(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "test_sync.db"


@pytest.fixture
def queue(temp_db: pathlib.Path) -> JobQueue:
    return JobQueue(temp_db)


def _make_client(handler, token: str = "valid-bearer-token") -> ApiClient:
    return ApiClient(
        base_url="https://api.docflow.test",
        token_provider=lambda: token,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


class TestHeartbeatService:
    def test_heartbeat_payload_and_success(self, queue: JobQueue):
        installation_id = str(uuid.uuid4())
        recorded_request = {}

        def handler(request: httpx.Request) -> httpx.Response:
            recorded_request["method"] = request.method
            recorded_request["path"] = request.url.path
            recorded_request["auth"] = request.headers.get("Authorization")
            recorded_request["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "server_time": "2026-10-15T12:00:00Z",
                    "configuration_version": 2,
                    "device_status": "active",
                },
                headers={"X-Request-ID": "req_hb_01"},
            )

        client = _make_client(handler)

        service = HeartbeatService(
            client=client,
            queue=queue,
            installation_id=installation_id,
            agent_version="0.2.1",
        )

        res = service.send_heartbeat(service_state="running")

        assert isinstance(res, HeartbeatResult)
        assert res.server_time == "2026-10-15T12:00:00Z"
        assert res.configuration_version == 2
        assert res.device_status == "active"
        assert res.is_active is True

        assert recorded_request["method"] == "POST"
        assert recorded_request["path"] == "/api/v1/agent/heartbeat"
        assert recorded_request["auth"] == "Bearer valid-bearer-token"
        assert recorded_request["body"]["agent_version"] == "0.2.1"
        assert recorded_request["body"]["installation_id"] == installation_id
        assert recorded_request["body"]["service_state"] == "running"
        assert recorded_request["body"]["queue_counts"] == {
            "queued": 0,
            "retry_wait": 0,
            "quarantined": 0,
        }

    def test_heartbeat_queue_counts_and_last_job(self, queue: JobQueue, tmp_path: pathlib.Path):
        installation_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())

        # Enqueue 2 validated jobs
        f1 = tmp_path / "919876543210.pdf"
        f1.write_bytes(b"%PDF-1.4 sample")
        res1 = queue.enqueue(
            ValidationResult(
                is_valid=True,
                source_path=f1,
                source_basename="919876543210.pdf",
                recipient_phone_e164="+919876543210",
                content_sha256="a" * 64,
                file_size_bytes=100,
                mtime_ns=1000,
            ),
            branch_id=branch_id,
        )

        f2 = tmp_path / "919876543211.pdf"
        f2.write_bytes(b"%PDF-1.4 sample")
        res2 = queue.enqueue(
            ValidationResult(
                is_valid=True,
                source_path=f2,
                source_basename="919876543211.pdf",
                recipient_phone_e164="+919876543211",
                content_sha256="b" * 64,
                file_size_bytes=200,
                mtime_ns=2000,
            ),
            branch_id=branch_id,
        )

        # Move one job to retry_wait (valid from validated)
        queue.update_status(res1.job.id, JobStatus.RETRY_WAIT)

        # Move second job to quarantined (valid from validated)
        queue.update_status(res2.job.id, JobStatus.QUARANTINED)

        # Add third job in validated state (counted in queued)
        f3 = tmp_path / "919876543212.pdf"
        f3.write_bytes(b"%PDF-1.4 sample")
        queue.enqueue(
            ValidationResult(
                is_valid=True,
                source_path=f3,
                source_basename="919876543212.pdf",
                recipient_phone_e164="+919876543212",
                content_sha256="c" * 64,
                file_size_bytes=300,
                mtime_ns=3000,
            ),
            branch_id=branch_id,
        )

        recorded_counts = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            recorded_counts.update(body["queue_counts"])
            return httpx.Response(
                200,
                json={
                    "server_time": "2026-10-15T12:00:00Z",
                    "configuration_version": 1,
                    "device_status": "active",
                },
            )

        client = _make_client(handler)

        service = HeartbeatService(
            client=client,
            queue=queue,
            installation_id=installation_id,
        )

        service.send_heartbeat()
        assert recorded_counts["queued"] == 1
        assert recorded_counts["retry_wait"] == 1
        assert recorded_counts["quarantined"] == 1

    def test_heartbeat_device_revoked_403_raises_error(self, queue: JobQueue):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                json={
                    "type": "about:blank",
                    "title": "Forbidden",
                    "status": 403,
                    "code": "permission_denied",
                    "detail": "Device organization or branch is inactive.",
                },
            )

        client = _make_client(handler)

        service = HeartbeatService(
            client=client,
            queue=queue,
            installation_id=str(uuid.uuid4()),
        )

        with pytest.raises(DeviceRevokedError) as exc_info:
            service.send_heartbeat()

        assert exc_info.value.status_code == 403
        assert exc_info.value.code == "permission_denied"

    def test_heartbeat_device_status_inactive_raises_revoked_error(self, queue: JobQueue):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "server_time": "2026-10-15T12:00:00Z",
                    "configuration_version": 1,
                    "device_status": "revoked",
                },
            )

        client = _make_client(handler)

        service = HeartbeatService(
            client=client,
            queue=queue,
            installation_id=str(uuid.uuid4()),
        )

        with pytest.raises(DeviceRevokedError) as exc_info:
            service.send_heartbeat()

        assert "revoked" in str(exc_info.value)

    def test_heartbeat_malformed_timestamp_fails_closed(self, queue: JobQueue):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "server_time": "2026-10-15 12:00:00",  # missing T and Z
                    "configuration_version": 1,
                    "device_status": "active",
                },
            )

        client = _make_client(handler)

        service = HeartbeatService(
            client=client,
            queue=queue,
            installation_id=str(uuid.uuid4()),
        )

        with pytest.raises(ApiPayloadError):
            service.send_heartbeat()


class TestConfigSyncService:
    def test_parse_remote_config_valid(self):
        device_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())
        payload = {
            "device_id": device_id,
            "branch_id": branch_id,
            "configuration_version": 3,
            "watch_folder_policy": "locally_configured",
            "filename_pattern": "phone_number.pdf",
            "default_phone_region": "IN",
            "stability_sample_seconds": 2,
            "stability_required_samples": 3,
            "stability_timeout_seconds": 120,
            "max_pdf_size_bytes": 52428800,
            "archive_policy": "after_provider_accepted",
            "quarantine_policy": "move_invalid_files",
        }

        cfg = parse_remote_config(payload)
        assert cfg.device_id == device_id
        assert cfg.branch_id == branch_id
        assert cfg.configuration_version == 3
        assert cfg.default_phone_region == "IN"
        assert cfg.stability_sample_seconds == 2
        assert cfg.max_pdf_size_bytes == 52428800

    def test_parse_remote_config_rejects_forbidden_keys(self):
        payload = {
            "device_id": str(uuid.uuid4()),
            "branch_id": str(uuid.uuid4()),
            "configuration_version": 1,
            "default_phone_region": "IN",
            "stability_sample_seconds": 2,
            "stability_required_samples": 3,
            "stability_timeout_seconds": 120,
            "max_pdf_size_bytes": 52428800,
            # Security attack: trying to redirect API base URL or inject tokens
            "api_base_url": "https://malicious.test",
        }
        with pytest.raises(ConfigValidationError) as exc_info:
            parse_remote_config(payload)
        assert "forbidden security-sensitive keys" in str(exc_info.value)

    def test_parse_remote_config_rejects_out_of_range_values(self):
        payload = {
            "device_id": str(uuid.uuid4()),
            "branch_id": str(uuid.uuid4()),
            "configuration_version": 1,
            "default_phone_region": "IN",
            "stability_sample_seconds": 9999,  # out of range (1-60)
            "stability_required_samples": 3,
            "stability_timeout_seconds": 120,
            "max_pdf_size_bytes": 52428800,
        }
        with pytest.raises(ConfigValidationError) as exc_info:
            parse_remote_config(payload)
        assert "stability_sample_seconds" in str(exc_info.value)

    def test_fetch_and_apply_persists_settings(self, queue: JobQueue):
        device_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/v1/agent/config"
            return httpx.Response(
                200,
                json={
                    "device_id": device_id,
                    "branch_id": branch_id,
                    "configuration_version": 5,
                    "watch_folder_policy": "locally_configured",
                    "filename_pattern": "phone_number.pdf",
                    "default_phone_region": "IN",
                    "stability_sample_seconds": 3,
                    "stability_required_samples": 4,
                    "stability_timeout_seconds": 150,
                    "max_pdf_size_bytes": 20000000,
                    "archive_policy": "after_provider_accepted",
                    "quarantine_policy": "move_invalid_files",
                },
            )

        client = _make_client(handler)

        service = ConfigSyncService(client=client, queue=queue)
        applied = service.fetch_and_apply()

        assert applied.configuration_version == 5
        assert queue.get_setting("remote_config_version") == "5"
        assert queue.get_setting("server_device_id") == device_id
        assert queue.get_setting("server_branch_id") == branch_id
        assert queue.get_setting("stability_sample_seconds") == "3"
        assert queue.get_setting("max_pdf_size_bytes") == "20000000"


class TestDeviceSyncManager:
    def test_sync_advances_config_when_version_increases(self, queue: JobQueue):
        installation_id = str(uuid.uuid4())
        device_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/api/v1/agent/heartbeat":
                return httpx.Response(
                    200,
                    json={
                        "server_time": "2026-10-15T12:00:00Z",
                        "configuration_version": 2,
                        "device_status": "active",
                    },
                )
            elif request.url.path == "/api/v1/agent/config":
                return httpx.Response(
                    200,
                    json={
                        "device_id": device_id,
                        "branch_id": branch_id,
                        "configuration_version": 2,
                        "watch_folder_policy": "locally_configured",
                        "filename_pattern": "phone_number.pdf",
                        "default_phone_region": "IN",
                        "stability_sample_seconds": 2,
                        "stability_required_samples": 3,
                        "stability_timeout_seconds": 120,
                        "max_pdf_size_bytes": 52428800,
                        "archive_policy": "after_provider_accepted",
                        "quarantine_policy": "move_invalid_files",
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)

        manager = DeviceSyncManager(
            client=client,
            queue=queue,
            installation_id=installation_id,
        )

        # Initial state: persisted config version is 0
        assert manager.config_service.get_persisted_version() == 0

        # Perform sync
        res = manager.perform_sync()
        assert res.configuration_version == 2

        # Both heartbeat and config endpoints were called
        assert "/api/v1/agent/heartbeat" in calls
        assert "/api/v1/agent/config" in calls

        # Persisted version is now 2
        assert manager.config_service.get_persisted_version() == 2

    def test_sync_skips_config_fetch_when_version_unchanged(self, queue: JobQueue):
        installation_id = str(uuid.uuid4())
        calls = []

        # Pre-set persisted config version to 2
        queue.set_setting("remote_config_version", "2")

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(
                200,
                json={
                    "server_time": "2026-10-15T12:00:00Z",
                    "configuration_version": 2,  # Same version as persisted
                    "device_status": "active",
                },
            )

        client = _make_client(handler)

        manager = DeviceSyncManager(
            client=client,
            queue=queue,
            installation_id=installation_id,
        )

        res = manager.perform_sync()
        assert res.configuration_version == 2
        # Only heartbeat was called; config was skipped!
        assert calls == ["/api/v1/agent/heartbeat"]

    def test_heartbeat_canary_sanitization(self, queue: JobQueue, caplog: pytest.LogCaptureFixture):
        import sqlite3
        canary_status = "CANARY_STATUS_+919876543210_PATIENT_DO_NOT_LEAK"
        canary_time = "CANARY_TIME_REPORT_DATA_SECRET"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "server_time": canary_time,
                    "configuration_version": 1,
                    "device_status": canary_status,
                },
            )

        client = _make_client(handler)
        service = HeartbeatService(client=client, queue=queue, installation_id=str(uuid.uuid4()))

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(Exception) as exc_info:
                service.send_heartbeat()

        exc_str = str(exc_info.value)
        exc_repr = repr(exc_info.value)
        log_text = caplog.text

        assert canary_time not in exc_str
        assert canary_time not in exc_repr
        assert canary_time not in log_text

        # Also test canary status when server_time is valid
        def handler_status(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "server_time": "2026-10-15T12:00:00Z",
                    "configuration_version": 1,
                    "device_status": canary_status,
                },
            )

        client2 = _make_client(handler_status)
        service2 = HeartbeatService(client=client2, queue=queue, installation_id=str(uuid.uuid4()))

        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(DeviceRevokedError) as exc_info2:
                service2.send_heartbeat()

        assert canary_status not in str(exc_info2.value)
        assert canary_status not in repr(exc_info2.value)
        assert canary_status not in caplog.text

    def test_config_sync_canary_sanitization(self, caplog: pytest.LogCaptureFixture):
        canary_region = "CANARY_REGION_+919876543210_PATIENT_ID_SECRET"
        payload = {
            "device_id": str(uuid.uuid4()),
            "branch_id": str(uuid.uuid4()),
            "configuration_version": 1,
            "default_phone_region": canary_region,
            "stability_sample_seconds": 2,
            "stability_required_samples": 3,
            "stability_timeout_seconds": 120,
            "max_pdf_size_bytes": 52428800,
        }
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(ConfigValidationError) as exc_info:
                parse_remote_config(payload)

        assert canary_region not in str(exc_info.value)
        assert canary_region not in repr(exc_info.value)
        assert canary_region not in caplog.text

    def test_fetch_and_apply_atomic_failure_retains_previous_settings(self, queue: JobQueue, monkeypatch):
        import sqlite3
        queue.set_settings_atomic({
            "remote_config_version": "1",
            "stability_sample_seconds": "2",
            "max_pdf_size_bytes": "10000000",
        })
        assert queue.get_setting("remote_config_version") == "1"
        assert queue.get_setting("stability_sample_seconds") == "2"

        device_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "device_id": device_id,
                    "branch_id": branch_id,
                    "configuration_version": 2,
                    "default_phone_region": "IN",
                    "stability_sample_seconds": 5,
                    "stability_required_samples": 4,
                    "stability_timeout_seconds": 150,
                    "max_pdf_size_bytes": 20000000,
                },
            )

        client = _make_client(handler)
        service = ConfigSyncService(client=client, queue=queue)

        def failing_atomic(settings_dict):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(queue, "set_settings_atomic", failing_atomic)

        applied_called = []
        with pytest.raises(sqlite3.OperationalError):
            service.fetch_and_apply(on_applied=lambda cfg: applied_called.append(cfg))

        assert len(applied_called) == 0
        assert queue.get_setting("remote_config_version") == "1"
        assert queue.get_setting("stability_sample_seconds") == "2"
        assert queue.get_setting("max_pdf_size_bytes") == "10000000"

    def test_fetch_and_apply_malformed_config_retains_previous_settings(self, queue: JobQueue):
        queue.set_settings_atomic({
            "remote_config_version": "1",
            "stability_sample_seconds": "2",
        })

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "device_id": "bad-uuid",
                    "configuration_version": "not-an-int",
                },
            )

        client = _make_client(handler)
        service = ConfigSyncService(client=client, queue=queue)

        applied_called = []
        with pytest.raises(Exception):
            service.fetch_and_apply(on_applied=lambda cfg: applied_called.append(cfg))

        assert len(applied_called) == 0
        assert queue.get_setting("remote_config_version") == "1"
        assert queue.get_setting("stability_sample_seconds") == "2"

    def test_sync_manager_updates_live_candidate_processing_callback(self, queue: JobQueue):
        installation_id = str(uuid.uuid4())
        device_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())

        applied_configs = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/agent/heartbeat":
                return httpx.Response(
                    200,
                    json={
                        "server_time": "2026-10-15T12:00:00Z",
                        "configuration_version": 3,
                        "device_status": "active",
                    },
                )
            elif request.url.path == "/api/v1/agent/config":
                return httpx.Response(
                    200,
                    json={
                        "device_id": device_id,
                        "branch_id": branch_id,
                        "configuration_version": 3,
                        "default_phone_region": "IN",
                        "stability_sample_seconds": 4,
                        "stability_required_samples": 5,
                        "stability_timeout_seconds": 180,
                        "max_pdf_size_bytes": 10485760,
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        manager = DeviceSyncManager(
            client=client,
            queue=queue,
            installation_id=installation_id,
            on_config_applied=lambda cfg: applied_configs.append(cfg),
        )

        manager.perform_sync()
        assert len(applied_configs) == 1
        assert applied_configs[0].configuration_version == 3
        assert applied_configs[0].max_pdf_size_bytes == 10485760
        assert queue.get_setting("remote_config_version") == "3"
