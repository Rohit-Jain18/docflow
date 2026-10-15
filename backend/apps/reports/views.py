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
from typing import Any
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone as tz_utils
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction, AuditEvent
from apps.devices.authentication import DeviceBearerAuthentication
from apps.devices.models import DeviceStatus
from apps.tenants.models import BranchStatus, LabStatus, OrganizationStatus
from apps.tenants.pagination import DocflowPagination
from apps.whatsapp.models import (
    AssignmentStatus,
    BranchWhatsAppAssignment,
    WhatsAppAccountStatus,
)
from .models import (
    DeliveryAttempt,
    DispatchOutbox,
    MediaKind,
    MediaReference,
    OutboxState,
    Report,
    ReportStatus,
)
from .serializers import (
    AgentReportCreateSerializer,
    AgentReportListQuerySerializer,
    MediaReferenceAttachmentSerializer,
)

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

    def get(self, request, *args, **kwargs):
        """GET /api/v1/agent/reports - List reports for the authenticated agent."""
        return AgentReportListView().get(request, *args, **kwargs)

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

        res = Response(result["data"], status=int(result["status_code"]))
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
    ) -> dict[str, Any]:
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


class AgentMediaReferenceAttachmentView(APIView):
    """
    PUT /api/v1/agent/reports/{report_id}/media-reference

    Attaches a validated media reference to an existing queued report.
    Transitions report queued -> uploaded, creates the first DeliveryAttempt
    and DispatchOutbox entry in a single atomic transaction.
    """

    authentication_classes = [DeviceBearerAuthentication]
    permission_classes = [IsAuthenticated]

    def put(self, request, report_id, *args, **kwargs):
        device = request.user
        request_id = _get_request_id(request)

        # 1. Scope report to authenticated device's authorized branch/tenant
        try:
            report = Report.objects.filter(
                organization=device.organization,
                branch=device.branch,
                id=report_id,
            ).first()
        except (ValidationError, ValueError):
            report = None

        if not report:
            raise Http404("Report not found or outside device scope.")

        # 2. Validate request payload
        serializer = MediaReferenceAttachmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        media_data = serializer.validated_data["media_reference"]
        kind = media_data["kind"]

        # 3. Provider media reference check
        if kind in (MediaKind.PROVIDER_MEDIA_ID, MediaKind.PROVIDER_UPLOAD_REFERENCE):
            res = Response(
                {
                    "type": "about:blank",
                    "title": "Provider unavailable",
                    "status": status.HTTP_503_SERVICE_UNAVAILABLE,
                    "code": "provider_unavailable",
                    "detail": "Provider media reference contract is pending confirmation.",
                    "request_id": request_id,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
            res["X-Request-ID"] = request_id
            return res

        url = media_data.get("url", "").strip()
        expires_at = media_data.get("expires_at")

        # 4. Atomic Attachment and Outbox creation
        with transaction.atomic():
            locked_report = (
                Report.objects.select_for_update()
                .filter(id=report.id)
                .first()
            )
            assert locked_report is not None

            # Recheck tenant hierarchy
            if (
                device.organization.status != OrganizationStatus.ACTIVE
                or device.branch.status != BranchStatus.ACTIVE
                or not device.branch.lab
                or device.branch.lab.status != LabStatus.ACTIVE
                or device.status != DeviceStatus.ACTIVE
            ):
                raise PermissionDenied("Device organization, branch, or lab is inactive.")

            # Recheck branch assignment
            if not locked_report.branch_assignment_id:
                res = Response(
                    {
                        "type": "about:blank",
                        "title": "Account not verified",
                        "status": status.HTTP_422_UNPROCESSABLE_ENTITY,
                        "code": "account_not_verified",
                        "detail": "No WhatsApp sender assignment found on report.",
                        "request_id": request_id,
                    },
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
                res["X-Request-ID"] = request_id
                return res

            assignment = (
                BranchWhatsAppAssignment.objects.select_for_update()
                .filter(id=locked_report.branch_assignment_id)
                .select_related("whatsapp_account")
                .first()
            )

            if not assignment or assignment.status != AssignmentStatus.ACTIVE:
                res = Response(
                    {
                        "type": "about:blank",
                        "title": "Account not verified",
                        "status": status.HTTP_422_UNPROCESSABLE_ENTITY,
                        "code": "account_not_verified",
                        "detail": "Original branch WhatsApp assignment is inactive.",
                        "request_id": request_id,
                    },
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
                res["X-Request-ID"] = request_id
                return res

            # Recheck that the branch currently still has this active assignment
            current_active = (
                BranchWhatsAppAssignment.objects.select_for_update()
                .filter(branch=device.branch, status=AssignmentStatus.ACTIVE)
                .first()
            )
            if not current_active or current_active.id != locked_report.branch_assignment_id:
                res = Response(
                    {
                        "type": "about:blank",
                        "title": "Account not verified",
                        "status": status.HTTP_422_UNPROCESSABLE_ENTITY,
                        "code": "account_not_verified",
                        "detail": "Branch WhatsApp assignment has changed since report registration.",
                        "request_id": request_id,
                    },
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
                res["X-Request-ID"] = request_id
                return res

            # Check WhatsApp account status
            account = assignment.whatsapp_account
            if not account or account.status != WhatsAppAccountStatus.VERIFIED:
                res = Response(
                    {
                        "type": "about:blank",
                        "title": "Account not verified",
                        "status": status.HTTP_422_UNPROCESSABLE_ENTITY,
                        "code": "account_not_verified",
                        "detail": "Assigned WhatsApp account is not verified.",
                        "request_id": request_id,
                    },
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
                res["X-Request-ID"] = request_id
                return res

            # Production mode fail-closed
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

            # Check existing MediaReference on the report
            existing_media = locked_report.media_references.filter(deleted_at__isnull=True).first()
            if existing_media:
                if existing_media.kind == kind and existing_media.download_url == url:
                    res = Response(
                        {
                            "report_id": str(locked_report.id),
                            "status": locked_report.status,
                            "duplicate": True,
                        },
                        status=status.HTTP_200_OK,
                    )
                    res["X-Request-ID"] = request_id
                    return res
                else:
                    res = Response(
                        {
                            "type": "about:blank",
                            "title": "State conflict",
                            "status": status.HTTP_409_CONFLICT,
                            "code": "state_conflict",
                            "detail": "A different media reference cannot replace the existing reference.",
                            "request_id": request_id,
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
                    res["X-Request-ID"] = request_id
                    return res

            # Ensure report is in QUEUED state
            if locked_report.status != ReportStatus.QUEUED:
                res = Response(
                    {
                        "type": "about:blank",
                        "title": "State conflict",
                        "status": status.HTTP_409_CONFLICT,
                        "code": "state_conflict",
                        "detail": f"Report in status '{locked_report.status}' is ineligible for media attachment.",
                        "request_id": request_id,
                    },
                    status=status.HTTP_409_CONFLICT,
                )
                res["X-Request-ID"] = request_id
                return res

            # Create MediaReference
            MediaReference.objects.create(
                report=locked_report,
                kind=kind,
                download_url=url,
                expires_at=expires_at,
                encrypted_reference="",
            )

            # Transition status queued -> uploaded
            locked_report.status = ReportStatus.UPLOADED
            locked_report.save(update_fields=["status", "updated_at"])

            # Create first DeliveryAttempt if not exists
            attempt, _ = DeliveryAttempt.objects.get_or_create(
                report=locked_report,
                attempt_number=1,
                defaults={
                    "organization": locked_report.organization,
                    "status": ReportStatus.QUEUED,
                    "provider_key": account.provider_key or "kiziee",
                },
            )

            # Create DispatchOutbox item if not exists
            DispatchOutbox.objects.get_or_create(
                report=locked_report,
                delivery_attempt=attempt,
                defaults={
                    "organization": locked_report.organization,
                    "event_type": "send_message",
                    "state": OutboxState.PENDING,
                    "available_at": tz_utils.now(),
                },
            )

            res = Response(
                {
                    "report_id": str(locked_report.id),
                    "status": "uploaded",
                    "duplicate": False,
                },
                status=status.HTTP_200_OK,
            )
            res["X-Request-ID"] = request_id
            return res


class AgentReportDetailView(APIView):
    """
    GET /api/v1/agent/reports/{report_id}

    Returns safe report status and delivery attempt summary.
    Scoped strictly to the authenticated device's authorized branch/tenant.
    """

    authentication_classes = [DeviceBearerAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, report_id, *args, **kwargs):
        device = request.user
        request_id = _get_request_id(request)

        try:
            report = Report.objects.filter(
                organization=device.organization,
                branch=device.branch,
                id=report_id,
            ).first()
        except (ValidationError, ValueError):
            report = None

        if not report:
            raise Http404("Report not found or outside device scope.")

        latest_attempt = report.delivery_attempts.order_by("-attempt_number").first()

        last_safe_error = None
        if latest_attempt and latest_attempt.error_code:
            last_safe_error = latest_attempt.error_code
        elif report.quarantined_reason_code:
            last_safe_error = report.quarantined_reason_code

        data: dict[str, Any] = {
            "report_id": str(report.id),
            "status": report.status,
            "created_at": report.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_at": report.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_safe_error_code": last_safe_error,
        }

        if latest_attempt:
            data["delivery_attempt"] = {
                "attempt_number": latest_attempt.attempt_number,
                "status": latest_attempt.status,
                "provider_message_id": latest_attempt.provider_message_id or None,
                "updated_at": latest_attempt.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "last_safe_error_code": latest_attempt.error_code or None,
            }

        res = Response(data, status=status.HTTP_200_OK)
        res["X-Request-ID"] = request_id
        return res


class AgentReportListView(APIView):
    """
    GET /api/v1/agent/reports?status=...&since=...&page=...&page_size=...

    Returns paginated safe report status summaries scoped to device's branch/tenant.
    """

    authentication_classes = [DeviceBearerAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = DocflowPagination

    def get(self, request, *args, **kwargs):
        device = request.user
        request_id = _get_request_id(request)

        # Validate query parameters
        query_serializer = AgentReportListQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)

        queryset = (
            Report.objects.filter(
                organization=device.organization,
                branch=device.branch,
            )
            .prefetch_related("delivery_attempts")
            .order_by("-created_at", "-id")
        )

        filter_status = query_serializer.validated_data.get("status")
        if filter_status:
            queryset = queryset.filter(status=filter_status)

        since = query_serializer.validated_data.get("since")
        if since:
            queryset = queryset.filter(created_at__gte=since)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        page_items = page if page is not None else list(queryset)

        results = []
        for r in page_items:
            attempts = list(r.delivery_attempts.all())
            latest_attempt = max(attempts, key=lambda a: a.attempt_number) if attempts else None
            last_safe_error = None
            if latest_attempt and latest_attempt.error_code:
                last_safe_error = latest_attempt.error_code
            elif r.quarantined_reason_code:
                last_safe_error = r.quarantined_reason_code

            results.append({
                "report_id": str(r.id),
                "status": r.status,
                "created_at": r.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "updated_at": r.updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "last_safe_error_code": last_safe_error,
            })

        paginated_response = paginator.get_paginated_response(results)
        paginated_response["X-Request-ID"] = request_id
        return paginated_response


