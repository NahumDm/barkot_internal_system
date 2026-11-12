"""Permission-matrix consistency tests (spec §9.2).

The role matrix is declared as data in :mod:`apps.accounts.permissions`. The
failure mode that matters is a permission that exists in one place and not the
other: the capability is either ungrantable (nobody can ever be given it) or
fails seeding outright. These tests make that a build failure rather than a
discovery at 2am.
"""

from __future__ import annotations

import pytest
from django.apps import apps as global_apps
from django.contrib.auth.models import Permission

from apps.accounts.models import Role, RoleManager, User
from apps.accounts.permissions import (
    ALL_PERMISSIONS,
    ROLE_MATRIX,
    filter_existing,
    split_permission,
)


def _declared_custom_permissions() -> set[str]:
    """Return every ``"app_label.codename"`` declared in a ``Meta.permissions``."""
    declared: set[str] = set()
    for config in global_apps.get_app_configs():
        for model in config.get_models():
            meta = model._meta
            for codename, _ in getattr(meta, "permissions", ()):
                declared.add(f"{meta.app_label}.{codename}")
    return declared


def test_every_matrix_permission_is_declared_by_a_model():
    """A matrix entry with no ``Meta.permissions`` can never be granted."""
    undeclared = sorted(set(ALL_PERMISSIONS) - _declared_custom_permissions())
    assert not undeclared, f"Matrix names permissions no model declares: {undeclared}"


def test_every_declared_permission_is_in_the_catalogue():
    """A declared permission missing from the catalogue is ungrantable to anyone."""
    orphaned = sorted(_declared_custom_permissions() - set(ALL_PERMISSIONS))
    assert not orphaned, f"Models declare permissions the catalogue omits: {orphaned}"


def test_no_duplicate_permissions_in_catalogue():
    duplicates = sorted({p for p in ALL_PERMISSIONS if ALL_PERMISSIONS.count(p) > 1})
    assert not duplicates, f"Duplicate entries in the catalogue: {duplicates}"


def test_every_role_permission_is_in_the_catalogue():
    """A role must not grant something the catalogue does not define."""
    stray = sorted({
        f"{code}: {perm}"
        for code, perms in ROLE_MATRIX.items()
        for perm in perms
        if perm not in ALL_PERMISSIONS
    })
    assert not stray, f"Roles reference uncatalogued permissions: {stray}"


def test_owner_role_holds_the_whole_catalogue():
    """The Owner is the fallback: any catalogue entry it lacks is a dead capability."""
    missing = sorted(set(ALL_PERMISSIONS) - set(ROLE_MATRIX[Role.Code.OWNER]))
    assert not missing, f"Owner is missing: {missing}"


def test_lower_roles_are_strict_subsets_of_the_owner():
    """No role may exceed the Owner, who is defined as full access."""
    owner = set(ROLE_MATRIX[Role.Code.OWNER])
    for code, perms in ROLE_MATRIX.items():
        if code == Role.Code.OWNER:
            continue
        extra = sorted(set(perms) - owner)
        assert not extra, f"{code} grants beyond the Owner: {extra}"


@pytest.mark.parametrize("bad", ["", "nodot", ".leading", "trailing."])
def test_split_permission_rejects_malformed_names(bad: str):
    """The parser the matrix depends on refuses anything not ``app.codename``."""
    with pytest.raises(ValueError):
        split_permission(bad)


@pytest.mark.parametrize("code", sorted(ROLE_MATRIX))
def test_every_matrix_permission_round_trips_through_the_parser(code: str):
    """Each entry must survive the split the seeding path performs on it."""
    for permission in ROLE_MATRIX[code]:
        app_label, codename = split_permission(permission)
        assert app_label and codename
        assert f"{app_label}.{codename}" == permission


@pytest.mark.django_db
def test_seeded_roles_match_the_matrix():
    """The database agrees with the declared matrix after seeding."""
    permissions = {
        f"{p.content_type.app_label}.{p.codename}" for p in filter_existing(ALL_PERMISSIONS)
    }
    assert len(permissions) == len(ALL_PERMISSIONS), (
        "Some catalogue permissions do not exist in the database; run migrate and bootstrap_roles."
    )

    for code, perms in ROLE_MATRIX.items():
        role = Role.objects.get(code=code)
        actual = {
            f"{p.content_type.app_label}.{p.codename}"
            for p in role.permissions_granted.select_related("content_type")
        }
        assert actual == {p for p in perms if p in permissions}, f"{code} grants drifted"


@pytest.mark.django_db
def test_managers_can_manage_reference_data_they_own():
    """The permissions added to the catalogue are reachable by the intended role."""
    manager = User.objects.create_user(
        username="matrix-manager", password="pw", role=Role.objects.get(code=Role.Code.MANAGER)
    )
    assert manager.has_perm("finance.manage_expense_categories") is True
    # The employee register is the Manager's (spec §5), but payroll's roster is
    # not: ``payroll.manage_payroll_employees`` is what feeds
    # ``POST /payroll/employees/``, and payroll is Owner-only (spec §9.2).
    assert manager.has_perm("users.manage_employees") is True
    assert manager.has_perm("payroll.manage_payroll_employees") is False


@pytest.mark.django_db
def test_shopfloor_roles_cannot_manage_reference_data():
    """Granting reference-data management to shopfloor roles would be privilege creep."""
    for code in (Role.Code.BARMAN, Role.Code.CASHIER):
        user = User.objects.create_user(
            username=f"matrix-{code.lower()}", password="pw", role=Role.objects.get(code=code)
        )
        assert user.has_perm("finance.manage_expense_categories") is False
        assert user.has_perm("payroll.manage_payroll_employees") is False


@pytest.mark.django_db
def test_permission_catalogue_has_no_orphans_in_the_database():
    """Every catalogue entry resolves to a real Permission row."""
    found = Permission.objects.filter(
        codename__in=[split_permission(p)[1] for p in ALL_PERMISSIONS]
    )
    assert found.count() >= len(ALL_PERMISSIONS)


class TestRoleManagerIsUsable:
    """``Role.objects`` must actually expose ``RoleQuerySet``'s methods.

    Assigning a QuerySet *instance* to ``objects`` (``objects =
    RoleQuerySet()``) does not build a manager from it: Django falls back to a
    plain ``Manager`` over bare ``QuerySet``, so every custom method is silently
    unreachable and ``Role.objects.for_code(...)`` raises ``AttributeError``.
    Nothing else in the suite called that method, so the breakage stayed
    invisible until ``create_owner`` needed it. Asserted here so it cannot
    regress unnoticed again.
    """

    def test_objects_is_the_derived_manager(self) -> None:
        """The fix is ``as_manager()``, which produces ``RoleManager``."""
        assert isinstance(Role.objects, RoleManager)

    def test_custom_queryset_methods_reach_the_manager(self) -> None:
        """``for_code`` is the call site that broke, so it is the one to pin."""
        assert hasattr(Role.objects, "for_code")

    @pytest.mark.django_db
    def test_for_code_resolves_a_seeded_role(self) -> None:
        """End to end: the method callers rely on actually returns the role."""
        assert Role.objects.for_code(Role.Code.OWNER).code == Role.Code.OWNER

    @pytest.mark.django_db
    def test_for_code_raises_for_an_unknown_code(self) -> None:
        """A missing role must surface as ``DoesNotExist``, not ``AttributeError``."""
        with pytest.raises(Role.DoesNotExist):
            Role.objects.for_code("NOT_A_ROLE")
