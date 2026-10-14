"""
Docflow development settings.

Uses Django-default SQLite; no DATABASE_URL required locally.
Do NOT use in staging or production.
"""

import os
from django.core.exceptions import ImproperlyConfigured
from .base import *  # noqa: F401, F403

# ---------------------------------------------------------------------------
# Reject production environment using development settings
# ---------------------------------------------------------------------------
if os.environ.get("DOCFLOW_ENV", "").lower() == "production":
    raise ImproperlyConfigured(
        "[Docflow] DOCFLOW_ENV=production is set but development settings are "
        "active. Use config.settings.production for production deployments."
    )

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    # Fallback only in development — never hard-code a production secret.
    "dev-insecure-secret-key-change-before-production",
)

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# ---------------------------------------------------------------------------
# Database — Django-default SQLite for local development
# No DATABASE_URL needed; the file lands at backend/db.sqlite3.
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405 — BASE_DIR from base.py
    }
}

# ---------------------------------------------------------------------------
# Development-only account verification override
# ---------------------------------------------------------------------------
DEV_ACCOUNT_VERIFICATION_OVERRIDE = (
    os.environ.get("DEV_ACCOUNT_VERIFICATION_OVERRIDE", "false").lower() == "true"
)
DEV_TEST_ORGANIZATION_ID = os.environ.get("DEV_TEST_ORGANIZATION_ID", "")
DEV_TEST_ACCOUNT_ID = os.environ.get("DEV_TEST_ACCOUNT_ID", "")

# ---------------------------------------------------------------------------
# Temporary upload (disabled by default even in development)
# ---------------------------------------------------------------------------
TEMP_UPLOAD_MODE = os.environ.get("TEMP_UPLOAD_MODE", "disabled")
TEMP_UPLOAD_FICTIONAL_DATA_ONLY = (
    os.environ.get("TEMP_UPLOAD_FICTIONAL_DATA_ONLY", "false").lower() == "true"
)
TEMP_UPLOAD_EXPECTED_HOST = os.environ.get("TEMP_UPLOAD_EXPECTED_HOST", "tmpfiles.org")

# ---------------------------------------------------------------------------
# Email (console backend for local dev)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
