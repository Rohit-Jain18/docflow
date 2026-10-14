"""
Tests for AuditEvent and WebhookReceipt models (Phase 1, Task 2E).

Covers:
  - AuditEvent: UUID PK, action choices, nullable organization FK only for platform actions,
    actor-device tenant consistency, strict metadata allowlist, bounded scalar validation,
    sensitive value inspection (PDF, URL, token, raw payload, phone numbers),
    and append-only immutability.
  - WebhookReceipt: UUID PK, provider-scoped uniqueness, identity immutability,
    processing-state updates, and safe error codes.
  - Django Admin registrations and permissions.
"""

import uuid
from datetime import timedelta

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone as tz_utils

from apps.audit.admin import AuditEventAdmin, WebhookReceiptAdmin
from apps.audit.models import (
    ALLOWED_AUDIT_METADATA_KEYS,
    AuditAction,
    AuditEvent,
    WebhookProcessingState,
    WebhookReceipt,
)
from apps.devices.models import Device, DeviceStatus
from apps.tenants.models import Branch, Lab, Organization

User = get_user_model()


class AuditEventModelTest(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A", slug="org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="org-b")
        self.lab_a = Lab.objects.create(organization=self.org_a, name="Lab A", code="LA")
        self.branch_a = Branch.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            name="Branch A",
            code="BA",
        )
        self.device_a = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            name="Device A",
            status=DeviceStatus.ACTIVE,
        )
        self.user_a = User.objects.create_user(
            email="auditor@docflow.test",
            password="test-password-123",
            display_name="Auditor A",
        )

    # -----------------------------------------------------------------------
    # Basic creation and representation
    # -----------------------------------------------------------------------

    def test_create_valid_tenant_audit_event(self):
        event = AuditEvent.objects.create(
            organization=self.org_a,
            actor_user=self.user_a,
            actor_device=self.device_a,
            action=AuditAction.DEVICE_ACTIVATED,
            target_type="device",
            target_id=str(self.device_a.id),
            request_id="req-12345",
            safe_metadata={"device_name": "Device A", "attempt_count": 1},
        )
        self.assertIsInstance(event.id, uuid.UUID)
        self.assertIsNotNone(event.timestamp)
        self.assertEqual(event.organization, self.org_a)
        self.assertEqual(event.action, AuditAction.DEVICE_ACTIVATED)
        self.assertIn("org-a", str(event))
        self.assertIn("device_activated", str(event))

    def test_create_valid_platform_audit_event_without_organization(self):
        event = AuditEvent.objects.create(
            organization=None,
            actor_user=self.user_a,
            action=AuditAction.PLATFORM_CONFIG_CHANGED,
            target_type="system_config",
            target_id="TEMP_UPLOAD_MODE",
            safe_metadata={"config_key": "TEMP_UPLOAD_MODE", "new_value": "disabled"},
        )
        self.assertIsNone(event.organization)
        self.assertEqual(event.action, AuditAction.PLATFORM_CONFIG_CHANGED)
        self.assertIn("platform", str(event))

    # -----------------------------------------------------------------------
    # Platform-level organization rules
    # -----------------------------------------------------------------------

    def test_tenant_action_without_organization_is_rejected(self):
        tenant_actions = [
            AuditAction.DEVICE_ACTIVATED,
            AuditAction.DEVICE_REVOKED,
            AuditAction.WHATSAPP_ACCOUNT_ASSIGNED,
            AuditAction.ROLE_ASSIGNED,
            AuditAction.REPORT_RESENT,
            AuditAction.SECURITY_FAILURE,
        ]
        for action in tenant_actions:
            with self.subTest(action=action):
                event = AuditEvent(
                    organization=None,
                    action=action,
                    target_type="test",
                    target_id="123",
                )
                with self.assertRaises(ValidationError) as ctx:
                    event.full_clean()
                self.assertIn("organization", ctx.exception.message_dict)

    def test_explicit_platform_actions_allow_null_organization(self):
        platform_actions = [
            AuditAction.PLATFORM_CONFIG_CHANGED,
            AuditAction.PLATFORM_ADMIN_ACCESS,
            AuditAction.PLATFORM_SECURITY_FAILURE,
            AuditAction.PLATFORM_MAINTENANCE,
            AuditAction.PLATFORM_SYSTEM_EVENT,
        ]
        for action in platform_actions:
            with self.subTest(action=action):
                event = AuditEvent(
                    organization=None,
                    action=action,
                    target_type="platform_target",
                    target_id="sys-1",
                )
                # full_clean should not raise for null organization
                event.full_clean()
                event.save()
                self.assertIsNone(event.organization)

    # -----------------------------------------------------------------------
    # Actor-device tenant consistency
    # -----------------------------------------------------------------------

    def test_actor_device_tenant_consistency_matching(self):
        event = AuditEvent(
            organization=self.org_a,
            actor_device=self.device_a,
            action=AuditAction.DEVICE_ACTIVATED,
        )
        event.full_clean()
        event.save()
        self.assertEqual(event.actor_device, self.device_a)

    def test_actor_device_cross_tenant_mismatch_is_rejected(self):
        event = AuditEvent(
            organization=self.org_b,
            actor_device=self.device_a,  # device belongs to org_a
            action=AuditAction.DEVICE_ACTIVATED,
        )
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("actor_device", ctx.exception.message_dict)

    def test_actor_device_on_platform_level_event_without_organization_is_rejected(self):
        event = AuditEvent(
            organization=None,
            actor_device=self.device_a,
            action=AuditAction.PLATFORM_CONFIG_CHANGED,
        )
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("actor_device", ctx.exception.message_dict)

    # -----------------------------------------------------------------------
    # Metadata validation: Allowlist & Key Format
    # -----------------------------------------------------------------------

    def test_safe_metadata_must_be_dict(self):
        event = AuditEvent(
            organization=self.org_a,
            action=AuditAction.DEVICE_ACTIVATED,
            safe_metadata="not-a-dict",
        )
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("safe_metadata", ctx.exception.message_dict)

    def test_allowlisted_keys_with_scalar_values_succeed(self):
        metadata = {
            "reason": "Routine activation",
            "attempt_count": 1,
            "attempt_number": 2,
            "role": "branch_manager",
            "config_key": "AGENT_CLEANUP_RETENTION_HOURS",
            "new_value": "48",
            "status": "active",
            "ip_address": "192.168.1.10",
        }
        event = AuditEvent(
            organization=self.org_a,
            action=AuditAction.CONFIG_CHANGED,
            safe_metadata=metadata,
        )
        event.full_clean()
        event.save()
        self.assertEqual(event.safe_metadata["new_value"], "48")

    def test_unknown_metadata_key_is_rejected(self):
        event = AuditEvent(
            organization=self.org_a,
            action=AuditAction.DEVICE_ACTIVATED,
            safe_metadata={"unrecognized_custom_field": "some_value"},
        )
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("safe_metadata", ctx.exception.message_dict)

    def test_unsafe_key_variants_rejected(self):
        invalid_keys = [
            "Reason",           # PascalCase
            "attemptCount",     # camelCase
            "device-name",      # kebab-case
            "device name",      # spaces
            "USER_ID",          # UPPERCASE
            "config__key",      # double underscore
        ]
        for key in invalid_keys:
            with self.subTest(key=key):
                event = AuditEvent(
                    organization=self.org_a,
                    action=AuditAction.DEVICE_ACTIVATED,
                    safe_metadata={key: "value"},
                )
                with self.assertRaises(ValidationError) as ctx:
                    event.full_clean()
                self.assertIn("safe_metadata", ctx.exception.message_dict)

    def test_forbidden_key_patterns_rejected(self):
        forbidden_keys = [
            "token",
            "auth_token",
            "secret_key",
            "password",
            "credential",
            "raw_payload",
            "webhook_payload",
            "body",
            "pdf_bytes",
            "download_url",
            "patient_name",
            "phone_number",
        ]
        for key in forbidden_keys:
            with self.subTest(key=key):
                event = AuditEvent(
                    organization=self.org_a,
                    action=AuditAction.SECURITY_FAILURE,
                    safe_metadata={key: "value"},
                )
                with self.assertRaises(ValidationError) as ctx:
                    event.full_clean()
                self.assertIn("safe_metadata", ctx.exception.message_dict)

    # -----------------------------------------------------------------------
    # Metadata validation: Value Structure and Scalar Types
    # -----------------------------------------------------------------------

    def test_nested_objects_in_metadata_are_rejected(self):
        nested_values = [
            {"nested": "dictionary"},
            ["list", "of", "items"],
            ("tuple", "items"),
            {"set_item"},
        ]
        for val in nested_values:
            with self.subTest(val=val):
                event = AuditEvent(
                    organization=self.org_a,
                    action=AuditAction.DEVICE_ACTIVATED,
                    safe_metadata={"reason": val},
                )
                with self.assertRaises(ValidationError) as ctx:
                    event.full_clean()
                self.assertIn("safe_metadata", ctx.exception.message_dict)

    def test_null_value_in_metadata_is_rejected(self):
        event = AuditEvent(
            organization=self.org_a,
            action=AuditAction.DEVICE_ACTIVATED,
            safe_metadata={"reason": None},
        )
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("safe_metadata", ctx.exception.message_dict)

    def test_oversized_value_is_rejected(self):
        event = AuditEvent(
            organization=self.org_a,
            action=AuditAction.DEVICE_ACTIVATED,
            safe_metadata={"reason": "a" * 256},
        )
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("safe_metadata", ctx.exception.message_dict)

    # -----------------------------------------------------------------------
    # Metadata validation: Content Security (Defense-in-Depth)
    # -----------------------------------------------------------------------

    def test_pdf_contents_in_value_are_rejected(self):
        event = AuditEvent(
            organization=self.org_a,
            action=AuditAction.DEVICE_ACTIVATED,
            safe_metadata={"reason": "%PDF-1.4 binary content header"},
        )
        with self.assertRaises(ValidationError) as ctx:
            event.full_clean()
        self.assertIn("safe_metadata", ctx.exception.message_dict)

    def test_urls_in_value_are_rejected(self):
        urls = [
            "https://tmpfiles.org/dl/1234/report.pdf",
            "http://example.com/api/callback",
            "HTTPS://INTERNAL.CORP/DOC",
        ]
        for url in urls:
            with self.subTest(url=url):
                event = AuditEvent(
                    organization=self.org_a,
                    action=AuditAction.DEVICE_ACTIVATED,
                    safe_metadata={"reason": url},
                )
                with self.assertRaises(ValidationError) as ctx:
                    event.full_clean()
                self.assertIn("safe_metadata", ctx.exception.message_dict)

    def test_tokens_in_value_are_rejected(self):
        tokens = [
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
            "token abcdef1234567890",
            "eyJhbGciOiJIUzI1NiJ9.payload.signature",
        ]
        for tok in tokens:
            with self.subTest(tok=tok):
                event = AuditEvent(
                    organization=self.org_a,
                    action=AuditAction.SECURITY_FAILURE,
                    safe_metadata={"failure_reason": tok},
                )
                with self.assertRaises(ValidationError) as ctx:
                    event.full_clean()
                self.assertIn("safe_metadata", ctx.exception.message_dict)

    def test_raw_serialized_payloads_in_value_are_rejected(self):
        raw_payloads = [
            '{"event": "delivery_receipt", "status": "sent"}',
            '[{"id": 1, "data": "value"}]',
        ]
        for payload in raw_payloads:
            with self.subTest(payload=payload):
                event = AuditEvent(
                    organization=self.org_a,
                    action=AuditAction.SECURITY_FAILURE,
                    safe_metadata={"error_message": payload},
                )
                with self.assertRaises(ValidationError) as ctx:
                    event.full_clean()
                self.assertIn("safe_metadata", ctx.exception.message_dict)

    def test_raw_patient_phone_numbers_in_value_are_rejected(self):
        phones = [
            "+919876543210",
            "+12025550123",
            "+447911123456",
        ]
        for phone in phones:
            with self.subTest(phone=phone):
                event = AuditEvent(
                    organization=self.org_a,
                    action=AuditAction.DEVICE_ACTIVATED,
                    safe_metadata={"reason": phone},
                )
                with self.assertRaises(ValidationError) as ctx:
                    event.full_clean()
                self.assertIn("safe_metadata", ctx.exception.message_dict)

    # -----------------------------------------------------------------------
    # Append-only immutability
    # -----------------------------------------------------------------------

    def test_persisted_audit_event_cannot_be_modified(self):
        event = AuditEvent.objects.create(
            organization=self.org_a,
            action=AuditAction.DEVICE_ACTIVATED,
            target_type="device",
            target_id=str(self.device_a.id),
        )
        event.action = AuditAction.DEVICE_REVOKED
        with self.assertRaises(ValidationError) as ctx:
            event.save()
        self.assertIn("immutable", str(ctx.exception).lower())

    def test_persisted_audit_event_cannot_be_deleted(self):
        event = AuditEvent.objects.create(
            organization=self.org_a,
            action=AuditAction.DEVICE_ACTIVATED,
            target_type="device",
            target_id=str(self.device_a.id),
        )
        with self.assertRaises(ValidationError) as ctx:
            event.delete()
        self.assertIn("cannot be deleted", str(ctx.exception).lower())

    def test_queryset_update_is_blocked(self):
        event = AuditEvent.objects.create(
            organization=self.org_a,
            action=AuditAction.DEVICE_ACTIVATED,
            target_type="device",
            target_id=str(self.device_a.id),
        )
        with self.assertRaises(ValidationError) as ctx:
            AuditEvent.objects.filter(id=event.id).update(action=AuditAction.DEVICE_REVOKED)
        self.assertIn("immutable", str(ctx.exception).lower())

    def test_queryset_delete_is_blocked(self):
        event = AuditEvent.objects.create(
            organization=self.org_a,
            action=AuditAction.DEVICE_ACTIVATED,
            target_type="device",
            target_id=str(self.device_a.id),
        )
        with self.assertRaises(ValidationError) as ctx:
            AuditEvent.objects.filter(id=event.id).delete()
        self.assertIn("cannot be deleted", str(ctx.exception).lower())


