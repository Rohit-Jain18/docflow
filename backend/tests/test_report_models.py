"""
Tests for Report, MediaReference, DeliveryAttempt, DeliveryEvent, and DispatchOutbox models (Phase 1, Task 2D).

Covers:
- Report: UUID PK, field format validations (64-hex, E.164, PII minimization in labels),
  canonical fingerprint calculation, database unique constraints on (org, idempotency_key)
  and (org, fingerprint), full tenant/hierarchy consistency (org, lab, branch, device, assignment),
  and immutability of persisted identity fields.
- MediaReference: UUID PK, kinds, PDF byte protection, encrypted_reference protection against
  plaintext temporary URLs, explicit expires_at requirement for temporary media,
  tmpfiles direct binary URL validation, settings-based gating, and admin display security.
- DeliveryAttempt: UUID PK, attempt numbering, unique (report, attempt_number) constraint,
  tenant consistency, immutable attempt history, resend preservation, and error categories.
- DeliveryEvent: UUID PK, tenant/attempt consistency, event sources, and safe_payload_summary
  protection against raw webhook payloads and secret tokens.
- DispatchOutbox: UUID PK, state choices, claim timestamps, durable dispatch indexes,
  and tenant/attempt consistency.
"""

import uuid
from datetime import timedelta

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone as tz_utils

from apps.devices.models import Device
from apps.reports.admin import (
    DeliveryAttemptAdmin,
    DeliveryEventAdmin,
    DispatchOutboxAdmin,
    MediaReferenceAdmin,
    ReportAdmin,
)
from apps.reports.models import (
    DeliveryAttempt,
    DeliveryEvent,
    DispatchOutbox,
    DocumentType,
    ErrorCategory,
    EventSource,
    MediaKind,
    MediaReference,
    OutboxState,
    Report,
    ReportStatus,
)
from apps.tenants.models import Branch, Lab, Organization
from apps.whatsapp.models import BranchWhatsAppAssignment, WhatsAppAccount


