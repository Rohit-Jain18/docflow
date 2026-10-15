"""
Report Metadata Registration Service for Docflow Windows Agent.

Implements requirements from:
- docs/AGENT_SPEC.md §§ 4, 6, 7, 8
- docs/API_CONTRACTS.md §§ 1, 2, 5
- docs/RULES.md (Rules 1, 2, 3, 4, 5, 7)
- docs/DELIVERY_STATE_MACHINE.md

Endpoints used:
- POST /api/v1/agent/reports
  Headers:
    Authorization: Bearer <device-token>
    Idempotency-Key: <64-character lowercase hex canonical fingerprint>
  Payload:
    recipient_phone_e164, content_sha256, file_size_bytes, document_type, agent_created_at
  Response (202 Accepted):
    report_id, status: "queued", duplicate: bool, created_at

Enforces:
- Metadata-first registration sequencing before any media preparation or dispatch.
- Strict data minimization: ZERO PDF bytes, no local filesystem paths, and no phone-bearing filenames.
- Derives tenant/branch authority strictly from the server-authenticated device.
- Atomic state transitions: VALIDATED/RETRY_WAIT -> METADATA_REGISTERING -> METADATA_REGISTERED.
- Idempotency preservation: identical fingerprints and keys reused across retries.
- Safe error classification: transient retry backoff vs account_not_verified vs conflict.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import re
import uuid
from typing import Any

from docflow_agent.client import (
    ApiClient,
    ApiResponseError,
    ApiConflictError,
    ApiAuthenticationError,
    ApiPermissionError,
    ApiTimeoutError,
    ApiConnectionError,
    ApiPayloadError,
    ApiRateLimitError,
)
from docflow_agent.sync import DeviceRevokedError
from docflow_agent.token_manager import (
    TokenError,
    TokenAuthenticationError,
    TokenReuseConflictError,
    TokenRotationAmbiguousError,
    TokenRateLimitedError,
)
from docflow_agent.queue import (
    JobQueue,
    JobRecord,
    JobStatus,
    compute_fingerprint,
    mask_phone,
)

logger = logging.getLogger(__name__)

REPORT_REGISTRATION_ENDPOINT = "/api/v1/agent/reports"

# 64 lowercase hex characters
_HEX_64_REGEX = re.compile(r"^[0-9a-f]{64}$")

# Strict ISO 8601 UTC timestamp regex ending in 'Z'
_ISO8601_UTC_Z_REGEX = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)


class RegistrationError(Exception):
    """Base exception for report registration failures."""


class AccountNotVerifiedError(RegistrationError):
    """Raised when server returns HTTP 422 account_not_verified."""


class RegistrationConflictError(RegistrationError):
    """Raised when server returns HTTP 409 idempotency_conflict."""


@dataclasses.dataclass(frozen=True)
class RegistrationResult:
    """Safe representation of a successful report metadata registration response."""

    report_id: str
    status: str
    is_duplicate: bool
    created_at: str

    def __repr__(self) -> str:
        return (
            f"RegistrationResult(report_id={self.report_id!r}, "
            f"status={self.status!r}, duplicate={self.is_duplicate})"
        )


class ReportRegistrationService:
    """Coordinates report metadata registration with the Docflow backend."""

    def __init__(
        self,
        client: ApiClient,
        queue: JobQueue,
        branch_id: str,
    ) -> None:
        self.client = client
        self.queue = queue
        self.branch_id = str(branch_id).strip()

        if not self.branch_id:
            raise ValueError("branch_id is required.")

    def register_job(self, job: JobRecord) -> RegistrationResult:
        """Register report metadata for a queued job.

        Transitions:
          - Pre-request: VALIDATED or RETRY_WAIT -> METADATA_REGISTERING
          - Success: METADATA_REGISTERING -> METADATA_REGISTERED (saving docflow_report_id)
          - Account unverified (422): METADATA_REGISTERING -> RETRY_WAIT (with safe error code)
          - Conflict (409): METADATA_REGISTERING -> FAILED (with idempotency_conflict)
          - Network error / timeout: METADATA_REGISTERING -> RETRY_WAIT
        """
        # 1. State verification and pre-request transition
        current_job = job
        if current_job.status != JobStatus.METADATA_REGISTERING.value:
            if current_job.status not in (JobStatus.VALIDATED.value, JobStatus.RETRY_WAIT.value):
                raise RegistrationError(
                    f"Job '{job.id}' is in status '{job.status}'; expected 'validated' or 'retry_wait'."
                )
            current_job = self.queue.update_status(
                job.id,
                JobStatus.METADATA_REGISTERING,
                details={"action": "registering_metadata"},
            )

        # 2. Canonical fingerprint and idempotency key
        fingerprint = current_job.idempotency_key
        if not _HEX_64_REGEX.match(fingerprint):
            # Recalculate if not matching 64 hex
            fingerprint = compute_fingerprint(
                branch_id=self.branch_id,
                recipient_phone_e164=current_job.recipient_phone_e164,
                content_sha256=current_job.content_sha256,
            )

        # 3. Payload preparation (strictly data-minimized; NO file paths, NO filenames, NO PDF bytes)
        payload = {
            "recipient_phone_e164": current_job.recipient_phone_e164,
            "content_sha256": current_job.content_sha256,
            "file_size_bytes": current_job.file_size_bytes,
            "document_type": "diagnostic_report",
            "agent_created_at": current_job.created_at,
        }

        headers = {
            "Idempotency-Key": fingerprint,
        }

        # 4. Authenticated API Call
        try:
            resp = self.client.post(
                REPORT_REGISTRATION_ENDPOINT,
                json=payload,
                headers=headers,
                authenticated=True,
            )
        except ApiConflictError as exc:
            logger.error("Report registration conflict (409) for job %s: %s", current_job.id, exc.code)
            self.queue.update_status(
                current_job.id,
                JobStatus.FAILED,
                error_code="idempotency_conflict",
                details={"reason": "idempotency_conflict"},
            )
            raise RegistrationConflictError("Idempotency conflict during report registration.") from exc

        except ApiPermissionError as exc:
            logger.error("Report registration rejected (403): Device or branch revoked/inactive.")
            self.queue.update_status(
                current_job.id,
                JobStatus.RETRY_WAIT,
                error_code="device_revoked",
                increment_attempt=False,
            )
            raise DeviceRevokedError(detail="Device or branch revoked or inactive.", request_id=exc.request_id) from exc

        except (TokenAuthenticationError, TokenReuseConflictError) as exc:
            logger.error("Authentication failed during report registration: %s", exc.code)
            self.queue.update_status(
                current_job.id,
                JobStatus.RETRY_WAIT,
                error_code=exc.code,
                increment_attempt=False,
            )
            raise

        except TokenRotationAmbiguousError as exc:
            logger.error("Token rotation ambiguous during report registration. Pausing for operator recovery.")
            self.queue.update_status(
                current_job.id,
                JobStatus.RETRY_WAIT,
                error_code="token_rotation_ambiguous",
                increment_attempt=False,
            )
            raise

        except (TokenRateLimitedError, ApiRateLimitError) as exc:
            retry_after = getattr(exc, "retry_after", None) or 60.0
            logger.warning("Rate limited during report registration; backing off for %s seconds.", retry_after)
            next_attempt_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=retry_after)
            self.queue.update_status(
                current_job.id,
                JobStatus.RETRY_WAIT,
                error_code="rate_limited",
                next_attempt_at=next_attempt_dt.isoformat(),
                increment_attempt=False,
            )
            raise

        except ApiResponseError as exc:
            if exc.code == "account_not_verified" or exc.status_code == 422:
                logger.warning(
                    "Branch has no active verified WhatsApp account (422) for job %s. Queuing for retry.",
                    current_job.id,
                )
                self.queue.update_status(
                    current_job.id,
                    JobStatus.RETRY_WAIT,
                    error_code="account_not_verified",
                    details={"reason": "account_not_verified"},
                )
                raise AccountNotVerifiedError("No active verified WhatsApp account assigned to branch.") from exc

            # Other API response errors
            logger.warning("API error during report registration for job %s: %s", current_job.id, exc.code)
            self.queue.update_status(
                current_job.id,
                JobStatus.RETRY_WAIT,
                error_code=exc.code or "registration_error",
                details={"reason": exc.code or "api_error"},
            )
            raise RegistrationError(f"Report registration failed: {exc.code}") from exc

        except (ApiTimeoutError, ApiConnectionError) as exc:
            logger.warning(
                "Network timeout/error during report registration for job %s. Keeping in retry_wait.",
                current_job.id,
            )
            self.queue.update_status(
                current_job.id,
                JobStatus.RETRY_WAIT,
                error_code="network_timeout",
                increment_attempt=False,
                details={"reason": type(exc).__name__},
            )
            raise

        # 5. Parse and validate response strictly without raw input leakage
        if not isinstance(resp, dict):
            self.queue.update_status(
                current_job.id,
                JobStatus.RETRY_WAIT,
                error_code="malformed_registration_response",
                increment_attempt=False,
            )
            raise ApiPayloadError("Server returned non-dictionary response for report registration.")

        report_id = resp.get("report_id")
        server_status = resp.get("status")
        duplicate_val = resp.get("duplicate")
        created_at = resp.get("created_at")

        # Required status == "queued"
        if server_status != "queued":
            self.queue.update_status(
                current_job.id,
                JobStatus.RETRY_WAIT,
                error_code="malformed_registration_response",
                increment_attempt=False,
            )
            raise ApiPayloadError("Report registration response status is invalid; expected 'queued'.")

        # Required report_id must be valid UUID string
        if not report_id or not isinstance(report_id, str):
            self.queue.update_status(
                current_job.id,
                JobStatus.RETRY_WAIT,
                error_code="malformed_registration_response",
                increment_attempt=False,
            )
            raise ApiPayloadError("Report registration response missing valid 'report_id'.")
        try:
            parsed_uuid = uuid.UUID(report_id)
            canonical_report_id = str(parsed_uuid)
        except (ValueError, TypeError):
            self.queue.update_status(
                current_job.id,
                JobStatus.RETRY_WAIT,
                error_code="malformed_registration_response",
                increment_attempt=False,
            )
            raise ApiPayloadError("Report registration response missing valid UUID 'report_id'.") from None

        # Required duplicate must be an actual boolean (no coercion)
        if not isinstance(duplicate_val, bool):
            self.queue.update_status(
                current_job.id,
                JobStatus.RETRY_WAIT,
                error_code="malformed_registration_response",
                increment_attempt=False,
            )
            raise ApiPayloadError("Report registration response missing valid boolean 'duplicate'.")

        # Required created_at must be strict UTC ISO 8601 ending in Z and calendar-valid
        if not created_at or not isinstance(created_at, str) or not _ISO8601_UTC_Z_REGEX.match(created_at):
            self.queue.update_status(
                current_job.id,
                JobStatus.RETRY_WAIT,
                error_code="malformed_registration_response",
                increment_attempt=False,
            )
            raise ApiPayloadError("Report registration response missing valid UTC Z 'created_at'.")
        try:
            iso_clean = created_at[:-1] + "+00:00"
            dt = datetime.datetime.fromisoformat(iso_clean)
            if dt.tzinfo is None:
                raise ValueError
        except (ValueError, TypeError):
            self.queue.update_status(
                current_job.id,
                JobStatus.RETRY_WAIT,
                error_code="malformed_registration_response",
                increment_attempt=False,
            )
            raise ApiPayloadError("Report registration response 'created_at' is not a calendar-valid UTC timestamp.")

        # 6. Success: Persist canonical_report_id and advance lifecycle state to METADATA_REGISTERED
        self.queue.update_status(
            current_job.id,
            JobStatus.METADATA_REGISTERED,
            docflow_report_id=canonical_report_id,
            details={
                "action": "metadata_registered",
                "report_id": canonical_report_id,
                "duplicate": duplicate_val,
            },
        )

        logger.info(
            "Report metadata successfully registered: job=%s, report_id=%s, duplicate=%s",
            current_job.id,
            canonical_report_id,
            duplicate_val,
        )

        return RegistrationResult(
            report_id=canonical_report_id,
            status=server_status,
            is_duplicate=duplicate_val,
            created_at=created_at,
        )