class WebhookReceiptModelTest(TestCase):
    def test_create_minimal_webhook_receipt(self):
        receipt = WebhookReceipt.objects.create(
            provider_key="kiziee",
            external_event_key="evt_001_meta_msg",
        )
        self.assertIsInstance(receipt.id, uuid.UUID)
        self.assertEqual(receipt.provider_key, "kiziee")
        self.assertEqual(receipt.external_event_key, "evt_001_meta_msg")
        self.assertEqual(receipt.processing_state, WebhookProcessingState.RECEIVED)
        self.assertIsNotNone(receipt.received_at)
        self.assertIsNone(receipt.processed_at)
        self.assertEqual(receipt.safe_error_code, "")
        self.assertIn("kiziee", str(receipt))
        self.assertIn("evt_001_meta_msg", str(receipt))

    def test_provider_scoped_duplicate_suppression_uniqueness(self):
        WebhookReceipt.objects.create(
            provider_key="kiziee",
            external_event_key="evt_unique_123",
        )

        # Same provider_key and external_event_key must fail
        with self.assertRaises(IntegrityError):
            WebhookReceipt.objects.create(
                provider_key="kiziee",
                external_event_key="evt_unique_123",
            )

    def test_different_provider_same_external_event_key_is_permitted(self):
        r1 = WebhookReceipt.objects.create(
            provider_key="kiziee",
            external_event_key="evt_shared_id_456",
        )
        r2 = WebhookReceipt.objects.create(
            provider_key="provider_b",
            external_event_key="evt_shared_id_456",
        )
        self.assertNotEqual(r1.id, r2.id)

    def test_event_identity_immutability(self):
        receipt = WebhookReceipt.objects.create(
            provider_key="kiziee",
            external_event_key="evt_immutable_789",
        )

        # Attempt to change provider_key
        receipt.provider_key = "tampered_provider"
        with self.assertRaises(ValidationError) as ctx:
            receipt.save()
        self.assertIn("provider_key", ctx.exception.message_dict)

        # Refresh and attempt to change external_event_key
        receipt.refresh_from_db()
        receipt.external_event_key = "tampered_key"
        with self.assertRaises(ValidationError) as ctx:
            receipt.save()
        self.assertIn("external_event_key", ctx.exception.message_dict)

        # Refresh and attempt to change received_at
        receipt.refresh_from_db()
        receipt.received_at = tz_utils.now() - timedelta(days=1)
        with self.assertRaises(ValidationError) as ctx:
            receipt.save()
        self.assertIn("received_at", ctx.exception.message_dict)

    def test_legitimate_processing_state_lifecycle_updates(self):
        receipt = WebhookReceipt.objects.create(
            provider_key="kiziee",
            external_event_key="evt_lifecycle_101",
        )
        self.assertEqual(receipt.processing_state, WebhookProcessingState.RECEIVED)

        # Transition to PROCESSED
        processed_time = tz_utils.now()
        receipt.processing_state = WebhookProcessingState.PROCESSED
        receipt.processed_at = processed_time
        receipt.save()

        receipt.refresh_from_db()
        self.assertEqual(receipt.processing_state, WebhookProcessingState.PROCESSED)
        self.assertIsNotNone(receipt.processed_at)

        # Transition to FAILED with safe error code
        receipt.processing_state = WebhookProcessingState.FAILED
        receipt.safe_error_code = "report_not_found"
        receipt.save()

        receipt.refresh_from_db()
        self.assertEqual(receipt.processing_state, WebhookProcessingState.FAILED)
        self.assertEqual(receipt.safe_error_code, "report_not_found")


