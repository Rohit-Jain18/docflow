"""
Docflow production settings.

Fails closed — startup raises ImproperlyConfigured when required
configuration is absent or unsafe.  Never falls back to SQLite.
Never logs secret values.
"""

import os
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401, F403


# ---------------------------------------------------------------------------
# Internal helper — fail closed without revealing the value
# ---------------------------------------------------------------------------
def _require_env(name: str) -> str:
    """Return the environment variable or raise ImproperlyConfigured."""
    value = os.environ.get(name, "")
    if not value:
        raise ImproperlyConfigured(
            f"[Docflow] Required environment variable '{name}' is not set. "
            "Set it via secret management before starting the server."
        )
    return value


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = _require_env("DJANGO_SECRET_KEY")

DEBUG_RAW = os.environ.get("DJANGO_DEBUG", "false").lower()
if DEBUG_RAW not in ("false", "0", ""):
    raise ImproperlyConfigured(
        "[Docflow] DJANGO_DEBUG must be false in production. "
        "Remove or set it to 'false'."
    )
DEBUG = False

_allowed_hosts_raw = _require_env("DJANGO_ALLOWED_HOSTS")
ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_raw.split(",") if h.strip()]

# ---------------------------------------------------------------------------
# CSRF / session cookie security
# ---------------------------------------------------------------------------
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# CSRF_TRUSTED_ORIGINS is required if the dashboard makes cross-origin requests
_csrf_origins_raw = os.environ.get("CSRF_TRUSTED_ORIGINS", "")
if _csrf_origins_raw:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_origins_raw.split(",") if o.strip()]

# ---------------------------------------------------------------------------
# Database — PostgreSQL only; fail closed if DATABASE_URL is absent or SQLite
# ---------------------------------------------------------------------------
_db_url = _require_env("DATABASE_URL")
if "sqlite" in _db_url.lower():
    raise ImproperlyConfigured(
        "[Docflow] SQLite is not permitted in production. "
        "Configure a PostgreSQL DATABASE_URL."
    )

DATABASES = {
    "default": dj_database_url.parse(
        _db_url,
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# Ensure the resolved engine is PostgreSQL
_db_engine = DATABASES["default"].get("ENGINE", "")
if "postgresql" not in _db_engine and "postgis" not in _db_engine:
    raise ImproperlyConfigured(
        "[Docflow] Production database must be PostgreSQL. "
        f"Resolved engine: '{_db_engine}'."
    )

# ---------------------------------------------------------------------------
# Development verification override — strictly forbidden in production
# ---------------------------------------------------------------------------
_dev_override_raw = os.environ.get("DEV_ACCOUNT_VERIFICATION_OVERRIDE", "false").lower()
if _dev_override_raw in ("true", "1", "yes"):
    raise ImproperlyConfigured(
        "[Docflow] DEV_ACCOUNT_VERIFICATION_OVERRIDE must not be enabled in production. "
        "Disable it before starting the server."
    )
DEV_ACCOUNT_VERIFICATION_OVERRIDE = False
DEV_TEST_ORGANIZATION_ID = ""
DEV_TEST_ACCOUNT_ID = ""

# ---------------------------------------------------------------------------
# Temporary upload — forcibly disabled in production
# ---------------------------------------------------------------------------
_temp_upload_mode = os.environ.get("TEMP_UPLOAD_MODE", "disabled").lower()
if _temp_upload_mode != "disabled":
    raise ImproperlyConfigured(
        "[Docflow] TEMP_UPLOAD_MODE must be 'disabled' in production. "
        "tmpfiles.org is a development-only tool."
    )
TEMP_UPLOAD_MODE = "disabled"
TEMP_UPLOAD_FICTIONAL_DATA_ONLY = False

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405
