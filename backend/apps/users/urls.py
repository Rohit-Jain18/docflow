"""
URL routing for Docflow Human User Authentication APIs (Phase 1, Task 3C).

Routes:
  - GET  /api/v1/auth/csrf
  - POST /api/v1/auth/login
  - POST /api/v1/auth/logout
  - GET  /api/v1/auth/me
"""

from django.urls import re_path

from .views import CSRFBootstrapView, LoginView, LogoutView, MeView

urlpatterns = [
    re_path(
        r"^auth/csrf/?$",
        CSRFBootstrapView.as_view(),
        name="auth-csrf",
    ),
    re_path(
        r"^auth/login/?$",
        LoginView.as_view(),
        name="auth-login",
    ),
    re_path(
        r"^auth/logout/?$",
        LogoutView.as_view(),
        name="auth-logout",
    ),
    re_path(
        r"^auth/me/?$",
        MeView.as_view(),
        name="auth-me",
    ),
]
