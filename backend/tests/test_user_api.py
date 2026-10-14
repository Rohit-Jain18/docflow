"""
Tests for Docflow Human User Authentication APIs (Phase 1, Task 3C).

Covers:
  - GET /api/v1/auth/csrf:
    * Standard Django CSRF cookie issuance without sensitive data leakage.
  - POST /api/v1/auth/login:
    * Successful authentication and session establishment.
    * Safe user summary and active-only membership serialization.
    * Generic failure responses for unknown email, wrong password, and inactive accounts.
    * Strict rejection of unknown request fields and malformed payloads.
    * CSRF enforcement for anonymous login requests.
    * IP-based rate limiting via SafeIPRateThrottle / UserLoginRateThrottle.
    * Zero password, hash, token, or raw-email leakage in responses or audit logs.
  - POST /api/v1/auth/logout:
    * Session invalidation and HTTP 204 return.
    * Rejection of unauthenticated requests and non-empty request body.
    * CSRF enforcement on logout.
  - GET /api/v1/auth/me:
    * Authenticated session retrieval of safe user summary.
    * Rejection of unauthenticated requests and device bearer tokens.
"""

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditAction, AuditEvent
from apps.devices.models import Device, DeviceStatus
from apps.devices.services import generate_access_token
from apps.tenants.models import (
    Branch,
    Lab,
    MembershipRole,
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)
from apps.users.models import User


class UserAPIBaseTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.password = "StrongPass123!@#"
        self.user = User.objects.create_user(
            email="dr.smith@example.test",
            password=self.password,
            display_name="Dr. Jane Smith",
            is_platform_admin=False,
        )

        # Organizations
        self.org_active = Organization.objects.create(
            name="Alpha Diagnostics",
            slug="alpha-diag",
            status=OrganizationStatus.ACTIVE,
        )
        self.org_inactive = Organization.objects.create(
            name="Beta Diagnostics",
            slug="beta-diag",
            status=OrganizationStatus.SUSPENDED,
        )

        # Memberships
        self.membership_active = OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org_active,
            role=MembershipRole.ORGANIZATION_ADMIN,
            status=MembershipStatus.ACTIVE,
        )
        # Inactive membership in active organization
        self.org_other = Organization.objects.create(
            name="Gamma Diagnostics",
            slug="gamma-diag",
            status=OrganizationStatus.ACTIVE,
        )
        self.membership_inactive = OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org_other,
            role=MembershipRole.OPERATOR,
            status=MembershipStatus.INACTIVE,
        )
        # Active membership in suspended organization
        self.membership_in_suspended_org = OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org_inactive,
            role=MembershipRole.VIEWER,
            status=MembershipStatus.ACTIVE,
        )


