"""
Views for Docflow Report APIs (Phase 1, Task 3G).

Implements:
  - POST /api/v1/agent/reports: Authenticated agent diagnostic report registration.

Enforces:
  - Device Bearer token authentication (DeviceBearerAuthentication).
  - Exact 64 lowercase hex Idempotency-Key header requirement.
  - Server-computed canonical fingerprint validation.
  - Active sender assignment to an eligible verified WhatsApp account (422 account_not_verified).
  - Production fail-closed enforcement against development-override accounts.
  - Transactional idempotency semantics with race condition recovery (409 idempotency_conflict).
  - Data minimization (zero PDF bytes, zero raw phone numbers or credentials in responses).
"""

import re
import uuid
from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction, AuditEvent
from apps.devices.authentication import DeviceBearerAuthentication
from apps.tenants.models import BranchStatus, LabStatus, OrganizationStatus
from apps.whatsapp.models import (
    AssignmentStatus,
    BranchWhatsAppAssignment,
    WhatsAppAccountStatus,
)
from .models import Report, ReportStatus
from .serializers import AgentReportCreateSerializer

HEX_64_REGEX = re.compile(r"^[0-9a-f]{64}$")


def _get_request_id(request) -> str:
    """Extract or generate request tracking identifier."""
    if request:
        req_id = getattr(request, "request_id", None) or getattr(request, "_request_id", None)
        if req_id:
            return str(req_id)
        header_val = request.headers.get("X-Request-ID") or request.META.get("HTTP_X_REQUEST_ID")
        if header_val:
            return str(header_val).strip()
    return f"req_{uuid.uuid4().hex[:16]}"