class ReportModelTest(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A", slug="org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="org-b")
        self.lab_a = Lab.objects.create(organization=self.org_a, name="Lab A", code="LA")
        self.lab_b = Lab.objects.create(organization=self.org_b, name="Lab B", code="LB")
        self.branch_a = Branch.objects.create(
            organization=self.org_a, lab=self.lab_a, name="Branch A", code="BA"
        )
        self.branch_b = Branch.objects.create(
            organization=self.org_b, lab=self.lab_b, name="Branch B", code="BB"
        )
        self.device_a = Device.objects.create(
            organization=self.org_a, branch=self.branch_a, name="Device A"
        )
        self.wa_account_a = WhatsAppAccount.objects.create(
            organization=self.org_a, phone_number_id="wa-a"
        )
        self.assignment_a = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.wa_account_a,
        )
        self.valid_sha256 = "a" * 64
        self.valid_idempotency_key = "b" * 64
        self.valid_phone = "+919876543210"

    def test_create_report_defaults_and_fields(self):
        report = Report.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            branch=self.branch_a,
            device=self.device_a,
            branch_assignment=self.assignment_a,
            recipient_phone_e164=self.valid_phone,
            content_sha256=self.valid_sha256,
            file_size_bytes=102400,
            idempotency_key=self.valid_idempotency_key,
        )
        self.assertIsInstance(report.id, uuid.UUID)
        self.assertEqual(report.status, ReportStatus.QUEUED)
        self.assertEqual(report.document_type, DocumentType.DIAGNOSTIC_REPORT)
        self.assertEqual(report.source_file_label, "")
        self.assertIsNone(report.accepted_at)
        self.assertIsNone(report.delivered_at)
        self.assertIsNone(report.read_at)
        self.assertIsNone(report.expires_at)
        self.assertEqual(report.quarantined_reason_code, "")
        self.assertIsNotNone(report.created_at)
        self.assertIsNotNone(report.updated_at)
        # Fingerprint auto-computed
        expected_fp = Report.compute_canonical_fingerprint(
            self.branch_a.id, self.valid_phone, self.valid_sha256
        )
        self.assertEqual(report.fingerprint, expected_fp)

    def test_canonical_fingerprint_formula(self):
        computed = Report.compute_canonical_fingerprint(
            self.branch_a.id, self.valid_phone, self.valid_sha256
        )
        self.assertEqual(len(computed), 64)
        # Verify exact specification: sha256("v1|" + branch_id + "|" + phone + "|" + content_sha256)
        import hashlib
        manual_expected = hashlib.sha256(
            f"v1|{self.branch_a.id}|{self.valid_phone}|{self.valid_sha256}".encode("utf-8")
        ).hexdigest()
        self.assertEqual(computed, manual_expected)

    def test_fingerprint_mismatch_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            Report.objects.create(
                organization=self.org_a,
                lab=self.lab_a,
                branch=self.branch_a,
                recipient_phone_e164=self.valid_phone,
                content_sha256=self.valid_sha256,
                file_size_bytes=50000,
                idempotency_key=self.valid_idempotency_key,
                fingerprint="c" * 64,  # wrong fingerprint
            )
        self.assertIn("fingerprint", ctx.exception.message_dict)

    def test_idempotency_key_format_validation(self):
        # Invalid length
        with self.assertRaises(ValidationError) as ctx:
            Report.objects.create(
                organization=self.org_a,
                lab=self.lab_a,
                branch=self.branch_a,
                recipient_phone_e164=self.valid_phone,
                content_sha256=self.valid_sha256,
                file_size_bytes=50000,
                idempotency_key="too-short",
            )
        self.assertIn("idempotency_key", ctx.exception.message_dict)

        # Non-hex characters
        with self.assertRaises(ValidationError) as ctx:
            Report.objects.create(
                organization=self.org_a,
                lab=self.lab_a,
                branch=self.branch_a,
                recipient_phone_e164=self.valid_phone,
                content_sha256=self.valid_sha256,
                file_size_bytes=50000,
                idempotency_key="z" * 64,
            )
        self.assertIn("idempotency_key", ctx.exception.message_dict)

    def test_content_sha256_format_validation(self):
        with self.assertRaises(ValidationError) as ctx:
            Report.objects.create(
                organization=self.org_a,
                lab=self.lab_a,
                branch=self.branch_a,
                recipient_phone_e164=self.valid_phone,
                content_sha256="not-valid-sha256",
                file_size_bytes=50000,
                idempotency_key=self.valid_idempotency_key,
            )
        self.assertIn("content_sha256", ctx.exception.message_dict)

    def test_recipient_phone_e164_format_validation(self):
        # Missing plus sign
        with self.assertRaises(ValidationError) as ctx:
            Report.objects.create(
                organization=self.org_a,
                lab=self.lab_a,
                branch=self.branch_a,
                recipient_phone_e164="919876543210",
                content_sha256=self.valid_sha256,
                file_size_bytes=50000,
                idempotency_key=self.valid_idempotency_key,
            )
        self.assertIn("recipient_phone_e164", ctx.exception.message_dict)

    def test_source_file_label_rejects_recipient_phone_pii(self):
        with self.assertRaises(ValidationError) as ctx:
            Report.objects.create(
                organization=self.org_a,
                lab=self.lab_a,
                branch=self.branch_a,
                recipient_phone_e164=self.valid_phone,
                content_sha256=self.valid_sha256,
                file_size_bytes=50000,
                idempotency_key=self.valid_idempotency_key,
                source_file_label="9876543210.pdf",  # contains phone digits
            )
        self.assertIn("source_file_label", ctx.exception.message_dict)

    def test_unique_organization_idempotency_key_constraint(self):
        Report.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            branch=self.branch_a,
            recipient_phone_e164=self.valid_phone,
            content_sha256=self.valid_sha256,
            file_size_bytes=50000,
            idempotency_key=self.valid_idempotency_key,
        )
        with self.assertRaises(IntegrityError):
            Report.objects.create(
                organization=self.org_a,
                lab=self.lab_a,
                branch=self.branch_a,
                recipient_phone_e164="+919999999999",  # different phone
                content_sha256="c" * 64,  # different sha
                file_size_bytes=50000,
                idempotency_key=self.valid_idempotency_key,  # same key in org A
            )

    def test_same_idempotency_key_in_different_org_allowed(self):
        r1 = Report.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            branch=self.branch_a,
            recipient_phone_e164=self.valid_phone,
            content_sha256=self.valid_sha256,
            file_size_bytes=50000,
            idempotency_key=self.valid_idempotency_key,
        )
        r2 = Report.objects.create(
            organization=self.org_b,
            lab=self.lab_b,
            branch=self.branch_b,
            recipient_phone_e164=self.valid_phone,
            content_sha256=self.valid_sha256,
            file_size_bytes=50000,
            idempotency_key=self.valid_idempotency_key,
        )
        self.assertNotEqual(r1.organization, r2.organization)
        self.assertEqual(r1.idempotency_key, r2.idempotency_key)

    def test_unique_organization_fingerprint_constraint(self):
        Report.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            branch=self.branch_a,
            recipient_phone_e164=self.valid_phone,
            content_sha256=self.valid_sha256,
            file_size_bytes=50000,
            idempotency_key=self.valid_idempotency_key,
        )
        with self.assertRaises(IntegrityError):
            # Same branch, phone, content -> same fingerprint within org A
            Report.objects.create(
                organization=self.org_a,
                lab=self.lab_a,
                branch=self.branch_a,
                recipient_phone_e164=self.valid_phone,
                content_sha256=self.valid_sha256,
                file_size_bytes=50000,
                idempotency_key="d" * 64,  # different key, same fingerprint
            )

    def test_cross_tenant_branch_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            Report.objects.create(
                organization=self.org_a,
                lab=self.lab_a,
                branch=self.branch_b,  # Branch B is in Org B
                recipient_phone_e164=self.valid_phone,
                content_sha256=self.valid_sha256,
                file_size_bytes=50000,
                idempotency_key=self.valid_idempotency_key,
            )
        self.assertIn("branch", ctx.exception.message_dict)

    def test_cross_lab_branch_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            Report.objects.create(
                organization=self.org_a,
                lab=self.lab_b,  # Lab B does not match Branch A's parent lab
                branch=self.branch_a,
                recipient_phone_e164=self.valid_phone,
                content_sha256=self.valid_sha256,
                file_size_bytes=50000,
                idempotency_key=self.valid_idempotency_key,
            )
        self.assertIn("lab", ctx.exception.message_dict)

    def test_cross_tenant_device_rejected(self):
        device_b = Device.objects.create(
            organization=self.org_b, branch=self.branch_b, name="Device B"
        )
        with self.assertRaises(ValidationError) as ctx:
            Report.objects.create(
                organization=self.org_a,
                lab=self.lab_a,
                branch=self.branch_a,
                device=device_b,
                recipient_phone_e164=self.valid_phone,
                content_sha256=self.valid_sha256,
                file_size_bytes=50000,
                idempotency_key=self.valid_idempotency_key,
            )
        self.assertIn("device", ctx.exception.message_dict)

    def test_cross_tenant_branch_assignment_rejected(self):
        wa_account_b = WhatsAppAccount.objects.create(
            organization=self.org_b, phone_number_id="wa-b"
        )
        assignment_b = BranchWhatsAppAssignment.objects.create(
            organization=self.org_b,
            branch=self.branch_b,
            whatsapp_account=wa_account_b,
        )
        with self.assertRaises(ValidationError) as ctx:
            Report.objects.create(
                organization=self.org_a,
                lab=self.lab_a,
                branch=self.branch_a,
                branch_assignment=assignment_b,
                recipient_phone_e164=self.valid_phone,
                content_sha256=self.valid_sha256,
                file_size_bytes=50000,
                idempotency_key=self.valid_idempotency_key,
            )
        self.assertIn("branch_assignment", ctx.exception.message_dict)

    def test_persisted_report_identity_fields_immutable(self):
        report = Report.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            branch=self.branch_a,
            device=self.device_a,
            branch_assignment=self.assignment_a,
            recipient_phone_e164=self.valid_phone,
            content_sha256=self.valid_sha256,
            file_size_bytes=50000,
            idempotency_key=self.valid_idempotency_key,
        )
        # Attempt to change organization
        report.organization = self.org_b
        with self.assertRaises(ValidationError) as ctx:
            report.save()
        self.assertIn("organization", ctx.exception.message_dict)

        report.refresh_from_db()
        self.assertEqual(report.organization, self.org_a)

        # Attempt to change idempotency key
        report.idempotency_key = "f" * 64
        with self.assertRaises(ValidationError) as ctx:
            report.save()
        self.assertIn("idempotency_key", ctx.exception.message_dict)

        # Normal status update is allowed
        report.refresh_from_db()
        report.status = ReportStatus.DELIVERED
        report.delivered_at = tz_utils.now()
        report.save()
        report.refresh_from_db()
        self.assertEqual(report.status, ReportStatus.DELIVERED)

    def test_admin_readonly_fields_on_edit(self):
        site = AdminSite()
        admin = ReportAdmin(Report, site)
        report = Report.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            branch=self.branch_a,
            recipient_phone_e164=self.valid_phone,
            content_sha256=self.valid_sha256,
            file_size_bytes=50000,
            idempotency_key=self.valid_idempotency_key,
        )
        readonly_create = admin.get_readonly_fields(request=None, obj=None)
        self.assertNotIn("organization", readonly_create)
        self.assertNotIn("idempotency_key", readonly_create)

        readonly_edit = admin.get_readonly_fields(request=None, obj=report)
        self.assertIn("organization", readonly_edit)
        self.assertIn("lab", readonly_edit)
        self.assertIn("branch", readonly_edit)
        self.assertIn("idempotency_key", readonly_edit)
        self.assertIn("fingerprint", readonly_edit)


class MediaReferenceModelTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Org A", slug="org-a")
        self.lab = Lab.objects.create(organization=self.org, name="Lab A", code="LA")
        self.branch = Branch.objects.create(
            organization=self.org, lab=self.lab, name="Branch A", code="BA"
        )
        self.report = Report.objects.create(
            organization=self.org,
            lab=self.lab,
            branch=self.branch,
            recipient_phone_e164="+919876543210",
            content_sha256="a" * 64,
            file_size_bytes=50000,
            idempotency_key="b" * 64,
        )

    def test_create_media_reference_with_provider_media_id(self):
        ref = MediaReference.objects.create(
            report=self.report,
            kind=MediaKind.PROVIDER_MEDIA_ID,
            provider_media_id="wamid-media-123456",
        )
        self.assertIsInstance(ref.id, uuid.UUID)
        self.assertEqual(ref.kind, MediaKind.PROVIDER_MEDIA_ID)
        self.assertEqual(ref.provider_media_id, "wamid-media-123456")
        self.assertEqual(ref.encrypted_reference, "")
        self.assertIsNone(ref.expires_at)
        self.assertIsNone(ref.deleted_at)

    def test_reject_pdf_bytes_in_reference_fields(self):
        with self.assertRaises(ValidationError) as ctx:
            MediaReference.objects.create(
                report=self.report,
                kind=MediaKind.PROVIDER_UPLOAD_REFERENCE,
                encrypted_reference="%PDF-1.4 binary stream data here",
            )
        self.assertIn("encrypted_reference", ctx.exception.message_dict)

    def test_reject_plaintext_url_in_encrypted_reference(self):
        with self.assertRaises(ValidationError) as ctx:
            MediaReference.objects.create(
                report=self.report,
                kind=MediaKind.PROVIDER_UPLOAD_REFERENCE,
                encrypted_reference="https://tmpfiles.org/dl/12345/fictional.pdf",
            )
        self.assertIn("encrypted_reference", ctx.exception.message_dict)

    @override_settings(TEMP_UPLOAD_MODE="tmpfiles", TEMP_UPLOAD_EXPECTED_HOST="tmpfiles.org")
    def test_development_download_url_requires_explicit_expires_at(self):
        with self.assertRaises(ValidationError) as ctx:
            MediaReference.objects.create(
                report=self.report,
                kind=MediaKind.DEVELOPMENT_DOWNLOAD_URL,
                download_url="https://tmpfiles.org/dl/12345/fictional.pdf",
                expires_at=None,  # missing required expires_at
            )
        self.assertIn("expires_at", ctx.exception.message_dict)

    @override_settings(TEMP_UPLOAD_MODE="tmpfiles", TEMP_UPLOAD_EXPECTED_HOST="tmpfiles.org")
    def test_development_download_url_rejects_html_landing_page(self):
        # Notice missing '/dl/' path
        with self.assertRaises(ValidationError) as ctx:
            MediaReference.objects.create(
                report=self.report,
                kind=MediaKind.DEVELOPMENT_DOWNLOAD_URL,
                download_url="https://tmpfiles.org/12345/fictional.pdf",
                expires_at=tz_utils.now() + timedelta(hours=1),
            )
        self.assertIn("download_url", ctx.exception.message_dict)

    @override_settings(TEMP_UPLOAD_MODE="disabled")
    def test_development_download_url_rejected_when_temp_upload_disabled(self):
        with self.assertRaises(ValidationError) as ctx:
            MediaReference.objects.create(
                report=self.report,
                kind=MediaKind.DEVELOPMENT_DOWNLOAD_URL,
                download_url="https://tmpfiles.org/dl/12345/fictional.pdf",
                expires_at=tz_utils.now() + timedelta(hours=1),
            )
        self.assertIn("kind", ctx.exception.message_dict)

    @override_settings(TEMP_UPLOAD_MODE="tmpfiles", TEMP_UPLOAD_EXPECTED_HOST="tmpfiles.org")
    def test_development_download_url_accepted_when_configured(self):
        expiry = tz_utils.now() + timedelta(hours=1)
        ref = MediaReference.objects.create(
            report=self.report,
            kind=MediaKind.DEVELOPMENT_DOWNLOAD_URL,
            download_url="https://tmpfiles.org/dl/12345/fictional.pdf",
            expires_at=expiry,
        )
        self.assertEqual(ref.download_url, "https://tmpfiles.org/dl/12345/fictional.pdf")
        self.assertEqual(ref.expires_at, expiry)

    def test_admin_excludes_sensitive_reference_fields_from_list_and_form(self):
        site = AdminSite()
        admin = MediaReferenceAdmin(MediaReference, site)
        ref = MediaReference.objects.create(
            report=self.report,
            kind=MediaKind.PROVIDER_MEDIA_ID,
            provider_media_id="wamid-media-123456",
        )

        sensitive_fields = ("encrypted_reference", "download_url", "provider_media_id")

        # Excluded from list display
        for field_name in sensitive_fields:
            self.assertNotIn(field_name, admin.list_display)

        # Excluded entirely from change form
        change_form = admin.get_form(request=None, obj=ref)
        for field_name in sensitive_fields:
            self.assertNotIn(field_name, change_form.base_fields)

        # Excluded entirely from create form
        create_form = admin.get_form(request=None, obj=None)
        for field_name in sensitive_fields:
            self.assertNotIn(field_name, create_form.base_fields)

        # Excluded from get_fields presentation
        fields = admin.get_fields(request=None, obj=ref)
        for field_name in sensitive_fields:
            self.assertNotIn(field_name, fields)

        # Safe operational metadata is preserved
        self.assertIn("id", admin.list_display)
        self.assertIn("kind", admin.list_display)
        self.assertIn("expires_at", admin.list_display)
        self.assertIn("created_at", admin.list_display)
        self.assertIn("deleted_at", admin.list_display)
        self.assertIn("expires_at", fields)
        self.assertIn("kind", fields)



