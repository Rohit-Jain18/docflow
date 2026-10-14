"""
Tests for the custom User model.

Covers:
- UUID primary key
- Email-based login (USERNAME_FIELD)
- Email normalisation
- create_user and create_superuser helpers
- is_platform_admin field
- __str__ returns email
- Timestamps (created_at, updated_at present)
- Empty email raises ValueError
"""

import uuid

from django.test import TestCase

from apps.users.models import User


class UserModelTest(TestCase):
    def _make_user(self, email="alice@example.test", password="testpass123"):
        return User.objects.create_user(email=email, password=password)

    # ------------------------------------------------------------------
    # Primary key and identification
    # ------------------------------------------------------------------

    def test_pk_is_uuid(self):
        user = self._make_user()
        self.assertIsInstance(user.id, uuid.UUID)

    def test_username_field_is_email(self):
        self.assertEqual(User.USERNAME_FIELD, "email")

    def test_str_returns_email(self):
        user = self._make_user()
        self.assertEqual(str(user), "alice@example.test")

    # ------------------------------------------------------------------
    # Email normalisation
    # ------------------------------------------------------------------

    def test_email_is_normalised(self):
        # RFC 5321 — local part is case-sensitive but domain is lowercased
        user = self._make_user(email="Alice@Example.TEST")
        self.assertEqual(user.email, "Alice@example.test")

    def test_email_uniqueness(self):
        from django.db import IntegrityError

        self._make_user(email="bob@example.test")
        with self.assertRaises(IntegrityError):
            self._make_user(email="bob@example.test")

    def test_empty_email_raises(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="x")

    # ------------------------------------------------------------------
    # create_user defaults
    # ------------------------------------------------------------------

    def test_create_user_defaults(self):
        user = self._make_user()
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_platform_admin)

    def test_password_is_hashed(self):
        user = self._make_user()
        self.assertNotEqual(user.password, "testpass123")
        self.assertTrue(user.check_password("testpass123"))

    # ------------------------------------------------------------------
    # create_superuser
    # ------------------------------------------------------------------

    def test_create_superuser_flags(self):
        su = User.objects.create_superuser(email="su@example.test", password="pass123")
        self.assertTrue(su.is_staff)
        self.assertTrue(su.is_superuser)
        self.assertTrue(su.is_platform_admin)

    def test_create_superuser_wrong_is_staff_raises(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email="bad@example.test", password="x", is_staff=False
            )

    # ------------------------------------------------------------------
    # Display name helpers
    # ------------------------------------------------------------------

    def test_get_full_name_with_display_name(self):
        user = self._make_user()
        user.display_name = "Alice Smith"
        self.assertEqual(user.get_full_name(), "Alice Smith")

    def test_get_full_name_falls_back_to_email(self):
        user = self._make_user()
        user.display_name = ""
        self.assertEqual(user.get_full_name(), "alice@example.test")

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------

    def test_created_at_is_set(self):
        user = self._make_user()
        self.assertIsNotNone(user.created_at)

    def test_updated_at_is_set(self):
        user = self._make_user()
        self.assertIsNotNone(user.updated_at)
