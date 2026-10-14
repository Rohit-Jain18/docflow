"""
Tests for Device Activation and Credential Services (Phase 1, Task 3A).

Covers:
  - Activation-code issuance: cryptographic randomness, hashed-only storage, replacement revocation, audit emission.
  - Atomic activation exchange: expiry, revocation, single-use consumption, attempt bounding, eligibility checks,
    initial credential creation, and zero secret logging in audit events.
  - Signed device access tokens: generation, verification, expiry enforcement, and tampering detection.
  - Refresh credential rotation: atomic replacement chaining, rejection of stale credentials, and token reuse detection
    triggering complete device credential revocation and tampering alerts.
  - DRF DeviceBearerAuthentication: Bearer parsing, token validation, inactive/revoked device rejection.
"""

import datetime
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.utils import timezone as tz_utils
from rest_framework.exceptions import AuthenticationFailed

from apps.audit.models import AuditAction, AuditEvent
from apps.devices.authentication import DeviceBearerAuthentication
from apps.devices.models import (
    Device,
    DeviceActivationCode,
    DeviceRefreshCredential,
    DeviceStatus,
)
from apps.devices.services import (
    ACCESS_TOKEN_PURPOSE,
    DEFAULT_ACTIVATION_CODE_LIFETIME,
    DEVICE_ACCESS_TOKEN_LIFETIME,
    DEVICE_REFRESH_TOKEN_LIFETIME,
    MAX_ACTIVATION_ATTEMPTS,
    ActivationAttemptLimitError,
    ActivationCodeConsumedError,
    ActivationCodeExpiredError,
    ActivationCodeRevokedError,
    IneligibleDeviceError,
    InvalidActivationCodeError,
    InvalidRefreshTokenError,
    RefreshTokenReuseError,
    exchange_activation_code,
    generate_access_token,
    hash_token,
    issue_activation_code,
    rotate_refresh_token,
    verify_access_token,
)
from apps.tenants.models import Branch, Lab, Organization

User = get_user_model()


class DeviceServiceBaseTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="LabCorp Diagnostics", slug="labcorp")
        self.other_org = Organization.objects.create(name="Other Org", slug="other-org")
        self.lab = Lab.objects.create(organization=self.org, name="Central Lab", code="CL01")
        self.branch = Branch.objects.create(
            organization=self.org,
            lab=self.lab,
            name="Main Branch",
            code="MB01",
        )
        self.other_lab = Lab.objects.create(organization=self.other_org, name="Other Lab", code="OL01")
        self.other_branch = Branch.objects.create(
            organization=self.other_org,
            lab=self.other_lab,
            name="Other Branch",
            code="OB01",
        )
        self.user = User.objects.create_user(
            email="manager@labcorp.test",
            password="secure-password-123",
            display_name="Branch Manager",
        )
        self.device = Device.objects.create(
            organization=self.org,
            branch=self.branch,
            name="Reception-PC-1",
            status=DeviceStatus.PENDING_ACTIVATION,
        )


