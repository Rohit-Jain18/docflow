"""
Views for Docflow WhatsApp Account and Assignment APIs (Phase 1, Task 3F).

Implements:
  - GET  /api/v1/whatsapp-accounts
  - POST /api/v1/whatsapp-accounts
  - GET  /api/v1/whatsapp-accounts/{account_id}
  - POST /api/v1/whatsapp-accounts/{account_id}/verify
  - POST /api/v1/branches/{branch_id}/whatsapp-assignment
  - DELETE /api/v1/branches/{branch_id}/whatsapp-assignment

Enforces:
  - Active human user session authentication and CSRF protection.
  - Strict tenant scoping (safe 404s for out-of-scope records).
  - Explicit role checks (platform admin vs. organization admin).
  - Gated production vs. development-only verification override with audit logging.
  - Transactional branch sender assignment switching and history preservation.
"""

import uuid
from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone as tz_utils
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction, AuditEvent
from apps.tenants.models import (
    Branch,
    BranchStatus,
    MembershipRole,
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationStatus,
)
from apps.tenants.pagination import DocflowPagination
from apps.tenants.permissions import IsAuthenticatedHumanUser
from apps.users.authentication import CSRFEnforcedSessionAuthentication
from .models import (
    AssignmentStatus,
    BranchWhatsAppAssignment,
    CredentialMode,
    WhatsAppAccount,
    WhatsAppAccountStatus,
)
from .serializers import (
    BranchWhatsAppAssignmentCreateSerializer,
    BranchWhatsAppAssignmentSummarySerializer,
    WhatsAppAccountCreateSerializer,
    WhatsAppAccountSerializer,
    WhatsAppAccountVerifySerializer,
)


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
    """Check if user is a platform admin or has active organization_admin role."""
    if getattr(user, "is_platform_admin", False):
        return True
    return OrganizationMembership.objects.filter(
        organization=organization,
        user=user,
        status=MembershipStatus.ACTIVE,
        role=MembershipRole.ORGANIZATION_ADMIN,
    ).exists()


def _get_visible_accounts_queryset(user):
    """
    Return queryset of WhatsApp accounts visible to the caller.
    Platform admins see all; tenant users see only accounts in active orgs
    where they hold an active organization_admin role.
    """
    if getattr(user, "is_platform_admin", False):
        return (
            WhatsAppAccount.objects.all()
            .select_related("organization")
            .order_by("created_at", "id")
        )
    return (
        WhatsAppAccount.objects.filter(
            organization__status=OrganizationStatus.ACTIVE,
            organization__memberships__user=user,
            organization__memberships__status=MembershipStatus.ACTIVE,
            organization__memberships__role=MembershipRole.ORGANIZATION_ADMIN,
        )
        .distinct()
        .select_related("organization")
        .order_by("created_at", "id")
    )


class WhatsAppAccountListCreateView(APIView):
    """
    GET  /api/v1/whatsapp-accounts: List visible WhatsApp accounts.
    POST /api/v1/whatsapp-accounts: Create a new WhatsApp account in pending_verification state.
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]
    pagination_class = DocflowPagination

    def get(self, request, *args, **kwargs):
        queryset = _get_visible_accounts_queryset(request.user)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        if page is not None:
            serializer = WhatsAppAccountSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = WhatsAppAccountSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = WhatsAppAccountCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        org_id = serializer.validated_data.get("organization_id")
        is_platform_admin = getattr(request.user, "is_platform_admin", False)

        if is_platform_admin:
            if not org_id:
                raise serializers.ValidationError(
                    {"organization_id": ["organization_id is required for platform administrators."]}
                )
            target_org = get_object_or_404(Organization.objects.all(), id=org_id)
        else:
            if org_id:
                target_org = get_object_or_404(
                    Organization.objects.filter(
                        status=OrganizationStatus.ACTIVE,
                        memberships__user=request.user,
                        memberships__status=MembershipStatus.ACTIVE,
                    ),
                    id=org_id,
                )
                if not _is_active_org_admin(request.user, target_org):
                    raise PermissionDenied("Organization admin privileges required to register WhatsApp account.")
            else:
                admin_memberships = OrganizationMembership.objects.filter(
                    user=request.user,
                    status=MembershipStatus.ACTIVE,
                    role=MembershipRole.ORGANIZATION_ADMIN,
                    organization__status=OrganizationStatus.ACTIVE,
                ).select_related("organization")

                if not admin_memberships.exists():
                    raise PermissionDenied("Organization admin privileges required to register WhatsApp account.")
                if admin_memberships.count() > 1:
                    raise serializers.ValidationError(
                        {"organization_id": ["organization_id is required when user manages multiple organizations."]}
                    )
                first_membership = admin_memberships.first()
                assert first_membership is not None
                target_org = first_membership.organization

        account_data = {
            k: v for k, v in serializer.validated_data.items() if k != "organization_id"
        }

        with transaction.atomic():
            account = WhatsAppAccount.objects.create(
                organization=target_org,
                status=WhatsAppAccountStatus.PENDING_VERIFICATION,
                credential_mode=CredentialMode.PLATFORM_MANAGED,
                credential_secret_ref="",
                created_by=request.user,
                **account_data,
            )
            AuditEvent.objects.create(
                organization=target_org,
                actor_user=request.user,
                action=AuditAction.CONFIG_CHANGED,
                target_type="whatsapp_account",
                target_id=str(account.id),
                request_id=_get_request_id(request),
                safe_metadata={
                    "target_resource": "whatsapp_account",
                    "status": account.status,
                },
            )

        return Response(WhatsAppAccountSerializer(account).data, status=status.HTTP_201_CREATED)


class WhatsAppAccountDetailView(APIView):
    """
    GET /api/v1/whatsapp-accounts/{account_id}: Scoped read of a WhatsApp account.
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]

    def get(self, request, account_id, *args, **kwargs):
        account = get_object_or_404(_get_visible_accounts_queryset(request.user), id=account_id)
        return Response(WhatsAppAccountSerializer(account).data, status=status.HTTP_200_OK)


