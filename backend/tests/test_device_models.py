"""
Tests for device and credential models (Phase 1, Task 2B).

Covers:
- Device: UUID PK, choices, platform default, IP address, timestamps,
  and tenant consistency (branch must belong to device's organization;
  persisted device organization immutability).
- DeviceActivationCode: UUID PK, code_hash uniqueness and storage, default
  10-minute expiry, consumed/revoked lifecycle, helper properties, and
  mutual organization/branch/device consistency.
- DeviceRefreshCredential: UUID PK, credential_hash uniqueness and storage,
  rotation via replaced_by self-reference, revocation, same-device replacement
  enforcement, and helper properties.
- Admin security: Credential and activation hashes excluded from list_display.
"""

import datetime
import uuid

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone as tz_utils

from apps.devices.admin import (
    DeviceActivationCodeAdmin,
    DeviceAdmin,
    DeviceRefreshCredentialAdmin,
)
from apps.devices.models import (
    Device,
    DeviceActivationCode,
    DeviceRefreshCredential,
    DeviceStatus,
)
from apps.tenants.models import Branch, Lab, Organization
from apps.users.models import User


class DeviceModelTest(TestCase):
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

    def test_create_device_defaults(self):
        device = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            name="Lab Front Desk PC",
        )
        self.assertIsInstance(device.id, uuid.UUID)
        self.assertEqual(device.status, DeviceStatus.PENDING_ACTIVATION)
        self.assertEqual(device.platform, "windows")
        self.assertEqual(device.agent_version, "")
        self.assertIsNone(device.last_seen_at)
        self.assertIsNone(device.last_ip)
        self.assertIsNone(device.activated_at)
        self.assertIsNone(device.revoked_at)
        self.assertIsNotNone(device.created_at)
        self.assertIsNotNone(device.updated_at)

    def test_str_representation(self):
        device = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            name="Lab Front Desk PC",
        )
        self.assertEqual(str(device), "Lab Front Desk PC (Pending Activation)")

    def test_device_status_choices(self):
        for status_val in DeviceStatus.values:
            device = Device.objects.create(
                organization=self.org_a,
                branch=self.branch_a,
                name=f"Device {status_val}",
                status=status_val,
            )
            device.full_clean()
            self.assertEqual(device.status, status_val)

    def test_device_with_optional_fields(self):
        now = tz_utils.now()
        device = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            name="Instrument PC",
            agent_version="1.2.0",
            last_ip="192.168.1.100",
            last_seen_at=now,
            activated_at=now,
        )
        self.assertEqual(device.agent_version, "1.2.0")
        self.assertEqual(device.last_ip, "192.168.1.100")
        self.assertEqual(device.last_seen_at, now)
        self.assertEqual(device.activated_at, now)

    def test_cross_org_branch_rejected_on_device_save(self):
        """Device under Org A with Branch from Org B must be rejected on save()."""
        device = Device(
            organization=self.org_a,
            branch=self.branch_b,  # Branch B belongs to Org B!
            name="Mismatched Device",
        )
        with self.assertRaises(ValidationError) as ctx:
            device.save()
        self.assertIn("branch", ctx.exception.message_dict)

    def test_cross_org_branch_rejected_on_device_create(self):
        with self.assertRaises(ValidationError) as ctx:
            Device.objects.create(
                organization=self.org_a,
                branch=self.branch_b,
                name="Mismatched Create",
            )
        self.assertIn("branch", ctx.exception.message_dict)

    def test_cross_org_branch_rejected_on_full_clean(self):
        device = Device(
            organization=self.org_a,
            branch=self.branch_b,
            name="Dirty Device",
        )
        with self.assertRaises(ValidationError) as ctx:
            device.full_clean()
        self.assertIn("branch", ctx.exception.message_dict)

    def test_persisted_device_organization_cannot_be_changed(self):
        device = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            name="Valid Device",
        )
        # Changing organization while branch is unchanged
        device.organization = self.org_b
        with self.assertRaises(ValidationError) as ctx:
            device.save()
        self.assertIn("organization", ctx.exception.message_dict)

        # Changing both organization and branch to Org B
        device.branch = self.branch_b
        with self.assertRaises(ValidationError) as ctx:
            device.save()
        self.assertIn("organization", ctx.exception.message_dict)

        device.refresh_from_db()
        self.assertEqual(device.organization, self.org_a)
        self.assertEqual(device.branch, self.branch_a)

    def test_normal_device_update_succeeds(self):
        device = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            name="Initial Name",
        )
        device.name = "Updated Name"
        device.status = DeviceStatus.ACTIVE
        device.save()
        device.refresh_from_db()
        self.assertEqual(device.name, "Updated Name")
        self.assertEqual(device.status, DeviceStatus.ACTIVE)

    def test_update_fields_skips_unnecessary_checks(self):
        device = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            name="Initial Name",
        )
        fresh_device = Device.objects.get(id=device.id)
        with self.assertNumQueries(1):
            fresh_device.agent_version = "2.0.0"
            fresh_device.save(update_fields=["agent_version"])
        fresh_device.refresh_from_db()
        self.assertEqual(fresh_device.agent_version, "2.0.0")

    def test_device_admin_organization_readonly_on_existing_instance(self):
        site = AdminSite()
        admin = DeviceAdmin(Device, site)
        device = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            name="Admin Test PC",
        )
        readonly_create = admin.get_readonly_fields(request=None, obj=None)
        self.assertNotIn("organization", readonly_create)

        readonly_change = admin.get_readonly_fields(request=None, obj=device)
        self.assertIn("organization", readonly_change)