class DeliveryAttemptModelTest(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A", slug="org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="org-b")
        self.lab = Lab.objects.create(organization=self.org_a, name="Lab A", code="LA")
        self.branch = Branch.objects.create(
            organization=self.org_a, lab=self.lab, name="Branch A", code="BA"
        )
        self.report = Report.objects.create(
            organization=self.org_a,
            lab=self.lab,
            branch=self.branch,
            recipient_phone_e164="+919876543210",
            content_sha256="a" * 64,
            file_size_bytes=50000,
            idempotency_key="b" * 64,
        )

    def test_create_attempt_defaults_and_fields(self):
        attempt = DeliveryAttempt.objects.create(
            organization=self.org_a,
            report=self.report,
            attempt_number=1,
        )
        self.assertIsInstance(attempt.id, uuid.UUID)
        self.assertEqual(attempt.status, ReportStatus.QUEUED)
        self.assertEqual(attempt.provider_key, "kiziee")
        self.assertEqual(attempt.provider_message_id, "")
        self.assertIsNone(attempt.request_started_at)
        self.assertIsNone(attempt.accepted_at)
        self.assertIsNone(attempt.finished_at)
        self.assertEqual(attempt.error_code, "")
        self.assertEqual(attempt.error_category, "")

    def test_unique_report_attempt_number_constraint(self):
        DeliveryAttempt.objects.create(
            organization=self.org_a,
            report=self.report,
            attempt_number=1,
        )
        with self.assertRaises(IntegrityError):
            DeliveryAttempt.objects.create(
                organization=self.org_a,
                report=self.report,
                attempt_number=1,  # duplicate attempt 1 on same report
            )

    def test_attempt_organization_must_match_report_organization(self):
        with self.assertRaises(ValidationError) as ctx:
            DeliveryAttempt.objects.create(
                organization=self.org_b,  # Org B does not match report's Org A
                report=self.report,
                attempt_number=1,
            )
        self.assertIn("organization", ctx.exception.message_dict)

    def test_resend_preserves_earlier_attempts(self):
        att1 = DeliveryAttempt.objects.create(
            organization=self.org_a,
            report=self.report,
            attempt_number=1,
            status=ReportStatus.FAILED,
            error_code="rate_limit_exceeded",
            error_category=ErrorCategory.TRANSIENT,
        )
        att2 = DeliveryAttempt.objects.create(
            organization=self.org_a,
            report=self.report,
            attempt_number=2,
            status=ReportStatus.ACCEPTED,
            provider_message_id="wamid.12345",
        )
        self.assertEqual(self.report.delivery_attempts.count(), 2)
        self.assertEqual(att1.status, ReportStatus.FAILED)
        self.assertEqual(att2.status, ReportStatus.ACCEPTED)

    def test_persisted_attempt_fields_immutable(self):
        att = DeliveryAttempt.objects.create(
            organization=self.org_a,
            report=self.report,
            attempt_number=1,
        )
        att.attempt_number = 2
        with self.assertRaises(ValidationError) as ctx:
            att.save()
        self.assertIn("attempt_number", ctx.exception.message_dict)

        att.refresh_from_db()
        self.assertEqual(att.attempt_number, 1)

    def test_admin_readonly_on_edit(self):
        site = AdminSite()
        admin = DeliveryAttemptAdmin(DeliveryAttempt, site)
        att = DeliveryAttempt.objects.create(
            organization=self.org_a,
            report=self.report,
            attempt_number=1,
        )
        readonly_edit = admin.get_readonly_fields(request=None, obj=att)
        self.assertIn("organization", readonly_edit)
        self.assertIn("report", readonly_edit)
        self.assertIn("attempt_number", readonly_edit)


