"""
URL routing for Docflow WhatsApp Account and Assignment APIs (Phase 1, Task 3F).

Routes:
  - GET  /api/v1/whatsapp-accounts
  - POST /api/v1/whatsapp-accounts
  - GET  /api/v1/whatsapp-accounts/{account_id}
  - POST /api/v1/whatsapp-accounts/{account_id}/verify
  - POST /api/v1/branches/{branch_id}/whatsapp-assignment
  - DELETE /api/v1/branches/{branch_id}/whatsapp-assignment
"""

from django.urls import re_path

from .views import (
    BranchWhatsAppAssignmentView,
    WhatsAppAccountDetailView,
    WhatsAppAccountListCreateView,
    WhatsAppAccountVerifyView,
)

UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

urlpatterns = [
    re_path(
        r"^whatsapp-accounts/?$",
        WhatsAppAccountListCreateView.as_view(),
        name="whatsapp-account-list-create",
    ),
    re_path(
        rf"^whatsapp-accounts/(?P<account_id>{UUID_PATTERN})/?$",
        WhatsAppAccountDetailView.as_view(),
        name="whatsapp-account-detail",
    ),
    re_path(
        rf"^whatsapp-accounts/(?P<account_id>{UUID_PATTERN})/verify/?$",
        WhatsAppAccountVerifyView.as_view(),
        name="whatsapp-account-verify",
    ),
    re_path(
        rf"^branches/(?P<branch_id>{UUID_PATTERN})/whatsapp-assignment/?$",
        BranchWhatsAppAssignmentView.as_view(),
        name="branch-whatsapp-assignment",
    ),
]
