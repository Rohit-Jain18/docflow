"""
Tests for core tenancy models (Phase 1, Task 2A).

Covers:
- Organization: UUID PK, slug uniqueness, status choices, timezone, created_by FK, timestamps.
- OrganizationMembership: UUID PK, unique (organization, user), roles, status, timestamps.
- Lab: UUID PK, code unique within organization, default diagnostic lab_type, status, timestamps.
- Branch: UUID PK, code unique within lab, optional address/phone, timezone, status, timestamps.
- Tenant safety: Branch's lab must belong to the same organization, enforced on normal save(),
  create(), and full_clean(), without unnecessary queries on partial updates.
"""

import uuid
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase, override_settings

from apps.tenants.models import (
    Branch,
    BranchStatus,
    Lab,
    LabStatus,
    LabType,
    MembershipRole,
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)
from apps.users.models import User


class OrganizationModelTest(TestCase):
    def test_create_organization_defaults(self):
        org = Organization.objects.create(name="Apex Diagnostics", slug="apex-diag")
        self.assertIsInstance(org.id, uuid.UUID)
        self.assertEqual(org.name, "Apex Diagnostics")
        self.assertEqual(org.slug, "apex-diag")
        self.assertEqual(org.status, OrganizationStatus.ACTIVE)
        self.assertEqual(org.timezone, "UTC")
        self.assertIsNone(org.created_by)
        self.assertIsNotNone(org.created_at)
        self.assertIsNotNone(org.updated_at)

    def test_str_returns_name(self):
        org = Organization.objects.create(name="Apex Diagnostics", slug="apex-diag")
        self.assertEqual(str(org), "Apex Diagnostics")

    def test_slug_uniqueness(self):
        Organization.objects.create(name="Org 1", slug="common-slug")
        with self.assertRaises(IntegrityError):
            Organization.objects.create(name="Org 2", slug="common-slug")

    def test_status_choices(self):
        for status_choice in OrganizationStatus.values:
            org = Organization.objects.create(
                name=f"Org {status_choice}",
                slug=f"org-{status_choice}",
                status=status_choice,
            )
            org.full_clean()
            self.assertEqual(org.status, status_choice)

    def test_created_by_relation_and_set_null_on_user_delete(self):
        user = User.objects.create_user(email="creator@example.test", password="pass")
        org = Organization.objects.create(
            name="Org With Creator",
            slug="org-creator",
            created_by=user,
        )
        self.assertEqual(org.created_by, user)
        self.assertIn(org, user.created_organizations.all())

        user.delete()
        org.refresh_from_db()
        self.assertIsNone(org.created_by)


class OrganizationMembershipModelTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Apex", slug="apex")
        self.user = User.objects.create_user(email="member@example.test", password="pass")

    def test_create_membership_defaults(self):
        membership = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.user,
        )
        self.assertIsInstance(membership.id, uuid.UUID)
        self.assertEqual(membership.role, MembershipRole.OPERATOR)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertIsNotNone(membership.created_at)
        self.assertIsNotNone(membership.updated_at)

    def test_str_representation(self):
        membership = OrganizationMembership.objects.create(
            organization=self.org,
            user=self.user,
            role=MembershipRole.ORGANIZATION_ADMIN,
        )
        expected = f"{self.user} (organization_admin) @ {self.org}"
        self.assertEqual(str(membership), expected)

    def test_unique_organization_user_constraint(self):
        OrganizationMembership.objects.create(organization=self.org, user=self.user)
        with self.assertRaises(IntegrityError):
            OrganizationMembership.objects.create(organization=self.org, user=self.user)

    def test_same_user_can_belong_to_multiple_organizations(self):
        org2 = Organization.objects.create(name="Beta", slug="beta")
        m1 = OrganizationMembership.objects.create(organization=self.org, user=self.user)
        m2 = OrganizationMembership.objects.create(organization=org2, user=self.user)
        self.assertNotEqual(m1.organization, m2.organization)
        self.assertEqual(self.user.organization_memberships.count(), 2)

    def test_all_membership_roles(self):
        for role in MembershipRole.values:
            u = User.objects.create_user(email=f"user_{role}@example.test", password="p")
            m = OrganizationMembership.objects.create(
                organization=self.org,
                user=u,
                role=role,
            )
            m.full_clean()
            self.assertEqual(m.role, role)

    def test_cascade_delete_on_organization(self):
        OrganizationMembership.objects.create(organization=self.org, user=self.user)
        self.org.delete()
        self.assertEqual(OrganizationMembership.objects.count(), 0)

    def test_cascade_delete_on_user(self):
        OrganizationMembership.objects.create(organization=self.org, user=self.user)
        self.user.delete()
        self.assertEqual(OrganizationMembership.objects.count(), 0)


class LabModelTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Apex", slug="apex")

    def test_create_lab_defaults(self):
        lab = Lab.objects.create(organization=self.org, name="Central Lab", code="CEN-01")
        self.assertIsInstance(lab.id, uuid.UUID)
        self.assertEqual(lab.lab_type, LabType.DIAGNOSTIC)
        self.assertEqual(lab.status, LabStatus.ACTIVE)
        self.assertEqual(lab.support_phone, "")
        self.assertIsNotNone(lab.created_at)
        self.assertIsNotNone(lab.updated_at)

    def test_str_representation(self):
        lab = Lab.objects.create(organization=self.org, name="Central Lab", code="CEN-01")
        self.assertEqual(str(lab), "Central Lab (CEN-01)")

    def test_code_unique_within_organization(self):
        Lab.objects.create(organization=self.org, name="Lab 1", code="CODE1")
        with self.assertRaises(IntegrityError):
            Lab.objects.create(organization=self.org, name="Lab 2", code="CODE1")

    def test_same_code_allowed_in_different_organizations(self):
        org2 = Organization.objects.create(name="Beta", slug="beta")
        lab1 = Lab.objects.create(organization=self.org, name="Lab 1", code="CODE1")
        lab2 = Lab.objects.create(organization=org2, name="Lab 2", code="CODE1")
        self.assertNotEqual(lab1.organization, lab2.organization)
        self.assertEqual(lab1.code, lab2.code)

    def test_cascade_delete_on_organization(self):
        Lab.objects.create(organization=self.org, name="Lab 1", code="CODE1")
        self.org.delete()
        self.assertEqual(Lab.objects.count(), 0)

    def test_persisted_lab_organization_cannot_be_changed_via_save(self):
        org2 = Organization.objects.create(name="Beta", slug="beta")
        lab = Lab.objects.create(organization=self.org, name="Lab 1", code="CODE1")
        branch = Branch.objects.create(
            organization=self.org, lab=lab, name="Branch 1", code="BR-1"
        )

        lab.organization = org2
        with self.assertRaises(ValidationError) as ctx:
            lab.save()
        self.assertIn("organization", ctx.exception.message_dict)

        # Verify DB is unchanged and branch remains consistent with lab
        lab.refresh_from_db()
        branch.refresh_from_db()
        self.assertEqual(lab.organization, self.org)
        self.assertEqual(branch.organization, self.org)
        self.assertEqual(branch.lab.organization, self.org)

    def test_persisted_lab_organization_cannot_be_changed_via_raw_id(self):
        org2 = Organization.objects.create(name="Beta", slug="beta")
        lab = Lab.objects.create(organization=self.org, name="Lab 1", code="CODE1")

        lab.organization_id = org2.id
        with self.assertRaises(ValidationError) as ctx:
            lab.save()
        self.assertIn("organization", ctx.exception.message_dict)

        lab.refresh_from_db()
        self.assertEqual(lab.organization, self.org)

    def test_persisted_lab_organization_cannot_be_changed_via_update_fields(self):
        org2 = Organization.objects.create(name="Beta", slug="beta")
        lab = Lab.objects.create(organization=self.org, name="Lab 1", code="CODE1")

        lab.organization = org2
        with self.assertRaises(ValidationError) as ctx:
            lab.save(update_fields=["organization"])
        self.assertIn("organization", ctx.exception.message_dict)

        lab.refresh_from_db()
        self.assertEqual(lab.organization, self.org)

    def test_persisted_lab_organization_cannot_be_changed_via_full_clean(self):
        org2 = Organization.objects.create(name="Beta", slug="beta")
        lab = Lab.objects.create(organization=self.org, name="Lab 1", code="CODE1")

        lab.organization = org2
        with self.assertRaises(ValidationError) as ctx:
            lab.full_clean()
        self.assertIn("organization", ctx.exception.message_dict)

    def test_normal_update_to_persisted_lab_succeeds(self):
        lab = Lab.objects.create(organization=self.org, name="Lab 1", code="CODE1")
        lab.name = "Renamed Lab"
        lab.support_phone = "+1-555-0100"
        lab.save()
        lab.refresh_from_db()
        self.assertEqual(lab.name, "Renamed Lab")
        self.assertEqual(lab.support_phone, "+1-555-0100")

    def test_lab_admin_organization_readonly_on_existing_instance(self):
        from apps.tenants.admin import LabAdmin
        from django.contrib.admin.sites import AdminSite

        site = AdminSite()
        admin = LabAdmin(Lab, site)
        lab = Lab.objects.create(organization=self.org, name="Lab 1", code="CODE1")

        readonly_create = admin.get_readonly_fields(request=None, obj=None)
        self.assertNotIn("organization", readonly_create)

        readonly_change = admin.get_readonly_fields(request=None, obj=lab)
        self.assertIn("organization", readonly_change)


