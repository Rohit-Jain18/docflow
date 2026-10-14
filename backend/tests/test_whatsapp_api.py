"""
Tests for Docflow WhatsApp Account and Branch Assignment APIs (Phase 1, Task 3F).

Covers:
  - Account list/create/detail permissions and tenant isolation.
  - Operator rejection (403) and safe 404s for out-of-scope records.
  - Unknown-field rejection and secret/reference redaction.
  - Accounts start pending; production verification returns safe 503 provider_unavailable.
  - Strict empty body requirement for verification endpoint.
  - Development override succeeds only for the exact allowlisted account/org and records audit event.
  - Production mode strictly rejects verification override even if flag is set (fail-closed).
  - Unverified and disabled accounts cannot be assigned.
  - Cross-organization branch/account assignments are rejected.
  - Replacing an assignment deactivates previous assignment, preserves history, and maintains unique constraint.
  - Database one-active-assignment constraint remains effective.
  - Assignment deletion and repeated idempotent deactivation.
  - CSRF enforcement, session authentication, request-ID propagation, pagination, and audit events.
"""

import uuid
from django.core.cache import cache
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone as tz_utils
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditAction, AuditEvent
from apps.tenants.models import (
    Branch,
    BranchStatus,
    Lab,
    LabStatus,
    MembershipRole,
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)
from apps.users.models import User
from apps.whatsapp.models import (
    AssignmentStatus,
    BranchWhatsAppAssignment,
    CredentialMode,
    WhatsAppAccount,
    WhatsAppAccountStatus,
)


class WhatsAppAPIBaseTestCase(TestCase):
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
        self.multi_org_admin = User.objects.create_user(
            email="multi.admin@example.test",
            password=self.password,
            display_name="Multi Admin",
            is_platform_admin=False,
        )

        # Organizations
        self.org_a = Organization.objects.create(
            name="Alpha Diagnostics",
            slug="alpha-diag",
            status=OrganizationStatus.ACTIVE,
        )
        self.org_b = Organization.objects.create(
            name="Beta Diagnostics",
            slug="beta-diag",
            status=OrganizationStatus.ACTIVE,
        )
        self.org_suspended = Organization.objects.create(
            name="Suspended Org",
            slug="suspended-org",
            status=OrganizationStatus.SUSPENDED,
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
        OrganizationMembership.objects.create(
            user=self.multi_org_admin,
            organization=self.org_a,
            role=MembershipRole.ORGANIZATION_ADMIN,
            status=MembershipStatus.ACTIVE,
        )
        OrganizationMembership.objects.create(
            user=self.multi_org_admin,
            organization=self.org_b,
            role=MembershipRole.ORGANIZATION_ADMIN,
            status=MembershipStatus.ACTIVE,
        )

        # Labs
        self.lab_a = Lab.objects.create(
            organization=self.org_a,
            name="Alpha Lab",
            code="LAB-A",
            status=LabStatus.ACTIVE,
        )
        self.lab_b = Lab.objects.create(
            organization=self.org_b,
            name="Beta Lab",
            code="LAB-B",
            status=LabStatus.ACTIVE,
        )

        # Branches
        self.branch_a1 = Branch.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            name="Alpha Branch North",
            code="BR-A1",
            status=BranchStatus.ACTIVE,
        )
        self.branch_b1 = Branch.objects.create(
            organization=self.org_b,
            lab=self.lab_b,
            name="Beta Branch South",
            code="BR-B1",
            status=BranchStatus.ACTIVE,
        )

        # WhatsApp Accounts
        self.account_a1 = WhatsAppAccount.objects.create(
            organization=self.org_a,
            display_name="Alpha Sender 1",
            phone_number_id="PN-A1-12345",
            display_phone_number="+15550001",
            provider_key="kiziee",
            provider_account_reference="REF-A1",
            status=WhatsAppAccountStatus.PENDING_VERIFICATION,
            credential_secret_ref="vault://secret/alpha-1",
        )
        self.account_a_verified = WhatsAppAccount.objects.create(
            organization=self.org_a,
            display_name="Alpha Sender Verified",
            phone_number_id="PN-A-VERIFIED",
            display_phone_number="+15550002",
            provider_key="kiziee",
            status=WhatsAppAccountStatus.VERIFIED,
            verified_at=tz_utils.now(),
            credential_secret_ref="vault://secret/alpha-ver",
        )
        self.account_a_disabled = WhatsAppAccount.objects.create(
            organization=self.org_a,
            display_name="Alpha Sender Disabled",
            phone_number_id="PN-A-DISABLED",
            provider_key="kiziee",
            status=WhatsAppAccountStatus.DISABLED,
        )
        self.account_b1 = WhatsAppAccount.objects.create(
            organization=self.org_b,
            display_name="Beta Sender 1",
            phone_number_id="PN-B1-67890",
            display_phone_number="+15550003",
            provider_key="kiziee",
            status=WhatsAppAccountStatus.VERIFIED,
            verified_at=tz_utils.now(),
            credential_secret_ref="vault://secret/beta-1",
        )
        self.account_suspended_org = WhatsAppAccount.objects.create(
            organization=self.org_suspended,
            display_name="Suspended Org Sender",
            phone_number_id="PN-SUSP-111",
            provider_key="kiziee",
            status=WhatsAppAccountStatus.VERIFIED,
            verified_at=tz_utils.now(),
        )

    def get_client(self, user=None):
        """Helper to create an authenticated APIClient with CSRF cookies and token."""
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies.get("csrftoken").value
        if user:
            client.force_login(user)
        return client, csrf_token


