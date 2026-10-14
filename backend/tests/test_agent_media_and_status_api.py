"""
Tests for Docflow Agent Media Reference Attachment and Report Status APIs (Phase 1, Task 3H).

Covers:
  - PUT /api/v1/agent/reports/{report_id}/media-reference
  - GET /api/v1/agent/reports/{report_id}
  - GET /api/v1/agent/reports

Validates:
  - DeviceBearerAuthentication enforcement and rejection of revoked/disabled devices.
  - Development media reference validation: mandatory, timezone-aware, future expires_at outside buffer.
  - Strict URL checks: HTTPS protocol, exact TEMP_UPLOAD_EXPECTED_HOST, direct /dl/ download path, no userinfo or unapproved ports.
  - Production gating and TEMP_UPLOAD_MODE enforcement.
  - Provider media kinds safely return 503 provider_unavailable.
  - Zero URL/PII leakage in responses, encrypted_reference remains empty for dev download URLs.
  - Transactional consistency: revalidates branch assignment, rejects deactivated or reassigned senders with 422 account_not_verified.
  - State transitions: queued -> uploaded with atomic creation of MediaReference, initial DeliveryAttempt, and DispatchOutbox.
  - Idempotent identical replays return duplicate: true without creating redundant records.
  - Conflicting attachments return 409 state_conflict.
  - Atomic rollback when any attachment step fails.
  - Report detail API: safe fields only, optional delivery_attempt summary, safe 404 for out-of-scope reports.
  - Report list API: strictly scoped, safe fields, documented status and since filtering, DocflowPagination envelope.
"""

import datetime
from unittest.mock import patch
from django.core.cache import cache
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone as tz_utils
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditAction, AuditEvent
from apps.devices.models import Device, DeviceStatus
from apps.devices.services import generate_access_token
from apps.reports.models import (
    DeliveryAttempt,
    DispatchOutbox,
    DocumentType,
    MediaKind,
    MediaReference,
    OutboxState,
    Report,
    ReportStatus,
)
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


class AgentMediaAndStatusBaseTestCase(TestCase):
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

        # Branch A2 (same Org A, different branch)
        self.branch_a2 = Branch.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            name="Alpha South Branch",
            code="BR-A2",
            status=BranchStatus.ACTIVE,
        )
        self.device_a2 = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a2,
            name="Workstation A2",
            status=DeviceStatus.ACTIVE,
            agent_version="1.0.0",
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
        self.assignment_a2 = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a2,
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
        self.token_a2, _ = generate_access_token(device=self.device_a2)
        self.token_revoked, _ = generate_access_token(device=self.device_revoked)
        self.token_disabled, _ = generate_access_token(device=self.device_disabled)
        self.token_b, _ = generate_access_token(device=self.device_b)

        self.client = APIClient()

    def auth_headers(self, token, **extra):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        headers.update(extra)
        return headers

    def create_report(self, branch=None, device=None, assignment=None, status=ReportStatus.QUEUED, phone="+919876543210"):
        branch = branch or self.branch_a
        device = device or self.device_a
        assignment = assignment or self.assignment_a
        sha = "a" * 64
        fp = Report.compute_canonical_fingerprint(str(branch.id), phone, sha)

        return Report.objects.create(
            organization=branch.organization,
            lab=branch.lab,
            branch=branch,
            device=device,
            branch_assignment=assignment,
            recipient_phone_e164=phone,
            source_file_label="sample-tracking-label",
            document_type=DocumentType.DIAGNOSTIC_REPORT,
            content_sha256=sha,
            file_size_bytes=1024,
            idempotency_key=fp,
            fingerprint=fp,
            status=status,
        )


# ===========================================================================
# 1. Media Reference Attachment Tests (PUT /api/v1/agent/reports/{id}/media-reference)
# ===========================================================================


