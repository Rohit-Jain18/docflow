"""
Docflow production settings.

Fails closed — startup raises ImproperlyConfigured when required
configuration is absent or unsafe.  Never falls back to SQLite.
Never logs secret values.
"""

import ipaddress
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

# Reject known development placeholder values — match the string used in development.py
_DEV_PLACEHOLDER_SECRETS = {
    "dev-insecure-secret-key-change-before-production",
    "insecure",
    "changeme",
    "django-insecure",
}
if any(placeholder in SECRET_KEY for placeholder in _DEV_PLACEHOLDER_SECRETS):
    raise ImproperlyConfigured(
        "[Docflow] DJANGO_SECRET_KEY appears to be a development placeholder. "
        "Set a strong unique secret before starting the production server."
    )

DEBUG_RAW = os.environ.get("DJANGO_DEBUG", "false").lower()
if DEBUG_RAW not in ("false", "0", ""):
    raise ImproperlyConfigured(
        "[Docflow] DJANGO_DEBUG must be false in production. "
        "Remove or set it to 'false'."
    )
DEBUG = False

_allowed_hosts_raw = _require_env("DJANGO_ALLOWED_HOSTS")
ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts_raw.split(",") if h.strip()]

# Reject wildcard — an open host header allows header injection in production
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "[Docflow] DJANGO_ALLOWED_HOSTS must not be empty in production."
    )
if "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "[Docflow] DJANGO_ALLOWED_HOSTS must not contain '*' in production. "
        "List explicit hostnames."
    )

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

# ---------------------------------------------------------------------------
# Reverse Proxy Trust Configuration
# ---------------------------------------------------------------------------
_trusted_proxies_raw = os.environ.get("DOCFLOW_TRUSTED_PROXIES", "")
if _trusted_proxies_raw:
    _entries = [p.strip() for p in _trusted_proxies_raw.split(",") if p.strip()]
    if not _entries:
        raise ImproperlyConfigured(
            "[Docflow] DOCFLOW_TRUSTED_PROXIES was provided but contains no valid IP addresses or CIDR entries."
        )
    for _entry in _entries:
        try:
            if "/" in _entry:
                _net = ipaddress.ip_network(_entry, strict=False)
                if _net.prefixlen == 0:
                    raise ImproperlyConfigured(
                        f"[Docflow] Insecure trusted proxy wildcard range '{_entry}' in DOCFLOW_TRUSTED_PROXIES is forbidden."
                    )
            else:
                ipaddress.ip_address(_entry)
        except ValueError as _exc:
            raise ImproperlyConfigured(
                f"[Docflow] Invalid trusted proxy address or CIDR in DOCFLOW_TRUSTED_PROXIES: '{_entry}'."
            ) from _exc
    DOCFLOW_TRUSTED_PROXIES = tuple(_entries)

_num_proxies_raw = os.environ.get("DOCFLOW_NUM_PROXIES", "")
if _num_proxies_raw:
    try:
        _num = int(_num_proxies_raw)
        if _num < 0:
            raise ValueError
    except ValueError:
        raise ImproperlyConfigured(
            f"[Docflow] DOCFLOW_NUM_PROXIES must be a non-negative integer, got '{_num_proxies_raw}'."
        )

    # Fail closed on conflicting configuration: proxy count alone cannot authorize forwarded headers
    if _num > 0 and not DOCFLOW_TRUSTED_PROXIES:
        raise ImproperlyConfigured(
            "[Docflow] DOCFLOW_NUM_PROXIES > 0 is configured without DOCFLOW_TRUSTED_PROXIES. "
            "A proxy count alone cannot authorize forwarded headers. Explicitly configure trusted proxy IPs/CIDRs."
        )
    DOCFLOW_NUM_PROXIES = _num
    NUM_PROXIES = _num
    REST_FRAMEWORK["NUM_PROXIES"] = _num