# ===========================================================================
# 1. Authentication and CSRF Tests
# ===========================================================================


class WhatsAppAuthAndCSRFTests(WhatsAppAPIBaseTestCase):
    def test_unauthenticated_requests_return_401(self):
        client = APIClient()
        routes = [
            ("GET", "/api/v1/whatsapp-accounts"),
            ("POST", "/api/v1/whatsapp-accounts"),
            ("GET", f"/api/v1/whatsapp-accounts/{self.account_a1.id}"),
            ("POST", f"/api/v1/whatsapp-accounts/{self.account_a1.id}/verify"),
            ("POST", f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment"),
            ("DELETE", f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment"),
        ]
        for method, route in routes:
            with self.subTest(method=method, route=route):
                if method == "GET":
                    resp = client.get(route)
                elif method == "POST":
                    resp = client.post(route, {}, format="json")
                else:
                    resp = client.delete(route)
                self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
                self.assertEqual(resp.data["code"], "authentication_required")

    def test_device_bearer_token_rejected_on_whatsapp_endpoints(self):
        client = APIClient()
        response = client.get(
            "/api/v1/whatsapp-accounts",
            HTTP_AUTHORIZATION="Bearer mock-device-access-token",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_unsafe_method_without_csrf_token_returns_403(self):
        client, _ = self.get_client(user=self.platform_admin)
        response = client.post(
            "/api/v1/whatsapp-accounts",
            {"phone_number_id": "PN-TEST-CSRF", "organization_id": str(self.org_a.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "permission_denied")

    def test_request_id_preserved_in_responses(self):
        client, _ = self.get_client(user=self.platform_admin)
        req_id = "custom-req-id-12345"
        response = client.get(
            "/api/v1/whatsapp-accounts",
            HTTP_X_REQUEST_ID=req_id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.headers.get("X-Request-ID"), req_id)


# ===========================================================================
# 2. Account Collection & Detail Tests (GET, POST /api/v1/whatsapp-accounts)
# ===========================================================================


class WhatsAppAccountCollectionTests(WhatsAppAPIBaseTestCase):
    def test_platform_admin_lists_all_accounts(self):
        client, _ = self.get_client(user=self.platform_admin)
        response = client.get("/api/v1/whatsapp-accounts")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Expected: 3 in Org A + 1 in Org B + 1 in Suspended Org = 5
        self.assertEqual(response.data["total"], 5)
        names = {a["display_name"] for a in response.data["results"]}
        self.assertIn("Alpha Sender 1", names)
        self.assertIn("Beta Sender 1", names)
        self.assertIn("Suspended Org Sender", names)

    def test_tenant_admin_lists_only_own_organization_accounts(self):
        client, _ = self.get_client(user=self.org_a_admin)
        response = client.get("/api/v1/whatsapp-accounts")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 3)
        names = {a["display_name"] for a in response.data["results"]}
        self.assertIn("Alpha Sender 1", names)
        self.assertIn("Alpha Sender Verified", names)
        self.assertNotIn("Beta Sender 1", names)
        self.assertNotIn("Suspended Org Sender", names)

    def test_operator_sees_zero_accounts(self):
        client, _ = self.get_client(user=self.org_a_operator)
        response = client.get("/api/v1/whatsapp-accounts")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 0)
        self.assertEqual(len(response.data["results"]), 0)

    def test_detail_view_returns_safe_metadata_only(self):
        client, _ = self.get_client(user=self.org_a_admin)
        response = client.get(f"/api/v1/whatsapp-accounts/{self.account_a1.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["id"], str(self.account_a1.id))
        self.assertEqual(data["display_name"], "Alpha Sender 1")
        self.assertEqual(data["phone_number_id"], "PN-A1-12345")
        self.assertEqual(data["display_phone_number"], "+15550001")
        self.assertEqual(data["status"], "pending_verification")
        # Ensure secret references and tokens are NOT exposed
        self.assertNotIn("credential_secret_ref", data)
        self.assertNotIn("access_token", data)
        self.assertNotIn("token", data)

    def test_detail_view_returns_safe_404_for_out_of_scope_account(self):
        client, _ = self.get_client(user=self.org_a_admin)
        # Attempt to read Org B account as Org A admin
        response = client.get(f"/api/v1/whatsapp-accounts/{self.account_b1.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "not_found")

    def test_operator_cannot_view_account_detail(self):
        client, _ = self.get_client(user=self.org_a_operator)
        response = client.get(f"/api/v1/whatsapp-accounts/{self.account_a1.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "not_found")

    def test_create_account_as_single_org_admin_derives_organization(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {
            "display_name": "New Alpha Sender",
            "phone_number_id": "PN-NEW-ALPHA",
            "display_phone_number": "+15559999",
        }
        response = client.post(
            "/api/v1/whatsapp-accounts",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "pending_verification")
        self.assertEqual(response.data["organization_id"], str(self.org_a.id))
        self.assertNotIn("credential_secret_ref", response.data)

        # Verify audit event
        audit = AuditEvent.objects.filter(
            target_type="whatsapp_account",
            target_id=response.data["id"],
            action=AuditAction.CONFIG_CHANGED,
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.organization, self.org_a)
        self.assertEqual(audit.actor_user, self.org_a_admin)

    def test_create_account_as_platform_admin_requires_organization_id(self):
        client, csrf_token = self.get_client(user=self.platform_admin)
        payload = {
            "phone_number_id": "PN-PLAT-MISSING-ORG",
        }
        response = client.post(
            "/api/v1/whatsapp-accounts",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("organization_id", response.data["field_errors"])

    def test_create_account_as_multi_org_admin_requires_organization_id(self):
        client, csrf_token = self.get_client(user=self.multi_org_admin)
        payload = {
            "phone_number_id": "PN-MULTI-MISSING-ORG",
        }
        response = client.post(
            "/api/v1/whatsapp-accounts",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("organization_id", response.data["field_errors"])

    def test_create_account_with_unauthorized_organization_id_returns_404(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        # Org A admin tries to create an account in Org B
        payload = {
            "organization_id": str(self.org_b.id),
            "phone_number_id": "PN-INTRUDER-ORG",
        }
        response = client.post(
            "/api/v1/whatsapp-accounts",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_operator_cannot_create_account(self):
        client, csrf_token = self.get_client(user=self.org_a_operator)
        payload = {
            "phone_number_id": "PN-OPERATOR-CREATE",
        }
        response = client.post(
            "/api/v1/whatsapp-accounts",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_account_rejects_unknown_fields(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {
            "phone_number_id": "PN-VALID-FIELD",
            "access_token": "secret-token-12345",
            "credential_secret_ref": "vault://steal",
            "status": "verified",
        }
        response = client.post(
            "/api/v1/whatsapp-accounts",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")
        field_errors = response.data.get("field_errors", {})
        self.assertTrue(
            "access_token" in field_errors
            or "credential_secret_ref" in field_errors
            or "status" in field_errors
        )


# ===========================================================================
# 3. Account Verification Tests (POST /api/v1/whatsapp-accounts/{id}/verify)
# ===========================================================================


class WhatsAppAccountVerifyTests(WhatsAppAPIBaseTestCase):
    def test_verify_rejects_non_empty_payload(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.post(
            f"/api/v1/whatsapp-accounts/{self.account_a1.id}/verify",
            {"unsupported": "data"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_production_mode_returns_safe_503(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        with override_settings(
            DOCFLOW_ENV="production",
            DEV_ACCOUNT_VERIFICATION_OVERRIDE=True,
            DEV_TEST_ORGANIZATION_ID=str(self.org_a.id),
            DEV_TEST_ACCOUNT_ID=str(self.account_a1.id),
        ):
            response = client.post(
                f"/api/v1/whatsapp-accounts/{self.account_a1.id}/verify",
                {},
                format="json",
                HTTP_X_CSRFTOKEN=csrf_token,
            )
            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertEqual(response.data["code"], "provider_unavailable")
            self.assertEqual(response.data["title"], "Provider unavailable")

            # Invariant: account remains unverified in DB
            self.account_a1.refresh_from_db()
            self.assertEqual(self.account_a1.status, WhatsAppAccountStatus.PENDING_VERIFICATION)
            self.assertIsNone(self.account_a1.verified_at)

    def test_dev_override_disabled_returns_safe_503(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        with override_settings(
            DOCFLOW_ENV="development",
            DEV_ACCOUNT_VERIFICATION_OVERRIDE=False,
            DEV_TEST_ORGANIZATION_ID=str(self.org_a.id),
            DEV_TEST_ACCOUNT_ID=str(self.account_a1.id),
        ):
            response = client.post(
                f"/api/v1/whatsapp-accounts/{self.account_a1.id}/verify",
                {},
                format="json",
                HTTP_X_CSRFTOKEN=csrf_token,
            )
            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertEqual(response.data["code"], "provider_unavailable")

    def test_dev_override_rejects_non_allowlisted_account(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        with override_settings(
            DOCFLOW_ENV="development",
            DEV_ACCOUNT_VERIFICATION_OVERRIDE=True,
            DEV_TEST_ORGANIZATION_ID=str(self.org_a.id),
            DEV_TEST_ACCOUNT_ID=str(uuid.uuid4()),  # Different account ID
        ):
            response = client.post(
                f"/api/v1/whatsapp-accounts/{self.account_a1.id}/verify",
                {},
                format="json",
                HTTP_X_CSRFTOKEN=csrf_token,
            )
            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
            self.assertEqual(response.data["code"], "provider_unavailable")

    def test_dev_override_rejects_non_allowlisted_organization(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        with override_settings(
            DOCFLOW_ENV="development",
            DEV_ACCOUNT_VERIFICATION_OVERRIDE=True,
            DEV_TEST_ORGANIZATION_ID=str(uuid.uuid4()),  # Different org ID
            DEV_TEST_ACCOUNT_ID=str(self.account_a1.id),
        ):
            response = client.post(
                f"/api/v1/whatsapp-accounts/{self.account_a1.id}/verify",
                {},
                format="json",
                HTTP_X_CSRFTOKEN=csrf_token,
            )
            self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_dev_override_succeeds_for_exact_allowlisted_account(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        req_id = "test-verify-req-999"
        with override_settings(
            DOCFLOW_ENV="development",
            DEV_ACCOUNT_VERIFICATION_OVERRIDE=True,
            DEV_TEST_ORGANIZATION_ID=str(self.org_a.id),
            DEV_TEST_ACCOUNT_ID=str(self.account_a1.id),
        ):
            response = client.post(
                f"/api/v1/whatsapp-accounts/{self.account_a1.id}/verify",
                {},
                format="json",
                HTTP_X_CSRFTOKEN=csrf_token,
                HTTP_X_REQUEST_ID=req_id,
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data["status"], "verified")
            self.assertIsNotNone(response.data["verified_at"])

            # Verify database state
            self.account_a1.refresh_from_db()
            self.assertEqual(self.account_a1.status, WhatsAppAccountStatus.VERIFIED)
            self.assertIsNotNone(self.account_a1.verified_at)

            # Verify audit event
            audit = AuditEvent.objects.filter(
                target_type="whatsapp_account",
                target_id=str(self.account_a1.id),
                action=AuditAction.WHATSAPP_ACCOUNT_DEV_VERIFICATION_OVERRIDE,
            ).first()
            self.assertIsNotNone(audit)
            self.assertEqual(audit.organization, self.org_a)
            self.assertEqual(audit.actor_user, self.org_a_admin)
            self.assertEqual(audit.request_id, req_id)
            self.assertEqual(
                audit.safe_metadata["verification_status"], "dev_override_verified"
            )


# ===========================================================================
# 4. Branch WhatsApp Assignment Tests (POST & DELETE)
# ===========================================================================


class BranchWhatsAppAssignmentTests(WhatsAppAPIBaseTestCase):
    def test_assign_verified_account_succeeds(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        req_id = "assign-req-111"
        payload = {"whatsapp_account_id": str(self.account_a_verified.id)}
        response = client.post(
            f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID=req_id,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["branch_id"], str(self.branch_a1.id))
        self.assertEqual(data["whatsapp_account_id"], str(self.account_a_verified.id))
        self.assertEqual(data["status"], "active")
        self.assertIsNotNone(data["assigned_at"])

        # Check DB
        assignment = BranchWhatsAppAssignment.objects.get(
            branch=self.branch_a1,
            status=AssignmentStatus.ACTIVE,
        )
        self.assertEqual(assignment.whatsapp_account, self.account_a_verified)
        self.assertIsNone(assignment.ended_at)

        # Check Audit
        audit = AuditEvent.objects.filter(
            target_type="branch_whatsapp_assignment",
            target_id=str(assignment.id),
            action=AuditAction.WHATSAPP_ACCOUNT_ASSIGNED,
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.organization, self.org_a)
        self.assertEqual(audit.actor_user, self.org_a_admin)
        self.assertEqual(audit.request_id, req_id)

    def test_assign_unverified_account_rejected(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {"whatsapp_account_id": str(self.account_a1.id)}  # status is pending_verification
        response = client.post(
            f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")
        self.assertIn("whatsapp_account_id", response.data["field_errors"])

    def test_assign_disabled_account_rejected(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {"whatsapp_account_id": str(self.account_a_disabled.id)}
        response = client.post(
            f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")
        self.assertIn("whatsapp_account_id", response.data["field_errors"])

    def test_cross_org_account_assignment_rejected_for_platform_admin(self):
        client, csrf_token = self.get_client(user=self.platform_admin)
        # Platform admin sees both branch A1 (Org A) and account B1 (Org B)
        payload = {"whatsapp_account_id": str(self.account_b1.id)}
        response = client.post(
            f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

    def test_cross_org_account_assignment_returns_404_for_tenant_admin(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        # Org A admin cannot see account B1, so account lookup returns 404
        payload = {"whatsapp_account_id": str(self.account_b1.id)}
        response = client.post(
            f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cross_org_branch_assignment_returns_404(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        # Org A admin tries to assign to branch B1
        payload = {"whatsapp_account_id": str(self.account_a_verified.id)}
        response = client.post(
            f"/api/v1/branches/{self.branch_b1.id}/whatsapp-assignment",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_assignment_payload_rejects_unknown_fields(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {
            "whatsapp_account_id": str(self.account_a_verified.id),
            "status": "active",
            "extra_field": "disallowed",
        }
        response = client.post(
            f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_replacing_assignment_deactivates_previous_and_preserves_history(self):
        # Create a second verified account in Org A
        second_verified_account = WhatsAppAccount.objects.create(
            organization=self.org_a,
            display_name="Alpha Sender Verified 2",
            phone_number_id="PN-A-VERIFIED-2",
            provider_key="kiziee",
            status=WhatsAppAccountStatus.VERIFIED,
            verified_at=tz_utils.now(),
        )

        client, csrf_token = self.get_client(user=self.org_a_admin)

        # 1. First assignment
        resp1 = client.post(
            f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment",
            {"whatsapp_account_id": str(self.account_a_verified.id)},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        first_assignment_id = resp1.data["id"]

        # Verify initial assignment active
        first_asgn = BranchWhatsAppAssignment.objects.get(id=first_assignment_id)
        self.assertEqual(first_asgn.status, AssignmentStatus.ACTIVE)
        self.assertIsNone(first_asgn.ended_at)

        # 2. Second assignment replaces first
        resp2 = client.post(
            f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment",
            {"whatsapp_account_id": str(second_verified_account.id)},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        second_assignment_id = resp2.data["id"]

        # Verify history preservation and state
        first_asgn.refresh_from_db()
        second_asgn = BranchWhatsAppAssignment.objects.get(id=second_assignment_id)

        self.assertEqual(first_asgn.status, AssignmentStatus.INACTIVE)
        self.assertIsNotNone(first_asgn.ended_at)
        self.assertEqual(second_asgn.status, AssignmentStatus.ACTIVE)
        self.assertIsNone(second_asgn.ended_at)

        # Exactly 1 active assignment exists for this branch
        active_count = BranchWhatsAppAssignment.objects.filter(
            branch=self.branch_a1,
            status=AssignmentStatus.ACTIVE,
        ).count()
        self.assertEqual(active_count, 1)

        # Total assignments for branch is 2 (history preserved)
        total_count = BranchWhatsAppAssignment.objects.filter(
            branch=self.branch_a1,
        ).count()
        self.assertEqual(total_count, 2)

    def test_database_active_assignment_unique_constraint(self):
        # Ensure that attempting to directly save two active assignments raises IntegrityError
        BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a1,
            whatsapp_account=self.account_a_verified,
            status=AssignmentStatus.ACTIVE,
        )
        with self.assertRaises(IntegrityError):
            BranchWhatsAppAssignment.objects.create(
                organization=self.org_a,
                branch=self.branch_a1,
                whatsapp_account=self.account_a_verified,
                status=AssignmentStatus.ACTIVE,
            )

    def test_delete_assignment_deactivates_and_preserves_history(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)

        # Create active assignment
        asgn = BranchWhatsAppAssignment.objects.create(
            organization=self.org_a,
            branch=self.branch_a1,
            whatsapp_account=self.account_a_verified,
            status=AssignmentStatus.ACTIVE,
        )

        req_id = "unassign-req-444"
        response = client.delete(
            f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID=req_id,
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response.content, b"")

        # Invariant: Record still exists, status is inactive, ended_at is set
        asgn.refresh_from_db()
        self.assertEqual(asgn.status, AssignmentStatus.INACTIVE)
        self.assertIsNotNone(asgn.ended_at)

        # Audit event created
        audit = AuditEvent.objects.filter(
            target_type="branch_whatsapp_assignment",
            target_id=str(asgn.id),
            action=AuditAction.WHATSAPP_ACCOUNT_UNASSIGNED,
        ).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.organization, self.org_a)
        self.assertEqual(audit.request_id, req_id)

    def test_repeated_delete_assignment_is_idempotent(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)

        # Branch has NO active assignment
        response1 = client.delete(
            f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response1.status_code, status.HTTP_204_NO_CONTENT)

        response2 = client.delete(
            f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response2.status_code, status.HTTP_204_NO_CONTENT)

        # No spurious audit events created
        unassign_audits = AuditEvent.objects.filter(
            action=AuditAction.WHATSAPP_ACCOUNT_UNASSIGNED,
        ).count()
        self.assertEqual(unassign_audits, 0)

    def test_operator_cannot_assign_or_delete_assignment(self):
        client, csrf_token = self.get_client(user=self.org_a_operator)
        # Attempt POST assignment
        post_resp = client.post(
            f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment",
            {"whatsapp_account_id": str(self.account_a_verified.id)},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(post_resp.status_code, status.HTTP_403_FORBIDDEN)

        # Attempt DELETE assignment
        del_resp = client.delete(
            f"/api/v1/branches/{self.branch_a1.id}/whatsapp-assignment",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(del_resp.status_code, status.HTTP_403_FORBIDDEN)