class CodeIssuanceServiceTest(DeviceServiceBaseTestCase):
    def test_successful_code_issuance_and_hashed_storage(self):
        issued = issue_activation_code(device=self.device, created_by=self.user)

        self.assertIsInstance(issued.raw_code, str)
        self.assertGreater(len(issued.raw_code), 20)

        # Verify DB record
        code_record = DeviceActivationCode.objects.get(id=issued.code_record.id)
        self.assertEqual(code_record.device, self.device)
        self.assertEqual(code_record.organization, self.org)
        self.assertEqual(code_record.branch, self.branch)
        self.assertEqual(code_record.created_by, self.user)
        self.assertIsNone(code_record.consumed_at)
        self.assertIsNone(code_record.revoked_at)
        self.assertEqual(code_record.attempt_count, 0)

        # Hashed-only storage: raw code must NEVER equal code_hash
        self.assertNotEqual(issued.raw_code, code_record.code_hash)
        self.assertEqual(code_record.code_hash, hash_token(issued.raw_code))

        # Check default expiry (~10 minutes)
        time_diff = code_record.expires_at - code_record.created_at
        self.assertAlmostEqual(time_diff.total_seconds(), DEFAULT_ACTIVATION_CODE_LIFETIME.total_seconds(), delta=5)

    def test_replaces_and_revokes_previous_unused_codes(self):
        code1 = issue_activation_code(device=self.device, created_by=self.user)
        code2 = issue_activation_code(device=self.device, created_by=self.user)

        code1_record = DeviceActivationCode.objects.get(id=code1.code_record.id)
        code2_record = DeviceActivationCode.objects.get(id=code2.code_record.id)

        self.assertIsNotNone(code1_record.revoked_at)
        self.assertTrue(code1_record.is_revoked)
        self.assertIsNone(code2_record.revoked_at)
        self.assertFalse(code2_record.is_revoked)

    def test_issuance_rejected_for_revoked_or_disabled_device(self):
        for status in (DeviceStatus.REVOKED, DeviceStatus.DISABLED):
            with self.subTest(status=status):
                self.device.status = status
                self.device.save(update_fields=["status"])

                with self.assertRaises(IneligibleDeviceError):
                    issue_activation_code(device=self.device, created_by=self.user)

    def test_issuance_audited_without_raw_code(self):
        issued = issue_activation_code(device=self.device, created_by=self.user, request_id="req-issue-1")

        event = AuditEvent.objects.filter(
            action=AuditAction.DEVICE_ACTIVATION_CODE_ISSUED,
            target_id=str(self.device.id),
        ).latest("timestamp")

        self.assertEqual(event.organization, self.org)
        self.assertEqual(event.actor_user, self.user)
        self.assertEqual(event.request_id, "req-issue-1")
        self.assertEqual(event.safe_metadata["device_name"], self.device.name)
        self.assertEqual(event.safe_metadata["device_id"], str(self.device.id))

        # Crucial check: raw code is NOT in metadata or anywhere in audit event
        self.assertNotIn(issued.raw_code, str(event.safe_metadata))
        self.assertNotIn(issued.code_record.code_hash, str(event.safe_metadata))


