"""Domain services for account administration (roadmap C5).

The Owner-facing admin surface - create a staff account, choose its role,
deactivate a colleague who leaves, adjust system settings - goes through
exactly three entry points, mirroring the view/URL trio in
:mod:`apps.accounts.admin_views`. The guards live here rather than in the
views, under the same one-transaction-plus-audit-record convention every
domain service follows (each write is a single ``atomic`` block ending in
:meth:`apps.audit.models.AuditLog.record`).

The rules worth stating:

* **One staff role each.** :meth:`apps.accounts.models.UserManager.create_staff_user`
  is the only supported onboarding path, so creation reuses it and refuses a
  service identity (``is_staff_role=False``), which cannot log in anyway.
* **Deactivation must flip both flags.** ``User.save`` reconciles ``is_active``
  with ``is_staff`` by forcing an active staff user active, so telling a user
  "inactive" while leaving ``is_staff`` true would be silently reversed by the
  very save that records the change. Deactivating sets both to false together.
* **You cannot lock yourself out.** An Owner may change any staff account except
  their own role and their own active flag; there is no "take it back" button if
  the only Owner strips their own access.
* **No deletion.** Accounts are deactivated, never removed, so the audit trail's
  references keep resolving to a real row.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.accounts.models import Role, SiteSetting, User
from apps.audit.models import AuditLog
from apps.core.exceptions import BARKOTDomainError

#: The stringly-typed object label the audit log uses for staff accounts.
AUTH_OBJECT_TYPE = "accounts.User"
#: ...and for the singleton settings row.
SETTINGS_OBJECT_TYPE = "accounts.SiteSetting"


def _require_staff_role(role: Role) -> None:
    """Refuse granting a service identity to a login-enabled account.

    Args:
        role: The role being granted.

    Raises:
        BARKOTDomainError: If the role is not permitted to log in.
    """
    if not role.is_staff_role:
        raise BARKOTDomainError(
            f"Role {role.code} is a service identity and cannot log in.",
            code="non_staff_role",
        )


def _snapshot(user: User) -> dict[str, Any]:
    """Return the user's administrable fields, for audit before/after images.

    Args:
        user: The user to read. The ``role`` relation must be loaded.

    Returns:
        A JSON-serialisable snapshot of the fields the Owner can change.
    """
    return {
        "username": user.username,
        "email": user.email,
        "phone_number": user.phone_number,
        "role": user.role.code,
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "is_temporary_password": user.is_temporary_password,
    }


@transaction.atomic
def create_user(
    *,
    actor: User | None,
    username: str,
    role: Role,
    email: str = "",
    phone_number: str = "",
    password: str | None = None,
) -> User:
    """Create a staff account (C5).

    ``password=None`` produces an unusable (locked) account; the Owner sets an
    initial password later. Otherwise the account is flagged
    ``is_temporary_password`` so the new hire must set their own on first
    sign-in (spec §9.3).

    Args:
        actor: The Owner performing the creation, recorded in the audit log.
        username: Unique login name.
        role: The single business role to grant. Must be a staff role.
        email: Optional contact address; Barkot signs staff in by username.
        phone_number: Optional contact number.
        password: Optional initial password.

    Returns:
        The created user.

    Raises:
        BARKOTDomainError: If ``role`` is not a staff role, or
            ``UserManager.create_staff_user`` refuses the request.
    """
    _require_staff_role(role)
    # create_staff_user raises ValueError for a role or username it will not
    # accept; surfacing that as a bare 500 would hide a data-entry mistake.
    try:
        user = User.objects.create_staff_user(
            username=username,
            role=role,
            password=password,
            email=email,
            phone_number=phone_number,
            is_temporary_password=password is not None,
        )
    except ValueError as exc:
        raise BARKOTDomainError(str(exc), code="invalid_staff_user") from exc

    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type=AUTH_OBJECT_TYPE,
        object_id=user.pk,
        actor=actor,
        summary=f"Created {role.code} account {user.username}.",
        after=_snapshot(user),
    )
    return user


@transaction.atomic
def update_user(
    *,
    actor: User | None,
    user: User,
    email: str | None = None,
    phone_number: str | None = None,
    role: Role | None = None,
    is_active: bool | None = None,
) -> User:
    """Update a staff account (C5).

    Only the supplied fields change. Resubmitting the current values is not an
    error: the row is left untouched and no audit entry is written.

    Args:
        actor: The Owner performing the update, recorded in the audit log.
        user: The account to update.
        email: Replacement contact address, or the empty string to clear it.
        phone_number: Replacement contact number, or the empty string to clear it.
        role: A different business role, or None to keep the current one.
        is_active: False deactivates the account (also clears ``is_staff``);
            True re-activates it (also sets ``is_staff``).

    Returns:
        The updated user.

    Raises:
        BARKOTDomainError: If the actor changes their own role or their own
            active flag, or a non-staff role is assigned.
    """
    if role is not None:
        _require_staff_role(role)
    if actor is not None and user.pk == actor.pk:
        if role is not None and role.pk != user.role_id:
            raise BARKOTDomainError(
                "You cannot change your own role; an Owner who does could lock everyone out.",
                code="cannot_change_own_role",
            )
        if is_active is not None:
            raise BARKOTDomainError(
                "You cannot deactivate your own account.",
                code="cannot_change_own_active",
            )

    before = _snapshot(user)
    changed: list[str] = []
    if email is not None and email != user.email:
        user.email = email
        changed.append("email")
    if phone_number is not None and phone_number != user.phone_number:
        user.phone_number = phone_number
        changed.append("phone_number")
    if role is not None and role.pk != user.role_id:
        user.role = role
        changed.append("role")
    if is_active is not None and bool(is_active) != user.is_active:
        user.is_active = bool(is_active)
        user.is_staff = bool(is_active)
        changed.extend(["is_active", "is_staff"])

    if not changed:
        return user

    user.save(update_fields=changed)
    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type=AUTH_OBJECT_TYPE,
        object_id=user.pk,
        actor=actor,
        summary=f"Updated {user.role.code} account {user.username}.",
        before=before,
        after=_snapshot(user),
    )
    return user


def _snapshot_settings(settings: SiteSetting) -> dict[str, Any]:
    """Return the administrable settings values, for audit before/after images.

    Args:
        settings: The settings row.

    Returns:
        A JSON-serialisable snapshot of the Owner-editable fields.
    """
    return {
        "session_timeout_minutes": settings.session_timeout_minutes,
        "password_max_age_days": settings.password_max_age_days,
        "require_password_change_for_new_users": settings.require_password_change_for_new_users,
    }


@transaction.atomic
def update_site_settings(*, actor: User | None, values: dict[str, Any]) -> SiteSetting:
    """Apply Owner-chosen system settings (C5, spec §20.2).

    Args:
        actor: The Owner, recorded as ``updated_by`` and in the audit log.
        values: The subset of settings fields to change, already validated.

    Returns:
        The settings row. Unchanged (no write, no audit entry) if every supplied
        value already matched.
    """
    settings = SiteSetting.load()
    changed = [name for name, value in values.items() if getattr(settings, name) != value]
    if not changed:
        return settings

    before = _snapshot_settings(settings)
    for name in changed:
        setattr(settings, name, values[name])
    settings.updated_by = actor
    settings.save(update_fields=[*changed, "updated_by", "updated_at"])
    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type=SETTINGS_OBJECT_TYPE,
        object_id=settings.singleton_key,
        actor=actor,
        summary="System settings updated.",
        before=before,
        after=_snapshot_settings(settings),
    )
    return settings
