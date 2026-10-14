"""
Tests for WhatsApp account and branch assignment models (Phase 1, Task 2C).

Covers:
- WhatsAppAccount: UUID PK, provider defaults, status choices, credential_mode choices,
  opaque credential_secret_ref storage without token leakage, non-unique lookup index,
  persisted organization immutability, and admin list_display security.
- BranchWhatsAppAssignment: UUID PK, mutual branch/account tenant consistency,
  single active assignment constraint per branch, preservation of historical
  inactive assignments, and multiple inactive assignments support.
"""

import uuid

from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone as tz_utils

from apps.tenants.models import Branch, Lab, Organization
from apps.users.models import User
from apps.whatsapp.admin import (
    BranchWhatsAppAssignmentAdmin,
    WhatsAppAccountAdmin,
)
from apps.whatsapp.models import (
    AssignmentStatus,
    BranchWhatsAppAssignment,
    CredentialMode,
    WhatsAppAccount,
    WhatsAppAccountStatus,
)


class WhatsAppAccountModelTest(TestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A", slug="org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="org-b")
        self.user = User.objects.create_user(email="admin@example.test", password="p")

    def test_create_account_defaults(self):
        account = WhatsAppAccount.objects.create(
            organization=self.org_a,
            phone_number_id="100987654321",
        )
        self.assertIsInstance(account.id, uuid.UUID)
        self.assertEqual(account.provider_key, "kiziee")
        self.assertEqual(account.provider_account_reference, "")
        self.assertEqual(account.phone_number_id, "100987654321")
        self.assertEqual(account.display_phone_number, "")
        self.assertEqual(account.display_name, "")
        self.assertEqual(account.credential_mode, CredentialMode.PLATFORM_MANAGED)
        self.assertEqual(account.credential_secret_ref, "")
        self.assertEqual(account.status, WhatsAppAccountStatus.PENDING_VERIFICATION)
        self.assertIsNone(account.verified_at)
        self.assertIsNone(account.created_by)
        self.assertIsNotNone(account.created_at)
        self.assertIsNotNone(account.updated_at)

    def test_str_representation(self):
        account_with_name = WhatsAppAccount.objects.create(
            organization=self.org_a,
            phone_number_id="1001",
            display_name="Apex Alerts",
        )
        self.assertEqual(str(account_with_name), "Apex Alerts (Pending Verification)")

        account_without_name = WhatsAppAccount.objects.create(
            organization=self.org_a,
            phone_number_id="1002",
        )
        self.assertEqual(str(account_without_name), "1002 (Pending Verification)")

    def test_status_choices(self):
        for status_val in WhatsAppAccountStatus.values:
            account = WhatsAppAccount.objects.create(
                organization=self.org_a,
                phone_number_id=f"phone-{status_val}",
                status=status_val,
            )
            account.full_clean()
            self.assertEqual(account.status, status_val)

    def test_credential_mode_choices(self):
        for mode_val in CredentialMode.values:
            account = WhatsAppAccount.objects.create(
                organization=self.org_a,
                phone_number_id=f"phone-{mode_val}",
                credential_mode=mode_val,
            )
            account.full_clean()
            self.assertEqual(account.credential_mode, mode_val)

    def test_opaque_credential_secret_ref(self):
        account = WhatsAppAccount.objects.create(
            organization=self.org_a,
            phone_number_id="1003",
            credential_mode=CredentialMode.BACKEND_SECRET,
            credential_secret_ref="vault://secret/wa/org-a/token-1",
        )
        self.assertEqual(account.credential_secret_ref, "vault://secret/wa/org-a/token-1")

    def test_persisted_account_organization_cannot_be_changed(self):
        account = WhatsAppAccount.objects.create(
            organization=self.org_a,
            phone_number_id="1004",
        )
        account.organization = self.org_b
        with self.assertRaises(ValidationError) as ctx:
            account.save()
        self.assertIn("organization", ctx.exception.message_dict)

        account.refresh_from_db()
        self.assertEqual(account.organization, self.org_a)

    def test_multiple_accounts_can_share_phone_id_across_providers_or_orgs(self):
        # Non-unique index allows unresolved upstream provider uniqueness scopes
        acc1 = WhatsAppAccount.objects.create(
            organization=self.org_a,
            phone_number_id="shared-phone-id",
        )
        acc2 = WhatsAppAccount.objects.create(
            organization=self.org_b,
            phone_number_id="shared-phone-id",
        )
        self.assertEqual(acc1.phone_number_id, acc2.phone_number_id)
        self.assertNotEqual(acc1.organization, acc2.organization)

    def test_admin_does_not_display_credential_secret_ref(self):
        site = AdminSite()
        admin = WhatsAppAccountAdmin(WhatsAppAccount, site)
        self.assertNotIn("credential_secret_ref", admin.list_display)

    def test_admin_organization_readonly_on_edit(self):
        site = AdminSite()
        admin = WhatsAppAccountAdmin(WhatsAppAccount, site)
        account = WhatsAppAccount.objects.create(
            organization=self.org_a,
            phone_number_id="1005",
        )
        readonly_create = admin.get_readonly_fields(request=None, obj=None)
        self.assertNotIn("organization", readonly_create)

        readonly_edit = admin.get_readonly_fields(request=None, obj=account)
        self.assertIn("organization", readonly_edit)