class DeliveryEventModelTest(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A", slug="org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="org-b")
        self.lab = Lab.objects.create(organization=self.org_a, name="Lab A", code="LA")
        self.branch = Branch.objects.create(
            organization=self.org_a, lab=self.lab, name="Branch A", code="BA"
        )
        self.report = Report.objects.create(
            organization=self.org_a,
            lab=self.lab,
            branch=self.branch,
            recipient_phone_e164="+919876543210",
            content_sha256="a" * 64,
            file_size_bytes=50000,
            idempotency_key="b" * 64,
        )
        self.attempt = DeliveryAttempt.objects.create(
            organization=self.org_a,
            report=self.report,
            attempt_number=1,
        )

    def test_create_delivery_event(self):
        event = DeliveryEvent.objects.create(
            organization=self.org_a,
            report=self.report,
            delivery_attempt=self.attempt,
            event_type="provider_accepted",
            source=EventSource.PLATFORM,
            provider_event_id="evt-1001",
            safe_payload_summary={"wamid": "wamid.1001", "status": "accepted"},
        )
        self.assertIsInstance(event.id, uuid.UUID)
        self.assertEqual(event.event_type, "provider_accepted")
        self.assertEqual(event.source, EventSource.PLATFORM)
        self.assertEqual(event.safe_payload_summary["wamid"], "wamid.1001")

    def test_event_organization_must_match_report(self):
        with self.assertRaises(ValidationError) as ctx:
            DeliveryEvent.objects.create(
                organization=self.org_b,  # Mismatch with report's Org A
                report=self.report,
                event_type="test",
                source=EventSource.DOCFLOW,
            )
        self.assertIn("organization", ctx.exception.message_dict)

    def test_event_attempt_must_match_report(self):
        other_report = Report.objects.create(
            organization=self.org_a,
            lab=self.lab,
            branch=self.branch,
            recipient_phone_e164="+919999999999",
            content_sha256="c" * 64,
            file_size_bytes=40000,
            idempotency_key="e" * 64,
        )
        # Attempt belongs to self.report, not other_report
        with self.assertRaises(ValidationError) as ctx:
            DeliveryEvent.objects.create(
                organization=self.org_a,
                report=other_report,
                delivery_attempt=self.attempt,
                event_type="test",
                source=EventSource.DOCFLOW,
            )
        self.assertIn("delivery_attempt", ctx.exception.message_dict)

    def test_safe_payload_summary_rejects_raw_payload_and_tokens(self):
        with self.assertRaises(ValidationError) as ctx:
            DeliveryEvent.objects.create(
                organization=self.org_a,
                report=self.report,
                event_type="test",
                source=EventSource.PLATFORM,
                safe_payload_summary={"raw_payload": "{'all': 'data'}"},
            )
        self.assertIn("safe_payload_summary", ctx.exception.message_dict)

        with self.assertRaises(ValidationError) as ctx:
            DeliveryEvent.objects.create(
                organization=self.org_a,
                report=self.report,
                event_type="test",
                source=EventSource.PLATFORM,
                safe_payload_summary={"access_token": "secret-token-123"},
            )
        self.assertIn("safe_payload_summary", ctx.exception.message_dict)

    def test_safe_payload_summary_rejects_nested_forbidden_keys(self):
        """Forbidden keys in nested dictionaries must be caught recursively."""
        nested_payloads = [
            {"details": {"accessToken": "secret-123"}},
            {"meta": {"auth": {"token": "xyz"}}},
            {"wrapper": {"payload": {"data": 1}}},
        ]
        for payload in nested_payloads:
            with self.assertRaises(ValidationError) as ctx:
                DeliveryEvent.objects.create(
                    organization=self.org_a,
                    report=self.report,
                    event_type="test",
                    source=EventSource.PLATFORM,
                    safe_payload_summary=payload,
                )
            self.assertIn("safe_payload_summary", ctx.exception.message_dict)

    def test_safe_payload_summary_rejects_forbidden_keys_in_lists(self):
        """Forbidden keys within lists of objects must be caught recursively."""
        list_payloads = [
            {"items": [{"raw-payload": "data"}]},
            {"records": [{"nested": [{"secret": "val"}]}]},
        ]
        for payload in list_payloads:
            with self.assertRaises(ValidationError) as ctx:
                DeliveryEvent.objects.create(
                    organization=self.org_a,
                    report=self.report,
                    event_type="test",
                    source=EventSource.PLATFORM,
                    safe_payload_summary=payload,
                )
            self.assertIn("safe_payload_summary", ctx.exception.message_dict)

    def test_safe_payload_summary_rejects_alternate_key_spellings(self):
        """Case variants, hyphens, underscores, and camelCase cannot bypass checks."""
        variant_keys = [
            "accessToken",
            "access_token",
            "ACCESS_TOKEN",
            "raw-payload",
            "raw_payload",
            "RawPayload",
            "RAW-PAYLOAD",
            "ApiKey",
            "api_key",
            "API-KEY",
            "Bearer",
            "Password",
        ]
        for key in variant_keys:
            with self.assertRaises(ValidationError) as ctx:
                DeliveryEvent.objects.create(
                    organization=self.org_a,
                    report=self.report,
                    event_type="test",
                    source=EventSource.PLATFORM,
                    safe_payload_summary={key: "sensitive_val"},
                )
            self.assertIn("safe_payload_summary", ctx.exception.message_dict)

    def test_safe_payload_summary_rejects_unrecognized_fields(self):
        """Arbitrary unrecognized fields not in the documented safe summary allowlist must be rejected."""
        unrecognized_payloads = [
            {"arbitrary_field": "val"},
            {"custom_meta": 123},
            {"internal_routing_id": "route-99"},
        ]
        for payload in unrecognized_payloads:
            with self.assertRaises(ValidationError) as ctx:
                DeliveryEvent.objects.create(
                    organization=self.org_a,
                    report=self.report,
                    event_type="test",
                    source=EventSource.PLATFORM,
                    safe_payload_summary=payload,
                )
            self.assertIn("safe_payload_summary", ctx.exception.message_dict)

    def test_safe_payload_summary_rejects_arbitrary_nested_objects(self):
        """Permitted keys cannot hold arbitrary nested dicts or lists."""
        nested_objects = [
            {"wamid": {"nested_id": "123"}},
            {"status": ["accepted", "sent"]},
            {"error_code": {"code": 404}},
        ]
        for payload in nested_objects:
            with self.assertRaises(ValidationError) as ctx:
                DeliveryEvent.objects.create(
                    organization=self.org_a,
                    report=self.report,
                    event_type="test",
                    source=EventSource.PLATFORM,
                    safe_payload_summary=payload,
                )
            self.assertIn("safe_payload_summary", ctx.exception.message_dict)

    def test_safe_payload_summary_allows_valid_safe_summaries(self):
        """Documented safe summary fields with primitive values must succeed."""
        valid_summaries = [
            {},
            {"wamid": "wamid.HBgLMTE...", "status": "delivered"},
            {
                "wamid": "wamid.123",
                "status": "failed",
                "error_code": "user_opt_out",
                "error_message": "User has opted out of WhatsApp messages.",
            },
            {"status": "accepted", "timestamp": "2026-10-14T20:00:00Z"},
            {"event_id": "evt_456", "reason": "rate_limited"},
        ]
        for summary in valid_summaries:
            event = DeliveryEvent.objects.create(
                organization=self.org_a,
                report=self.report,
                event_type="test_valid",
                source=EventSource.PLATFORM,
                safe_payload_summary=summary,
            )
            self.assertEqual(event.safe_payload_summary, summary)

    def test_safe_payload_summary_enforced_on_save_and_clean(self):
        """Validation is enforced both during full_clean and on direct save."""
        event = DeliveryEvent(
            organization=self.org_a,
            report=self.report,
            event_type="test",
            source=EventSource.PLATFORM,
            safe_payload_summary={"accessToken": "leaked_token"},
        )
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("safe_payload_summary", ctx.exception.message_dict)

        with self.assertRaises(ValidationError) as ctx:
            event.save()
        self.assertIn("safe_payload_summary", ctx.exception.message_dict)



