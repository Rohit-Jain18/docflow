"""
Tests for Docflow Device Management APIs (Phase 1, Task 3E).

Covers:
  - Device collection (GET /api/v1/devices, POST /api/v1/devices)
  - Device detail and safe name update (GET, PATCH /api/v1/devices/{device_id})
  - One-time activation code issuance with server bounds (POST /api/v1/devices/{device_id}/activation-code)
  - Administrator device revocation and credential invalidation (POST /api/v1/devices/{device_id}/revoke)
  - Platform-admin versus tenant-admin authorization, and operator rejection (403)
  - Cross-tenant object access returns safe 404s
  - Rejection of unknown and protected fields
  - Idempotent revocation behavior and audit attribution
  - Session-only auth, CSRF enforcement, pagination, and request-ID propagation
"""

import datetime
from typing import Any
import uuid
from django.core.cache import cache
from django.utils import timezone as tz_utils
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.audit.models import AuditAction, AuditEvent
from apps.devices.models import (
    Device,
    DeviceActivationCode,
    DeviceRefreshCredential,
    DeviceStatus,
)
from apps.devices.services import (
    generate_access_token,
    generate_refresh_secret,
    hash_token,
)
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


class DeviceManagementAPIBaseTestCase(APITestCase):
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
        self.branch_a_inactive = Branch.objects.create(
            organization=self.org_a,
            lab=self.lab_a,
            name="Alpha Branch Closed",
            code="BR-A-CLOSED",
            status=BranchStatus.INACTIVE,
        )
        self.branch_b1 = Branch.objects.create(
            organization=self.org_b,
            lab=self.lab_b,
            name="Beta Branch South",
            code="BR-B1",
            status=BranchStatus.ACTIVE,
        )

        # Devices
        self.device_a1 = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a1,
            name="Alpha Workstation 1",
            status=DeviceStatus.PENDING_ACTIVATION,
        )
        self.device_a2 = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a1,
            name="Alpha Workstation 2",
            status=DeviceStatus.ACTIVE,
        )
        self.device_a_revoked = Device.objects.create(
            organization=self.org_a,
            branch=self.branch_a1,
            name="Alpha Old Workstation",
            status=DeviceStatus.REVOKED,
            revoked_at=tz_utils.now(),
        )
        self.device_b1 = Device.objects.create(
            organization=self.org_b,
            branch=self.branch_b1,
            name="Beta Workstation 1",
            status=DeviceStatus.ACTIVE,
        )

    def get_client(self, user=None):
        """Helper to create an authenticated APIClient with CSRF cookies and token."""
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        cookie = client.cookies.get("csrftoken")
        assert cookie is not None
        csrf_token = cookie.value
        if user:
            client.force_login(user)
        return client, csrf_token


# ===========================================================================
# 1. Authentication and CSRF Tests
# ===========================================================================


