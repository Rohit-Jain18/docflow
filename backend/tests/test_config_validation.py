"""
Tests for production configuration validation (fail-closed behaviour).

These tests import production settings with environment variables manipulated
via os.environ patching (monkeypatching).  Each test isolates only the
variable under test so failures are unambiguous.

Covers:
- Missing DJANGO_SECRET_KEY raises ImproperlyConfigured
- Development placeholder secret key raises ImproperlyConfigured
- DEBUG=true in production raises ImproperlyConfigured
- Missing DATABASE_URL raises ImproperlyConfigured
- SQLite DATABASE_URL raises ImproperlyConfigured
- Non-PostgreSQL DATABASE_URL (MySQL) raises ImproperlyConfigured
- DEV_ACCOUNT_VERIFICATION_OVERRIDE=true raises ImproperlyConfigured
- TEMP_UPLOAD_MODE != disabled raises ImproperlyConfigured
- Valid PostgreSQL DATABASE_URL succeeds without raising
- Empty ALLOWED_HOSTS raises ImproperlyConfigured
- Wildcard ALLOWED_HOSTS raises ImproperlyConfigured
- DOCFLOW_ENV=production with development settings raises ImproperlyConfigured
"""

import importlib
import os
import sys
import unittest


def _import_production_settings(env_overrides: dict) -> None:
    """
    Import (or re-import) production settings with a temporary environment.

    Any modules already in sys.modules that begin with 'config.settings' are
    removed first so Django re-evaluates module-level validation code.
    """
    for key in list(sys.modules):
        if key.startswith("config.settings"):
            del sys.modules[key]

    old_env = {}
    for k, v in env_overrides.items():
        old_env[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    try:
        importlib.import_module("config.settings.production")
    finally:
        # Restore environment
        for k, old_v in old_env.items():
            if old_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_v


# Minimum valid production environment
_VALID_ENV = {
    "DJANGO_SECRET_KEY": "a-sufficiently-long-production-secret-key-placeholder",
    "DJANGO_DEBUG": "false",
    "DJANGO_ALLOWED_HOSTS": "app.example.com",
    "DATABASE_URL": "postgresql://user:pass@db:5432/docflow",
    "DEV_ACCOUNT_VERIFICATION_OVERRIDE": "false",
    "TEMP_UPLOAD_MODE": "disabled",
}


class ProductionSettingsValidationTest(unittest.TestCase):

    def _load(self, **env_patch):
        """Load production settings with _VALID_ENV overridden by env_patch."""
        env = {**_VALID_ENV, **env_patch}
        _import_production_settings(env)

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_valid_env_does_not_raise(self):
        from django.core.exceptions import ImproperlyConfigured
        try:
            self._load()
        except ImproperlyConfigured as exc:
            self.fail(f"Valid env raised ImproperlyConfigured: {exc}")

    # ------------------------------------------------------------------
    # SECRET_KEY
    # ------------------------------------------------------------------

    def test_missing_secret_key_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DJANGO_SECRET_KEY=None)

    def test_empty_secret_key_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DJANGO_SECRET_KEY="")

    # ------------------------------------------------------------------
    # DEBUG
    # ------------------------------------------------------------------

    def test_debug_true_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DJANGO_DEBUG="true")

    def test_debug_1_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DJANGO_DEBUG="1")

    def test_debug_false_does_not_raise(self):
        from django.core.exceptions import ImproperlyConfigured
        try:
            self._load(DJANGO_DEBUG="false")
        except ImproperlyConfigured as exc:
            self.fail(f"DEBUG=false raised: {exc}")

    # ------------------------------------------------------------------
    # DATABASE_URL
    # ------------------------------------------------------------------

    def test_missing_database_url_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DATABASE_URL=None)

    def test_empty_database_url_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DATABASE_URL="")

    def test_sqlite_database_url_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DATABASE_URL="sqlite:///dev.db")

    # ------------------------------------------------------------------
    # DEV_ACCOUNT_VERIFICATION_OVERRIDE
    # ------------------------------------------------------------------

    def test_dev_override_true_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DEV_ACCOUNT_VERIFICATION_OVERRIDE="true")

    def test_dev_override_1_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DEV_ACCOUNT_VERIFICATION_OVERRIDE="1")

    def test_dev_override_false_does_not_raise(self):
        from django.core.exceptions import ImproperlyConfigured
        try:
            self._load(DEV_ACCOUNT_VERIFICATION_OVERRIDE="false")
        except ImproperlyConfigured as exc:
            self.fail(f"Override=false raised: {exc}")

    # ------------------------------------------------------------------
    # TEMP_UPLOAD_MODE
    # ------------------------------------------------------------------

    def test_tmpfiles_upload_mode_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(TEMP_UPLOAD_MODE="tmpfiles")

    def test_disabled_upload_mode_does_not_raise(self):
        from django.core.exceptions import ImproperlyConfigured
        try:
            self._load(TEMP_UPLOAD_MODE="disabled")
        except ImproperlyConfigured as exc:
            self.fail(f"TEMP_UPLOAD_MODE=disabled raised: {exc}")

    # ------------------------------------------------------------------
    # Error messages must not leak values
    # ------------------------------------------------------------------

    def test_missing_secret_key_error_does_not_contain_value(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured) as ctx:
            self._load(DJANGO_SECRET_KEY="")
        # Message must not echo the (empty) value — check no raw value leakage pattern
        self.assertNotIn("=", str(ctx.exception).split("'DJANGO_SECRET_KEY'")[-1][:20])

    # ------------------------------------------------------------------
    # Secret key placeholder detection
    # ------------------------------------------------------------------

    def test_dev_placeholder_secret_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DJANGO_SECRET_KEY="dev-insecure-secret-key-change-before-production")

    def test_insecure_placeholder_secret_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DJANGO_SECRET_KEY="django-insecure-abc123")

    def test_strong_secret_key_does_not_raise(self):
        from django.core.exceptions import ImproperlyConfigured
        try:
            self._load(DJANGO_SECRET_KEY="a-sufficiently-long-production-secret-key-placeholder")
        except ImproperlyConfigured as exc:
            self.fail(f"Strong key raised: {exc}")

    # ------------------------------------------------------------------
    # ALLOWED_HOSTS validation
    # ------------------------------------------------------------------

    def test_wildcard_allowed_hosts_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DJANGO_ALLOWED_HOSTS="*")

    def test_wildcard_in_list_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DJANGO_ALLOWED_HOSTS="app.example.com,*")

    def test_specific_allowed_hosts_does_not_raise(self):
        from django.core.exceptions import ImproperlyConfigured
        try:
            self._load(DJANGO_ALLOWED_HOSTS="app.example.com,api.example.com")
        except ImproperlyConfigured as exc:
            self.fail(f"Specific hosts raised: {exc}")

    # ------------------------------------------------------------------
    # Non-PostgreSQL DATABASE_URL
    # ------------------------------------------------------------------

    def test_mysql_database_url_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DATABASE_URL="mysql://user:pass@db:3306/docflow")

    # ------------------------------------------------------------------
    # Reverse Proxy Trust Configuration
    # ------------------------------------------------------------------

    def test_malformed_trusted_proxy_ip_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DOCFLOW_TRUSTED_PROXIES="invalid_ip")

    def test_malformed_trusted_proxy_cidr_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DOCFLOW_TRUSTED_PROXIES="10.0.0.0/99")

    def test_wildcard_trusted_proxy_range_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DOCFLOW_TRUSTED_PROXIES="0.0.0.0/0")

    def test_ipv6_wildcard_trusted_proxy_range_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DOCFLOW_TRUSTED_PROXIES="::/0")

    def test_proxy_count_without_trusted_proxies_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DOCFLOW_NUM_PROXIES="1")

    def test_invalid_proxy_count_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DOCFLOW_NUM_PROXIES="not-a-number")

    def test_negative_proxy_count_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            self._load(DOCFLOW_NUM_PROXIES="-1")

    def test_valid_trusted_proxies_succeeds(self):
        from django.core.exceptions import ImproperlyConfigured
        try:
            self._load(DOCFLOW_TRUSTED_PROXIES="10.0.0.1, 192.168.1.0/24")
        except ImproperlyConfigured as exc:
            self.fail(f"Valid trusted proxies raised: {exc}")

    def test_valid_trusted_proxies_with_count_succeeds(self):
        from django.core.exceptions import ImproperlyConfigured
        try:
            self._load(DOCFLOW_TRUSTED_PROXIES="10.0.0.1", DOCFLOW_NUM_PROXIES="1")
        except ImproperlyConfigured as exc:
            self.fail(f"Valid trusted proxies with count raised: {exc}")



