"""
URL routing for Docflow Agent Authentication APIs.

Routes:
  - POST /api/v1/agent/activation/exchange
  - POST /api/v1/agent/auth/refresh
  - POST /api/v1/agent/auth/revoke-self
"""

from django.urls import re_path

from .views import ActivationExchangeView, RefreshTokenView, RevokeSelfView

urlpatterns = [
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
]
