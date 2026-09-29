"""Seeding of the role → permission matrix (spec §9.2).

The matrix in :mod:`apps.accounts.permissions` is the single source of truth for
what each role may do. This module applies it to the database.

Seeding is wired to Django's ``post_migrate`` signal rather than a data migration
because ``auth.Permission`` rows are themselves created in a ``post_migrate``
receiver. A data migration runs *before* that, so it would find no permissions
to grant, create four empty roles, and deny every staff member everything with no
error to explain it.

``apps.accounts`` is listed after ``django.contrib.auth`` in ``INSTALLED_APPS``,
so this receiver is connected later and Django therefore runs it after
``create_permissions``. That ordering is load-bearing: reversing the two entries
in ``INSTALLED_APPS`` would silently produce empty roles again.

:func:`seed_roles` is idempotent, so re-running ``migrate`` or the
``bootstrap_roles`` command after changing the matrix is safe.
"""

from __future__ import annotations

from typing import Any

from django.apps import apps
from django.db import transaction

from apps.accounts.permissions import (
    ALL_PERMISSIONS,
    ROLE_DESCRIPTIONS,
    ROLE_MATRIX,
    filter_existing,
)


def resolve_permissions() -> dict[str, Any]:
    """Map each ``"app.codename"`` in the matrix to its ``Permission`` row.

    Returns:
        A mapping of permission name to ``Permission``. Permissions named in the
        matrix but absent from the database are simply missing from the result;
        :func:`check_roles` is what turns that into a loud failure.

    Raises:
        RuntimeError: If called before the model registry is ready.
    """
    role_model = apps.get_model("accounts", "Role")
    if role_model is None:  # pragma: no cover - defensive
        raise RuntimeError("The accounts.Role model is not available yet.")
    return {
        f"{perm.content_type.app_label}.{perm.codename}": perm
        for perm in filter_existing(ALL_PERMISSIONS)
    }


@transaction.atomic
def seed_roles() -> None:
    """Create the roles and grant them their matrix permissions.

    Safe to call repeatedly: roles are matched by code and their grants are
    replaced wholesale, so removing a permission from the matrix actually revokes
    it rather than leaving a stale grant behind.
    """
    role_model = apps.get_model("accounts", "Role")
    if role_model is None:  # pragma: no cover - defensive
        return

    permissions = resolve_permissions()
    for code, codenames in ROLE_MATRIX.items():
        label = str(role_model.Code(code).label)
        role, _ = role_model.objects.get_or_create(
            code=code,
            defaults={"name": label, "description": ROLE_DESCRIPTIONS.get(code, "")},
        )
        if role.name != label:
            role.name = label
            role.save(update_fields=["name"])
        role.permissions_granted.set([
            permissions[name] for name in codenames if name in permissions
        ])


def check_roles() -> list[str]:
    """Return a list of ways the database disagrees with the matrix.

    An empty list means the seeded state matches
    :data:`apps.accounts.permissions.ROLE_MATRIX`.
    """
    role_model = apps.get_model("accounts", "Role")
    problems: list[str] = []
    if role_model is None:  # pragma: no cover - defensive
        return ["the accounts.Role model is not available"]

    permissions = resolve_permissions()
    for code, codenames in ROLE_MATRIX.items():
        try:
            role = role_model.objects.get(code=code)
        except role_model.DoesNotExist:
            problems.append(f"role {code} is missing")
            continue

        expected = {name for name in codenames if name in permissions}
        actual = {
            f"{perm.content_type.app_label}.{perm.codename}"
            for perm in role.permissions_granted.select_related("content_type")
        }
        for name in sorted(expected - actual):
            problems.append(f"role {code} is missing: {name}")
        for name in sorted(actual - expected):
            problems.append(f"role {code} has unexpected: {name}")

    for name in ALL_PERMISSIONS:
        if name not in permissions:
            app_label, codename = name.split(".", 1)
            problems.append(f"permission {app_label}.{codename} does not exist")

    return problems