class BranchModelTest(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Apex", slug="apex")
        self.lab = Lab.objects.create(organization=self.org, name="Main Lab", code="MAIN")

    def test_create_branch_defaults(self):
        branch = Branch.objects.create(
            organization=self.org,
            lab=self.lab,
            name="Downtown Branch",
            code="DT-01",
        )
        self.assertIsInstance(branch.id, uuid.UUID)
        self.assertEqual(branch.status, BranchStatus.ACTIVE)
        self.assertEqual(branch.timezone, "UTC")
        self.assertEqual(branch.address, "")
        self.assertEqual(branch.support_phone, "")
        self.assertIsNotNone(branch.created_at)
        self.assertIsNotNone(branch.updated_at)

    def test_str_representation(self):
        branch = Branch.objects.create(
            organization=self.org,
            lab=self.lab,
            name="Downtown Branch",
            code="DT-01",
        )
        self.assertEqual(str(branch), "Downtown Branch (DT-01)")

    def test_code_unique_within_lab(self):
        Branch.objects.create(organization=self.org, lab=self.lab, name="B1", code="BR-1")
        with self.assertRaises(IntegrityError):
            Branch.objects.create(organization=self.org, lab=self.lab, name="B2", code="BR-1")

    def test_same_branch_code_allowed_in_different_labs(self):
        lab2 = Lab.objects.create(organization=self.org, name="Second Lab", code="SEC")
        b1 = Branch.objects.create(organization=self.org, lab=self.lab, name="B1", code="BR-1")
        b2 = Branch.objects.create(organization=self.org, lab=lab2, name="B2", code="BR-1")
        self.assertEqual(b1.code, b2.code)
        self.assertNotEqual(b1.lab, b2.lab)

    def test_normal_update_succeeds(self):
        branch = Branch.objects.create(
            organization=self.org,
            lab=self.lab,
            name="Original Name",
            code="BR-1",
        )
        branch.name = "Updated Name"
        branch.address = "123 Main St"
        branch.save()
        branch.refresh_from_db()
        self.assertEqual(branch.name, "Updated Name")
        self.assertEqual(branch.address, "123 Main St")

    def test_update_fields_on_unrelated_fields_succeeds_without_lab_queries(self):
        branch = Branch.objects.create(
            organization=self.org,
            lab=self.lab,
            name="Branch Name",
            code="BR-1",
        )
        # Fetch branch fresh from DB without select_related so lab is not cached
        fresh_branch = Branch.objects.get(id=branch.id)
        self.assertNotIn("lab", fresh_branch._state.fields_cache)

        with self.assertNumQueries(1):
            # Only 1 UPDATE query, no extra SELECT for lab validation
            fresh_branch.status = BranchStatus.INACTIVE
            fresh_branch.save(update_fields=["status"])

        fresh_branch.refresh_from_db()
        self.assertEqual(fresh_branch.status, BranchStatus.INACTIVE)


class BranchTenantSafetyTest(TestCase):
    """
    Mandatory tests for cross-organization consistency (Rule 1, SECURITY.md §2).
    A branch's lab must belong to the same organization.
    """

    def setUp(self):
        self.org_a = Organization.objects.create(name="Org A", slug="org-a")
        self.org_b = Organization.objects.create(name="Org B", slug="org-b")
        self.lab_a = Lab.objects.create(organization=self.org_a, name="Lab A", code="LAB-A")
        self.lab_b = Lab.objects.create(organization=self.org_b, name="Lab B", code="LAB-B")

    def test_valid_same_organization_branch_saves_cleanly(self):
        branch = Branch(
            organization=self.org_a,
            lab=self.lab_a,
            name="Valid Branch",
            code="VB-1",
        )
        branch.save()
        self.assertIsNotNone(branch.pk)

    def test_cross_org_branch_rejected_on_save(self):
        """Branch for Org A with Lab from Org B must be rejected on normal save()."""
        branch = Branch(
            organization=self.org_a,
            lab=self.lab_b,  # Belongs to Org B!
            name="Spoofed Branch",
            code="SB-1",
        )
        with self.assertRaises(ValidationError) as ctx:
            branch.save()
        self.assertIn("lab", ctx.exception.message_dict)

    def test_cross_org_branch_rejected_on_objects_create(self):
        """Branch.objects.create() must reject mismatched organization and lab."""
        with self.assertRaises(ValidationError) as ctx:
            Branch.objects.create(
                organization=self.org_a,
                lab=self.lab_b,
                name="Spoofed Create",
                code="SB-2",
            )
        self.assertIn("lab", ctx.exception.message_dict)

    def test_cross_org_branch_rejected_on_full_clean(self):
        """full_clean() must reject mismatched organization and lab."""
        branch = Branch(
            organization=self.org_a,
            lab=self.lab_b,
            name="Dirty Branch",
            code="DB-1",
        )
        with self.assertRaises(ValidationError) as ctx:
            branch.full_clean()
        self.assertIn("lab", ctx.exception.message_dict)

    def test_cross_org_branch_rejected_with_raw_ids(self):
        """Mismatched organization_id and lab_id using raw IDs must be rejected."""
        branch = Branch(
            organization_id=self.org_a.id,
            lab_id=self.lab_b.id,
            name="Raw ID Mismatch",
            code="RAW-1",
        )
        with self.assertRaises(ValidationError) as ctx:
            branch.save()
        self.assertIn("lab", ctx.exception.message_dict)

    def test_updating_lab_to_another_org_via_update_fields_is_rejected(self):
        """Updating lab via update_fields must still enforce tenant consistency."""
        branch = Branch.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            name="Initial Valid",
            code="IV-1",
        )
        branch.lab = self.lab_b  # Cross-tenant change
        with self.assertRaises(ValidationError) as ctx:
            branch.save(update_fields=["lab"])
        self.assertIn("lab", ctx.exception.message_dict)
