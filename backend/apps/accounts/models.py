"""User and role models (spec §9.1, §9.2, principle P06).

Two deliberate choices:

1. **A dedicated :class:`Role` model, not ``auth.Group``.** Spec §9.2 fixes the
   vocabulary at four roles and states that every user holds exactly one. A
   non-null ``User.role`` foreign key makes that a database-level guarantee;
   a ``Group`` many-to-many would make "this user has both Cashier and Owner" a
   representable state that only application code prevents.

2. **Server-authoritative permissions.** A user's effective permissions are the
   union of their role's grants plus any direct grants. Roles are *not* checked
   as ``if user.role == Role.CASHIER`` at call sites — the matrix in
   :mod:`apps.accounts.permissions` is resolved into real Django permissions so
   ``user.has_perm`` is the single enforcement point (P06).
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib.auth.models import (
    AbstractUser,
    PermissionsMixin,
)
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class RoleQuerySet(models.QuerySet["Role"]):
    """QuerySet for :class:`Role`."""

    def for_code(self, code: str) -> Role:
        """Return the role with ``code``.

        Raises:
            Role.DoesNotExist: If the role is missing, which means the role
                seeding migration has not been applied.
        """
        return self.get(code=code)


class Role(models.Model):
    """A business role and the permissions it grants (spec §9.2).

    The four roles in :attr:`code` are the approved vocabulary. New roles are a
    business decision requiring a spec revision, not a config tweak.

    Deletion is restricted: a role in use cannot be removed, because that would
    silently strip a staff member's authorization mid-shift.
    """

    class Code(models.TextChoices):
        """The approved role vocabulary (spec §9.2)."""

        BARMAN = "BARMAN", _("Barman")
        CASHIER = "CASHIER", _("Cashier")
        MANAGER = "MANAGER", _("Manager")
        OWNER = "OWNER", _("Owner")

    code = models.CharField(
        _("code"),
        max_length=20,
        choices=Code.choices,
        unique=True,
        help_text=_("Stable machine code. Never shown to staff; the name is."),
    )
    name = models.CharField(_("name"), max_length=100, help_text=_("Label shown in staff UIs."))
    description = models.TextField(_("description"), blank=True)
    permissions_granted = models.ManyToManyField(
        "auth.Permission",
        verbose_name=_("granted permissions"),
        related_name="barkot_roles",
        blank=True,
        help_text=_(
            "Seeded from apps.accounts.permissions.ROLE_MATRIX. "
            "Do not edit at runtime; change the matrix and the seed migration."
        ),
    )
    is_staff_role = models.BooleanField(
        _("is staff role"),
        default=True,
        help_text=_("False marks a service/integration identity that cannot log in."),
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    objects: ClassVar[RoleQuerySet] = RoleQuerySet()

    class Meta:
        verbose_name = _("role")
        verbose_name_plural = _("roles")
        ordering = ["code"]
        permissions = (("manage_roles", "Can manage business roles"),)

    def __str__(self) -> str:
        return self.name

    def effective_permissions(self) -> set[str]:
        """Return this role's granted permission codenames as a set.

        Used by the management command and the matrix test to compare the seeded
        state against the declared intent.
        """
        return set(self.permissions_granted.values_list("codename", flat=True))


class UserManager(DjangoUserManager["User"]):
    """Manager for :class:`User`.

    Extends Django 5.2's concrete ``auth.models.UserManager`` — rather than
    ``BaseUserManager`` — because :class:`User` is a concrete swappable model
    with the same shape as the built-in one. That base resolves the model class
    through the app registry, so the manager keeps working inside migrations.

    Inherits ``create_user`` / ``create_superuser`` from Django but makes
    ``email`` optional and adds :meth:`create_staff_user`, which is the only
    supported way to onboard a staff member because it forces an explicit role.
    """

    use_in_migrations = True

    def create_staff_user(
        self,
        username: str,
        *,
        role: Role,
        password: str | None = None,
        email: str = "",
        **extra_fields: Any,
    ) -> User:
        """Create a login-enabled staff user with an explicit role.

        Args:
            username: Login name. Required and unique.
            role: The single business role to grant. Required — a user with no
                role would have no permissions and be unable to do anything,
                which is almost certainly a mistake rather than an intent.
            password: Raw password. ``None`` creates an unusable account, which
                is the correct state for a new hire until the Owner sets one.
            email: Optional; Barkot logs in by username.
            **extra_fields: Passed through to the model.

        Returns:
            The created user.
        """
        if not role:
            raise ValueError("A role is required when creating a staff user.")
        if not role.is_staff_role:
            raise ValueError(f"Role {role.code} is not permitted to log in.")
        if not username:
            raise ValueError("A username is required.")

        extra_fields.setdefault("is_staff", True)
        user = self.model(
            username=username, role=role, email=self.normalize_email(email), **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractUser):
    """BARKOT staff user (spec §9.1).

    Session-authenticated. There is no token issuance and no JWT: the browser
    client uses secure HttpOnly cookies, so a stolen localStorage token — the
    usual failure mode of token-in-browser auth — cannot happen here.
    """

    role = models.ForeignKey(
        Role,
        verbose_name=_("role"),
        related_name="users",
        on_delete=models.PROTECT,
        help_text=_("Exactly one business role (spec §9.2). Required."),
    )
    phone_number = models.CharField(_("phone number"), max_length=32, blank=True)
    is_temporary_password = models.BooleanField(
        _("is temporary password"),
        default=False,
        help_text=_("The Owner must reset the password before normal operation."),
    )
    last_login_ip = models.GenericIPAddressField(_("last login IP"), null=True, blank=True)

    # `UserManager` already binds its model parameter through
    # `DjangoUserManager["User"]`, so it is a plain (non-generic) subclass here
    # that is assignable to the `UserManager[User]` slot `AbstractUser` declares.
    objects: ClassVar[UserManager] = UserManager()

    class Meta:
        # AbstractUser.Meta carries `swappable = "AUTH_USER_MODEL"`, which must be
        # repeated here for the swapped-in user to register correctly. The parent
        # also sets abstract=False, which is already the default for a concrete
        # model, so listing the options explicitly is equivalent and keeps the
        # lazy translation strings type-clean.
        swappable = "AUTH_USER_MODEL"
        verbose_name = _("user")
        verbose_name_plural = _("users")
        permissions = (("manage_users", "Can manage staff users and roles"),)

    def __str__(self) -> str:
        return self.get_username()

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Ensure the active flag and staff flag agree with the role.

        Django's ``is_staff`` gates admin access and ``is_active`` gates login.
        A service identity must be able to authenticate without being able to
        log in, so the two are reconciled from the role rather than left as two
        independent booleans that can drift.
        """
        super().save(*args, **kwargs)
        if self.is_staff and not self.is_active:
            self.is_active = True
            super().save(update_fields=["is_active"])

    @property
    def display_name(self) -> str:
        """Best available human label for this user."""
        full_name = self.get_full_name().strip()
        return full_name or self.get_username()

    def has_role(self, *codes: str) -> bool:
        """Whether this user's role code is one of ``codes``.

        Convenience for *display* decisions only (which menu section to show).
        Authorization must still go through :meth:`has_perm` (P06).
        """
        if self.role_id is None:
            return False
        return self.role.code in codes