@override_settings(
    TEMP_UPLOAD_MODE="tmpfiles",
    TEMP_UPLOAD_EXPECTED_HOST="tmpfiles.org",
    TEMP_UPLOAD_EXPIRY_BUFFER_SECONDS=300,
    DOCFLOW_ENV="development",
)
class AgentMediaReferenceAttachmentTests(AgentMediaAndStatusBaseTestCase):
    def setUp(self):
        super().setUp()
        self.report = self.create_report()
        self.url = f"/api/v1/agent/reports/{self.report.id}/media-reference"
        self.valid_expiry = (tz_utils.now() + datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.valid_payload = {
            "media_reference": {
                "kind": "development_download_url",
                "url": "https://tmpfiles.org/dl/example/fictional-sample.pdf",
                "expires_at": self.valid_expiry,
            }
        }

    def test_successful_media_attachment(self):
        headers = self.auth_headers(self.token_a, HTTP_X_REQUEST_ID="media-req-001")
        response = self.client.put(self.url, self.valid_payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.headers.get("X-Request-ID"), "media-req-001")

        data = response.data
        self.assertEqual(data["report_id"], str(self.report.id))
        self.assertEqual(data["status"], "uploaded")
        self.assertEqual(data["duplicate"], False)

        # Zero URL or credential leakage
        self.assertNotIn("url", data)
        self.assertNotIn("download_url", data)
        self.assertNotIn("media_reference", data)
        self.assertNotIn("token", data)

        # Verify DB: Report transitioned to uploaded
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.UPLOADED)

        # Verify DB: MediaReference created
        media_refs = self.report.media_references.all()
        self.assertEqual(media_refs.count(), 1)
        media = media_refs.first()
        self.assertEqual(media.kind, MediaKind.DEVELOPMENT_DOWNLOAD_URL)
        self.assertEqual(media.download_url, "https://tmpfiles.org/dl/example/fictional-sample.pdf")
        self.assertEqual(media.encrypted_reference, "")
        self.assertIsNotNone(media.expires_at)

        # Verify DB: DeliveryAttempt created
        attempts = self.report.delivery_attempts.all()
        self.assertEqual(attempts.count(), 1)
        attempt = attempts.first()
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(attempt.status, ReportStatus.QUEUED)
        self.assertEqual(attempt.provider_key, "kiziee")

        # Verify DB: DispatchOutbox created
        outbox_items = self.report.outbox_items.all()
        self.assertEqual(outbox_items.count(), 1)
        outbox = outbox_items.first()
        self.assertEqual(outbox.delivery_attempt, attempt)
        self.assertEqual(outbox.event_type, "send_message")
        self.assertEqual(outbox.state, OutboxState.PENDING)

    def test_identical_attachment_replay_is_idempotent(self):
        headers = self.auth_headers(self.token_a)

        # First attachment
        resp1 = self.client.put(self.url, self.valid_payload, format="json", **headers)
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertEqual(resp1.data["duplicate"], False)

        # Replay identical attachment
        resp2 = self.client.put(self.url, self.valid_payload, format="json", **headers)
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp2.data["duplicate"], True)
        self.assertEqual(resp2.data["report_id"], str(self.report.id))
        self.assertEqual(resp2.data["status"], "uploaded")

        # Verify no duplicate references, attempts, or outbox items created
        self.assertEqual(self.report.media_references.count(), 1)
        self.assertEqual(self.report.delivery_attempts.count(), 1)
        self.assertEqual(self.report.outbox_items.count(), 1)

    def test_conflicting_attachment_returns_409_state_conflict(self):
        headers = self.auth_headers(self.token_a)

        # First attachment
        resp1 = self.client.put(self.url, self.valid_payload, format="json", **headers)
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)

        # Different download URL
        conflicting_payload = {
            "media_reference": {
                "kind": "development_download_url",
                "url": "https://tmpfiles.org/dl/different/other-file.pdf",
                "expires_at": self.valid_expiry,
            }
        }
        resp2 = self.client.put(self.url, conflicting_payload, format="json", **headers)
        self.assertEqual(resp2.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp2.data["code"], "state_conflict")

        # Verify original media reference unchanged
        self.assertEqual(self.report.media_references.count(), 1)
        self.assertEqual(
            self.report.media_references.first().download_url,
            "https://tmpfiles.org/dl/example/fictional-sample.pdf",
        )

    def test_ineligible_report_status_returns_409(self):
        # Report is already delivered without prior media
        self.report.status = ReportStatus.DELIVERED
        self.report.save(update_fields=["status"])

        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, self.valid_payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "state_conflict")

    @override_settings(TEMP_UPLOAD_MODE="disabled")
    def test_temp_upload_mode_disabled_rejected(self):
        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, self.valid_payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

    @override_settings(DOCFLOW_ENV="production")
    def test_production_environment_rejects_development_download_url(self):
        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, self.valid_payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

    def test_missing_expires_at_rejected(self):
        payload = {
            "media_reference": {
                "kind": "development_download_url",
                "url": "https://tmpfiles.org/dl/example/fictional-sample.pdf",
            }
        }
        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expires_at", str(response.data.get("field_errors", {})))

    def test_naive_expires_at_rejected(self):
        payload = {
            "media_reference": {
                "kind": "development_download_url",
                "url": "https://tmpfiles.org/dl/example/fictional-sample.pdf",
                "expires_at": "2026-10-15T12:00:00",  # missing timezone offset / Z
            }
        }
        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expires_at", str(response.data.get("field_errors", {})))

    def test_past_expires_at_rejected(self):
        past_expiry = (tz_utils.now() - datetime.timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = {
            "media_reference": {
                "kind": "development_download_url",
                "url": "https://tmpfiles.org/dl/example/fictional-sample.pdf",
                "expires_at": past_expiry,
            }
        }
        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expires_at", str(response.data.get("field_errors", {})))

    def test_near_expiry_within_safety_buffer_rejected(self):
        # Buffer is 300s (5 mins); set expiry to 60s in future
        near_expiry = (tz_utils.now() + datetime.timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = {
            "media_reference": {
                "kind": "development_download_url",
                "url": "https://tmpfiles.org/dl/example/fictional-sample.pdf",
                "expires_at": near_expiry,
            }
        }
        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expires_at", str(response.data.get("field_errors", {})))

    def test_non_https_url_rejected(self):
        payload = {
            "media_reference": {
                "kind": "development_download_url",
                "url": "http://tmpfiles.org/dl/example/fictional-sample.pdf",
                "expires_at": self.valid_expiry,
            }
        }
        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("url", str(response.data.get("field_errors", {})))

    def test_wrong_host_url_rejected(self):
        payload = {
            "media_reference": {
                "kind": "development_download_url",
                "url": "https://otherfiles.org/dl/example/fictional-sample.pdf",
                "expires_at": self.valid_expiry,
            }
        }
        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("url", str(response.data.get("field_errors", {})))

    def test_userinfo_in_url_rejected(self):
        payload = {
            "media_reference": {
                "kind": "development_download_url",
                "url": "https://admin:secret@tmpfiles.org/dl/example/fictional-sample.pdf",
                "expires_at": self.valid_expiry,
            }
        }
        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("url", str(response.data.get("field_errors", {})))

    def test_unapproved_port_rejected(self):
        payload = {
            "media_reference": {
                "kind": "development_download_url",
                "url": "https://tmpfiles.org:8443/dl/example/fictional-sample.pdf",
                "expires_at": self.valid_expiry,
            }
        }
        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("url", str(response.data.get("field_errors", {})))

    def test_html_landing_page_rejected(self):
        # Missing '/dl/' prefix in path
        payload = {
            "media_reference": {
                "kind": "development_download_url",
                "url": "https://tmpfiles.org/12345/fictional-sample.pdf",
                "expires_at": self.valid_expiry,
            }
        }
        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("url", str(response.data.get("field_errors", {})))

    def test_provider_media_kinds_return_503(self):
        for provider_kind in ("provider_media_id", "provider_upload_reference"):
            payload = {
                "media_reference": {
                    "kind": provider_kind,
                    "provider_media_id": "media-12345",
                }
            }
            headers = self.auth_headers(self.token_a)
            response = self.client.put(self.url, payload, format="json", **headers)
            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertEqual(response.data["code"], "provider_unavailable")

    def test_unknown_fields_rejected(self):
        payload = {
            "media_reference": {
                "kind": "development_download_url",
                "url": "https://tmpfiles.org/dl/example/fictional-sample.pdf",
                "expires_at": self.valid_expiry,
                "unexpected_field": "disallowed",
            }
        }
        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_inactive_branch_assignment_returns_422(self):
        # Assignment deactivated after report registration
        self.assignment_a.status = AssignmentStatus.INACTIVE
        self.assignment_a.save(update_fields=["status"])

        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, self.valid_payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["code"], "account_not_verified")

        # Zero side effects
        self.assertEqual(self.report.media_references.count(), 0)
        self.assertEqual(self.report.delivery_attempts.count(), 0)
        self.assertEqual(self.report.outbox_items.count(), 0)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.QUEUED)

    def test_reassigned_branch_assignment_returns_422(self):
        # Branch assignment changed to a different assignment since registration
        new_account = WhatsAppAccount.objects.create(
            organization=self.org_a,
            display_name="New Sender",
            phone_number_id="PN-A-NEW",
            provider_key="kiziee",
            status=WhatsAppAccountStatus.VERIFIED,
            verified_at=tz_utils.now(),
        )
        self.assignment_a.status = AssignmentStatus.INACTIVE
        self.assignment_a.save(update_fields=["status"])

        BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=new_account,
            status=AssignmentStatus.ACTIVE,
        )

        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, self.valid_payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["code"], "account_not_verified")

        # Zero side effects
        self.assertEqual(self.report.media_references.count(), 0)
        self.assertEqual(self.report.delivery_attempts.count(), 0)
        self.assertEqual(self.report.outbox_items.count(), 0)

    def test_unverified_whatsapp_account_returns_422(self):
        self.whatsapp_account_a_verified.status = WhatsAppAccountStatus.PENDING_VERIFICATION
        self.whatsapp_account_a_verified.save(update_fields=["status"])

        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, self.valid_payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(response.data["code"], "account_not_verified")

    @override_settings(DOCFLOW_ENV="production")
    def test_dev_verification_override_in_production_returns_422(self):
        # Mark account as verified via dev override
        AuditEvent.objects.create(
            organization=self.org_a,
            target_type="whatsapp_account",
            target_id=str(self.whatsapp_account_a_verified.id),
            action=AuditAction.WHATSAPP_ACCOUNT_DEV_VERIFICATION_OVERRIDE,
            safe_metadata={"status": "verified"},
        )
        headers = self.auth_headers(self.token_a)
        response = self.client.put(self.url, self.valid_payload, format="json", **headers)
        # Prohibited in production by development check or account_not_verified
        self.assertIn(response.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY))

    def test_cross_tenant_isolation_returns_404(self):
        # Device B (Org B) attempts to attach media to Org A report
        headers = self.auth_headers(self.token_b)
        response = self.client.put(self.url, self.valid_payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "not_found")

    def test_cross_branch_isolation_returns_404(self):
        # Device A2 (same Org A, different branch) attempts to attach media to Branch A report
        headers = self.auth_headers(self.token_a2)
        response = self.client.put(self.url, self.valid_payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "not_found")

    def test_invalid_uuid_returns_404(self):
        headers = self.auth_headers(self.token_a)
        response = self.client.put("/api/v1/agent/reports/not-a-uuid/media-reference", self.valid_payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unauthenticated_request_rejected(self):
        response = self.client.put(self.url, self.valid_payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_revoked_device_rejected(self):
        headers = self.auth_headers(self.token_revoked)
        response = self.client.put(self.url, self.valid_payload, format="json", **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_transaction_rollback_on_failure(self):
        headers = self.auth_headers(self.token_a)

        with patch("apps.reports.models.DispatchOutbox.objects.get_or_create", side_effect=RuntimeError("Simulated outbox failure")):
            response = self.client.put(self.url, self.valid_payload, format="json", **headers)
            self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Confirm rollback: report stays queued, no media reference, no attempt, no outbox
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.QUEUED)
        self.assertEqual(self.report.media_references.count(), 0)
        self.assertEqual(self.report.delivery_attempts.count(), 0)
        self.assertEqual(self.report.outbox_items.count(), 0)


# ===========================================================================
# 2. Get Report Detail Tests (GET /api/v1/agent/reports/{report_id})
# ===========================================================================


class AgentReportDetailTests(AgentMediaAndStatusBaseTestCase):
    def setUp(self):
        super().setUp()
        self.report = self.create_report()
        self.url = f"/api/v1/agent/reports/{self.report.id}"

    def test_detail_without_delivery_attempt(self):
        headers = self.auth_headers(self.token_a, HTTP_X_REQUEST_ID="rep-det-001")
        response = self.client.get(self.url, **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.headers.get("X-Request-ID"), "rep-det-001")

        data = response.data
        self.assertEqual(data["report_id"], str(self.report.id))
        self.assertEqual(data["status"], "queued")
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)
        self.assertIsNone(data["last_safe_error_code"])

        # Omit delivery_attempt when no attempt exists
        self.assertNotIn("delivery_attempt", data)

        # Zero PII, phone, or media reference leakage
        self.assertNotIn("recipient_phone_e164", data)
        self.assertNotIn("recipient_phone", data)
        self.assertNotIn("phone", data)
        self.assertNotIn("media_reference", data)
        self.assertNotIn("download_url", data)

    def test_detail_with_delivery_attempt(self):
        attempt = DeliveryAttempt.objects.create(
            organization=self.org_a,
            report=self.report,
            attempt_number=1,
            status=ReportStatus.QUEUED,
            provider_key="kiziee",
            provider_message_id="wamid.1234567890",
        )

        headers = self.auth_headers(self.token_a)
        response = self.client.get(self.url, **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertIn("delivery_attempt", data)

        att_data = data["delivery_attempt"]
        self.assertEqual(att_data["attempt_number"], 1)
        self.assertEqual(att_data["status"], "queued")
        self.assertEqual(att_data["provider_message_id"], "wamid.1234567890")
        self.assertIn("updated_at", att_data)
        self.assertIsNone(att_data["last_safe_error_code"])

    def test_detail_with_error_code(self):
        DeliveryAttempt.objects.create(
            organization=self.org_a,
            report=self.report,
            attempt_number=1,
            status=ReportStatus.FAILED,
            provider_key="kiziee",
            error_code="rate_limited",
        )

        headers = self.auth_headers(self.token_a)
        response = self.client.get(self.url, **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["last_safe_error_code"], "rate_limited")
        self.assertEqual(response.data["delivery_attempt"]["last_safe_error_code"], "rate_limited")

    def test_cross_tenant_report_detail_returns_404(self):
        headers = self.auth_headers(self.token_b)
        response = self.client.get(self.url, **headers)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "not_found")

    def test_cross_branch_report_detail_returns_404(self):
        headers = self.auth_headers(self.token_a2)
        response = self.client.get(self.url, **headers)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "not_found")

    def test_unauthenticated_request_rejected(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_revoked_device_rejected(self):
        headers = self.auth_headers(self.token_revoked)
        response = self.client.get(self.url, **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")


# ===========================================================================
# 3. List Reports Tests (GET /api/v1/agent/reports)
# ===========================================================================


class AgentReportListTests(AgentMediaAndStatusBaseTestCase):
    def setUp(self):
        super().setUp()
        self.url = "/api/v1/agent/reports"

        # Create reports for Org A / Branch A
        self.rep1 = self.create_report(phone="+919876543201")
        self.rep2 = self.create_report(phone="+919876543202", status=ReportStatus.UPLOADED)
        self.rep3 = self.create_report(phone="+919876543203", status=ReportStatus.DELIVERED)

        # Create report for Branch A2 (same org, different branch)
        self.rep_a2 = self.create_report(branch=self.branch_a2, device=self.device_a2, assignment=self.assignment_a2, phone="+919876543204")

        # Create report for Org B / Branch B
        self.rep_b = self.create_report(branch=self.branch_b, device=self.device_b, assignment=self.assignment_b, phone="+919876543205")

    def test_list_reports_scoped_to_device_branch(self):
        headers = self.auth_headers(self.token_a, HTTP_X_REQUEST_ID="rep-list-001")
        response = self.client.get(self.url, **headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.headers.get("X-Request-ID"), "rep-list-001")

        data = response.data
        self.assertIn("results", data)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 25)
        self.assertEqual(data["total"], 3)
        self.assertEqual(len(data["results"]), 3)

        report_ids = [r["report_id"] for r in data["results"]]
        self.assertIn(str(self.rep1.id), report_ids)
        self.assertIn(str(self.rep2.id), report_ids)
        self.assertIn(str(self.rep3.id), report_ids)

        # Strictly excludes Branch A2 and Org B reports
        self.assertNotIn(str(self.rep_a2.id), report_ids)
        self.assertNotIn(str(self.rep_b.id), report_ids)

        # Verify safe shape of each item
        for item in data["results"]:
            self.assertIn("report_id", item)
            self.assertIn("status", item)
            self.assertIn("created_at", item)
            self.assertIn("updated_at", item)
            self.assertIn("last_safe_error_code", item)

            # Zero PII leakage
            self.assertNotIn("recipient_phone", item)
            self.assertNotIn("recipient_phone_e164", item)
            self.assertNotIn("phone", item)
            self.assertNotIn("media_reference", item)
            self.assertNotIn("download_url", item)

    def test_list_reports_filter_by_status(self):
        headers = self.auth_headers(self.token_a)

        # Filter: status=uploaded
        response = self.client.get(f"{self.url}?status=uploaded", **headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 1)
        self.assertEqual(response.data["results"][0]["report_id"], str(self.rep2.id))

        # Filter: status=queued
        response = self.client.get(f"{self.url}?status=queued", **headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 1)
        self.assertEqual(response.data["results"][0]["report_id"], str(self.rep1.id))

    def test_list_reports_invalid_status_returns_400(self):
        headers = self.auth_headers(self.token_a)
        response = self.client.get(f"{self.url}?status=not_a_valid_status", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

    def test_list_reports_filter_by_since(self):
        headers = self.auth_headers(self.token_a)

        # Filter since 1 hour ago
        one_hour_ago = (tz_utils.now() - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        response = self.client.get(f"{self.url}?since={one_hour_ago}", **headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 3)

        # Filter since 1 hour in future
        one_hour_future = (tz_utils.now() + datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        response = self.client.get(f"{self.url}?since={one_hour_future}", **headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 0)

    def test_list_reports_invalid_since_returns_400(self):
        headers = self.auth_headers(self.token_a)
        response = self.client.get(f"{self.url}?since=invalid-date", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

    def test_list_reports_pagination(self):
        headers = self.auth_headers(self.token_a)

        # Page 1, size 2
        resp1 = self.client.get(f"{self.url}?page=1&page_size=2", **headers)
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertEqual(resp1.data["page"], 1)
        self.assertEqual(resp1.data["page_size"], 2)
        self.assertEqual(resp1.data["total"], 3)
        self.assertEqual(len(resp1.data["results"]), 2)

        # Page 2, size 2
        resp2 = self.client.get(f"{self.url}?page=2&page_size=2", **headers)
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp2.data["page"], 2)
        self.assertEqual(len(resp2.data["results"]), 1)

    def test_list_reports_invalid_pagination_bounds_returns_400(self):
        headers = self.auth_headers(self.token_a)

        # page_size > 100
        resp1 = self.client.get(f"{self.url}?page_size=101", **headers)
        self.assertEqual(resp1.status_code, status.HTTP_400_BAD_REQUEST)

        # page_size < 1
        resp2 = self.client.get(f"{self.url}?page_size=0", **headers)
        self.assertEqual(resp2.status_code, status.HTTP_400_BAD_REQUEST)

        # page < 1
        resp3 = self.client.get(f"{self.url}?page=0", **headers)
        self.assertEqual(resp3.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unexpected_query_parameters_rejected(self):
        headers = self.auth_headers(self.token_a)

        response = self.client.get(f"{self.url}?recipient_phone=%2B919876543201", **headers)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

        response2 = self.client.get(f"{self.url}?unapproved_param=value", **headers)
        self.assertEqual(response2.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_reports_unauthenticated_rejected(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_list_reports_revoked_device_rejected(self):
        headers = self.auth_headers(self.token_revoked)
        response = self.client.get(self.url, **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_list_reports_includes_last_safe_error_code(self):
        DeliveryAttempt.objects.create(
            organization=self.org_a,
            report=self.rep1,
            attempt_number=1,
            status=ReportStatus.FAILED,
            provider_key="kiziee",
            error_code="phone_not_registered",
        )

        headers = self.auth_headers(self.token_a)
        response = self.client.get(f"{self.url}?status=queued", **headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["last_safe_error_code"], "phone_not_registered")