class BranchWhatsAppAssignmentModelTest(TestCase):
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
        self.account_a1 = WhatsAppAccount.objects.create(
            organization=self.org_a,
            phone_number_id="wa-a1",
            display_name="Account A1",
        )
        self.account_a2 = WhatsAppAccount.objects.create(
            organization=self.org_a,
            phone_number_id="wa-a2",
            display_name="Account A2",
        )
        self.account_b = WhatsAppAccount.objects.create(
            organization=self.org_b,
            phone_number_id="wa-b",
            display_name="Account B",
        )
        self.user = User.objects.create_user(email="staff@example.test", password="p")

    def test_create_assignment_defaults(self):
        assignment = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_a1,
            assigned_by=self.user,
        )
        self.assertIsInstance(assignment.id, uuid.UUID)
        self.assertEqual(assignment.status, AssignmentStatus.ACTIVE)
        self.assertEqual(assignment.assigned_by, self.user)
        self.assertIsNotNone(assignment.assigned_at)
        self.assertIsNone(assignment.ended_at)

    def test_str_representation(self):
        assignment = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_a1,
        )
        self.assertIn("Branch A", str(assignment))
        self.assertIn("Account A1", str(assignment))
        self.assertIn("active", str(assignment))

    def test_cross_org_branch_rejected_on_assignment(self):
        """Branch from Org B cannot be assigned under Org A."""
        with self.assertRaises(ValidationError) as ctx:
            BranchWhatsAppAssignment.objects.create(
                organization=self.org_a,
                branch=self.branch_b,  # Branch B is in Org B
                whatsapp_account=self.account_a1,
            )
        self.assertIn("branch", ctx.exception.message_dict)

    def test_cross_org_account_rejected_on_assignment(self):
        """Account from Org B cannot be assigned to a branch in Org A."""
        with self.assertRaises(ValidationError) as ctx:
            BranchWhatsAppAssignment.objects.create(
                organization=self.org_a,
                branch=self.branch_a,
                whatsapp_account=self.account_b,  # Account B is in Org B
            )
        self.assertIn("whatsapp_account", ctx.exception.message_dict)

    def test_cross_org_assignment_rejected_on_full_clean(self):
        assignment = BranchWhatsAppAssignment(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_b,
        )
        with self.assertRaises(ValidationError) as ctx:
            assignment.full_clean()
        self.assertIn("whatsapp_account", ctx.exception.message_dict)

    def test_single_active_assignment_per_branch_enforced(self):
        """At most one active assignment can exist for a branch."""
        BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_a1,
            status=AssignmentStatus.ACTIVE,
        )
        # Attempt to create a second active assignment for the same branch
        with self.assertRaises(IntegrityError):
            BranchWhatsAppAssignment.objects.create(
                organization=self.org_a,
                branch=self.branch_a,
                whatsapp_account=self.account_a2,
                status=AssignmentStatus.ACTIVE,
            )

    def test_historical_inactive_assignments_preserved(self):
        """Deactivating an assignment allows a new active assignment on the same branch."""
        now = tz_utils.now()
        first_assignment = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_a1,
            status=AssignmentStatus.ACTIVE,
        )
        # Deactivate first assignment
        first_assignment.status = AssignmentStatus.INACTIVE
        first_assignment.ended_at = now
        first_assignment.save()

        # Now creating a new active assignment succeeds
        second_assignment = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_a2,
            status=AssignmentStatus.ACTIVE,
        )
        self.assertEqual(second_assignment.status, AssignmentStatus.ACTIVE)

        # Both records exist in the database (history preserved)
        branch_history = BranchWhatsAppAssignment.objects.filter(branch=self.branch_a)
        self.assertEqual(branch_history.count(), 2)

    def test_multiple_inactive_assignments_can_coexist(self):
        """Multiple historical inactive assignments for the same branch are allowed."""
        now = tz_utils.now()
        BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_a1,
            status=AssignmentStatus.INACTIVE,
            ended_at=now,
        )
        BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_a2,
            status=AssignmentStatus.INACTIVE,
            ended_at=now,
        )
        inactive_count = BranchWhatsAppAssignment.objects.filter(
            branch=self.branch_a, status=AssignmentStatus.INACTIVE
        ).count()
        self.assertEqual(inactive_count, 2)

    def test_admin_displays_assignment_fields(self):
        site = AdminSite()
        admin = BranchWhatsAppAssignmentAdmin(BranchWhatsAppAssignment, site)
        self.assertIn("branch", admin.list_display)
        self.assertIn("whatsapp_account", admin.list_display)
        self.assertIn("status", admin.list_display)

    def test_persisted_assignment_organization_cannot_be_changed(self):
        """Changing the organization of a persisted assignment must raise ValidationError."""
        assignment = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_a1,
        )
        assignment.organization = self.org_b
        with self.assertRaises(ValidationError) as ctx:
            assignment.save()
        self.assertIn("organization", ctx.exception.message_dict)

        with self.assertRaises(ValidationError) as ctx:
            assignment.full_clean()
        self.assertIn("organization", ctx.exception.message_dict)

        assignment.refresh_from_db()
        self.assertEqual(assignment.organization, self.org_a)

    def test_persisted_assignment_branch_cannot_be_changed(self):
        """Changing the branch of a persisted assignment must raise ValidationError."""
        branch_a2 = Branch.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            name="Branch A2",
            code="BA2",
        )
        assignment = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_a1,
        )
        assignment.branch = branch_a2
        with self.assertRaises(ValidationError) as ctx:
            assignment.save()
        self.assertIn("branch", ctx.exception.message_dict)

        with self.assertRaises(ValidationError) as ctx:
            assignment.full_clean()
        self.assertIn("branch", ctx.exception.message_dict)

        assignment.refresh_from_db()
        self.assertEqual(assignment.branch, self.branch_a)

    def test_persisted_assignment_whatsapp_account_cannot_be_changed(self):
        """Changing the WhatsApp account of a persisted assignment must raise ValidationError."""
        assignment = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_a1,
        )
        assignment.whatsapp_account = self.account_a2
        with self.assertRaises(ValidationError) as ctx:
            assignment.save()
        self.assertIn("whatsapp_account", ctx.exception.message_dict)

        with self.assertRaises(ValidationError) as ctx:
            assignment.full_clean()
        self.assertIn("whatsapp_account", ctx.exception.message_dict)

        assignment.refresh_from_db()
        self.assertEqual(assignment.whatsapp_account, self.account_a1)

    def test_persisted_assignment_multiple_relationship_changes_reported(self):
        """Changing multiple identity fields reports all corresponding validation errors."""
        branch_a2 = Branch.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            name="Branch A3",
            code="BA3",
        )
        assignment = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_a1,
        )
        assignment.branch = branch_a2
        assignment.whatsapp_account = self.account_a2
        with self.assertRaises(ValidationError) as ctx:
            assignment.clean()
        self.assertIn("branch", ctx.exception.message_dict)
        self.assertIn("whatsapp_account", ctx.exception.message_dict)

    def test_lifecycle_updates_allowed_on_persisted_assignment(self):
        """Legitimate lifecycle transitions (e.g. status and ended_at) must succeed."""
        now = tz_utils.now()
        assignment = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_a1,
            status=AssignmentStatus.ACTIVE,
        )
        # Normal save update
        assignment.status = AssignmentStatus.INACTIVE
        assignment.ended_at = now
        assignment.full_clean()
        assignment.save()

        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.INACTIVE)
        self.assertEqual(assignment.ended_at, now)

        # Update with update_fields
        assignment.status = AssignmentStatus.ACTIVE
        assignment.ended_at = None
        assignment.save(update_fields=["status", "ended_at"])

        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.ACTIVE)
        self.assertIsNone(assignment.ended_at)

    def test_admin_relationship_fields_readonly_on_edit(self):
        """Relationship fields are editable on creation, but read-only when editing."""
        site = AdminSite()
        admin = BranchWhatsAppAssignmentAdmin(BranchWhatsAppAssignment, site)
        assignment = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a,
            whatsapp_account=self.account_a1,
        )

        readonly_create = admin.get_readonly_fields(request=None, obj=None)
        self.assertNotIn("organization", readonly_create)
        self.assertNotIn("branch", readonly_create)
        self.assertNotIn("whatsapp_account", readonly_create)

        readonly_edit = admin.get_readonly_fields(request=None, obj=assignment)
        self.assertIn("organization", readonly_edit)
        self.assertIn("branch", readonly_edit)
        self.assertIn("whatsapp_account", readonly_edit)