class ActivationExchangeServiceTest(DeviceServiceBaseTestCase):
    def setUp(self):
        super().setUp()
        self.issued = issue_activation_code(device=self.device, created_by=self.user)
        self.raw_code = self.issued.raw_code

    def test_successful_activation_exchange_and_credential_return(self):
        result = exchange_activation_code(
            activation_code=self.raw_code,
            installation_id="install-guid-1234",
            agent_version="0.1.0",
            platform="windows",
            ip_address="10.0.0.42",
            request_id="req-activate-1",
        )

        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.ACTIVE)
        self.assertIsNotNone(self.device.activated_at)
        self.assertIsNotNone(self.device.last_seen_at)
        self.assertEqual(self.device.agent_version, "0.1.0")
        self.assertEqual(self.device.platform, "windows")
        self.assertEqual(self.device.last_ip, "10.0.0.42")

        # Code record marked consumed
        code_record = DeviceActivationCode.objects.get(id=self.issued.code_record.id)
        self.assertTrue(code_record.is_consumed)
        self.assertEqual(code_record.attempt_count, 1)

        # Credentials returned
        self.assertIsNotNone(result.access_token)
        self.assertIsNotNone(result.refresh_token)
        self.assertEqual(result.configuration_version, 1)

        # Refresh credential stored as hash
        cred = DeviceRefreshCredential.objects.get(device=self.device)
        self.assertEqual(cred.credential_hash, hash_token(result.refresh_token))
        self.assertFalse(cred.is_expired)
        self.assertFalse(cred.is_rotated)
        self.assertFalse(cred.is_revoked)

        # Audit event created without raw codes/tokens
        event = AuditEvent.objects.filter(
            action=AuditAction.DEVICE_ACTIVATED,
            target_id=str(self.device.id),
        ).latest("timestamp")
        self.assertEqual(event.organization, self.org)
        self.assertEqual(event.actor_device, self.device)
        self.assertEqual(event.safe_metadata["device_name"], self.device.name)
        self.assertEqual(event.safe_metadata["status"], "active")
        self.assertNotIn(self.raw_code, str(event.safe_metadata))
        self.assertNotIn(result.refresh_token, str(event.safe_metadata))
        self.assertNotIn(result.access_token, str(event.safe_metadata))

    def test_invalid_code_rejected_and_audited(self):
        with self.assertRaises(InvalidActivationCodeError):
            exchange_activation_code(
                activation_code="non-existent-code-xyz",
                installation_id="install-1",
                request_id="req-invalid",
            )

        # Platform audit event recorded
        event = AuditEvent.objects.filter(
            action=AuditAction.PLATFORM_SECURITY_FAILURE,
            request_id="req-invalid",
        ).latest("timestamp")
        self.assertIsNone(event.organization)
        self.assertEqual(event.safe_metadata["error_code"], "activation_code_not_found")

    def test_expired_code_rejected(self):
        # Set code expires_at to 1 second in the past
        code_record = self.issued.code_record
        code_record.expires_at = tz_utils.now() - datetime.timedelta(seconds=1)
        code_record.save(update_fields=["expires_at"])

        with self.assertRaises(ActivationCodeExpiredError):
            exchange_activation_code(
                activation_code=self.raw_code,
                installation_id="install-1",
            )

        code_record.refresh_from_db()
        self.assertEqual(code_record.attempt_count, 1)
        self.assertFalse(code_record.is_consumed)
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.PENDING_ACTIVATION)

    def test_revoked_code_rejected(self):
        code_record = self.issued.code_record
        code_record.revoked_at = tz_utils.now()
        code_record.save(update_fields=["revoked_at"])

        with self.assertRaises(ActivationCodeRevokedError):
            exchange_activation_code(
                activation_code=self.raw_code,
                installation_id="install-1",
            )

        code_record.refresh_from_db()
        self.assertEqual(code_record.attempt_count, 1)

    def test_already_consumed_code_rejected_and_cannot_activate_twice(self):
        # First exchange succeeds
        res1 = exchange_activation_code(
            activation_code=self.raw_code,
            installation_id="install-1",
        )
        self.assertIsNotNone(res1.access_token)

        # Second exchange of same code MUST fail
        with self.assertRaises(ActivationCodeConsumedError):
            exchange_activation_code(
                activation_code=self.raw_code,
                installation_id="install-1",
            )

        code_record = self.issued.code_record
        code_record.refresh_from_db()
        self.assertEqual(code_record.attempt_count, 2)

    def test_attempt_limit_exceeded_rejects_and_revokes(self):
        code_record = self.issued.code_record
        code_record.attempt_count = MAX_ACTIVATION_ATTEMPTS
        code_record.save(update_fields=["attempt_count"])

        with self.assertRaises(ActivationAttemptLimitError):
            exchange_activation_code(
                activation_code=self.raw_code,
                installation_id="install-1",
            )

        code_record.refresh_from_db()
        self.assertIsNotNone(code_record.revoked_at)
        self.assertEqual(code_record.attempt_count, MAX_ACTIVATION_ATTEMPTS + 1)

    def test_ineligible_device_status_rejected(self):
        for status in (DeviceStatus.REVOKED, DeviceStatus.DISABLED):
            with self.subTest(status=status):
                self.device.status = status
                self.device.save(update_fields=["status"])

                with self.assertRaises(IneligibleDeviceError):
                    exchange_activation_code(
                        activation_code=self.raw_code,
                        installation_id="install-1",
                    )

    def test_transaction_rollback_on_activation_failure(self):
        # Patch DeviceRefreshCredential.objects.create to raise an unexpected error
        with patch("apps.devices.services.DeviceRefreshCredential.objects.create", side_effect=RuntimeError("DB error")):
            with self.assertRaises(RuntimeError):
                exchange_activation_code(
                    activation_code=self.raw_code,
                    installation_id="install-1",
                )

        # Verify device remains pending activation and code remains unconsumed due to rollback
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, DeviceStatus.PENDING_ACTIVATION)

        code_record = self.issued.code_record
        code_record.refresh_from_db()
        self.assertFalse(code_record.is_consumed)


