"""
URL routing for Docflow Agent Authentication APIs.

Routes:
  - POST /api/v1/agent/activation/exchange
  - POST /api/v1/agent/auth/refresh
  - POST /api/v1/agent/auth/revoke-self
"""

from django.urls import re_path

from .management_views import (
    DeviceActivationCodeIssueView,
    DeviceDetailUpdateView,
    DeviceListCreateView,
    DeviceRevokeView,
)
from .views import ActivationExchangeView, RefreshTokenView, RevokeSelfView

UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

urlpatterns = [
    # Agent APIs
    re_path(
        r"^agent/activation/exchange/?$",
        ActivationExchangeView.as_view(),
        name="agent-activation-exchange",
    ),
    re_path(
        r"^agent/auth/refresh/?$",
        RefreshTokenView.as_view(),
        name="agent-auth-refresh",
    ),
    re_path(
        r"^agent/auth/revoke-self/?$",
        RevokeSelfView.as_view(),
        name="agent-auth-revoke-self",
    ),
    # Human Device Management APIs (Phase 1, Task 3E)
    re_path(
        r"^devices/?$",
        DeviceListCreateView.as_view(),
        name="device-list-create",
    ),
    re_path(
        rf"^devices/(?P<device_id>{UUID_PATTERN})/?$",
        DeviceDetailUpdateView.as_view(),
        name="device-detail-update",
    ),
    re_path(
        rf"^devices/(?P<device_id>{UUID_PATTERN})/activation-code/?$",
        DeviceActivationCodeIssueView.as_view(),
        name="device-activation-code-issue",
    ),
    re_path(
        rf"^devices/(?P<device_id>{UUID_PATTERN})/revoke/?$",
        DeviceRevokeView.as_view(),
        name="device-revoke",
    ),
]