class DeviceManagementAuthAndCSRFTests(DeviceManagementAPIBaseTestCase):
    def test_unauthenticated_requests_return_401(self):
        client, csrf_token = self.get_client(user=None)
        routes = [
            ("GET", "/api/v1/devices"),
            ("POST", "/api/v1/devices"),
            ("GET", f"/api/v1/devices/{self.device_a1.id}"),
            ("PATCH", f"/api/v1/devices/{self.device_a1.id}"),
            ("POST", f"/api/v1/devices/{self.device_a1.id}/activation-code"),
            ("POST", f"/api/v1/devices/{self.device_a1.id}/revoke"),
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

    def test_device_bearer_tokens_rejected_on_management_endpoints(self):
        client = APIClient()
        response = client.get(
            "/api/v1/devices",
            HTTP_AUTHORIZATION="Bearer some-device-access-token",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_unsafe_method_without_csrf_token_returns_403(self):
        client, _ = self.get_client(user=self.platform_admin)
        response = client.post(
            "/api/v1/devices",
            {"branch_id": str(self.branch_a1.id), "name": "No CSRF PC"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "permission_denied")


# ===========================================================================
# 2. Device Collection Tests (GET, POST /api/v1/devices)
# ===========================================================================


class DeviceCollectionTests(DeviceManagementAPIBaseTestCase):
    def test_platform_admin_lists_all_devices(self):
        client, _ = self.get_client(user=self.platform_admin)
        response = client.get("/api/v1/devices")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Total devices: 3 in Org A + 1 in Org B = 4
        self.assertEqual(response.data["total"], 4)
        names = {d["name"] for d in response.data["results"]}
        self.assertIn("Alpha Workstation 1", names)
        self.assertIn("Beta Workstation 1", names)

    def test_tenant_user_lists_only_own_organization_devices(self):
        client, _ = self.get_client(user=self.org_a_admin)
        response = client.get("/api/v1/devices")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 3)
        names = {d["name"] for d in response.data["results"]}
        self.assertIn("Alpha Workstation 1", names)
        self.assertIn("Alpha Workstation 2", names)
        self.assertNotIn("Beta Workstation 1", names)

    def test_branch_filter_returns_matching_devices(self):
        client, _ = self.get_client(user=self.platform_admin)
        response = client.get(f"/api/v1/devices?branch_id={self.branch_a1.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 3)

    def test_branch_filter_out_of_scope_returns_empty_results(self):
        client, _ = self.get_client(user=self.org_a_admin)
        # User in Org A filters for Org B's branch -> empty results, no leaks
        response = client.get(f"/api/v1/devices?branch_id={self.branch_b1.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 0)
        self.assertEqual(response.data["results"], [])

    def test_invalid_uuid_branch_filter_returns_400(self):
        client, _ = self.get_client(user=self.platform_admin)
        response = client.get("/api/v1/devices?branch_id=invalid-uuid-string")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("branch_id", response.data["field_errors"])

    def test_platform_admin_creates_device(self):
        client, csrf_token = self.get_client(user=self.platform_admin)
        payload = {
            "branch_id": str(self.branch_a1.id),
            "name": "Platform Created Device",
        }
        response = client.post(
            "/api/v1/devices",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-dev-create-1",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Platform Created Device")
        self.assertEqual(response.data["status"], DeviceStatus.PENDING_ACTIVATION)
        self.assertEqual(response.data["branch_id"], str(self.branch_a1.id))
        self.assertEqual(response.data["organization_id"], str(self.org_a.id))

        # Check audit event
        audit = AuditEvent.objects.get(
            action=AuditAction.CONFIG_CHANGED,
            request_id="req-dev-create-1",
        )
        self.assertEqual(audit.organization_id, self.org_a.id)
        self.assertEqual(audit.safe_metadata["target_resource"], "device")
        self.assertEqual(audit.safe_metadata["device_name"], "Platform Created Device")

    def test_tenant_admin_creates_device_in_own_branch(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {
            "branch_id": str(self.branch_a1.id),
            "name": "Org Admin PC",
        }
        response = client.post(
            "/api/v1/devices",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["organization_id"], str(self.org_a.id))

    def test_tenant_admin_cannot_create_device_in_other_tenant_branch(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {
            "branch_id": str(self.branch_b1.id),
            "name": "Intruder Device",
        }
        response = client.post(
            "/api/v1/devices",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_tenant_operator_cannot_create_device(self):
        client, csrf_token = self.get_client(user=self.org_a_operator)
        payload = {
            "branch_id": str(self.branch_a1.id),
            "name": "Operator Device",
        }
        response = client.post(
            "/api/v1/devices",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_device_rejects_unknown_fields(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {
            "branch_id": str(self.branch_a1.id),
            "name": "Injected Fields PC",
            "organization_id": str(self.org_b.id),
            "status": "active",
        }
        response = client.post(
            "/api/v1/devices",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("organization_id", response.data["field_errors"])

    def test_create_device_fails_for_inactive_branch(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        payload = {
            "branch_id": str(self.branch_a_inactive.id),
            "name": "Inactive Branch Device",
        }
        response = client.post(
            "/api/v1/devices",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("branch_id", response.data["field_errors"])


# ===========================================================================
# 3. Device Detail and PATCH Tests
# ===========================================================================


class DeviceDetailAndPatchTests(DeviceManagementAPIBaseTestCase):
    def test_device_detail_scoped_read(self):
        client, _ = self.get_client(user=self.org_a_admin)
        # Can read Org A device
        res = client.get(f"/api/v1/devices/{self.device_a1.id}")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["id"], str(self.device_a1.id))
        self.assertEqual(res.data["name"], self.device_a1.name)

        # Cross-tenant read of Org B device returns safe 404
        res_cross = client.get(f"/api/v1/devices/{self.device_b1.id}")
        self.assertEqual(res_cross.status_code, status.HTTP_404_NOT_FOUND)

    def test_device_patch_updates_name(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.patch(
            f"/api/v1/devices/{self.device_a1.id}",
            {"name": "Alpha Workstation Renamed"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-dev-patch-1",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Alpha Workstation Renamed")

        # Verify audit event
        audit = AuditEvent.objects.get(
            action=AuditAction.CONFIG_CHANGED,
            request_id="req-dev-patch-1",
        )
        self.assertEqual(audit.safe_metadata["device_name"], "Alpha Workstation Renamed")

    def test_device_patch_rejects_protected_fields(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        protected_fields: list[dict[str, Any]] = [
            {"status": DeviceStatus.ACTIVE},
            {"organization_id": str(self.org_b.id)},
            {"branch_id": str(self.branch_b1.id)},
            {"last_ip": "1.2.3.4"},
            {"agent_version": "2.0.0"},
            {"access_token": "secret"},
        ]
        for payload in protected_fields:
            with self.subTest(payload=payload):
                payload["name"] = "Valid Name"
                response = client.patch(
                    f"/api/v1/devices/{self.device_a1.id}",
                    payload,
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf_token,
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data["code"], "validation_error")

    def test_tenant_operator_cannot_patch_device(self):
        client, csrf_token = self.get_client(user=self.org_a_operator)
        response = client.patch(
            f"/api/v1/devices/{self.device_a1.id}",
            {"name": "Operator Renamed"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_patch_device_returns_404(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.patch(
            f"/api/v1/devices/{self.device_b1.id}",
            {"name": "Hacked Device"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ===========================================================================
# 4. One-Time Activation Code Issuance Tests
# ===========================================================================


class ActivationCodeIssuanceTests(DeviceManagementAPIBaseTestCase):
    def test_issue_activation_code_success(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.post(
            f"/api/v1/devices/{self.device_a1.id}/activation-code",
            {"expires_in_seconds": 600},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-act-issue-1",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("activation_code", response.data)
        self.assertIn("expires_at", response.data)
        raw_code = response.data["activation_code"]
        self.assertTrue(len(raw_code) > 20)

        # Ensure subsequent GET /api/v1/devices/{id} does NOT expose the code
        get_res = client.get(f"/api/v1/devices/{self.device_a1.id}")
        self.assertNotIn("activation_code", str(get_res.data))
        self.assertNotIn(raw_code, str(get_res.data))

        # Check audit event DEVICE_ACTIVATION_CODE_ISSUED
        audit = AuditEvent.objects.get(
            action=AuditAction.DEVICE_ACTIVATION_CODE_ISSUED,
            request_id="req-act-issue-1",
        )
        self.assertEqual(audit.organization_id, self.org_a.id)
        # Ensure raw code is NOT in audit metadata
        self.assertNotIn(raw_code, str(audit.safe_metadata))

    def test_issue_activation_code_empty_body_uses_default(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.post(
            f"/api/v1/devices/{self.device_a1.id}/activation-code",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("activation_code", response.data)

    def test_issue_activation_code_server_bounds_enforced(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        # Below min (60 seconds)
        res_low = client.post(
            f"/api/v1/devices/{self.device_a1.id}/activation-code",
            {"expires_in_seconds": 30},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(res_low.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expires_in_seconds", res_low.data["field_errors"])

        # Above max (3600 seconds)
        res_high = client.post(
            f"/api/v1/devices/{self.device_a1.id}/activation-code",
            {"expires_in_seconds": 7200},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(res_high.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expires_in_seconds", res_high.data["field_errors"])

    def test_reissuing_activation_code_revokes_previous_code(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        # First issuance
        res1 = client.post(
            f"/api/v1/devices/{self.device_a1.id}/activation-code",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        code1 = res1.data["activation_code"]
        record1 = DeviceActivationCode.objects.get(code_hash=hash_token(code1))
        self.assertIsNone(record1.revoked_at)

        # Second issuance
        res2 = client.post(
            f"/api/v1/devices/{self.device_a1.id}/activation-code",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        code2 = res2.data["activation_code"]
        self.assertNotEqual(code1, code2)

        # Previous code record must now be revoked
        record1.refresh_from_db()
        self.assertIsNotNone(record1.revoked_at)

    def test_issue_activation_code_for_revoked_device_fails_safely(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.post(
            f"/api/v1/devices/{self.device_a_revoked.id}/activation-code",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

    def test_tenant_operator_cannot_issue_activation_code(self):
        client, csrf_token = self.get_client(user=self.org_a_operator)
        response = client.post(
            f"/api/v1/devices/{self.device_a1.id}/activation-code",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_activation_code_issuance_returns_404(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.post(
            f"/api/v1/devices/{self.device_b1.id}/activation-code",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ===========================================================================
# 5. Administrator Device Revocation Tests
# ===========================================================================


class DeviceRevocationTests(DeviceManagementAPIBaseTestCase):
    def test_admin_revokes_device_and_invalidates_credentials(self):
        # Setup active refresh credential and access token for device A2
        raw_refresh = generate_refresh_secret()
        cred = DeviceRefreshCredential.objects.create(
            device=self.device_a2,
            credential_hash=hash_token(raw_refresh),
            issued_at=tz_utils.now(),
            expires_at=tz_utils.now() + datetime.timedelta(days=30),
        )
        access_token, _ = generate_access_token(self.device_a2)

        # Revoke device via management API
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.post(
            f"/api/v1/devices/{self.device_a2.id}/revoke",
            {"reason_code": "compromised"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-admin-revoke-1",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], DeviceStatus.REVOKED)
        self.assertIsNotNone(response.data["revoked_at"])

        # 1. DeviceRefreshCredential must be revoked
        cred.refresh_from_db()
        self.assertIsNotNone(cred.revoked_at)

        # 2. Subsequent Agent Bearer request with access_token fails immediately
        agent_client = APIClient()
        agent_resp = agent_client.post(
            "/api/v1/agent/auth/revoke-self",
            {},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )
        self.assertEqual(agent_resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("revoked", str(agent_resp.data))

        # 3. Audit attribution must be to actor_user
        audit = AuditEvent.objects.get(
            action=AuditAction.DEVICE_REVOKED,
            request_id="req-admin-revoke-1",
        )
        self.assertEqual(audit.actor_user_id, self.org_a_admin.id)
        self.assertIsNone(audit.actor_device_id)
        self.assertEqual(audit.safe_metadata["reason_code"], "compromised")

    def test_revocation_is_idempotent(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        # First revocation
        res1 = client.post(
            f"/api/v1/devices/{self.device_a2.id}/revoke",
            {"reason_code": "decommissioned"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-revoke-idem-1",
        )
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        revoked_at_1 = res1.data["revoked_at"]

        # Audit count after 1st revocation
        audit_count_1 = AuditEvent.objects.filter(
            action=AuditAction.DEVICE_REVOKED,
            target_id=str(self.device_a2.id),
        ).count()

        # Second revocation (repeated call)
        res2 = client.post(
            f"/api/v1/devices/{self.device_a2.id}/revoke",
            {"reason_code": "decommissioned"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-revoke-idem-2",
        )
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        revoked_at_2 = res2.data["revoked_at"]

        # Timestamp must not be mutated
        self.assertEqual(revoked_at_1, revoked_at_2)

        # Audit count must not increase (no duplicate audit events)
        audit_count_2 = AuditEvent.objects.filter(
            action=AuditAction.DEVICE_REVOKED,
            target_id=str(self.device_a2.id),
        ).count()
        self.assertEqual(audit_count_1, audit_count_2)

    def test_revocation_rejects_invalid_reason_codes(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        invalid_codes = [
            "",
            "free text with spaces",
            "X" * 60,
            "123_invalid_start",
            "<script>alert(1)</script>",
        ]
        for code in invalid_codes:
            with self.subTest(code=code):
                response = client.post(
                    f"/api/v1/devices/{self.device_a1.id}/revoke",
                    {"reason_code": code},
                    format="json",
                    HTTP_X_CSRFTOKEN=csrf_token,
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data["code"], "validation_error")

    def test_tenant_operator_cannot_revoke_device(self):
        client, csrf_token = self.get_client(user=self.org_a_operator)
        response = client.post(
            f"/api/v1/devices/{self.device_a1.id}/revoke",
            {"reason_code": "compromised"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cross_tenant_device_revocation_returns_404(self):
        client, csrf_token = self.get_client(user=self.org_a_admin)
        response = client.post(
            f"/api/v1/devices/{self.device_b1.id}/revoke",
            {"reason_code": "compromised"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ===========================================================================
# 6. Pagination & Stable Ordering Tests
# ===========================================================================


class DevicePaginationTests(DeviceManagementAPIBaseTestCase):
    def test_pagination_and_stable_ordering(self):
        client, _ = self.get_client(user=self.platform_admin)
        # Create 30 additional devices
        for i in range(30):
            Device.objects.create(
                organization=self.org_a,
                branch=self.branch_a1,
                name=f"Paginated Device {i:02d}",
            )

        # Default page_size 25
        response = client.get("/api/v1/devices")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["page"], 1)
        self.assertEqual(response.data["page_size"], 25)
        self.assertEqual(len(response.data["results"]), 25)
        # Total: 4 initial + 30 = 34
        self.assertEqual(response.data["total"], 34)

        # Page 2
        response2 = client.get("/api/v1/devices?page=2")
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.data["page"], 2)
        self.assertEqual(len(response2.data["results"]), 9)

        # Disjoint IDs on pagination
        ids1 = {d["id"] for d in response.data["results"]}
        ids2 = {d["id"] for d in response2.data["results"]}
        self.assertTrue(ids1.isdisjoint(ids2))
