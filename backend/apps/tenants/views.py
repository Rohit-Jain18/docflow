"""
Views for Docflow Tenant APIs (Phase 1, Task 3D).

Implements:
  - Organizations: GET / POST / GET {id} / PATCH {id}
  - Labs: GET / POST / GET {id} / PATCH {id}
  - Branches: GET / POST / GET {id} / PATCH {id}

Enforces:
  - Active human user session authentication and CSRF protection.
  - Strict tenant isolation and pre-query scoping (safe 404s).
  - Explicit role checks (platform admin vs. organization admin).
  - Transactional persistence of resource changes and audit events.
  - Standard pagination (results, page, page_size, total) and stable ordering.
"""

import uuid
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditAction, AuditEvent
from apps.users.authentication import CSRFEnforcedSessionAuthentication
from .models import (
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
from .pagination import DocflowPagination
from .permissions import IsAuthenticatedHumanUser
from .serializers import (
    BranchCreateSerializer,
    BranchSerializer,
    BranchUpdateSerializer,
    LabCreateSerializer,
    LabSerializer,
    LabUpdateSerializer,
    OrganizationCreateSerializer,
    OrganizationSerializer,
    OrganizationUpdateSerializer,
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
    """Check if the user is a platform admin or has active organization_admin role."""
    if getattr(user, "is_platform_admin", False):
        return True
    return OrganizationMembership.objects.filter(
        organization=organization,
        user=user,
        status=MembershipStatus.ACTIVE,
        role=MembershipRole.ORGANIZATION_ADMIN,
    ).exists()


def _get_visible_organizations_queryset(user):
    """
    Return queryset of organizations visible to the given user.
    Platform admins see all; tenant users see only active orgs with active memberships.
    """
    if getattr(user, "is_platform_admin", False):
        return Organization.objects.all().order_by("created_at", "id")
    return (
        Organization.objects.filter(
            status=OrganizationStatus.ACTIVE,
            memberships__user=user,
            memberships__status=MembershipStatus.ACTIVE,
        )
        .distinct()
        .order_by("created_at", "id")
    )


def _get_visible_labs_queryset(user):
    """
    Return queryset of labs visible to the given user.
    Platform admins see all; tenant users see only labs in active orgs with active memberships.
    """
    if getattr(user, "is_platform_admin", False):
        return Lab.objects.all().select_related("organization").order_by("created_at", "id")
    return (
        Lab.objects.filter(
            organization__status=OrganizationStatus.ACTIVE,
            organization__memberships__user=user,
            organization__memberships__status=MembershipStatus.ACTIVE,
        )
        .distinct()
        .select_related("organization")
        .order_by("created_at", "id")
    )


def _get_visible_branches_queryset(user):
    """
    Return queryset of branches visible to the given user.
    Platform admins see all; tenant users see only branches in active orgs with active memberships.
    """
    if getattr(user, "is_platform_admin", False):
        return (
            Branch.objects.all()
            .select_related("organization", "lab")
            .order_by("created_at", "id")
        )
    return (
        Branch.objects.filter(
            organization__status=OrganizationStatus.ACTIVE,
            organization__memberships__user=user,
            organization__memberships__status=MembershipStatus.ACTIVE,
        )
        .distinct()
        .select_related("organization", "lab")
        .order_by("created_at", "id")
    )


# ===========================================================================
# Organization Views
# ===========================================================================


class OrganizationListCreateView(APIView):
    """
    GET  /api/v1/organizations: List organizations visible to the authenticated user.
    POST /api/v1/organizations: Create a new organization (Platform admin only).
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]
    pagination_class = DocflowPagination

    def get(self, request, *args, **kwargs):
        queryset = _get_visible_organizations_queryset(request.user)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        if page is not None:
            serializer = OrganizationSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = OrganizationSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        if not getattr(request.user, "is_platform_admin", False):
            raise PermissionDenied("Platform administrator access required to create an organization.")

        serializer = OrganizationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            org = serializer.save(created_by=request.user)
            AuditEvent.objects.create(
                organization=org,
                actor_user=request.user,
                action=AuditAction.ORGANIZATION_CREATED,
                target_type="organization",
                target_id=str(org.id),
                request_id=_get_request_id(request),
                safe_metadata={
                    "action_by": str(request.user.id),
                    "status": str(org.status),
                },
            )

        return Response(OrganizationSerializer(org).data, status=status.HTTP_201_CREATED)


class OrganizationDetailUpdateView(APIView):
    """
    GET   /api/v1/organizations/{organization_id}: Scoped read of an organization.
    PATCH /api/v1/organizations/{organization_id}: Scoped update of an organization.
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]

    def _get_scoped_org(self, request, organization_id):
        return get_object_or_404(
            _get_visible_organizations_queryset(request.user),
            id=organization_id,
        )

    def get(self, request, organization_id, *args, **kwargs):
        org = self._get_scoped_org(request, organization_id)
        return Response(OrganizationSerializer(org).data, status=status.HTTP_200_OK)

    def patch(self, request, organization_id, *args, **kwargs):
        org = self._get_scoped_org(request, organization_id)
        if not _is_active_org_admin(request.user, org):
            raise PermissionDenied("Organization admin privileges required to update organization.")

        serializer = OrganizationUpdateSerializer(
            org,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            old_status = org.status
            updated_org = serializer.save()
            new_status = updated_org.status

            if old_status != new_status:
                AuditEvent.objects.create(
                    organization=updated_org,
                    actor_user=request.user,
                    action=AuditAction.ORGANIZATION_STATUS_CHANGED,
                    target_type="organization",
                    target_id=str(updated_org.id),
                    request_id=_get_request_id(request),
                    safe_metadata={
                        "previous_status": str(old_status),
                        "status": str(new_status),
                    },
                )
            else:
                AuditEvent.objects.create(
                    organization=updated_org,
                    actor_user=request.user,
                    action=AuditAction.CONFIG_CHANGED,
                    target_type="organization",
                    target_id=str(updated_org.id),
                    request_id=_get_request_id(request),
                    safe_metadata={
                        "target_resource": "organization",
                        "status": str(updated_org.status),
                    },
                )

        return Response(OrganizationSerializer(updated_org).data, status=status.HTTP_200_OK)


# ===========================================================================
# Lab Views
# ===========================================================================


class LabListCreateView(APIView):
    """
    GET  /api/v1/labs?organization_id=...: List labs visible to user.
    POST /api/v1/labs: Create a lab (platform admin or org admin).
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]
    pagination_class = DocflowPagination

    def get(self, request, *args, **kwargs):
        queryset = _get_visible_labs_queryset(request.user)
        org_filter = request.query_params.get("organization_id")
        if org_filter:
            try:
                uuid.UUID(str(org_filter))
            except (ValueError, TypeError):
                raise serializers.ValidationError({"organization_id": ["Invalid UUID format."]})
            queryset = queryset.filter(organization_id=org_filter)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        if page is not None:
            serializer = LabSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = LabSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = LabCreateSerializer(data=request.data)
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
                if not OrganizationMembership.objects.filter(
                    organization=target_org,
                    user=request.user,
                    status=MembershipStatus.ACTIVE,
                    role=MembershipRole.ORGANIZATION_ADMIN,
                ).exists():
                    raise PermissionDenied("Organization admin privileges required to create a lab.")
            else:
                admin_memberships = OrganizationMembership.objects.filter(
                    user=request.user,
                    status=MembershipStatus.ACTIVE,
                    role=MembershipRole.ORGANIZATION_ADMIN,
                    organization__status=OrganizationStatus.ACTIVE,
                ).select_related("organization")

                if not admin_memberships.exists():
                    raise PermissionDenied("Organization admin privileges required to create a lab.")
                if admin_memberships.count() > 1:
                    raise serializers.ValidationError(
                        {"organization_id": ["organization_id is required when user manages multiple organizations."]}
                    )
                target_org = admin_memberships.first().organization

        code = serializer.validated_data["code"]
        if Lab.objects.filter(organization=target_org, code=code).exists():
            raise serializers.ValidationError(
                {"code": ["A lab with this code already exists in the organization."]}
            )

        with transaction.atomic():
            lab_data = {k: v for k, v in serializer.validated_data.items() if k != "organization_id"}
            lab = Lab.objects.create(organization=target_org, **lab_data)
            AuditEvent.objects.create(
                organization=target_org,
                actor_user=request.user,
                action=AuditAction.CONFIG_CHANGED,
                target_type="lab",
                target_id=str(lab.id),
                request_id=_get_request_id(request),
                safe_metadata={
                    "target_resource": "lab",
                    "status": str(lab.status),
                },
            )

        return Response(LabSerializer(lab).data, status=status.HTTP_201_CREATED)


class LabDetailUpdateView(APIView):
    """
    GET   /api/v1/labs/{lab_id}: Scoped read of a lab.
    PATCH /api/v1/labs/{lab_id}: Scoped update of a lab (platform admin or org admin).
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]

    def _get_scoped_lab(self, request, lab_id):
        return get_object_or_404(_get_visible_labs_queryset(request.user), id=lab_id)

    def get(self, request, lab_id, *args, **kwargs):
        lab = self._get_scoped_lab(request, lab_id)
        return Response(LabSerializer(lab).data, status=status.HTTP_200_OK)

    def patch(self, request, lab_id, *args, **kwargs):
        lab = self._get_scoped_lab(request, lab_id)
        if not _is_active_org_admin(request.user, lab.organization):
            raise PermissionDenied("Organization admin privileges required to update lab.")

        serializer = LabUpdateSerializer(lab, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            updated_lab = serializer.save()
            AuditEvent.objects.create(
                organization=updated_lab.organization,
                actor_user=request.user,
                action=AuditAction.CONFIG_CHANGED,
                target_type="lab",
                target_id=str(updated_lab.id),
                request_id=_get_request_id(request),
                safe_metadata={
                    "target_resource": "lab",
                    "status": str(updated_lab.status),
                },
            )

        return Response(LabSerializer(updated_lab).data, status=status.HTTP_200_OK)


# ===========================================================================
# Branch Views
# ===========================================================================


class BranchListCreateView(APIView):
    """
    GET  /api/v1/branches?lab_id=...: List branches visible to user.
    POST /api/v1/branches: Create a branch (platform admin or org admin).
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]
    pagination_class = DocflowPagination

    def get(self, request, *args, **kwargs):
        queryset = _get_visible_branches_queryset(request.user)
        lab_filter = request.query_params.get("lab_id")
        if lab_filter:
            try:
                uuid.UUID(str(lab_filter))
            except (ValueError, TypeError):
                raise serializers.ValidationError({"lab_id": ["Invalid UUID format."]})
            queryset = queryset.filter(lab_id=lab_filter)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        if page is not None:
            serializer = BranchSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = BranchSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = BranchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        lab_id = serializer.validated_data["lab_id"]
        is_platform_admin = getattr(request.user, "is_platform_admin", False)

        if is_platform_admin:
            lab = get_object_or_404(Lab.objects.all().select_related("organization"), id=lab_id)
        else:
            lab = get_object_or_404(
                Lab.objects.filter(
                    organization__status=OrganizationStatus.ACTIVE,
                    organization__memberships__user=request.user,
                    organization__memberships__status=MembershipStatus.ACTIVE,
                ).select_related("organization"),
                id=lab_id,
            )
            if not OrganizationMembership.objects.filter(
                organization=lab.organization,
                user=request.user,
                status=MembershipStatus.ACTIVE,
                role=MembershipRole.ORGANIZATION_ADMIN,
            ).exists():
                raise PermissionDenied("Organization admin privileges required to create a branch.")

        code = serializer.validated_data["code"]
        if Branch.objects.filter(lab=lab, code=code).exists():
            raise serializers.ValidationError(
                {"code": ["A branch with this code already exists in this lab."]}
            )

        with transaction.atomic():
            branch_data = {k: v for k, v in serializer.validated_data.items() if k != "lab_id"}
            branch = Branch.objects.create(lab=lab, organization=lab.organization, **branch_data)
            AuditEvent.objects.create(
                organization=branch.organization,
                actor_user=request.user,
                action=AuditAction.CONFIG_CHANGED,
                target_type="branch",
                target_id=str(branch.id),
                request_id=_get_request_id(request),
                safe_metadata={
                    "target_resource": "branch",
                    "branch_code": str(branch.code),
                    "status": str(branch.status),
                },
            )

        return Response(BranchSerializer(branch).data, status=status.HTTP_201_CREATED)


class BranchDetailUpdateView(APIView):
    """
    GET   /api/v1/branches/{branch_id}: Scoped read of a branch.
    PATCH /api/v1/branches/{branch_id}: Scoped update of a branch (platform admin or org admin).
    """

    authentication_classes = [CSRFEnforcedSessionAuthentication]
    permission_classes = [IsAuthenticatedHumanUser]

    def _get_scoped_branch(self, request, branch_id):
        return get_object_or_404(
            _get_visible_branches_queryset(request.user),
            id=branch_id,
        )

    def get(self, request, branch_id, *args, **kwargs):
        branch = self._get_scoped_branch(request, branch_id)
        return Response(BranchSerializer(branch).data, status=status.HTTP_200_OK)

    def patch(self, request, branch_id, *args, **kwargs):
        branch = self._get_scoped_branch(request, branch_id)
        if not _is_active_org_admin(request.user, branch.organization):
            raise PermissionDenied("Organization admin privileges required to update branch.")

        serializer = BranchUpdateSerializer(branch, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            updated_branch = serializer.save()
            AuditEvent.objects.create(
                organization=updated_branch.organization,
                actor_user=request.user,
                action=AuditAction.CONFIG_CHANGED,
                target_type="branch",
                target_id=str(updated_branch.id),
                request_id=_get_request_id(request),
                safe_metadata={
                    "target_resource": "branch",
                    "branch_code": str(updated_branch.code),
                    "status": str(updated_branch.status),
                },
            )

        return Response(BranchSerializer(updated_branch).data, status=status.HTTP_200_OK)
