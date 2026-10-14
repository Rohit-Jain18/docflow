"""
URL routing for Docflow Tenant APIs (Phase 1, Task 3D).

Routes:
  - GET / POST          /api/v1/organizations
  - GET / PATCH         /api/v1/organizations/{organization_id}
  - GET / POST          /api/v1/labs
  - GET / PATCH         /api/v1/labs/{lab_id}
  - GET / POST          /api/v1/branches
  - GET / PATCH         /api/v1/branches/{branch_id}
"""

from django.urls import re_path

from .views import (
    BranchDetailUpdateView,
    BranchListCreateView,
    LabDetailUpdateView,
    LabListCreateView,
    OrganizationDetailUpdateView,
    OrganizationListCreateView,
)

UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

urlpatterns = [
    re_path(
        r"^organizations/?$",
        OrganizationListCreateView.as_view(),
        name="organization-list-create",
    ),
    re_path(
        rf"^organizations/(?P<organization_id>{UUID_PATTERN})/?$",
        OrganizationDetailUpdateView.as_view(),
        name="organization-detail-update",
    ),
    re_path(
        r"^labs/?$",
        LabListCreateView.as_view(),
        name="lab-list-create",
    ),
    re_path(
        rf"^labs/(?P<lab_id>{UUID_PATTERN})/?$",
        LabDetailUpdateView.as_view(),
        name="lab-detail-update",
    ),
    re_path(
        r"^branches/?$",
        BranchListCreateView.as_view(),
        name="branch-list-create",
    ),
    re_path(
        rf"^branches/(?P<branch_id>{UUID_PATTERN})/?$",
        BranchDetailUpdateView.as_view(),
        name="branch-detail-update",
    ),
]