class DispatchOutboxModelTest(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A", slug="org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="org-b")
        self.lab = Lab.objects.create(organization=self.org_a, name="Lab A", code="LA")
        self.branch = Branch.objects.create(
            organization=self.org_a, lab=self.lab, name="Branch A", code="BA"
        )
        self.report = Report.objects.create(
            organization=self.org_a,
            lab=self.lab,
            branch=self.branch,
            recipient_phone_e164="+919876543210",
            content_sha256="a" * 64,
            file_size_bytes=50000,
            idempotency_key="b" * 64,
        )
        self.attempt = DeliveryAttempt.objects.create(
            organization=self.org_a,
            report=self.report,
            attempt_number=1,
        )

    def test_create_outbox_item(self):
        item = DispatchOutbox.objects.create(
            organization=self.org_a,
            report=self.report,
            delivery_attempt=self.attempt,
            event_type="send_message",
        )
        self.assertIsInstance(item.id, uuid.UUID)
        self.assertEqual(item.state, OutboxState.PENDING)
        self.assertEqual(item.attempt_count, 0)
        self.assertIsNone(item.claimed_at)
        self.assertIsNone(item.claim_expires_at)
        self.assertEqual(item.last_error_code, "")

    def test_outbox_organization_must_match_report(self):
        with self.assertRaises(ValidationError) as ctx:
            DispatchOutbox.objects.create(
                organization=self.org_b,
                report=self.report,
                event_type="send_message",
            )
        self.assertIn("organization", ctx.exception.message_dict)

    def test_outbox_attempt_must_match_report(self):
        other_report = Report.objects.create(
            organization=self.org_a,
            lab=self.lab,
            branch=self.branch,
            recipient_phone_e164="+919999999999",
            content_sha256="c" * 64,
            file_size_bytes=40000,
            idempotency_key="e" * 64,
        )
        with self.assertRaises(ValidationError) as ctx:
            DispatchOutbox.objects.create(
                organization=self.org_a,
                report=other_report,
                delivery_attempt=self.attempt,
                event_type="send_message",
            )
        self.assertIn("delivery_attempt", ctx.exception.message_dict)

    def test_outbox_states_and_claiming_lifecycle(self):
        now = tz_utils.now()
        item = DispatchOutbox.objects.create(
            organization=self.org_a,
            report=self.report,
            delivery_attempt=self.attempt,
            state=OutboxState.CLAIMED,
            claimed_at=now,
            claim_expires_at=now + timedelta(seconds=60),
            attempt_count=1,
        )
        self.assertEqual(item.state, OutboxState.CLAIMED)
        self.assertEqual(item.attempt_count, 1)

        # Transition to completed
        item.state = OutboxState.COMPLETED
        item.save()
        item.refresh_from_db()
        self.assertEqual(item.state, OutboxState.COMPLETED)