class WhatsAppAccountVerifyView(APIView):
    """
    POST /api/v1/whatsapp-accounts/{account_id}/verify

    In production: returns 503 provider_unavailable.
    In development: permits verification only when DEV_ACCOUNT_VERIFICATION_OVERRIDE=true
    and the account and organization match DEV_TEST_ACCOUNT_ID and DEV_TEST_ORGANIZATION_ID.
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]

    def post(self, request, account_id, *args, **kwargs):
        account = get_object_or_404(_get_visible_accounts_queryset(request.user), id=account_id)
        if not _is_active_org_admin(request.user, account.organization):
            raise PermissionDenied("Organization admin privileges required to verify WhatsApp account.")

        serializer = WhatsAppAccountVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        is_production = getattr(settings, "DOCFLOW_ENV", "") == "production"
        dev_override_enabled = getattr(settings, "DEV_ACCOUNT_VERIFICATION_OVERRIDE", False) is True

        if is_production or not dev_override_enabled:
            return Response(
                {
                    "type": "about:blank",
                    "title": "Provider unavailable",
                    "status": status.HTTP_503_SERVICE_UNAVAILABLE,
                    "code": "provider_unavailable",
                    "detail": "Account verification is unavailable because provider verification contract is pending confirmation.",
                    "request_id": _get_request_id(request),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Development override is enabled; verify against allowlisted test account
        configured_org_id = str(getattr(settings, "DEV_TEST_ORGANIZATION_ID", "")).strip()
        configured_account_id = str(getattr(settings, "DEV_TEST_ACCOUNT_ID", "")).strip()

        if (
            configured_org_id
            and configured_account_id
            and str(account.organization_id) == configured_org_id
            and str(account.id) == configured_account_id
        ):
            with transaction.atomic():
                account.status = WhatsAppAccountStatus.VERIFIED
                account.verified_at = tz_utils.now()
                account.save(update_fields=["status", "verified_at", "updated_at"])

                AuditEvent.objects.create(
                    organization=account.organization,
                    actor_user=request.user,
                    action=AuditAction.WHATSAPP_ACCOUNT_DEV_VERIFICATION_OVERRIDE,
                    target_type="whatsapp_account",
                    target_id=str(account.id),
                    request_id=_get_request_id(request),
                    safe_metadata={
                        "target_resource": "whatsapp_account",
                        "status": WhatsAppAccountStatus.VERIFIED,
                        "verification_status": "dev_override_verified",
                        "override_reason": "Development-only test verification override",
                    },
                )

            return Response(WhatsAppAccountSerializer(account).data, status=status.HTTP_200_OK)

        # Development override active, but account/org does not match the allowlist
        return Response(
            {
                "type": "about:blank",
                "title": "Provider unavailable",
                "status": status.HTTP_503_SERVICE_UNAVAILABLE,
                "code": "provider_unavailable",
                "detail": "Account verification is unavailable. Development override is restricted to allowlisted test account.",
                "request_id": _get_request_id(request),
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class BranchWhatsAppAssignmentView(APIView):
    """
    POST   /api/v1/branches/{branch_id}/whatsapp-assignment: Assign verified WhatsApp account to branch.
    DELETE /api/v1/branches/{branch_id}/whatsapp-assignment: Deactivate active WhatsApp account assignment.
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]

    def _get_scoped_branch(self, request, branch_id):
        is_platform_admin = getattr(request.user, "is_platform_admin", False)
        if is_platform_admin:
            return get_object_or_404(
                Branch.objects.all().select_related("organization"),
                id=branch_id,
            )
        branch = get_object_or_404(
            Branch.objects.filter(
                organization__status=OrganizationStatus.ACTIVE,
                organization__memberships__user=request.user,
                organization__memberships__status=MembershipStatus.ACTIVE,
            ).select_related("organization"),
            id=branch_id,
        )
        if not _is_active_org_admin(request.user, branch.organization):
            raise PermissionDenied("Organization admin privileges required for branch WhatsApp assignment.")
        return branch

    def post(self, request, branch_id, *args, **kwargs):
        branch = self._get_scoped_branch(request, branch_id)

        serializer = BranchWhatsAppAssignmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        account_id = serializer.validated_data["whatsapp_account_id"]
        account = get_object_or_404(
            _get_visible_accounts_queryset(request.user),
            id=account_id,
        )

        if account.organization_id != branch.organization_id:
            raise serializers.ValidationError(
                {"whatsapp_account_id": ["WhatsApp account and branch must belong to the same organization."]}
            )

        if account.status != WhatsAppAccountStatus.VERIFIED:
            raise serializers.ValidationError(
                {
                    "whatsapp_account_id": [
                        f"WhatsApp account must be verified before assignment (current status: {account.status})."
                    ]
                }
            )

        with transaction.atomic():
            now = tz_utils.now()
            # Deactivate all active assignments for this branch first to satisfy unique constraint
            active_assignments = BranchWhatsAppAssignment.objects.select_for_update().filter(
                branch=branch,
                status=AssignmentStatus.ACTIVE,
            )
            for existing in active_assignments:
                existing.status = AssignmentStatus.INACTIVE
                existing.ended_at = now
                existing.save(update_fields=["status", "ended_at"])

            # Create new active assignment
            new_assignment = BranchWhatsAppAssignment.objects.create(
                organization=branch.organization,
                branch=branch,
                whatsapp_account=account,
                status=AssignmentStatus.ACTIVE,
                assigned_by=request.user,
                assigned_at=now,
            )

            AuditEvent.objects.create(
                organization=branch.organization,
                actor_user=request.user,
                action=AuditAction.WHATSAPP_ACCOUNT_ASSIGNED,
                target_type="branch_whatsapp_assignment",
                target_id=str(new_assignment.id),
                request_id=_get_request_id(request),
                safe_metadata={
                    "target_resource": "branch_whatsapp_assignment",
                    "branch_id": str(branch.id),
                    "branch_code": str(branch.code),
                    "status": AssignmentStatus.ACTIVE,
                },
            )

        return Response(
            BranchWhatsAppAssignmentSummarySerializer(new_assignment).data,
            status=status.HTTP_200_OK,
        )

    def delete(self, request, branch_id, *args, **kwargs):
        branch = self._get_scoped_branch(request, branch_id)

        with transaction.atomic():
            active_assignments = BranchWhatsAppAssignment.objects.select_for_update().filter(
                branch=branch,
                status=AssignmentStatus.ACTIVE,
            )
            if active_assignments.exists():
                now = tz_utils.now()
                for assignment in active_assignments:
                    assignment.status = AssignmentStatus.INACTIVE
                    assignment.ended_at = now
                    assignment.save(update_fields=["status", "ended_at"])

                    AuditEvent.objects.create(
                        organization=branch.organization,
                        actor_user=request.user,
                        action=AuditAction.WHATSAPP_ACCOUNT_UNASSIGNED,
                        target_type="branch_whatsapp_assignment",
                        target_id=str(assignment.id),
                        request_id=_get_request_id(request),
                        safe_metadata={
                            "target_resource": "branch_whatsapp_assignment",
                            "branch_id": str(branch.id),
                            "branch_code": str(branch.code),
                            "status": AssignmentStatus.INACTIVE,
                        },
                    )

        return Response(status=status.HTTP_204_NO_CONTENT)