class AccessTokenSecurityTest(DeviceServiceBaseTestCase):
    def setUp(self):
        super().setUp()
        self.device.status = DeviceStatus.ACTIVE
        self.device.save(update_fields=["status"])

    def test_access_token_generation_and_payload_verification(self):
        token, expires_at = generate_access_token(self.device)
        payload = verify_access_token(token)

        self.assertEqual(payload["device_id"], str(self.device.id))
        self.assertEqual(payload["organization_id"], str(self.org.id))
        self.assertEqual(payload["branch_id"], str(self.branch.id))
        self.assertEqual(payload["purpose"], ACCESS_TOKEN_PURPOSE)

    def test_access_token_tampering_rejected(self):
        token, _ = generate_access_token(self.device)
        # Modify signature portion
        tampered_token = token[:-4] + "abcd"

        with self.assertRaises(ValidationError) as ctx:
            verify_access_token(tampered_token)
        self.assertIn("signature", str(ctx.exception).lower())

    def test_expired_access_token_rejected(self):
        # Generate token with 0 lifetime
        token, _ = generate_access_token(self.device, lifetime=datetime.timedelta(seconds=-5))

        with self.assertRaises(ValidationError) as ctx:
            verify_access_token(token)
        self.assertIn("expired", str(ctx.exception).lower())


class RefreshTokenRotationServiceTest(DeviceServiceBaseTestCase):
    def setUp(self):
        super().setUp()
        issued = issue_activation_code(device=self.device, created_by=self.user)
        result = exchange_activation_code(
            activation_code=issued.raw_code,
            installation_id="install-1",
        )
        self.initial_refresh_token = result.refresh_token

    def test_successful_refresh_rotation(self):
        rotate_result = rotate_refresh_token(
            refresh_token=self.initial_refresh_token,
            ip_address="10.1.2.3",
            request_id="req-rot-1",
        )

        self.assertIsNotNone(rotate_result.access_token)
        self.assertIsNotNone(rotate_result.refresh_token)
        self.assertNotEqual(self.initial_refresh_token, rotate_result.refresh_token)

        # Check old credential is now marked rotated and points to new credential
        old_cred = DeviceRefreshCredential.objects.get(credential_hash=hash_token(self.initial_refresh_token))
        self.assertTrue(old_cred.is_rotated)
        self.assertIsNotNone(old_cred.rotated_at)
        self.assertIsNotNone(old_cred.replaced_by)

        # New credential exists and is active
        new_cred = DeviceRefreshCredential.objects.get(credential_hash=hash_token(rotate_result.refresh_token))
        self.assertEqual(old_cred.replaced_by, new_cred)
        self.assertTrue(new_cred.is_active)

        # Device last seen and IP updated
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_ip, "10.1.2.3")

    def test_rotated_token_reuse_detection_revokes_all_credentials_and_alerts(self):
        # 1. Legitimate rotation: Token 1 -> Token 2
        rotate_result = rotate_refresh_token(self.initial_refresh_token)
        token_2 = rotate_result.refresh_token

        # 2. Replay/reuse attempt: Submit Token 1 AGAIN
        with self.assertRaises(RefreshTokenReuseError):
            rotate_refresh_token(self.initial_refresh_token)

        # 3. All outstanding credentials for device must now be revoked
        active_creds = DeviceRefreshCredential.objects.filter(
            device=self.device,
            revoked_at__isnull=True,
        )
        self.assertEqual(active_creds.count(), 0)

        # Token 2 should also now be revoked
        token_2_cred = DeviceRefreshCredential.objects.get(credential_hash=hash_token(token_2))
        self.assertTrue(token_2_cred.is_revoked)

        # 4. Tampering alert audit event recorded
        event = AuditEvent.objects.filter(
            action=AuditAction.TAMPERING_DETECTED,
            target_id=str(self.device.id),
        ).latest("timestamp")
        self.assertEqual(event.organization, self.org)
        self.assertEqual(event.safe_metadata["error_code"], "refresh_token_reuse_detected")
        self.assertNotIn(self.initial_refresh_token, str(event.safe_metadata))

    def test_expired_refresh_token_rejected(self):
        cred = DeviceRefreshCredential.objects.get(credential_hash=hash_token(self.initial_refresh_token))
        cred.expires_at = tz_utils.now() - datetime.timedelta(seconds=1)
        cred.save(update_fields=["expires_at"])

        with self.assertRaises(InvalidRefreshTokenError) as ctx:
            rotate_refresh_token(self.initial_refresh_token)
        self.assertIn("expired", str(ctx.exception).lower())

    def test_revoked_refresh_token_rejected(self):
        cred = DeviceRefreshCredential.objects.get(credential_hash=hash_token(self.initial_refresh_token))
        cred.revoked_at = tz_utils.now()
        cred.save(update_fields=["revoked_at"])

        with self.assertRaises(InvalidRefreshTokenError) as ctx:
            rotate_refresh_token(self.initial_refresh_token)
        self.assertIn("revoked", str(ctx.exception).lower())

    def test_inactive_device_cannot_refresh(self):
        self.device.status = DeviceStatus.DISABLED
        self.device.save(update_fields=["status"])

        with self.assertRaises(InvalidRefreshTokenError) as ctx:
            rotate_refresh_token(self.initial_refresh_token)
        self.assertIn("disabled", str(ctx.exception).lower())