class AgentReportRegistrationView(APIView):
    """
    POST /api/v1/agent/reports

    Registers an outbound diagnostic report job from an active device.
    Verifies Idempotency-Key against the canonical fingerprint and checks sender eligibility.
    """

    authentication_classes = [DeviceBearerAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        device = request.user
        request_id = _get_request_id(request)

        # 1. Validate Idempotency-Key header
        idempotency_key = (
            request.headers.get("Idempotency-Key")
            or request.META.get("HTTP_IDEMPOTENCY_KEY")
            or ""
        ).strip()

        if not idempotency_key or not HEX_64_REGEX.match(idempotency_key):
            res = Response(
                {
                    "type": "about:blank",
                    "title": "Validation failed",
                    "status": status.HTTP_400_BAD_REQUEST,
                    "code": "validation_error",
                    "detail": "One or more fields are invalid.",
                    "field_errors": {
                        "idempotency_key": [
                            "A valid 64-character lowercase hex Idempotency-Key header is required."
                        ]
                    },
                    "request_id": request_id,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
            res["X-Request-ID"] = request_id
            return res

        # 2. Validate request payload
        serializer = AgentReportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 3. Hierarchy and status checks
        if (
            device.organization.status != OrganizationStatus.ACTIVE
            or device.branch.status != BranchStatus.ACTIVE
            or not device.branch.lab
            or device.branch.lab.status != LabStatus.ACTIVE
        ):
            raise PermissionDenied("Device organization, branch, or lab is inactive.")

        # 4. Canonical fingerprint validation
        expected_fp = Report.compute_canonical_fingerprint(
            str(device.branch_id),
            data["recipient_phone_e164"],
            data["content_sha256"],
        )

        if idempotency_key != expected_fp:
            res = Response(
                {
                    "type": "about:blank",
                    "title": "State conflict",
                    "status": status.HTTP_409_CONFLICT,
                    "code": "idempotency_conflict",
                    "detail": "Supplied Idempotency-Key does not match the canonical fingerprint.",
                    "request_id": request_id,
                },
                status=status.HTTP_409_CONFLICT,
            )
            res["X-Request-ID"] = request_id
            return res

        # 5. Sender assignment and eligibility checks
        assignment = (
            BranchWhatsAppAssignment.objects.filter(
                branch=device.branch,
                status=AssignmentStatus.ACTIVE,
            )
            .select_related("whatsapp_account")
            .first()
        )

        if not assignment or not assignment.whatsapp_account:
            res = Response(
                {
                    "type": "about:blank",
                    "title": "Account not verified",
                    "status": status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "code": "account_not_verified",
                    "detail": "No active WhatsApp sender assignment found for branch.",
                    "request_id": request_id,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
            res["X-Request-ID"] = request_id
            return res

        account = assignment.whatsapp_account

        if account.organization_id != device.organization_id:
            res = Response(
                {
                    "type": "about:blank",
                    "title": "Account not verified",
                    "status": status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "code": "account_not_verified",
                    "detail": "Assigned WhatsApp account organization mismatch.",
                    "request_id": request_id,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
            res["X-Request-ID"] = request_id
            return res

        if account.status != WhatsAppAccountStatus.VERIFIED:
            res = Response(
                {
                    "type": "about:blank",
                    "title": "Account not verified",
                    "status": status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "code": "account_not_verified",
                    "detail": f"Assigned WhatsApp account is not verified (status: {account.status}).",
                    "request_id": request_id,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
            res["X-Request-ID"] = request_id
            return res

        # Fail closed in production if account verification was via dev override
        is_production = getattr(settings, "DOCFLOW_ENV", "") == "production"
        if is_production:
            is_dev_override = AuditEvent.objects.filter(
                target_type="whatsapp_account",
                target_id=str(account.id),
                action=AuditAction.WHATSAPP_ACCOUNT_DEV_VERIFICATION_OVERRIDE,
            ).exists()
            if is_dev_override:
                res = Response(
                    {
                        "type": "about:blank",
                        "title": "Account not verified",
                        "status": status.HTTP_422_UNPROCESSABLE_ENTITY,
                        "code": "account_not_verified",
                        "detail": "WhatsApp account verified via development override is disallowed in production.",
                        "request_id": request_id,
                    },
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
                res["X-Request-ID"] = request_id
                return res

        # 6. Atomic Idempotency & Report Creation
        result = self._execute_registration(
            device=device,
            assignment=assignment,
            data=data,
            idempotency_key=idempotency_key,
            fingerprint=expected_fp,
            request_id=request_id,
        )

        res = Response(result["data"], status=result["status_code"])
        res["X-Request-ID"] = request_id
        return res

    def _execute_registration(
        self,
        device,
        assignment,
        data,
        idempotency_key,
        fingerprint,
        request_id,
    ):
        """Execute transactional idempotency check, conflict detection, and record creation."""
        try:
            with transaction.atomic():
                existing_by_key = (
                    Report.objects.select_for_update()
                    .filter(
                        organization=device.organization,
                        idempotency_key=idempotency_key,
                    )
                    .first()
                )
                existing_by_fp = (
                    Report.objects.select_for_update()
                    .filter(
                        organization=device.organization,
                        fingerprint=fingerprint,
                    )
                    .first()
                )

                if existing_by_key:
                    # Same key: check if request parameters match
                    is_match = (
                        existing_by_key.fingerprint == fingerprint
                        and existing_by_key.recipient_phone_e164 == data["recipient_phone_e164"]
                        and existing_by_key.content_sha256 == data["content_sha256"]
                        and existing_by_key.document_type == data["document_type"]
                        and existing_by_key.file_size_bytes == data["file_size_bytes"]
                        and str(existing_by_key.branch_id) == str(device.branch_id)
                    )
                    if is_match:
                        return {
                            "status_code": status.HTTP_202_ACCEPTED,
                            "data": {
                                "report_id": str(existing_by_key.id),
                                "status": existing_by_key.status,
                                "duplicate": True,
                                "created_at": existing_by_key.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            },
                        }
                    else:
                        return {
                            "status_code": status.HTTP_409_CONFLICT,
                            "data": {
                                "type": "about:blank",
                                "title": "State conflict",
                                "status": status.HTTP_409_CONFLICT,
                                "code": "idempotency_conflict",
                                "detail": "Idempotency key already exists with different request parameters.",
                                "request_id": request_id,
                            },
                        }

                if existing_by_fp:
                    # Same fingerprint, different key
                    return {
                        "status_code": status.HTTP_409_CONFLICT,
                        "data": {
                            "type": "about:blank",
                            "title": "State conflict",
                            "status": status.HTTP_409_CONFLICT,
                            "code": "idempotency_conflict",
                            "detail": "Report with same canonical fingerprint was registered with a different key.",
                            "request_id": request_id,
                        },
                    }

                report = Report.objects.create(
                    organization=device.organization,
                    lab=device.branch.lab,
                    branch=device.branch,
                    device=device,
                    branch_assignment=assignment,
                    recipient_phone_e164=data["recipient_phone_e164"],
                    source_file_label=data.get("client_tracking_label", ""),
                    document_type=data["document_type"],
                    content_sha256=data["content_sha256"],
                    file_size_bytes=data["file_size_bytes"],
                    idempotency_key=idempotency_key,
                    fingerprint=fingerprint,
                    status=ReportStatus.QUEUED,
                )

                return {
                    "status_code": status.HTTP_202_ACCEPTED,
                    "data": {
                        "report_id": str(report.id),
                        "status": report.status,
                        "duplicate": False,
                        "created_at": report.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    },
                }

        except IntegrityError:
            # Handle uniqueness race condition by re-reading the conflicting record
            conflicting = Report.objects.filter(
                organization=device.organization,
                idempotency_key=idempotency_key,
            ).first()

            if conflicting:
                is_match = (
                    conflicting.fingerprint == fingerprint
                    and conflicting.recipient_phone_e164 == data["recipient_phone_e164"]
                    and conflicting.content_sha256 == data["content_sha256"]
                    and conflicting.document_type == data["document_type"]
                    and conflicting.file_size_bytes == data["file_size_bytes"]
                    and str(conflicting.branch_id) == str(device.branch_id)
                )
                if is_match:
                    return {
                        "status_code": status.HTTP_202_ACCEPTED,
                        "data": {
                            "report_id": str(conflicting.id),
                            "status": conflicting.status,
                            "duplicate": True,
                            "created_at": conflicting.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        },
                    }

            return {
                "status_code": status.HTTP_409_CONFLICT,
                "data": {
                    "type": "about:blank",
                    "title": "State conflict",
                    "status": status.HTTP_409_CONFLICT,
                    "code": "idempotency_conflict",
                    "detail": "Idempotency conflict detected during concurrent submission.",
                    "request_id": request_id,
                },
            }
