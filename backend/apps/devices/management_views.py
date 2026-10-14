"""
Views for Docflow Device Management APIs (Phase 1, Task 3E).

Implements:
  - Device collection:
      GET  /api/v1/devices?branch_id=<uuid>
      POST /api/v1/devices
  - Device detail:
      GET   /api/v1/devices/{device_id}
      PATCH /api/v1/devices/{device_id}
  - One-time activation code issuance:
      POST  /api/v1/devices/{device_id}/activation-code
  - Administrator device revocation:
      POST  /api/v1/devices/{device_id}/revoke

Enforces:
  - Human user session authentication and CSRF protection.
  - Strict tenant scoping (safe 404s for out-of-scope records).
  - Explicit role checks (platform admin vs. organization admin).
  - Transactional mutations and safe audit logging.
  - Idempotent revocation attribution.
  - Bounded activation-code lifetimes.
"""

import datetime
import uuid
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction, AuditEvent
from apps.tenants.models import (
    Branch,
    BranchStatus,
    LabStatus,
    MembershipRole,
    MembershipStatus,
    OrganizationMembership,
    OrganizationStatus,
)
from apps.tenants.pagination import DocflowPagination
from apps.tenants.permissions import IsAuthenticatedHumanUser
from apps.users.authentication import CSRFEnforcedSessionAuthentication
from .ip_utils import get_client_ip
from .models import Device, DeviceStatus
from .serializers import (
    ActivationCodeIssueSerializer,
    DeviceCreateSerializer,
    DeviceRevokeSerializer,
    DeviceSerializer,
    DeviceUpdateSerializer,
)
from .services import issue_activation_code, revoke_device


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


def _is_active_org_admin(user, organization) -> bool:
    """Check if the user is a platform admin or has active organization_admin role."""
    if getattr(user, "is_platform_admin", False):
        return True
    return OrganizationMembership.objects.filter(
        organization=organization,
        user=user,
        status=MembershipStatus.ACTIVE,
        role=MembershipRole.ORGANIZATION_ADMIN,
    ).exists()


def _get_visible_devices_queryset(user):
    """
    Return queryset of devices visible to the given user.
    Platform admins see all; tenant users see only devices in active orgs with active memberships.
    """
    if getattr(user, "is_platform_admin", False):
        return (
            Device.objects.all()
            .select_related("organization", "branch")
            .order_by("created_at", "id")
        )
    return (
        Device.objects.filter(
            organization__status=OrganizationStatus.ACTIVE,
            organization__memberships__user=user,
            organization__memberships__status=MembershipStatus.ACTIVE,
        )
        .distinct()
        .select_related("organization", "branch")
        .order_by("created_at", "id")
    )