class SiteSetting(models.Model):
    """Singleton holding Owner-managed system settings (spec §9.2, §20.2).

    A one-row table rather than loose environment variables, because the Owner
    changes these through the UI at runtime: an expired staff password, a
    shorter session timeout after a suspected compromise. Only a handful of
    values genuinely need runtime control, so this is deliberately not a
    general key/value settings store.

    Exactly one row may exist (:attr:`singleton_key`), enforced by a unique
    constraint rather than an ``if not exists`` check that two concurrent
    requests could both pass.
    """

    SINGLETON_KEY = 1

    singleton_key = models.PositiveSmallIntegerField(
        _("singleton key"),
        primary_key=True,
        default=SINGLETON_KEY,
        editable=False,
        help_text=_("Fixed to 1. Guarantees a single settings row exists."),
    )
    session_timeout_minutes = models.PositiveIntegerField(
        _("session timeout (minutes)"),
        default=480,
        help_text=_("Idle timeout after which a staff session must log in again."),
    )
    password_max_age_days = models.PositiveIntegerField(
        _("password max age (days)"),
        default=0,
        help_text=_("0 means passwords do not expire by age."),
    )
    require_password_change_for_new_users = models.BooleanField(
        _("require password change for new users"),
        default=True,
    )
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)
    updated_by = models.ForeignKey(
        "accounts.User",
        verbose_name=_("updated by"),
        related_name="site_setting_updates",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("site setting")
        verbose_name_plural = _("site settings")
        permissions = (("manage_settings", "Can manage system settings"),)

    def __str__(self) -> str:
        return "Site settings"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Force the singleton key so a stray copy cannot be created."""
        self.singleton_key = self.SINGLETON_KEY
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> SiteSetting:
        """Return the settings row, creating it on first access."""
        obj, _ = cls.objects.get_or_create(pk=cls.SINGLETON_KEY)
        return obj


__all__ = ["PermissionsMixin", "Role", "SiteSetting", "User", "UserManager"]
