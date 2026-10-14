"""
Tests for Docflow Tenant-Aware Organization, Lab & Branch APIs (Phase 1, Task 3D).

Covers:
  - Human-user session authentication, rejection of device bearer tokens, and CSRF enforcement.
  - Platform-admin versus tenant-user access.
  - Membership roles (org admin vs operator/viewer) and inactive membership/org handling.
  - Cross-tenant list, detail, filter, create, and update attempts (safe 404s, zero leaks).
  - Unknown-field rejection and immutable tenant relationships (no reparenting).
  - Status transition authorization and closed organization terminal state.
  - Standard pagination (results, page, page_size, total) and stable ordering.
  - Transactional persistence and safe audit events with request-ID propagation.
"""

import uuid
from django.core.cache import cache
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditAction, AuditEvent
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


class TenantAPIBaseTestCase(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.password = "StrongPassword123!@#"

        # Users
        self.platform_admin = User.objects.create_user(
            email="platform.admin@example.test",
            password=self.password,
            display_name="Platform Admin",
            is_platform_admin=True,
        )
        self.org_a_admin = User.objects.create_user(
            email="admin.a@example.test",
            password=self.password,
            display_name="Org A Admin",
            is_platform_admin=False,
        )
        self.org_a_operator = User.objects.create_user(
            email="operator.a@example.test",
            password=self.password,
            display_name="Org A Operator",
            is_platform_admin=False,
        )
        self.org_b_admin = User.objects.create_user(
            email="admin.b@example.test",
            password=self.password,
            display_name="Org B Admin",
            is_platform_admin=False,
        )

        # Organizations
        self.org_a = Organization.objects.create(
            name="Alpha Health",
            slug="alpha-health",
            status=OrganizationStatus.ACTIVE,
            timezone="Asia/Kolkata",
        )
        self.org_b = Organization.objects.create(
            name="Beta Diagnostics",
            slug="beta-diag",
            status=OrganizationStatus.ACTIVE,
            timezone="UTC",
        )
        self.org_suspended = Organization.objects.create(
            name="Suspended Org",
            slug="suspended-org",
            status=OrganizationStatus.SUSPENDED,
            timezone="UTC",
        )
        self.org_closed = Organization.objects.create(
            name="Closed Org",
            slug="closed-org",
            status=OrganizationStatus.CLOSED,
            timezone="UTC",
        )

        # Memberships
        OrganizationMembership.objects.create(
            user=self.org_a_admin,
            organization=self.org_a,
            role=MembershipRole.ORGANIZATION_ADMIN,
            status=MembershipStatus.ACTIVE,
        )
        OrganizationMembership.objects.create(
            user=self.org_a_operator,
            organization=self.org_a,
            role=MembershipRole.OPERATOR,
            status=MembershipStatus.ACTIVE,
        )
        OrganizationMembership.objects.create(
            user=self.org_b_admin,
            organization=self.org_b,
            role=MembershipRole.ORGANIZATION_ADMIN,
            status=MembershipStatus.ACTIVE,
        )
        # Inactive membership in Org B for Org A Admin
        OrganizationMembership.objects.create(
            user=self.org_a_admin,
            organization=self.org_b,
            role=MembershipRole.ORGANIZATION_ADMIN,
            status=MembershipStatus.INACTIVE,
        )
        # Active membership in Suspended Org for Org A Admin
        OrganizationMembership.objects.create(
            user=self.org_a_admin,
            organization=self.org_suspended,
            role=MembershipRole.ORGANIZATION_ADMIN,
            status=MembershipStatus.ACTIVE,
        )

        # Labs
        self.lab_a1 = Lab.objects.create(
            organization=self.org_a,
            name="Alpha Central Lab",
            code="LAB-A1",
            lab_type=LabType.DIAGNOSTIC,
            support_phone="+919876543210",
            status=LabStatus.ACTIVE,
        )
        self.lab_b1 = Lab.objects.create(
            organization=self.org_b,
            name="Beta Main Lab",
            code="LAB-B1",
            lab_type=LabType.DIAGNOSTIC,
            support_phone="+919876543211",
            status=LabStatus.ACTIVE,
        )

        # Branches
        self.branch_a1 = Branch.objects.create(
            organization=self.org_a,
            lab=self.lab_a1,
            name="Alpha Branch North",
            code="BR-A1",
            address="123 North St",
            support_phone="+919876543210",
            timezone="Asia/Kolkata",
            status=BranchStatus.ACTIVE,
        )
        self.branch_b1 = Branch.objects.create(
            organization=self.org_b,
            lab=self.lab_b1,
            name="Beta Branch South",
            code="BR-B1",
            address="456 South St",
            support_phone="+919876543211",
            timezone="UTC",
            status=BranchStatus.ACTIVE,
        )

    def get_client(self, user=None):
        """Helper to create an authenticated APIClient with CSRF cookies and token."""
        client = APIClient(enforce_csrf_checks=True)
        # Bootstrap CSRF cookie
        csrf_resp = client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies.get("csrftoken").value
        if user:
            client.force_login(user)
        return client, csrf_token


# ===========================================================================
# 1. Authentication, CSRF & Identity Rejection Tests
# ===========================================================================


class AuthenticationAndCSRFTests(TenantAPIBaseTestCase):
    def test_unauthenticated_requests_return_401(self):
        client, csrf_token = self.get_client(user=None)
        routes = [
            ("GET", "/api/v1/organizations"),
            ("POST", "/api/v1/organizations"),
            ("GET", f"/api/v1/organizations/{self.org_a.id}"),
            ("PATCH", f"/api/v1/organizations/{self.org_a.id}"),
            ("GET", "/api/v1/labs"),
            ("POST", "/api/v1/labs"),
            ("GET", f"/api/v1/labs/{self.lab_a1.id}"),
            ("PATCH", f"/api/v1/labs/{self.lab_a1.id}"),
            ("GET", "/api/v1/branches"),
            ("POST", "/api/v1/branches"),
            ("GET", f"/api/v1/branches/{self.branch_a1.id}"),
            ("PATCH", f"/api/v1/branches/{self.branch_a1.id}"),
        ]
        for method, route in routes:
            with self.subTest(method=method, route=route):
                if method == "GET":
                    resp = client.get(route)
                elif method == "POST":
                    resp = client.post(route, {}, format="json", HTTP_X_CSRFTOKEN=csrf_token)
                else:
                    resp = client.patch(route, {}, format="json", HTTP_X_CSRFTOKEN=csrf_token)
                self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
                self.assertEqual(resp.data["code"], "authentication_required")

    def test_device_bearer_tokens_explicitly_rejected(self):
        client = APIClient()
        response = client.get(
            "/api/v1/organizations",
            HTTP_AUTHORIZATION="Bearer valid-looking-device-token-123",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_unsafe_method_without_csrf_token_returns_403(self):
        client, _ = self.get_client(user=self.platform_admin)
        # Attempt POST without HTTP_X_CSRFTOKEN
        response = client.post(
            "/api/v1/organizations",
            {"name": "New Org", "slug": "new-org", "timezone": "UTC"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "permission_denied")


# ===========================================================================
# 2. Organization API Tests
# ===========================================================================


class OrganizationAPITests(TenantAPIBaseTestCase):
    def test_platform_admin_lists_all_organizations(self):
        client, _ = self.get_client(user=self.platform_admin)
        response = client.get("/api/v1/organizations")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        slugs = {o["slug"] for o in results}
        # Platform admin sees active, suspended, and closed
        self.assertIn("alpha-health", slugs)
        self.assertIn("beta-diag", slugs)
        self.assertIn("suspended-org", slugs)
        self.assertIn("closed-org", slugs)
        self.assertEqual(response.data["total"], 4)

    def test_tenant_user_lists_only_active_memberships_in_active_orgs(self):
        client, _ = self.get_client(user=self.org_a_admin)
        response = client.get("/api/v1/organizations")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        slugs = {o["slug"] for o in results}
        # Only Org A is active with active membership
        self.assertEqual(slugs, {"alpha-health"})
        self.assertEqual(response.data["total"], 1)

    def test_platform_admin_creates_organization(self):
        client, csrf_token = self.get_client(user=self.platform_admin)
        payload = {
            "name": "Gamma Diagnostics",
            "slug": "gamma-diag",
            "timezone": "Asia/Kolkata",
        }
        response = client.post(
            "/api/v1/organizations",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-create-org-1",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.data
        self.assertEqual(data["name"], "Gamma Diagnostics")
        self.assertEqual(data["slug"], "gamma-diag")
        self.assertEqual(data["status"], OrganizationStatus.ACTIVE)
        self.assertEqual(data["timezone"], "Asia/Kolkata")
        self.assertIn("id", data)
        self.assertIn("created_at", data)

        # Audit event recorded
        audit = AuditEvent.objects.get(
            action=AuditAction.ORGANIZATION_CREATED,
            target_id=str(data["id"]),
        )
        self.assertEqual(audit.request_id, "req-create-org-1")
        self.assertEqual(audit.safe_metadata.get("status"), OrganizationStatus.ACTIVE)

    def test_tenant_user_cannot_create_organization(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.post(
            "/api/v1/organizations",
            {"name": "Unauthorized Org", "slug": "unauth-org"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "permission_denied")

    def test_create_organization_rejects_unknown_fields(self):
        client, csrf_token = self.get_client(user=self.platform_admin)
        payload = {
            "name": "Delta Org",
            "slug": "delta-org",
            "unknown_field": "injected",
            "is_admin": True,
        }
        response = client.post(
            "/api/v1/organizations",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")
        self.assertIn("unknown_field", response.data["field_errors"])

    def test_create_organization_rejects_duplicate_slug(self):
        client, csrf_token = self.get_client(user=self.platform_admin)
        payload = {
            "name": "Duplicate Alpha",
            "slug": "alpha-health",
        }
        response = client.post(
            "/api/v1/organizations",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("slug", response.data["field_errors"])

    def test_organization_detail_scoped_read(self):
        client_a, _ = self.get_client(user=self.org_a_admin)
        # Can read Org A
        res_a = client_a.get(f"/api/v1/organizations/{self.org_a.id}")
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)
        self.assertEqual(res_a.data["id"], str(self.org_a.id))

        # Cross-tenant read of Org B returns safe 404 (not 403)
        res_b = client_a.get(f"/api/v1/organizations/{self.org_b.id}")
        self.assertEqual(res_b.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res_b.data["code"], "not_found")

        # Inactive / suspended org returns safe 404
        res_susp = client_a.get(f"/api/v1/organizations/{self.org_suspended.id}")
        self.assertEqual(res_susp.status_code, status.HTTP_404_NOT_FOUND)

    def test_platform_admin_can_patch_organization_status(self):
        client, csrf_token = self.get_client(user=self.platform_admin)
        response = client.patch(
            f"/api/v1/organizations/{self.org_a.id}",
            {"status": OrganizationStatus.SUSPENDED},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-org-suspend",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], OrganizationStatus.SUSPENDED)

        # Audit event ORGANIZATION_STATUS_CHANGED recorded
        audit = AuditEvent.objects.get(
            action=AuditAction.ORGANIZATION_STATUS_CHANGED,
            request_id="req-org-suspend",
        )
        self.assertEqual(audit.safe_metadata["previous_status"], OrganizationStatus.ACTIVE)
        self.assertEqual(audit.safe_metadata["status"], OrganizationStatus.SUSPENDED)

    def test_tenant_admin_cannot_change_organization_status(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.patch(
            f"/api/v1/organizations/{self.org_a.id}",
            {"status": OrganizationStatus.SUSPENDED},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "permission_denied")

    def test_tenant_admin_can_patch_organization_name_and_timezone(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.patch(
            f"/api/v1/organizations/{self.org_a.id}",
            {"name": "Alpha Health Network", "timezone": "Asia/Calcutta"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-org-patch-name",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Alpha Health Network")
        self.assertEqual(response.data["timezone"], "Asia/Calcutta")

        # Audit CONFIG_CHANGED recorded
        audit = AuditEvent.objects.get(
            action=AuditAction.CONFIG_CHANGED,
            request_id="req-org-patch-name",
        )
        self.assertEqual(audit.safe_metadata["target_resource"], "organization")

    def test_tenant_operator_cannot_patch_organization(self):
        client, csrf_token = self.get_client(user=self.org_a_operator)
        response = client.patch(
            f"/api/v1/organizations/{self.org_a.id}",
            {"name": "Attempted By Operator"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_organization_patch_returns_404(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.patch(
            f"/api/v1/organizations/{self.org_b.id}",
            {"name": "Hacked Org B"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_organization_patch_rejects_immutable_slug(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.patch(
            f"/api/v1/organizations/{self.org_a.id}",
            {"slug": "new-slug"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("slug", response.data["field_errors"])

    def test_closed_organization_cannot_reopen(self):
        client, csrf_token = self.get_client(user=self.platform_admin)
        response = client.patch(
            f"/api/v1/organizations/{self.org_closed.id}",
            {"status": OrganizationStatus.ACTIVE},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("status", response.data["field_errors"])


# ===========================================================================
# 3. Lab API Tests
# ===========================================================================


class LabAPITests(TenantAPIBaseTestCase):
    def test_platform_admin_lists_all_labs_and_can_filter(self):
        client, _ = self.get_client(user=self.platform_admin)
        # All labs
        res = client.get("/api/v1/labs")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["total"], 2)

        # Filter by Org A
        res_a = client.get(f"/api/v1/labs?organization_id={self.org_a.id}")
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)
        self.assertEqual(res_a.data["total"], 1)
        self.assertEqual(res_a.data["results"][0]["code"], "LAB-A1")

    def test_tenant_user_lists_only_own_labs_and_filter_cannot_expand(self):
        client, _ = self.get_client(user=self.org_a_admin)
        # Own labs
        res = client.get("/api/v1/labs")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["total"], 1)
        self.assertEqual(res.data["results"][0]["code"], "LAB-A1")

        # Passing other organization ID returns empty list, never leaks Org B labs
        res_b = client.get(f"/api/v1/labs?organization_id={self.org_b.id}")
        self.assertEqual(res_b.status_code, status.HTTP_200_OK)
        self.assertEqual(res_b.data["total"], 0)
        self.assertEqual(res_b.data["results"], [])

    def test_invalid_uuid_organization_filter_returns_400(self):
        client, _ = self.get_client(user=self.platform_admin)
        res = client.get("/api/v1/labs?organization_id=not-a-valid-uuid")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("organization_id", res.data["field_errors"])

    def test_tenant_admin_creates_lab_with_derived_organization(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {
            "name": "Alpha Satellite Lab",
            "code": "LAB-A2",
            "support_phone": "+919876543299",
        }
        response = client.post(
            "/api/v1/labs",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-lab-create-1",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Alpha Satellite Lab")
        self.assertEqual(response.data["code"], "LAB-A2")
        self.assertEqual(response.data["organization_id"], str(self.org_a.id))
        self.assertEqual(response.data["lab_type"], LabType.DIAGNOSTIC)

        # Audit event CONFIG_CHANGED recorded
        audit = AuditEvent.objects.get(
            action=AuditAction.CONFIG_CHANGED,
            request_id="req-lab-create-1",
        )
        self.assertEqual(audit.organization_id, self.org_a.id)
        self.assertEqual(audit.safe_metadata["target_resource"], "lab")

    def test_tenant_admin_cannot_create_lab_in_another_organization(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {
            "organization_id": str(self.org_b.id),
            "name": "Intruder Lab",
            "code": "LAB-INTRUDER",
        }
        response = client.post(
            "/api/v1/labs",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        # Returns 404 because Org B is out of scope for user A
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_tenant_operator_cannot_create_lab(self):
        client, csrf_token = self.get_client(user=self.org_a_operator)
        payload = {
            "name": "Operator Lab",
            "code": "LAB-OP",
        }
        response = client.post(
            "/api/v1/labs",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_lab_create_rejects_duplicate_code_in_same_org(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {
            "name": "Duplicate Code Lab",
            "code": "LAB-A1",  # already exists in Org A
        }
        response = client.post(
            "/api/v1/labs",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("code", response.data["field_errors"])

    def test_same_lab_code_in_different_org_is_allowed(self):
        client, csrf_token = self.get_client(user=self.org_b_admin)
        payload = {
            "name": "Beta Lab with Same Code",
            "code": "LAB-A1",  # exists in Org A, but allowed in Org B
        }
        response = client.post(
            "/api/v1/labs",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_cross_tenant_lab_read_returns_404(self):
        client, _ = self.get_client(user=self.org_a_admin)
        # Reading Org B lab returns 404
        response = client.get(f"/api/v1/labs/{self.lab_b1.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_tenant_admin_patches_lab(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.patch(
            f"/api/v1/labs/{self.lab_a1.id}",
            {"name": "Alpha Central Super Lab", "status": LabStatus.SUSPENDED},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Alpha Central Super Lab")
        self.assertEqual(response.data["status"], LabStatus.SUSPENDED)

    def test_lab_patch_rejects_reparenting_organization(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.patch(
            f"/api/v1/labs/{self.lab_a1.id}",
            {"organization_id": str(self.org_b.id)},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("organization_id", response.data["field_errors"])


# ===========================================================================
# 4. Branch API Tests
# ===========================================================================


class BranchAPITests(TenantAPIBaseTestCase):
    def test_platform_admin_lists_all_branches_and_can_filter(self):
        client, _ = self.get_client(user=self.platform_admin)
        res = client.get("/api/v1/branches")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["total"], 2)

        # Filter by Lab A1
        res_a = client.get(f"/api/v1/branches?lab_id={self.lab_a1.id}")
        self.assertEqual(res_a.status_code, status.HTTP_200_OK)
        self.assertEqual(res_a.data["total"], 1)
        self.assertEqual(res_a.data["results"][0]["code"], "BR-A1")

    def test_tenant_user_lists_only_own_branches(self):
        client, _ = self.get_client(user=self.org_a_admin)
        res = client.get("/api/v1/branches")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["total"], 1)
        self.assertEqual(res.data["results"][0]["code"], "BR-A1")

        # Filtering by other tenant's lab returns empty list
        res_b = client.get(f"/api/v1/branches?lab_id={self.lab_b1.id}")
        self.assertEqual(res_b.status_code, status.HTTP_200_OK)
        self.assertEqual(res_b.data["total"], 0)
        self.assertEqual(res_b.data["results"], [])

    def test_tenant_admin_creates_branch_with_derived_organization(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {
            "lab_id": str(self.lab_a1.id),
            "name": "Alpha Branch East",
            "code": "BR-A2",
            "address": "789 East Blvd",
            "support_phone": "+919876543222",
            "timezone": "Asia/Kolkata",
        }
        response = client.post(
            "/api/v1/branches",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-branch-create-1",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Alpha Branch East")
        self.assertEqual(response.data["code"], "BR-A2")
        self.assertEqual(response.data["organization_id"], str(self.org_a.id))
        self.assertEqual(response.data["lab_id"], str(self.lab_a1.id))

        # Audit event CONFIG_CHANGED recorded with branch_code
        audit = AuditEvent.objects.get(
            action=AuditAction.CONFIG_CHANGED,
            request_id="req-branch-create-1",
        )
        self.assertEqual(audit.organization_id, self.org_a.id)
        self.assertEqual(audit.safe_metadata["branch_code"], "BR-A2")

    def test_branch_create_rejects_client_supplied_organization_id(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {
            "lab_id": str(self.lab_a1.id),
            "organization_id": str(self.org_a.id),
            "name": "Alpha Branch Test",
            "code": "BR-TEST",
        }
        response = client.post(
            "/api/v1/branches",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("organization_id", response.data["field_errors"])

    def test_tenant_admin_cannot_create_branch_in_other_tenant_lab(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {
            "lab_id": str(self.lab_b1.id),
            "name": "Intruder Branch",
            "code": "BR-INTRUDER",
        }
        response = client.post(
            "/api/v1/branches",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        # Lab B1 is out of scope for User A -> 404
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_tenant_operator_cannot_create_branch(self):
        client, csrf_token = self.get_client(user=self.org_a_operator)
        payload = {
            "lab_id": str(self.lab_a1.id),
            "name": "Operator Branch",
            "code": "BR-OP",
        }
        response = client.post(
            "/api/v1/branches",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_branch_read_returns_404(self):
        client, _ = self.get_client(user=self.org_a_admin)
        response = client.get(f"/api/v1/branches/{self.branch_b1.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_branch_patch_updates_allowlisted_fields(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.patch(
            f"/api/v1/branches/{self.branch_a1.id}",
            {"name": "Alpha North Main", "address": "Updated Address 101"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Alpha North Main")
        self.assertEqual(response.data["address"], "Updated Address 101")

    def test_branch_patch_rejects_reparenting_lab_or_org(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        # Attempt to change lab_id
        res_lab = client.patch(
            f"/api/v1/branches/{self.branch_a1.id}",
            {"lab_id": str(self.lab_b1.id)},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(res_lab.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("lab_id", res_lab.data["field_errors"])

        # Attempt to change organization_id
        res_org = client.patch(
            f"/api/v1/branches/{self.branch_a1.id}",
            {"organization_id": str(self.org_b.id)},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(res_org.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("organization_id", res_org.data["field_errors"])


# ===========================================================================
# 5. Pagination, Ordering & Error Envelope Tests
# ===========================================================================


class PaginationAndOrderingTests(TenantAPIBaseTestCase):
    def test_pagination_shape_and_stable_ordering(self):
        client, _ = self.get_client(user=self.platform_admin)
        # Create additional organizations for pagination testing
        for i in range(30):
            Organization.objects.create(
                name=f"Paginated Org {i:02d}",
                slug=f"pag-org-{i:02d}",
            )

        # Default page_size 25
        res = client.get("/api/v1/organizations")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("results", res.data)
        self.assertEqual(res.data["page"], 1)
        self.assertEqual(res.data["page_size"], 25)
        self.assertEqual(len(res.data["results"]), 25)
        # Total: 4 initial + 30 created = 34
        self.assertEqual(res.data["total"], 34)

        # Page 2
        res2 = client.get("/api/v1/organizations?page=2")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["page"], 2)
        self.assertEqual(len(res2.data["results"]), 9)

        # Custom page_size
        res_custom = client.get("/api/v1/organizations?page_size=10")
        self.assertEqual(res_custom.status_code, status.HTTP_200_OK)
        self.assertEqual(res_custom.data["page_size"], 10)
        self.assertEqual(len(res_custom.data["results"]), 10)

        # Page size clamped to maximum 100
        res_max = client.get("/api/v1/organizations?page_size=200")
        self.assertEqual(res_max.status_code, status.HTTP_200_OK)
        self.assertEqual(res_max.data["page_size"], 100)

        # Stable ordering test: IDs in page 1 and page 2 must be completely disjoint
        ids_p1 = {o["id"] for o in res.data["results"]}
        ids_p2 = {o["id"] for o in res2.data["results"]}
        self.assertTrue(ids_p1.isdisjoint(ids_p2))

    def test_request_id_propagation_and_error_envelope(self):
        client, csrf_token = self.get_client(user=self.platform_admin)
        # Send bad request with explicit X-Request-ID
        response = client.post(
            "/api/v1/organizations",
            {"name": "Bad Payload"},  # missing slug
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-tracking-test-12345",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["type"], "about:blank")
        self.assertEqual(response.data["title"], "Validation failed")
        self.assertEqual(response.data["code"], "validation_error")
        self.assertEqual(response.data["request_id"], "req-tracking-test-12345")
        self.assertIn("slug", response.data["field_errors"])
