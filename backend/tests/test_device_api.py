"""
Tests for Docflow Agent Authentication APIs (Phase 1, Task 3B).

Covers:
  - POST /api/v1/agent/activation/exchange:
    * Activation success, device summary, access/refresh tokens, configuration version.
    * Invalid, expired, revoked, already-consumed code rejection.
    * Attempt-limit exhaustion and ineligible device handling.
    * Malformed JSON, unknown fields, and tenant override rejection.
    * IP-based throttling.
  - POST /api/v1/agent/auth/refresh:
    * Refresh rotation success and credential chaining.
    * Invalid and revoked refresh token rejection.
    * Refresh token reuse detection (HTTP 409 state_conflict) and full credential revocation.
    * Unknown fields and IP-based throttling.
  - POST /api/v1/agent/auth/revoke-self:
    * Authenticated device self-revocation (HTTP 204).
    * Credential revocation and device status update to revoked.
    * Rejection of repeated requests with old bearer token.
    * Non-empty body rejection.
    * Unauthenticated and tampered token rejection.
  - Standard error envelope, X-Request-ID propagation, and zero secret leakage.
"""

import datetime
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone as tz_utils
from rest_framework import status
from rest_framework.test import APIClient

from apps.audit.models import AuditAction, AuditEvent
from apps.devices.models import (
    Device,
    DeviceActivationCode,
    DeviceRefreshCredential,
    DeviceStatus,
)
from apps.devices.services import (
    generate_access_token,
    hash_token,
    issue_activation_code,
    verify_access_token,
)
from apps.tenants.models import Branch, Lab, Organization


class DeviceAPIBaseTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.org = Organization.objects.create(name="Central Diagnostics", slug="central-diag")
        self.other_org = Organization.objects.create(name="Malicious Org", slug="malicious-org")
        self.lab = Lab.objects.create(organization=self.org, name="Main Lab", code="ML01")
        self.other_lab = Lab.objects.create(organization=self.other_org, name="Other Lab", code="OL01")
        self.branch = Branch.objects.create(
            organization=self.org,
            lab=self.lab,
            name="Downtown Branch",
            code="DT01",
        )
        self.other_branch = Branch.objects.create(
            organization=self.other_org,
            lab=self.other_lab,
            name="Other Branch",
            code="OB01",
        )
        self.device = Device.objects.create(
            organization=self.org,
            branch=self.branch,
            name="Front Desk Agent",
            status=DeviceStatus.PENDING_ACTIVATION,
        )


