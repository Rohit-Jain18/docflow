"""
Tests for Docflow Agent Configuration, Heartbeat, and Report Registration APIs (Phase 1, Task 3G).

Covers:
  - GET  /api/v1/agent/config
  - POST /api/v1/agent/heartbeat
  - POST /api/v1/agent/reports

Validates:
  - DeviceBearerAuthentication enforcement and rejection of revoked/disabled devices.
  - Configuration retrieval with server-derived identities and safe defaults.
  - Heartbeat telemetry parsing, strict validation of queue counts and service state, and device updates.
  - Report registration with required 64 lowercase hex Idempotency-Key matching canonical fingerprint.
  - Strict rejection of forbidden fields (file_name, local paths, media URLs, PDF bytes, tenant IDs).
  - Branch WhatsApp sender eligibility checks (422 account_not_verified for missing/unverified/disabled).
  - Production fail-closed enforcement when sender relies on dev verification override.
  - Atomic idempotency: duplicate replay (202 duplicate: true), payload mismatch (409), key mismatch (409).
  - Concurrent race condition recovery without 500 internal server error.
  - Data minimization and zero secret leakage.
"""

import hashlib
import uuid
from django.core.cache import cache
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone as tz_utils
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditAction, AuditEvent
from apps.devices.models import Device, DeviceStatus
from apps.devices.services import generate_access_token
from apps.reports.models import Report, ReportStatus
from apps.tenants.models import (
    Branch,
    BranchStatus,
    Lab,
    LabStatus,
    Organization,
    OrganizationStatus,
)
from apps.whatsapp.models import (
    AssignmentStatus,
    BranchWhatsAppAssignment,
    WhatsAppAccount,
    WhatsAppAccountStatus,
)


class AgentEndpointsBaseTestCase(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

        # Organization A
        self.org_a = Organization.objects.create(
            name="Alpha Labs Org",
            slug="alpha-labs",
            status=OrganizationStatus.ACTIVE,
        )
        self.lab_a = Lab.objects.create(
            organization=self.org_a,
            name="Alpha Central Lab",
            code="LAB-A",
            status=LabStatus.ACTIVE,
        )
        self.branch_a = Branch.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            name="Alpha North Branch",
            code="BR-A1",
            status=BranchStatus.ACTIVE,
        )
        self.device_a = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            name="Workstation A1",
            status=DeviceStatus.ACTIVE,
            agent_version="1.0.0",
        )

        # Inactive Device / Org / Branch
        self.device_revoked = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            name="Revoked Workstation",
            status=DeviceStatus.REVOKED,
            revoked_at=tz_utils.now(),
        )
        self.device_disabled = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            name="Disabled Workstation",
            status=DeviceStatus.DISABLED,
        )

        # Organization B
        self.org_b = Organization.objects.create(
            name="Beta Labs Org",
            slug="beta-labs",
            status=OrganizationStatus.ACTIVE,
        )
        self.lab_b = Lab.objects.create(
            organization=self.org_b,
            name="Beta Central Lab",
            code="LAB-B",
            status=LabStatus.ACTIVE,
        )
        self.branch_b = Branch.objects.create(
            organization=self.org_b,
            lab=self.lab_b,
            name="Beta South Branch",
            code="BR-B1",
            status=BranchStatus.ACTIVE,
        )
        self.device_b = Device.objects.create(
            organization=self.org_b,
            branch=self.branch_b,
            name="Workstation B1",
            status=DeviceStatus.ACTIVE,
            agent_version="1.0.0",
        )

        # WhatsApp Accounts and Assignments
        self.whatsapp_account_a_verified = WhatsAppAccount.objects.create(
            organization=self.org_a,
            display_name="Alpha Sender Verified",
            phone_number_id="PN-A-VERIFIED",
            display_phone_number="+15550001",
            provider_key="kiziee",
            status=WhatsAppAccountStatus.VERIFIED,
            verified_at=tz_utils.now(),
        )
        self.assignment_a = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.whatsapp_account_a_verified,
            status=AssignmentStatus.ACTIVE,
        )

        self.whatsapp_account_b_verified = WhatsAppAccount.objects.create(
            organization=self.org_b,
            display_name="Beta Sender Verified",
            phone_number_id="PN-B-VERIFIED",
            display_phone_number="+15550002",
            provider_key="kiziee",
            status=WhatsAppAccountStatus.VERIFIED,
            verified_at=tz_utils.now(),
        )
        self.assignment_b = BranchWhatsAppAssignment.objects.create(
            organization=self.org_b,
            branch=self.branch_b,
            whatsapp_account=self.whatsapp_account_b_verified,
            status=AssignmentStatus.ACTIVE,
        )

        # Generate tokens
        self.token_a, _ = generate_access_token(device=self.device_a)
        self.token_revoked, _ = generate_access_token(device=self.device_revoked)
        self.token_disabled, _ = generate_access_token(device=self.device_disabled)
        self.token_b, _ = generate_access_token(device=self.device_b)

        self.client = APIClient()

    def auth_headers(self, token, **extra):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        headers.update(extra)
        return headers


