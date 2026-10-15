"""
Docflow User model.

Replaces Django's built-in User with a UUID-primary-key, email-based model
as per DATA_MODEL.md §1.  Must be set as AUTH_USER_MODEL before the first
migration; do not change afterwards.

Fields:
  id              — UUID primary key (API-safe).
  email           — unique, normalised login identity.
  display_name    — human-readable name shown in the UI.
  is_active       — whether the account may log in.
  is_platform_admin — elevated platform-wide access; audited separately.
  last_login      — managed by Django auth machinery.
  created_at      — UTC timestamp set on creation.
  updated_at      — UTC timestamp updated on every save.

Deliberately excluded from this model (belong in separate models per spec):
  organization memberships, roles, device credentials.
"""

import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """Manager for the custom User model."""

    def _create_user(
        self,
        email: str,
        password: str | None,
        **extra_fields,
    ) -> "User":
        if not email:
            raise ValueError("Email address is required.")
        email = self.normalize_email(email)
        user: User = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields,
    ) -> "User":
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("is_platform_admin", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields,
    ) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_platform_admin", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Docflow user account.

    Login is email-based.  Membership in organizations and platform-admin
    privileges are kept in separate models/fields rather than groups alone.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # pyrefly: ignore[bad-override-mutable-attribute]
    email = models.EmailField(
        unique=True,
        verbose_name="email address",
        help_text="Normalised unique email used for login.",
    )
    display_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="display name",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="active",
        help_text="Inactive accounts cannot log in.",
    )
    is_staff = models.BooleanField(
        default=False,
        verbose_name="staff status",
        help_text="Required for Django admin access.",
    )
    is_platform_admin = models.BooleanField(
        default=False,
        verbose_name="platform admin",
        help_text=(
            "Grants platform-wide administrative access.  "
            "Use sparingly and audit all actions."
        ),
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    objects: UserManager = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # email is already the username field

    class Meta:
        db_table = "users_user"
        verbose_name = "user"
        verbose_name_plural = "users"
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email

    def get_full_name(self) -> str:
        return self.display_name or self.email

    def get_short_name(self) -> str:
        return self.display_name or self.email