class DeviceBearerAuthenticationTest(DeviceServiceBaseTestCase):
    def setUp(self):
        super().setUp()
        self.device.status = DeviceStatus.ACTIVE
        self.device.save(update_fields=["status"])
        self.token, _ = generate_access_token(self.device)
        self.auth = DeviceBearerAuthentication()
        self.rf = RequestFactory()

    def test_authenticated_request_with_valid_bearer_token(self):
        request = self.rf.get("/api/v1/reports", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        result = self.auth.authenticate(request)

        self.assertIsNotNone(result)
        authenticated_device, token = result
        self.assertEqual(authenticated_device.id, self.device.id)
        self.assertTrue(authenticated_device.is_authenticated)
        self.assertFalse(authenticated_device.is_anonymous)
        self.assertEqual(token, self.token)

    def test_missing_authorization_header_returns_none(self):
        request = self.rf.get("/api/v1/reports")
        self.assertIsNone(self.auth.authenticate(request))

    def test_non_bearer_header_returns_none(self):
        request = self.rf.get("/api/v1/reports", HTTP_AUTHORIZATION="Basic dXNlcjpwYXNz")
        self.assertIsNone(self.auth.authenticate(request))

    def test_malformed_bearer_headers_fail(self):
        malformed_headers = [
            "Bearer",
            "Bearer token1 token2",
        ]
        for header in malformed_headers:
            with self.subTest(header=header):
                request = self.rf.get("/api/v1/reports", HTTP_AUTHORIZATION=header)
                with self.assertRaises(AuthenticationFailed):
                    self.auth.authenticate(request)

    def test_tampered_token_fails_authentication(self):
        tampered = self.token[:-4] + "zzzz"
        request = self.rf.get("/api/v1/reports", HTTP_AUTHORIZATION=f"Bearer {tampered}")
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(request)

    def test_inactive_or_revoked_device_fails_authentication(self):
        for status in (DeviceStatus.PENDING_ACTIVATION, DeviceStatus.REVOKED, DeviceStatus.DISABLED):
            with self.subTest(status=status):
                self.device.status = status
                self.device.save(update_fields=["status"])

                request = self.rf.get("/api/v1/reports", HTTP_AUTHORIZATION=f"Bearer {self.token}")
                with self.assertRaises(AuthenticationFailed) as ctx:
                    self.auth.authenticate(request)
                self.assertIn(status, str(ctx.exception))