class DeviceActivationAPITests(DeviceAPIBaseTestCase):
    def test_activation_exchange_success(self):
        issued = issue_activation_code(self.device, request_id="req-issue-01")
        payload = {
            "activation_code": issued.raw_code,
            "installation_id": "inst-win-42",
            "agent_version": "0.1.0",
            "platform": "windows",
        }

        response = self.client.post(
            "/api/v1/agent/activation/exchange",
            payload,
            format="json",
            HTTP_X_REQUEST_ID="req-act-success-123",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response["X-Request-ID"], "req-act-success-123")

        data = response.data
        self.assertIn("device", data)
        self.assertEqual(data["device"]["id"], str(self.device.id))
        self.assertEqual(data["device"]["name"], "Front Desk Agent")
        self.assertEqual(data["device"]["status"], "active")
        self.assertEqual(data["device"]["branch_id"], str(self.branch.id))

        self.assertIn("access_token", data)
        self.assertTrue(data["access_token_expires_at"].endswith("Z"))
        self.assertIn("refresh_token", data)
        self.assertTrue(data["refresh_token_expires_at"].endswith("Z"))
        self.assertEqual(data["configuration_version"], 1)

        # Raw code must never appear in response
        self.assertNotIn(issued.raw_code, str(data))

        # Device is now active in database
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.ACTIVE)
        self.assertEqual(self.device.agent_version, "0.1.0")

        # Success audit event must exist
        self.assertTrue(
            AuditEvent.objects.filter(
                action=AuditAction.DEVICE_ACTIVATED,
                target_id=str(self.device.id),
                request_id="req-act-success-123",
            ).exists()
        )

    def test_activation_exchange_invalid_code(self):
        payload = {
            "activation_code": "unknown-nonexistent-code",
            "installation_id": "inst-01",
        }
        response = self.client.post(
            "/api/v1/agent/activation/exchange",
            payload,
            format="json",
            HTTP_X_REQUEST_ID="req-invalid-code",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response["X-Request-ID"], "req-invalid-code")
        self.assertEqual(response.data["type"], "about:blank")
        self.assertEqual(response.data["status"], 400)
        self.assertEqual(response.data["code"], "validation_error")
        self.assertEqual(response.data["request_id"], "req-invalid-code")

        # Security audit event must be persisted
        self.assertTrue(
            AuditEvent.objects.filter(
                action=AuditAction.PLATFORM_SECURITY_FAILURE,
                request_id="req-invalid-code",
            ).exists()
        )

    def test_activation_exchange_expired_code(self):
        issued = issue_activation_code(self.device)
        issued.code_record.expires_at = tz_utils.now() - datetime.timedelta(minutes=5)
        issued.code_record.save(update_fields=["expires_at"])

        payload = {
            "activation_code": issued.raw_code,
            "installation_id": "inst-01",
        }
        response = self.client.post(
            "/api/v1/agent/activation/exchange",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_410_GONE)
        self.assertEqual(response.data["code"], "activation_expired")

    def test_activation_exchange_revoked_code(self):
        issued = issue_activation_code(self.device)
        issued.code_record.revoked_at = tz_utils.now()
        issued.code_record.save(update_fields=["revoked_at"])

        payload = {
            "activation_code": issued.raw_code,
            "installation_id": "inst-01",
        }
        response = self.client.post(
            "/api/v1/agent/activation/exchange",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_410_GONE)
        self.assertEqual(response.data["code"], "activation_expired")

    def test_activation_exchange_consumed_code(self):
        issued = issue_activation_code(self.device)
        # First exchange consumes code
        self.client.post(
            "/api/v1/agent/activation/exchange",
            {"activation_code": issued.raw_code, "installation_id": "inst-01"},
            format="json",
        )

        # Second exchange with the same code must return 410 activation_expired
        response = self.client.post(
            "/api/v1/agent/activation/exchange",
            {"activation_code": issued.raw_code, "installation_id": "inst-01"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_410_GONE)
        self.assertEqual(response.data["code"], "activation_expired")

    def test_activation_exchange_attempt_limit_exceeded(self):
        issued = issue_activation_code(self.device)
        issued.code_record.attempt_count = 5
        issued.code_record.save(update_fields=["attempt_count"])

        payload = {
            "activation_code": issued.raw_code,
            "installation_id": "inst-01",
        }
        response = self.client.post(
            "/api/v1/agent/activation/exchange",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_410_GONE)
        self.assertEqual(response.data["code"], "activation_expired")

    def test_activation_exchange_ineligible_device(self):
        self.device.status = DeviceStatus.REVOKED
        self.device.save(update_fields=["status"])

        raw_code = "ineligible-test-code-12345"
        DeviceActivationCode.objects.create(
            organization=self.org,
            branch=self.branch,
            device=self.device,
            code_hash=hash_token(raw_code),
        )

        payload = {
            "activation_code": raw_code,
            "installation_id": "inst-01",
        }
        response = self.client.post(
            "/api/v1/agent/activation/exchange",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

    def test_activation_exchange_malformed_json(self):
        response = self.client.post(
            "/api/v1/agent/activation/exchange",
            "not-a-json-object",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

    def test_activation_exchange_unknown_fields_rejected(self):
        issued = issue_activation_code(self.device)
        payload = {
            "activation_code": issued.raw_code,
            "installation_id": "inst-01",
            "malicious_extra": "unexpected",
        }
        response = self.client.post(
            "/api/v1/agent/activation/exchange",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")
        self.assertIn("field_errors", response.data)
        self.assertIn("malicious_extra", response.data["field_errors"])

    def test_activation_exchange_tenant_override_rejected(self):
        issued = issue_activation_code(self.device)
        payload = {
            "activation_code": issued.raw_code,
            "installation_id": "inst-01",
            "organization_id": str(self.other_org.id),
            "branch_id": str(self.other_branch.id),
        }
        response = self.client.post(
            "/api/v1/agent/activation/exchange",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

        # Device remains firmly bound to original tenant
        self.device.refresh_from_db()
        self.assertEqual(self.device.organization_id, self.org.id)
        self.assertEqual(self.device.branch_id, self.branch.id)

    @override_settings(
        REST_FRAMEWORK={
            "DEFAULT_AUTHENTICATION_CLASSES": [],
            "DEFAULT_PERMISSION_CLASSES": [],
            "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
            "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
            "EXCEPTION_HANDLER": "apps.devices.exceptions.api_exception_handler",
            "DEFAULT_THROTTLE_RATES": {"agent_activation": "2/minute", "agent_refresh": "30/minute"},
        }
    )
    def test_activation_exchange_throttling(self):
        issued = issue_activation_code(self.device)
        payload = {"activation_code": issued.raw_code, "installation_id": "inst-01"}

        # Request 1: 201 Created
        res1 = self.client.post("/api/v1/agent/activation/exchange", payload, format="json")
        self.assertEqual(res1.status_code, status.HTTP_201_CREATED)

        # Request 2 (second call triggers 410 or throttle depending on order):
        res2 = self.client.post("/api/v1/agent/activation/exchange", payload, format="json")
        self.assertIn(res2.status_code, (status.HTTP_410_GONE, status.HTTP_429_TOO_MANY_REQUESTS))

        # Request 3: Rate limited
        res3 = self.client.post("/api/v1/agent/activation/exchange", payload, format="json")
        self.assertEqual(res3.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(res3.data["code"], "rate_limited")
        self.assertIn("Retry-After", res3)


class DeviceRefreshAPITests(DeviceAPIBaseTestCase):
    def setUp(self):
        super().setUp()
        issued = issue_activation_code(self.device)
        act_res = self.client.post(
            "/api/v1/agent/activation/exchange",
            {"activation_code": issued.raw_code, "installation_id": "inst-01"},
            format="json",
        )
        self.assertEqual(act_res.status_code, status.HTTP_201_CREATED)
        self.initial_refresh = act_res.data["refresh_token"]
        self.initial_access = act_res.data["access_token"]

    def test_refresh_success(self):
        payload = {"refresh_token": self.initial_refresh}
        response = self.client.post(
            "/api/v1/agent/auth/refresh",
            payload,
            format="json",
            HTTP_X_REQUEST_ID="req-refresh-success",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["X-Request-ID"], "req-refresh-success")

        data = response.data
        self.assertIn("access_token", data)
        self.assertTrue(data["access_token_expires_at"].endswith("Z"))
        self.assertIn("refresh_token", data)
        self.assertTrue(data["refresh_token_expires_at"].endswith("Z"))
        self.assertNotEqual(data["refresh_token"], self.initial_refresh)

        # The new access token must be valid
        payload_verified = verify_access_token(data["access_token"])
        self.assertEqual(payload_verified["device_id"], str(self.device.id))

        # Old refresh token is now rotated and linked
        old_cred = DeviceRefreshCredential.objects.get(credential_hash=hash_token(self.initial_refresh))
        self.assertIsNotNone(old_cred.rotated_at)
        self.assertIsNotNone(old_cred.replaced_by)

    def test_refresh_invalid_token(self):
        payload = {"refresh_token": "non-existent-secret-token"}
        response = self.client.post(
            "/api/v1/agent/auth/refresh",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_refresh_revoked_token(self):
        cred = DeviceRefreshCredential.objects.get(credential_hash=hash_token(self.initial_refresh))
        cred.revoked_at = tz_utils.now()
        cred.save(update_fields=["revoked_at"])

        payload = {"refresh_token": self.initial_refresh}
        response = self.client.post(
            "/api/v1/agent/auth/refresh",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_refresh_reuse_conflict(self):
        # 1. Legitimate rotation
        rot_res = self.client.post(
            "/api/v1/agent/auth/refresh",
            {"refresh_token": self.initial_refresh},
            format="json",
        )
        self.assertEqual(rot_res.status_code, status.HTTP_200_OK)
        second_refresh = rot_res.data["refresh_token"]

        # 2. Reusing old initial_refresh (token reuse attack!)
        reuse_res = self.client.post(
            "/api/v1/agent/auth/refresh",
            {"refresh_token": self.initial_refresh},
            format="json",
            HTTP_X_REQUEST_ID="req-reuse-theft",
        )
        self.assertEqual(reuse_res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(reuse_res.data["code"], "state_conflict")
        self.assertEqual(reuse_res["X-Request-ID"], "req-reuse-theft")

        # 3. All active credentials for the device must now be revoked
        active_creds = DeviceRefreshCredential.objects.filter(
            device=self.device,
            revoked_at__isnull=True,
        )
        self.assertEqual(active_creds.count(), 0)

        # 4. Tampering audit event must be persisted
        self.assertTrue(
            AuditEvent.objects.filter(
                action=AuditAction.TAMPERING_DETECTED,
                target_id=str(self.device.id),
                request_id="req-reuse-theft",
            ).exists()
        )

        # 5. Even second_refresh is now rejected
        res3 = self.client.post(
            "/api/v1/agent/auth/refresh",
            {"refresh_token": second_refresh},
            format="json",
        )
        self.assertEqual(res3.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_unknown_fields_rejected(self):
        payload = {
            "refresh_token": self.initial_refresh,
            "organization_id": str(self.other_org.id),
        }
        response = self.client.post(
            "/api/v1/agent/auth/refresh",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

    @override_settings(
        REST_FRAMEWORK={
            "DEFAULT_AUTHENTICATION_CLASSES": [],
            "DEFAULT_PERMISSION_CLASSES": [],
            "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
            "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
            "EXCEPTION_HANDLER": "apps.devices.exceptions.api_exception_handler",
            "DEFAULT_THROTTLE_RATES": {"agent_activation": "10/minute", "agent_refresh": "2/minute"},
        }
    )
    def test_refresh_throttling(self):
        # Call 1
        r1 = self.client.post(
            "/api/v1/agent/auth/refresh",
            {"refresh_token": self.initial_refresh},
            format="json",
        )
        self.assertEqual(r1.status_code, status.HTTP_200_OK)

        # Call 2
        r2 = self.client.post(
            "/api/v1/agent/auth/refresh",
            {"refresh_token": r1.data["refresh_token"]},
            format="json",
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)

        # Call 3: Throttled
        r3 = self.client.post(
            "/api/v1/agent/auth/refresh",
            {"refresh_token": r2.data["refresh_token"]},
            format="json",
        )
        self.assertEqual(r3.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(r3.data["code"], "rate_limited")


class DeviceRevokeSelfAPITests(DeviceAPIBaseTestCase):
    def setUp(self):
        super().setUp()
        self.device.status = DeviceStatus.ACTIVE
        self.device.save(update_fields=["status"])
        self.access_token, _ = generate_access_token(self.device)

        # Create active refresh credential
        raw_refresh = "active-refresh-cred-secret"
        DeviceRefreshCredential.objects.create(
            device=self.device,
            credential_hash=hash_token(raw_refresh),
            issued_at=tz_utils.now(),
            expires_at=tz_utils.now() + datetime.timedelta(days=30),
        )

    def test_revoke_self_success(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        response = self.client.post(
            "/api/v1/agent/auth/revoke-self",
            {},
            format="json",
            HTTP_X_REQUEST_ID="req-revoke-self-01",
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(response["X-Request-ID"], "req-revoke-self-01")
        self.assertEqual(response.content, b"")

        # Device status transitioned to revoked
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.REVOKED)
        self.assertIsNotNone(self.device.revoked_at)

        # All refresh credentials for this device are revoked
        active_creds = DeviceRefreshCredential.objects.filter(
            device=self.device,
            revoked_at__isnull=True,
        )
        self.assertEqual(active_creds.count(), 0)

        # Safe audit event recorded
        self.assertTrue(
            AuditEvent.objects.filter(
                action=AuditAction.DEVICE_REVOKED,
                target_id=str(self.device.id),
                request_id="req-revoke-self-01",
            ).exists()
        )

    def test_revoke_self_repeat_request_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        res1 = self.client.post("/api/v1/agent/auth/revoke-self", {}, format="json")
        self.assertEqual(res1.status_code, status.HTTP_204_NO_CONTENT)

        # Repeating with the same Bearer token fails because device is revoked
        res2 = self.client.post("/api/v1/agent/auth/revoke-self", {}, format="json")
        self.assertEqual(res2.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(res2.data["code"], "authentication_required")

    def test_revoke_self_unauthenticated(self):
        # No Bearer header
        response = self.client.post("/api/v1/agent/auth/revoke-self", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_revoke_self_tampered_token(self):
        tampered = self.access_token[:-4] + "xxxx"
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tampered}")
        response = self.client.post("/api/v1/agent/auth/revoke-self", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["code"], "authentication_required")

    def test_revoke_self_non_empty_body_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token}")
        response = self.client.post(
            "/api/v1/agent/auth/revoke-self",
            {"reason": "malformed_request_with_body"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["code"], "validation_error")

        # Device must not have been revoked
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.ACTIVE)


class DeviceAPISecurityAndContractTests(DeviceAPIBaseTestCase):
    def test_error_envelope_structure(self):
        response = self.client.post(
            "/api/v1/agent/activation/exchange",
            {},
            format="json",
            HTTP_X_REQUEST_ID="req-envelope-test",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        data = response.data
        self.assertEqual(data["type"], "about:blank")
        self.assertEqual(data["title"], "Validation failed")
        self.assertEqual(data["status"], 400)
        self.assertEqual(data["code"], "validation_error")
        self.assertIn("detail", data)
        self.assertEqual(data["request_id"], "req-envelope-test")
        self.assertIn("field_errors", data)

    def test_generated_request_id_when_header_absent(self):
        response = self.client.post(
            "/api/v1/agent/activation/exchange",
            {},
            format="json",
        )
        header_id = response.get("X-Request-ID")
        self.assertIsNotNone(header_id)
        self.assertTrue(header_id.startswith("req_"))
        self.assertEqual(response.data["request_id"], header_id)

    def test_no_secret_or_token_leakage_in_error_responses(self):
        super_secret_code = "my-super-secret-code-do-not-leak-9999"
        response = self.client.post(
            "/api/v1/agent/activation/exchange",
            {"activation_code": super_secret_code, "installation_id": "inst-01"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response_str = str(response.data)
        self.assertNotIn(super_secret_code, response_str)

        # Ensure no audit event contains the raw secret
        events = AuditEvent.objects.filter(safe_metadata__icontains=super_secret_code)
        self.assertEqual(events.count(), 0)