class CSRFBootstrapAPITests(UserAPIBaseTestCase):
    def test_csrf_cookie_issuance(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.get("/api/v1/auth/csrf")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("csrftoken", client.cookies)
        csrf_token = client.cookies["csrftoken"].value
        self.assertTrue(len(csrf_token) > 0)
        self.assertEqual(response.data.get("detail"), "CSRF cookie set")
        # Ensure no sensitive user or platform info is in the response
        self.assertNotIn("password", str(response.data))
        self.assertNotIn("token", str(response.data))


class UserLoginAPITests(UserAPIBaseTestCase):
    def test_login_success_and_session_establishment(self):
        client = APIClient(enforce_csrf_checks=True)
        # 1. Bootstrap CSRF
        client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies["csrftoken"].value

        # 2. Login
        payload = {
            "email": "dr.smith@example.test",
            "password": self.password,
        }
        response = client.post(
            "/api/v1/auth/login",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-login-success-01",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["X-Request-ID"], "req-login-success-01")

        # Session cookie established
        self.assertIn("sessionid", client.cookies)
        session_id = client.cookies["sessionid"].value
        self.assertTrue(len(session_id) > 0)

        # Safe user summary structure
        data = response.data
        self.assertEqual(data["id"], str(self.user.id))
        self.assertEqual(data["email"], "dr.smith@example.test")
        self.assertEqual(data["display_name"], "Dr. Jane Smith")
        self.assertFalse(data["is_platform_admin"])

        # Memberships: only active membership in active org must be present
        memberships = data["memberships"]
        self.assertEqual(len(memberships), 1)
        self.assertEqual(memberships[0]["organization_id"], str(self.org_active.id))
        self.assertEqual(memberships[0]["organization_name"], "Alpha Diagnostics")
        self.assertEqual(memberships[0]["role"], MembershipRole.ORGANIZATION_ADMIN)

        # Zero credential or token leakage in payload
        self.assertNotIn("password", data)
        self.assertNotIn("password_hash", data)
        self.assertNotIn("access_token", data)
        self.assertNotIn("refresh_token", data)

    def test_login_email_case_insensitivity(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies["csrftoken"].value

        # Submit uppercase / mixed-case email
        payload = {
            "email": "DR.SMITH@EXAMPLE.TEST",
            "password": self.password,
        }
        response = client.post(
            "/api/v1/auth/login",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "dr.smith@example.test")

    def test_login_invalid_password_returns_generic_failure(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies["csrftoken"].value

        payload = {
            "email": "dr.smith@example.test",
            "password": "WrongPassword!999",
        }
        response = client.post(
            "/api/v1/auth/login",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-login-fail-pw",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.assertEqual(response.data["code"], "authentication_required")
        self.assertEqual(response.data["detail"], "Invalid credentials.")
        self.assertNotIn("sessionid", client.cookies)

        # Audit security failure event recorded
        audit = AuditEvent.objects.get(
            action=AuditAction.PLATFORM_SECURITY_FAILURE,
            request_id="req-login-fail-pw",
        )
        self.assertEqual(audit.safe_metadata.get("error_code"), "authentication_failed")
        # Ensure password and raw email were not leaked to audit
        self.assertNotIn("WrongPassword!999", str(audit.safe_metadata))
        self.assertNotIn("dr.smith@example.test", str(audit.safe_metadata))

    def test_login_unknown_email_returns_identical_generic_failure(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies["csrftoken"].value

        payload = {
            "email": "nonexistent.user@example.test",
            "password": "SomePassword123!",
        }
        response = client.post(
            "/api/v1/auth/login",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            HTTP_X_REQUEST_ID="req-login-fail-unknown",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")
        self.assertEqual(response.data["detail"], "Invalid credentials.")

        # Ensure nonexistent email is not in audit log
        audit = AuditEvent.objects.get(
            action=AuditAction.PLATFORM_SECURITY_FAILURE,
            request_id="req-login-fail-unknown",
        )
        self.assertNotIn("nonexistent.user@example.test", str(audit.safe_metadata))

    def test_login_inactive_user_returns_identical_generic_failure(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies["csrftoken"].value

        payload = {
            "email": "dr.smith@example.test",
            "password": self.password,
        }
        response = client.post(
            "/api/v1/auth/login",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")
        self.assertEqual(response.data["detail"], "Invalid credentials.")
        self.assertNotIn("sessionid", client.cookies)

    def test_login_unknown_fields_rejected(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies["csrftoken"].value

        payload = {
            "email": "dr.smith@example.test",
            "password": self.password,
            "organization_id": str(self.org_active.id),
            "role": "platform_admin",
        }
        response = client.post(
            "/api/v1/auth/login",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")
        self.assertIn("organization_id", response.data.get("field_errors", {}))
        self.assertIn("role", response.data.get("field_errors", {}))

    def test_login_csrf_protection_enforced_for_anonymous_request(self):
        client = APIClient(enforce_csrf_checks=True)

        # 1. Post with no CSRF token at all -> 403
        payload = {"email": "dr.smith@example.test", "password": self.password}
        res_no_csrf = client.post("/api/v1/auth/login", payload, format="json")
        self.assertEqual(res_no_csrf.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res_no_csrf.data["code"], "permission_denied")

        # 2. Post with invalid / tampered CSRF token -> 403
        client.get("/api/v1/auth/csrf")
        res_bad_csrf = client.post(
            "/api/v1/auth/login",
            payload,
            format="json",
            HTTP_X_CSRFTOKEN="invalid-tampered-token",
        )
        self.assertEqual(res_bad_csrf.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res_bad_csrf.data["code"], "permission_denied")

    @override_settings(
        REST_FRAMEWORK={
            "DEFAULT_AUTHENTICATION_CLASSES": [],
            "DEFAULT_PERMISSION_CLASSES": [],
            "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
            "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
            "EXCEPTION_HANDLER": "apps.devices.exceptions.api_exception_handler",
            "DEFAULT_THROTTLE_RATES": {
                "agent_activation": "10/minute",
                "agent_refresh": "30/minute",
                "user_login": "2/minute",
            },
            "NUM_PROXIES": 0,
        },
        DOCFLOW_TRUSTED_PROXIES=(),
        DOCFLOW_NUM_PROXIES=0,
    )
    def test_login_rate_limiting_and_safe_client_ip(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies["csrftoken"].value

        # Attempt 1 from 203.0.113.10 with spoofed XFF
        r1 = client.post(
            "/api/v1/auth/login",
            {"email": "dr.smith@example.test", "password": "bad1"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            REMOTE_ADDR="203.0.113.10",
            HTTP_X_FORWARDED_FOR="1.1.1.1",
        )
        self.assertEqual(r1.status_code, status.HTTP_401_UNAUTHORIZED)

        # Attempt 2 from 203.0.113.10 with different spoofed XFF
        r2 = client.post(
            "/api/v1/auth/login",
            {"email": "dr.smith@example.test", "password": "bad2"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            REMOTE_ADDR="203.0.113.10",
            HTTP_X_FORWARDED_FOR="2.2.2.2",
        )
        self.assertEqual(r2.status_code, status.HTTP_401_UNAUTHORIZED)

        # Attempt 3 from 203.0.113.10 must be throttled (429) despite rotating XFF
        r3 = client.post(
            "/api/v1/auth/login",
            {"email": "dr.smith@example.test", "password": "bad3"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
            REMOTE_ADDR="203.0.113.10",
            HTTP_X_FORWARDED_FOR="3.3.3.3",
        )
        self.assertEqual(r3.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(r3.data["code"], "rate_limited")


class UserLogoutAPITests(UserAPIBaseTestCase):
    def test_logout_success_and_session_invalidation(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies["csrftoken"].value

        # Log in first
        login_res = client.post(
            "/api/v1/auth/login",
            {"email": "dr.smith@example.test", "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(login_res.status_code, status.HTTP_200_OK)

        # Verify /me works before logout
        me_res1 = client.get("/api/v1/auth/me")
        self.assertEqual(me_res1.status_code, status.HTTP_200_OK)

        # Logout with {}
        csrf_token_post_login = client.cookies["csrftoken"].value
        logout_res = client.post(
            "/api/v1/auth/logout",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token_post_login,
        )
        self.assertEqual(logout_res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(logout_res.content, b"")

        # Session is invalidated: /me now returns 401
        me_res2 = client.get("/api/v1/auth/me")
        self.assertEqual(me_res2.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(me_res2.data["code"], "authentication_required")

    def test_logout_unauthenticated_rejected(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies["csrftoken"].value

        # Without an active session
        response = client.post(
            "/api/v1/auth/logout",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_logout_non_empty_body_rejected(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies["csrftoken"].value

        client.post(
            "/api/v1/auth/login",
            {"email": "dr.smith@example.test", "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        csrf_token_post_login = client.cookies["csrftoken"].value

        response = client.post(
            "/api/v1/auth/logout",
            {"reason": "manual_logout"},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token_post_login,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

        # Session should still be valid because logout request was rejected
        me_res = client.get("/api/v1/auth/me")
        self.assertEqual(me_res.status_code, status.HTTP_200_OK)

    def test_logout_csrf_protection_enforced(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies["csrftoken"].value

        client.post(
            "/api/v1/auth/login",
            {"email": "dr.smith@example.test", "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        # Attempt logout without CSRF token
        response = client.post("/api/v1/auth/logout", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "permission_denied")


class UserMeAPITests(UserAPIBaseTestCase):
    def test_me_authenticated_session(self):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/v1/auth/csrf")
        csrf_token = client.cookies["csrftoken"].value

        client.post(
            "/api/v1/auth/login",
            {"email": "dr.smith@example.test", "password": self.password},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        response = client.get("/api/v1/auth/me")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["id"], str(self.user.id))
        self.assertEqual(data["email"], "dr.smith@example.test")
        self.assertEqual(data["display_name"], "Dr. Jane Smith")
        self.assertFalse(data["is_platform_admin"])
        self.assertEqual(len(data["memberships"]), 1)
        self.assertEqual(data["memberships"][0]["organization_name"], "Alpha Diagnostics")

    def test_me_unauthenticated_returns_401(self):
        client = APIClient()
        response = client.get("/api/v1/auth/me")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_me_rejects_device_bearer_tokens(self):
        # Create a device and generate a device access token
        lab = Lab.objects.create(organization=self.org_active, name="Main Lab", code="ML01")
        branch = Branch.objects.create(organization=self.org_active, lab=lab, name="Main Branch", code="MB01")
        device = Device.objects.create(
            organization=self.org_active,
            branch=branch,
            name="Lab Device",
            status=DeviceStatus.ACTIVE,
        )
        device_token, _ = generate_access_token(device)

        client = APIClient()
        # Attempt to access /me using Device Bearer token
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {device_token}")
        response = client.get("/api/v1/auth/me")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")