class DeviceActivationCodeModelTest(TestCase):
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
            organization=self.org_a,
            branch=self.branch_a,
            name="Device A",
        )
        self.user = User.objects.create_user(email="admin@example.test", password="p")

    def test_create_activation_code_defaults(self):
        code = DeviceActivationCode.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            device=self.device_a,
            created_by=self.user,
            code_hash="fake-sha256-hash-001",
        )
        self.assertIsInstance(code.id, uuid.UUID)
        self.assertEqual(code.code_hash, "fake-sha256-hash-001")
        self.assertEqual(code.attempt_count, 0)
        self.assertIsNone(code.consumed_at)
        self.assertIsNone(code.revoked_at)
        self.assertIsNotNone(code.created_at)

        # Default expiry should be approximately 10 minutes in the future
        time_diff = (code.expires_at - code.created_at).total_seconds()
        self.assertAlmostEqual(time_diff, 600, delta=5)

    def test_code_hash_uniqueness(self):
        DeviceActivationCode.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            device=self.device_a,
            code_hash="unique-hash-123",
        )
        with self.assertRaises(IntegrityError):
            DeviceActivationCode.objects.create(
                organization=self.org_a,
                branch=self.branch_a,
                device=self.device_a,
                code_hash="unique-hash-123",
            )

    def test_lifecycle_helper_properties(self):
        now = tz_utils.now()
        # Fresh active code
        code = DeviceActivationCode.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            device=self.device_a,
            code_hash="hash-lifecycle-1",
            expires_at=now + datetime.timedelta(minutes=10),
        )
        self.assertTrue(code.is_valid)
        self.assertFalse(code.is_expired)
        self.assertFalse(code.is_consumed)
        self.assertFalse(code.is_revoked)

        # Expired code
        code.expires_at = now - datetime.timedelta(seconds=1)
        self.assertTrue(code.is_expired)
        self.assertFalse(code.is_valid)

        # Consumed code
        code.expires_at = now + datetime.timedelta(minutes=10)
        code.consumed_at = now
        self.assertTrue(code.is_consumed)
        self.assertFalse(code.is_valid)

        # Revoked code
        code.consumed_at = None
        code.revoked_at = now
        self.assertTrue(code.is_revoked)
        self.assertFalse(code.is_valid)

    def test_cross_org_branch_rejected_on_activation_code(self):
        with self.assertRaises(ValidationError) as ctx:
            DeviceActivationCode.objects.create(
                organization=self.org_a,
                branch=self.branch_b,  # Branch B is in Org B
                device=self.device_a,
                code_hash="hash-mismatch-1",
            )
        self.assertIn("branch", ctx.exception.message_dict)

    def test_cross_org_device_rejected_on_activation_code(self):
        device_b = Device.objects.create(
            organization=self.org_b,
            branch=self.branch_b,
            name="Device in Org B",
        )
        with self.assertRaises(ValidationError) as ctx:
            DeviceActivationCode.objects.create(
                organization=self.org_a,
                branch=self.branch_a,
                device=device_b,  # Device is in Org B!
                code_hash="hash-mismatch-2",
            )
        self.assertIn("device", ctx.exception.message_dict)

    def test_cross_branch_device_rejected_on_activation_code(self):
        branch_a2 = Branch.objects.create(
            organization=self.org_a, lab=self.lab_a, name="Branch A2", code="BA2"
        )
        with self.assertRaises(ValidationError) as ctx:
            DeviceActivationCode.objects.create(
                organization=self.org_a,
                branch=branch_a2,  # branch_a2 differs from device_a.branch (branch_a)
                device=self.device_a,
                code_hash="hash-mismatch-3",
            )
        self.assertIn("device", ctx.exception.message_dict)

    def test_admin_does_not_display_code_hash(self):
        site = AdminSite()
        admin = DeviceActivationCodeAdmin(DeviceActivationCode, site)
        self.assertNotIn("code_hash", admin.list_display)


class DeviceRefreshCredentialModelTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Apex", slug="apex")
        self.lab = Lab.objects.create(organization=self.org, name="Lab", code="L")
        self.branch = Branch.objects.create(
            organization=self.org, lab=self.lab, name="Branch", code="B"
        )
        self.device = Device.objects.create(
            organization=self.org,
            branch=self.branch,
            name="Device",
        )

    def test_create_credential_defaults(self):
        now = tz_utils.now()
        cred = DeviceRefreshCredential.objects.create(
            device=self.device,
            credential_hash="cred-hash-001",
            expires_at=now + datetime.timedelta(days=30),
        )
        self.assertIsInstance(cred.id, uuid.UUID)
        self.assertEqual(cred.credential_hash, "cred-hash-001")
        self.assertIsNone(cred.rotated_at)
        self.assertIsNone(cred.revoked_at)
        self.assertIsNone(cred.replaced_by)
        self.assertTrue(cred.is_active)
        self.assertFalse(cred.is_rotated)
        self.assertFalse(cred.is_revoked)
        self.assertFalse(cred.is_expired)

    def test_credential_hash_uniqueness(self):
        now = tz_utils.now()
        DeviceRefreshCredential.objects.create(
            device=self.device,
            credential_hash="unique-cred-hash",
            expires_at=now + datetime.timedelta(days=30),
        )
        with self.assertRaises(IntegrityError):
            DeviceRefreshCredential.objects.create(
                device=self.device,
                credential_hash="unique-cred-hash",
                expires_at=now + datetime.timedelta(days=30),
            )

    def test_credential_rotation_relationship(self):
        now = tz_utils.now()
        cred_1 = DeviceRefreshCredential.objects.create(
            device=self.device,
            credential_hash="cred-hash-step-1",
            expires_at=now + datetime.timedelta(days=30),
        )
        cred_2 = DeviceRefreshCredential.objects.create(
            device=self.device,
            credential_hash="cred-hash-step-2",
            expires_at=now + datetime.timedelta(days=30),
        )
        # Rotate cred_1, replaced by cred_2
        cred_1.rotated_at = now
        cred_1.replaced_by = cred_2
        cred_1.save()

        cred_1.refresh_from_db()
        cred_2.refresh_from_db()
        self.assertEqual(cred_1.replaced_by, cred_2)
        self.assertEqual(cred_2.replaces, cred_1)
        self.assertTrue(cred_1.is_rotated)
        self.assertFalse(cred_1.is_active)
        self.assertTrue(cred_2.is_active)

    def test_cross_device_replacement_rejected(self):
        now = tz_utils.now()
        other_device = Device.objects.create(
            organization=self.org,
            branch=self.branch,
            name="Other Device",
        )
        cred_1 = DeviceRefreshCredential.objects.create(
            device=self.device,
            credential_hash="cred-device-1",
            expires_at=now + datetime.timedelta(days=30),
        )
        cred_other = DeviceRefreshCredential.objects.create(
            device=other_device,
            credential_hash="cred-other-device",
            expires_at=now + datetime.timedelta(days=30),
        )
        cred_1.replaced_by = cred_other
        with self.assertRaises(ValidationError) as ctx:
            cred_1.save()
        self.assertIn("replaced_by", ctx.exception.message_dict)

    def test_credential_revocation(self):
        now = tz_utils.now()
        cred = DeviceRefreshCredential.objects.create(
            device=self.device,
            credential_hash="cred-to-revoke",
            expires_at=now + datetime.timedelta(days=30),
        )
        self.assertTrue(cred.is_active)
        cred.revoked_at = now
        cred.save()
        cred.refresh_from_db()
        self.assertTrue(cred.is_revoked)
        self.assertFalse(cred.is_active)

    def test_credential_expiry_property(self):
        now = tz_utils.now()
        cred = DeviceRefreshCredential.objects.create(
            device=self.device,
            credential_hash="cred-expired",
            expires_at=now - datetime.timedelta(seconds=1),
        )
        self.assertTrue(cred.is_expired)
        self.assertFalse(cred.is_active)

    def test_admin_does_not_display_credential_hash(self):
        site = AdminSite()
        admin = DeviceRefreshCredentialAdmin(DeviceRefreshCredential, site)
        self.assertNotIn("credential_hash", admin.list_display)
