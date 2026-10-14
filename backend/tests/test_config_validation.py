"""
Tests for production configuration validation (fail-closed behaviour).

These tests import production settings with environment variables manipulated
via os.environ patching (monkeypatching).  Each test isolates only the
variable under test so failures are unambiguous.

Covers:
- Missing DJANGO_SECRET_KEY raises ImproperlyConfigured
- DEBUG=true in production raises ImproperlyConfigured
- Missing DATABASE_URL raises ImproperlyConfigured
- SQLite DATABASE_URL raises ImproperlyConfigured
- Non-PostgreSQL DATABASE_URL raises ImproperlyConfigured
- DEV_ACCOUNT_VERIFICATION_OVERRIDE=true raises ImproperlyConfigured
- TEMP_UPLOAD_MODE != disabled raises ImproperlyConfigured
- Valid PostgreSQL DATABASE_URL succeeds without raising
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