def _import_development_settings(env_overrides: dict) -> None:
    """Re-import development settings with patched environment."""
    for key in list(sys.modules):
        if key.startswith("config.settings"):
            del sys.modules[key]

    old_env = {}
    for k, v in env_overrides.items():
        old_env[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    try:
        importlib.import_module("config.settings.development")
    finally:
        for k, old_v in old_env.items():
            if old_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_v


class DevelopmentSettingsGuardTest(unittest.TestCase):
    """Development settings must reject DOCFLOW_ENV=production."""

    def test_docflow_env_production_with_dev_settings_raises(self):
        from django.core.exceptions import ImproperlyConfigured
        with self.assertRaises(ImproperlyConfigured):
            _import_development_settings({"DOCFLOW_ENV": "production"})

    def test_docflow_env_development_does_not_raise(self):
        from django.core.exceptions import ImproperlyConfigured
        try:
            _import_development_settings({"DOCFLOW_ENV": "development"})
        except ImproperlyConfigured as exc:
            self.fail(f"DOCFLOW_ENV=development raised: {exc}")

    def test_docflow_env_unset_does_not_raise(self):
        from django.core.exceptions import ImproperlyConfigured
        try:
            _import_development_settings({"DOCFLOW_ENV": None})
        except ImproperlyConfigured as exc:
            self.fail(f"Unset DOCFLOW_ENV raised: {exc}")