class AuditAdminTest(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.audit_admin = AuditEventAdmin(AuditEvent, self.site)
        self.receipt_admin = WebhookReceiptAdmin(WebhookReceipt, self.site)
        self.org = Organization.objects.create(name="Admin Org", slug="admin-org")
        self.event = AuditEvent.objects.create(
            organization=self.org,
            action=AuditAction.DEVICE_ACTIVATED,
            target_type="device",
            target_id="dev-123",
        )
        self.receipt = WebhookReceipt.objects.create(
            provider_key="kiziee",
            external_event_key="evt_admin_test",
        )

    def test_audit_event_admin_permissions(self):
        self.assertFalse(self.audit_admin.has_add_permission(None))
        self.assertFalse(self.audit_admin.has_change_permission(None, self.event))
        self.assertFalse(self.audit_admin.has_delete_permission(None, self.event))

    def test_audit_event_admin_readonly_fields(self):
        readonly = self.audit_admin.get_readonly_fields(None, self.event)
        model_field_names = [f.name for f in AuditEvent._meta.fields]
        for field_name in model_field_names:
            self.assertIn(field_name, readonly)

    def test_webhook_receipt_admin_permissions(self):
        self.assertFalse(self.receipt_admin.has_delete_permission(None, self.receipt))

    def test_webhook_receipt_admin_readonly_fields(self):
        # On new instance
        new_readonly = self.receipt_admin.get_readonly_fields(None, None)
        self.assertIn("id", new_readonly)
        self.assertIn("received_at", new_readonly)
        self.assertNotIn("provider_key", new_readonly)

        # On existing instance, identity fields must be read-only
        existing_readonly = self.receipt_admin.get_readonly_fields(None, self.receipt)
        self.assertIn("id", existing_readonly)
        self.assertIn("received_at", existing_readonly)
        self.assertIn("provider_key", existing_readonly)
        self.assertIn("external_event_key", existing_readonly)