# ===========================================================================
# 1. Agent Config Tests (GET /api/v1/agent/config)
# ===========================================================================


class AgentConfigTests(AgentEndpointsBaseTestCase):
    def test_unauthenticated_request_rejected(self):
        response = self.client.get("/api/v1/agent/config")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_revoked_device_rejected(self):
        headers = self.auth_headers(self.token_revoked)
        response = self.client.get("/api/v1/agent/config", **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_disabled_device_rejected(self):
        headers = self.auth_headers(self.token_disabled)
        response = self.client.get("/api/v1/agent/config", **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_active_device_receives_documented_config(self):
        headers = self.auth_headers(self.token_a, HTTP_X_REQUEST_ID="cfg-req-001")
        response = self.client.get("/api/v1/agent/config", **headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.headers.get("X-Request-ID"), "cfg-req-001")

        data = response.data
        self.assertEqual(data["device_id"], str(self.device_a.id))
        self.assertEqual(data["branch_id"], str(self.branch_a.id))
        self.assertEqual(data["configuration_version"], 1)
        self.assertEqual(data["watch_folder_policy"], "locally_configured")
        self.assertEqual(data["filename_pattern"], "phone_number.pdf")
        self.assertEqual(data["default_phone_region"], "IN")
        self.assertEqual(data["stability_sample_seconds"], 2)
        self.assertEqual(data["stability_required_samples"], 3)
        self.assertEqual(data["stability_timeout_seconds"], 120)
        self.assertEqual(data["max_pdf_size_bytes"], 52428800)
        self.assertEqual(data["archive_policy"], "after_provider_accepted")
        self.assertEqual(data["quarantine_policy"], "move_invalid_files")

        # Zero secret or token exposure
        self.assertNotIn("token", data)
        self.assertNotIn("secret", data)
        self.assertNotIn("credentials", data)

    def test_inactive_organization_returns_403(self):
        self.org_a.status = OrganizationStatus.SUSPENDED
        self.org_a.save(update_fields=["status"])

        headers = self.auth_headers(self.token_a)
        response = self.client.get("/api/v1/agent/config", **headers)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ===========================================================================
# 2. Agent Heartbeat Tests (POST /api/v1/agent/heartbeat)
# ===========================================================================


class AgentHeartbeatTests(AgentEndpointsBaseTestCase):
    def test_unauthenticated_heartbeat_rejected(self):
        response = self.client.post("/api/v1/agent/heartbeat", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_revoked_device_heartbeat_rejected(self):
        headers = self.auth_headers(self.token_revoked)
        payload = {
            "agent_version": "1.0.1",
            "installation_id": "inst-1234",
            "service_state": "running",
            "queue_counts": {"queued": 0, "retry_wait": 0, "quarantined": 0},
        }
        response = self.client.post("/api/v1/agent/heartbeat", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_valid_heartbeat_updates_device_telemetry(self):
        headers = self.auth_headers(self.token_a, HTTP_X_REQUEST_ID="hb-req-111", REMOTE_ADDR="192.168.1.100")
        payload = {
            "agent_version": "1.2.3",
            "installation_id": "install-abc-xyz",
            "service_state": "running",
            "queue_counts": {
                "queued": 5,
                "retry_wait": 2,
                "quarantined": 1,
            },
            "last_successful_job_at": "2026-10-12T10:10:00Z",
        }
        response = self.client.post("/api/v1/agent/heartbeat", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.headers.get("X-Request-ID"), "hb-req-111")

        data = response.data
        self.assertIn("server_time", data)
        self.assertEqual(data["configuration_version"], 1)
        self.assertEqual(data["device_status"], "active")

        # Invariant: Device updated in DB
        self.device_a.refresh_from_db()
        self.assertEqual(self.device_a.agent_version, "1.2.3")
        self.assertEqual(self.device_a.last_ip, "192.168.1.100")
        self.assertIsNotNone(self.device_a.last_seen_at)

    def test_heartbeat_rejects_negative_queue_counts(self):
        headers = self.auth_headers(self.token_a)
        payload = {
            "agent_version": "1.0.0",
            "installation_id": "inst-1",
            "service_state": "running",
            "queue_counts": {
                "queued": -1,
                "retry_wait": 0,
                "quarantined": 0,
            },
        }
        response = self.client.post("/api/v1/agent/heartbeat", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

    def test_heartbeat_rejects_unknown_fields_in_root(self):
        headers = self.auth_headers(self.token_a)
        payload = {
            "agent_version": "1.0.0",
            "installation_id": "inst-1",
            "service_state": "running",
            "queue_counts": {"queued": 0, "retry_wait": 0, "quarantined": 0},
            "unauthorized_field": "injected",
            "organization_id": str(self.org_b.id),
        }
        response = self.client.post("/api/v1/agent/heartbeat", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_heartbeat_rejects_unknown_fields_in_queue_counts(self):
        headers = self.auth_headers(self.token_a)
        payload = {
            "agent_version": "1.0.0",
            "installation_id": "inst-1",
            "service_state": "running",
            "queue_counts": {
                "queued": 0,
                "retry_wait": 0,
                "quarantined": 0,
                "extra_metric": 99,
            },
        }
        response = self.client.post("/api/v1/agent/heartbeat", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ===========================================================================
# 3. Agent Report Registration Tests (POST /api/v1/agent/reports)
# ===========================================================================


class AgentReportRegistrationTests(AgentEndpointsBaseTestCase):
    def setUp(self):
        super().setUp()
        self.phone = "+919876543210"
        self.content_sha256 = "a" * 64
        self.file_size = 183420
        self.document_type = "diagnostic_report"
        self.fingerprint = Report.compute_canonical_fingerprint(
            str(self.branch_a.id), self.phone, self.content_sha256
        )

    def test_unauthenticated_request_rejected(self):
        headers = {"HTTP_IDEMPOTENCY_KEY": self.fingerprint}
        response = self.client.post("/api/v1/agent/reports", {}, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_idempotency_key_header_rejected(self):
        headers = self.auth_headers(self.token_a)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }
        response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("idempotency_key", response.data.get("field_errors", {}))

    def test_invalid_idempotency_key_format_rejected(self):
        # 64 hex characters but contains uppercase
        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint.upper())
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }
        response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("idempotency_key", response.data.get("field_errors", {}))

    def test_key_fingerprint_mismatch_returns_409(self):
        mismatched_key = "f" * 64
        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=mismatched_key)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }
        response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "idempotency_conflict")

    def test_successful_report_registration(self):
        headers = self.auth_headers(
            self.token_a,
            HTTP_IDEMPOTENCY_KEY=self.fingerprint,
            HTTP_X_REQUEST_ID="rep-req-777",
        )
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
            "agent_created_at": "2026-10-12T10:10:00Z",
            "client_tracking_label": "sample-opaque-label-42",
        }
        response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.headers.get("X-Request-ID"), "rep-req-777")

        data = response.data
        self.assertIn("report_id", data)
        self.assertEqual(data["status"], "queued")
        self.assertEqual(data["duplicate"], False)
        self.assertIn("created_at", data)

        # Zero PII in response
        self.assertNotIn("recipient_phone_e164", data)
        self.assertNotIn("recipient_phone", data)
        self.assertNotIn("phone", data)

        # Verify DB record
        report = Report.objects.get(id=data["report_id"])
        self.assertEqual(report.organization, self.org_a)
        self.assertEqual(report.lab, self.lab_a)
        self.assertEqual(report.branch, self.branch_a)
        self.assertEqual(report.device, self.device_a)
        self.assertEqual(report.branch_assignment, self.assignment_a)
        self.assertEqual(report.recipient_phone_e164, self.phone)
        self.assertEqual(report.source_file_label, "sample-opaque-label-42")
        self.assertEqual(report.idempotency_key, self.fingerprint)
        self.assertEqual(report.fingerprint, self.fingerprint)
        self.assertEqual(report.status, ReportStatus.QUEUED)

    def test_idempotent_replay_returns_202_duplicate_true(self):
        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }

        # First request creates report
        resp1 = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(resp1.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp1.data["duplicate"], False)
        first_id = resp1.data["report_id"]

        # Second identical request returns duplicate: true with same report_id
        resp2 = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(resp2.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp2.data["duplicate"], True)
        self.assertEqual(resp2.data["report_id"], first_id)

        # Invariant: exactly 1 report created
        self.assertEqual(Report.objects.filter(organization=self.org_a).count(), 1)

    def test_same_key_different_payload_returns_409(self):
        # Create report initially
        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }
        resp1 = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(resp1.status_code, status.HTTP_202_ACCEPTED)

        # Attempt to use same key with different file size (different payload)
        payload_diff = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size + 100,  # Modified
            "document_type": self.document_type,
        }
        resp2 = self.client.post("/api/v1/agent/reports", payload_diff, format="json", **headers)
        self.assertEqual(resp2.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp2.data["code"], "idempotency_conflict")

    def test_same_fingerprint_different_key_returns_409(self):
        # Initial report
        headers1 = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }
        resp1 = self.client.post("/api/v1/agent/reports", payload, format="json", **headers1)
        self.assertEqual(resp1.status_code, status.HTTP_202_ACCEPTED)

        # Attempt replay with different key
        # (Note: client validation rejects mismatched key with 409)
        different_key = "1" * 64
        headers2 = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=different_key)
        resp2 = self.client.post("/api/v1/agent/reports", payload, format="json", **headers2)
        self.assertEqual(resp2.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp2.data["code"], "idempotency_conflict")

    def test_missing_whatsapp_assignment_returns_422(self):
        # Deactivate assignment on branch A
        self.assignment_a.status = AssignmentStatus.INACTIVE
        self.assignment_a.ended_at = tz_utils.now()
        self.assignment_a.save(update_fields=["status", "ended_at"])

        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }
        response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["code"], "account_not_verified")
        self.assertEqual(Report.objects.count(), 0)

    def test_unverified_whatsapp_account_returns_422(self):
        # Set account status to pending_verification
        self.whatsapp_account_a_verified.status = WhatsAppAccountStatus.PENDING_VERIFICATION
        self.whatsapp_account_a_verified.save(update_fields=["status"])

        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }
        response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["code"], "account_not_verified")
        self.assertEqual(Report.objects.count(), 0)

    def test_production_fails_closed_on_dev_verification_override(self):
        # Create an audit event showing dev override was used
        AuditEvent.objects.create(
            organization=self.org_a,
            actor_user=None,
            action=AuditAction.WHATSAPP_ACCOUNT_DEV_VERIFICATION_OVERRIDE,
            target_type="whatsapp_account",
            target_id=str(self.whatsapp_account_a_verified.id),
            safe_metadata={"status": "verified"},
        )

        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }

        # In production mode: MUST fail closed (422 account_not_verified)
        with override_settings(DOCFLOW_ENV="production"):
            response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
            self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
            self.assertEqual(response.data["code"], "account_not_verified")
            self.assertEqual(Report.objects.count(), 0)

        # In development mode: permitted
        with override_settings(DOCFLOW_ENV="development"):
            response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            self.assertEqual(Report.objects.count(), 1)

    def test_forbidden_fields_rejected(self):
        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        forbidden_test_cases = [
            ("file_name", "test_report.pdf"),
            ("path", "C:\\reports\\test.pdf"),
            ("media_url", "https://example.com/test.pdf"),
            ("pdf", "JVBERi0xLjQK..."),
            ("bytes", "some-bytes"),
            ("organization_id", str(self.org_b.id)),
            ("branch_id", str(self.branch_b.id)),
            ("device_id", str(self.device_b.id)),
            ("whatsapp_account_id", str(self.whatsapp_account_b_verified.id)),
            ("phone_number_id", "PN-INTRUDER"),
        ]

        for field, value in forbidden_test_cases:
            with self.subTest(field=field):
                payload = {
                    "recipient_phone_e164": self.phone,
                    "content_sha256": self.content_sha256,
                    "file_size_bytes": self.file_size,
                    "document_type": self.document_type,
                    field: value,
                }
                response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data["code"], "validation_error")

    def test_client_tracking_label_with_phone_number_rejected(self):
        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
            "client_tracking_label": "report_for_9876543210.pdf",  # Contains phone digits
        }
        response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

    def test_file_size_limits_enforced(self):
        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        # Exceeds 50MB (52428800 bytes)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": 52428801,
            "document_type": self.document_type,
        }
        response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("file_size_bytes", response.data.get("field_errors", {}))

    def test_tenant_isolation_enforced(self):
        # Device A token attempts to create report
        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }
        response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        # Verify the report is strictly associated with Org A and Branch A
        report = Report.objects.get(id=response.data["report_id"])
        self.assertEqual(report.organization, self.org_a)
        self.assertEqual(report.branch, self.branch_a)
        self.assertNotEqual(report.organization, self.org_b)

    def test_disabled_whatsapp_account_returns_422(self):
        self.whatsapp_account_a_verified.status = WhatsAppAccountStatus.DISABLED
        self.whatsapp_account_a_verified.save(update_fields=["status"])

        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }
        response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["code"], "account_not_verified")

    def test_inactive_lab_returns_403(self):
        self.lab_a.status = LabStatus.INACTIVE
        self.lab_a.save(update_fields=["status"])

        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }
        response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_inactive_branch_returns_403(self):
        self.branch_a.status = BranchStatus.INACTIVE
        self.branch_a.save(update_fields=["status"])

        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }
        response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_race_condition_duplicate_recovery_without_500(self):
        from unittest.mock import patch

        # Pre-create the matching report in DB as if a racing thread just committed it
        Report.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            branch=self.branch_a,
            device=self.device_a,
            branch_assignment=self.assignment_a,
            recipient_phone_e164=self.phone,
            document_type=self.document_type,
            content_sha256=self.content_sha256,
            file_size_bytes=self.file_size,
            idempotency_key=self.fingerprint,
            fingerprint=self.fingerprint,
            status=ReportStatus.QUEUED,
        )

        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }

        # Mock Report.objects.create to simulate unique constraint collision
        with patch.object(Report.objects, "create", side_effect=IntegrityError("unique constraint")):
            response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
            self.assertEqual(response.data["duplicate"], True)
            self.assertIn("report_id", response.data)

    def test_race_condition_conflict_returns_409(self):
        from unittest.mock import patch

        # Pre-create a conflicting report in DB with same key but different file size
        Report.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            branch=self.branch_a,
            device=self.device_a,
            branch_assignment=self.assignment_a,
            recipient_phone_e164=self.phone,
            document_type=self.document_type,
            content_sha256=self.content_sha256,
            file_size_bytes=self.file_size + 999,  # Mismatch
            idempotency_key=self.fingerprint,
            fingerprint=self.fingerprint,
            status=ReportStatus.QUEUED,
        )

        headers = self.auth_headers(self.token_a, HTTP_IDEMPOTENCY_KEY=self.fingerprint)
        payload = {
            "recipient_phone_e164": self.phone,
            "content_sha256": self.content_sha256,
            "file_size_bytes": self.file_size,
            "document_type": self.document_type,
        }

        with patch.object(Report.objects, "create", side_effect=IntegrityError("unique constraint")):
            response = self.client.post("/api/v1/agent/reports", payload, format="json", **headers)
            self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
            self.assertEqual(response.data["code"], "idempotency_conflict")