class DeviceListCreateView(APIView):
    """
    GET  /api/v1/devices?branch_id=...: List visible devices with pagination.
    POST /api/v1/devices: Register a new device with pending_activation status.
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]
    pagination_class = DocflowPagination

    def get(self, request, *args, **kwargs):
        queryset = _get_visible_devices_queryset(request.user)
        branch_filter = request.query_params.get("branch_id")
        if branch_filter:
            try:
                uuid.UUID(str(branch_filter))
            except (ValueError, TypeError):
                raise serializers.ValidationError({"branch_id": ["Invalid UUID format."]})
            queryset = queryset.filter(branch_id=branch_filter)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        if page is not None:
            serializer = DeviceSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = DeviceSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = DeviceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        branch_id = serializer.validated_data["branch_id"]
        name = serializer.validated_data["name"]

        # Resolve branch and check tenant authorization
        is_platform_admin = getattr(request.user, "is_platform_admin", False)
        if is_platform_admin:
            branch = get_object_or_404(
                Branch.objects.all().select_related("organization", "lab"),
                id=branch_id,
            )
        else:
            branch = get_object_or_404(
                Branch.objects.filter(
                    organization__status=OrganizationStatus.ACTIVE,
                    organization__memberships__user=request.user,
                    organization__memberships__status=MembershipStatus.ACTIVE,
                ).select_related("organization", "lab"),
                id=branch_id,
            )
            if not _is_active_org_admin(request.user, branch.organization):
                raise PermissionDenied("Organization admin privileges required to register a device.")

        # Require branch, organization, and lab to be active
        if branch.status != BranchStatus.ACTIVE:
            raise serializers.ValidationError({"branch_id": ["Branch is not active."]})
        if branch.organization.status != OrganizationStatus.ACTIVE:
            raise serializers.ValidationError({"branch_id": ["Organization is not active."]})
        if branch.lab.status != LabStatus.ACTIVE:
            raise serializers.ValidationError({"branch_id": ["Lab is not active."]})

        with transaction.atomic():
            device = Device.objects.create(
                organization=branch.organization,
                branch=branch,
                name=name,
                status=DeviceStatus.PENDING_ACTIVATION,
            )
            AuditEvent.objects.create(
                organization=device.organization,
                actor_user=request.user,
                action=AuditAction.CONFIG_CHANGED,
                target_type="device",
                target_id=str(device.id),
                request_id=_get_request_id(request),
                safe_metadata={
                    "target_resource": "device",
                    "device_name": device.name,
                    "device_id": str(device.id),
                    "branch_id": str(device.branch_id),
                    "status": DeviceStatus.PENDING_ACTIVATION,
                },
            )

        return Response(DeviceSerializer(device).data, status=status.HTTP_201_CREATED)


class DeviceDetailUpdateView(APIView):
    """
    GET   /api/v1/devices/{device_id}: Scoped read of a device.
    PATCH /api/v1/devices/{device_id}: Scoped update of human-editable device metadata (name).
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]

    def _get_scoped_device(self, request, device_id):
        return get_object_or_404(
            _get_visible_devices_queryset(request.user),
            id=device_id,
        )

    def get(self, request, device_id, *args, **kwargs):
        device = self._get_scoped_device(request, device_id)
        return Response(DeviceSerializer(device).data, status=status.HTTP_200_OK)

    def patch(self, request, device_id, *args, **kwargs):
        device = self._get_scoped_device(request, device_id)
        if not _is_active_org_admin(request.user, device.organization):
            raise PermissionDenied("Organization admin privileges required to update device.")

        serializer = DeviceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            device.name = serializer.validated_data["name"]
            device.save(update_fields=["name", "updated_at"])
            AuditEvent.objects.create(
                organization=device.organization,
                actor_user=request.user,
                action=AuditAction.CONFIG_CHANGED,
                target_type="device",
                target_id=str(device.id),
                request_id=_get_request_id(request),
                safe_metadata={
                    "target_resource": "device",
                    "device_name": device.name,
                    "device_id": str(device.id),
                    "status": device.status,
                },
            )

        return Response(DeviceSerializer(device).data, status=status.HTTP_200_OK)


class DeviceActivationCodeIssueView(APIView):
    """
    POST /api/v1/devices/{device_id}/activation-code

    Issues a one-time activation code for the specified device.
    Displays the raw code exactly once.
    Reuses existing issue_activation_code service and audit event.
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]

    def post(self, request, device_id, *args, **kwargs):
        device = get_object_or_404(
            _get_visible_devices_queryset(request.user),
            id=device_id,
        )
        if not _is_active_org_admin(request.user, device.organization):
            raise PermissionDenied("Organization admin privileges required to issue activation code.")

        serializer = ActivationCodeIssueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        expires_in_seconds = serializer.validated_data.get("expires_in_seconds", 600)
        lifetime = datetime.timedelta(seconds=expires_in_seconds)

        result = issue_activation_code(
            device=device,
            created_by=request.user,
            lifetime=lifetime,
            request_id=_get_request_id(request),
        )

        response_data = {
            "activation_code": result.raw_code,
            "expires_at": result.expires_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        return Response(response_data, status=status.HTTP_201_CREATED)


class DeviceRevokeView(APIView):
    """
    POST /api/v1/devices/{device_id}/revoke

    Revokes a device and all its active credentials.
    Idempotent: repeated calls for an already-revoked device return HTTP 200 without
    re-mutating timestamps or emitting duplicate audit events.
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]

    def post(self, request, device_id, *args, **kwargs):
        device = get_object_or_404(
            _get_visible_devices_queryset(request.user),
            id=device_id,
        )
        if not _is_active_org_admin(request.user, device.organization):
            raise PermissionDenied("Organization admin privileges required to revoke device.")

        serializer = DeviceRevokeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        reason_code = serializer.validated_data["reason_code"]
        client_ip = get_client_ip(request)

        revoked_device = revoke_device(
            device=device,
            request_id=_get_request_id(request),
            ip_address=client_ip,
            actor_user=request.user,
            reason_code=reason_code,
        )

        return Response(DeviceSerializer(revoked_device).data, status=status.HTTP_200_OK)
