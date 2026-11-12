"""A8: the shipped DRF permission classes, and the gate they enforce.

Two failure modes this file exists to catch:

1. A permission in :data:`ROLE_MATRIX` with no permission class. The capability is in
   the catalogue, so it looks available, but no view can require it, so it is silently
   unreachable. Nothing else in the suite would notice.
2. A permission class whose verdict disagrees with the matrix. ``HasRolePermission``
   asks ``has_perm``, which reads the seeded grants, so this holds by construction -
   but the whole safety argument rests on that one link, and a future change that read
   the matrix directly, or added a shortcut for the Owner, would break it with no other
   test failing. Hence the full cross-product below rather than spot checks.

The end-to-end tests go through real middleware and a real session via
``tests.api.urls_for_tests``, which routes through the shipped
``CanApprovePayrollRun`` rather than a stand-in.

Written after probing actual behaviour, which corrected three assumptions:

- An inactive user's request is refused as **401 by the authenticator**, not 403 by a
  permission class, because ``RolePermissionBackend`` grants them nothing and
  ``BarketSessionAuthentication`` refuses them first. Tested here as the 401 it is.
- A **roleless** user, and a user whose role row was deleted, cannot be stored at all:
  ``User.role`` is ``null=False`` with ``on_delete=PROTECT``. Testing them would mean
  mocking the model into a state the schema forbids, so they are not tested here.
- The 403 body **never names the missing permission** - ``apps.core.exceptions`` maps
  every ``PermissionDenied`` to one fixed string. Pinned below, because it is a
  deliberate non-disclosure property and not an oversight.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import override_settings
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.accounts.models import Role, User
from apps.accounts.permissions import (
    ALL_PERMISSIONS,
    PERMISSION_CLASSES,
    ROLE_MATRIX,
    CanApprovePayrollRun,
    CanGeneratePayrollRun,
    HasRolePermission,
)
from apps.accounts.role_seeding import seed_roles

if TYPE_CHECKING:
    from collections.abc import Callable

TEST_URLS = "tests.api.urls_for_tests"
APPROVE_PAYROLL_ROUTE = "/api/v1/payroll/approve/"


def _request_for(factory: APIRequestFactory, user: Any) -> Request:
    """Return a request carrying ``user``, for calling ``has_permission`` directly."""
    request = Request(factory.get("/api/v1/probe/"))
    request.user = user
    return request


# ── Catalogue <-> class coverage ────────────────────────────────────────────────
# Without this, a permission could be added to ALL_PERMISSIONS and the matrix and ship
# with no class and no failing test.


def test_every_catalogued_permission_has_a_permission_class() -> None:
    """Each capability a role can hold has a class a view can require."""
    unclassed = sorted(set(ALL_PERMISSIONS) - set(PERMISSION_CLASSES))
    assert not unclassed, f"Permissions with no DRF class to require: {unclassed}"


def test_no_class_requires_an_uncatalogued_permission() -> None:
    """A class naming something outside the catalogue could never be granted."""
    stray = sorted(set(PERMISSION_CLASSES) - set(ALL_PERMISSIONS))
    assert not stray, f"Permission classes require uncatalogued permissions: {stray}"


def test_every_class_is_registered() -> None:
    """A class defined but not registered would be invisible to the checks above."""
    exported = {
        obj
        for obj in vars().values()
        if isinstance(obj, type)
        and issubclass(obj, HasRolePermission)
        and obj is not HasRolePermission
    }
    missing = sorted(cls.__name__ for cls in exported - set(PERMISSION_CLASSES.values()))
    assert not missing, f"Permission classes not in PERMISSION_CLASSES: {missing}"


@pytest.mark.django_db
def test_the_base_class_denies_everything() -> None:
    """An unset ``required_permission`` must fail closed, not open.

    The base class is not abstract in practice - nothing stops a view listing it by
    mistake - so it has to deny. Uses the Owner, the one role holding every permission,
    so the only thing that can produce True is the empty codename being granted.
    """
    factory = APIRequestFactory()
    owner = _user_with(Role.Code.OWNER)
    assert HasRolePermission().has_permission(_request_for(factory, owner), None) is False


# ── The classes agree with the matrix ───────────────────────────────────────────


@pytest.mark.parametrize("code", sorted(ROLE_MATRIX))
@pytest.mark.parametrize("permission", ALL_PERMISSIONS)
@pytest.mark.django_db
def test_permission_classes_agree_with_the_matrix(
    make_staff_user: Callable[..., Any],
    code: str,
    permission: str,
) -> None:
    """The full cross-product: class verdict equals matrix grant, for every pair.

    Parametrised over all four roles times all 27 permissions, 108 cases. That is a lot
    of output for one failure, and that is the point: a spot check would leave most of
    the matrix unverified, and the argument for ``has_perm`` being the single decision
    point is only worth something if it holds everywhere.
    """
    user = make_staff_user(code, suffix=permission.replace(".", "-"))
    permission_class = PERMISSION_CLASSES[permission]
    factory = APIRequestFactory()

    from_matrix = permission in ROLE_MATRIX[code]
    from_class = permission_class().has_permission(_request_for(factory, user), None)

    assert from_class is from_matrix, (
        f"{code} {permission}: matrix says {from_matrix}, class says {from_class}"
    )


def test_only_the_owner_can_approve_payroll() -> None:
    """The A8 gate, stated in the matrix itself."""
    holders = sorted(code for code, perms in ROLE_MATRIX.items() if "payroll.approve_run" in perms)
    assert holders == [Role.Code.OWNER]


def test_only_the_owner_can_generate_or_approve_a_run() -> None:
    """Worth naming separately: the one place the matrix encodes separation of duties.

    The gradient elsewhere is "more capabilities as you go up". Payroll runs are
    withheld from everyone but the Owner, so the person who reads the figures is
    also the only one who can produce and sign them off — the A8 split is what
    keeps both grants out of a Manager's reach at once. Dropping either grant
    from the Owner, or handing generation back to a Manager, would be the single
    most damaging plausible edit to the matrix, so both are pinned directly.
    """
    generators = sorted(
        code for code, perms in ROLE_MATRIX.items() if "payroll.generate_run" in perms
    )
    assert generators == [Role.Code.OWNER]
    assert "payroll.generate_run" not in ROLE_MATRIX[Role.Code.MANAGER]
    assert "payroll.approve_run" not in ROLE_MATRIX[Role.Code.MANAGER]


@pytest.mark.django_db
def test_the_owner_only_split_holds_through_the_classes_too() -> None:
    """The separation survives the trip through ``has_perm``, not just in the data."""
    owner = _user_with(Role.Code.OWNER)
    manager = _user_with(Role.Code.MANAGER)
    factory = APIRequestFactory()

    assert CanGeneratePayrollRun().has_permission(_request_for(factory, owner), None) is True
    assert CanApprovePayrollRun().has_permission(_request_for(factory, owner), None) is True
    assert CanGeneratePayrollRun().has_permission(_request_for(factory, manager), None) is False
    assert CanApprovePayrollRun().has_permission(_request_for(factory, manager), None) is False


# ── Signed out ──────────────────────────────────────────────────────────────────


def test_an_anonymous_request_is_refused() -> None:
    """No session means no permission, whatever the route asks for."""
    factory = APIRequestFactory()
    request = _request_for(factory, AnonymousUser())
    assert CanApprovePayrollRun().has_permission(request, None) is False


# ── 401 versus 403, over real HTTP ──────────────────────────────────────────────


@override_settings(ROOT_URLCONF=TEST_URLS)
def test_signed_out_is_401_not_403(client) -> None:
    """``IsAuthenticated`` answers first, so the client knows to send the user to login.

    A 403 here would tell the frontend the session is fine and merely unauthorised, and
    the frontend would have no way to recover. ``IsAuthenticated`` is listed before the
    permission class in ``permission_classes``, and DRF evaluates in order.
    """
    response = client.get(APPROVE_PAYROLL_ROUTE)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=TEST_URLS)
@pytest.mark.parametrize(
    "code",
    [Role.Code.BARMAN, Role.Code.CASHIER, Role.Code.MANAGER],
    ids=["barman", "cashier", "manager"],
)
def test_no_role_below_owner_can_approve_payroll(client, staff_login, code: str) -> None:
    """The A8 gate over real HTTP: BarMan, Cashier and Manager are all refused.

    Manager is the case that matters. BarMan and Cashier lack the grant outright;
    Manager has legitimate payroll access — reads and deductions — but both run
    grants are withheld. A test using only a Cashier would not have covered that,
    and would have passed even if the separation of duties had quietly been
    dropped from the matrix.
    """
    staff_login(client, code)

    response = client.get(APPROVE_PAYROLL_ROUTE)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=TEST_URLS)
def test_the_owner_can_approve_payroll(client, staff_login) -> None:
    """The other direction, so the 403 above cannot pass by refusing everyone."""
    staff_login(client, Role.Code.OWNER)

    response = client.get(APPROVE_PAYROLL_ROUTE)

    assert response.status_code == 200
    assert response.json() == {"reached": "protected"}


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=TEST_URLS)
def test_the_refusal_does_not_reveal_which_permission_was_missing(client, staff_login) -> None:
    """The 403 body is a fixed string, naming nothing.

    Deliberate: a refusal that said "you need payroll.approve_run" would hand a Cashier
    a map of the grants they lack. Pinned so a future attempt to add a helpful message
    is a deliberate, visible change rather than an accident.
    """
    staff_login(client, Role.Code.MANAGER)

    response = client.get(APPROVE_PAYROLL_ROUTE)

    assert response.status_code == 403
    assert b"payroll.approve_run" not in response.content
    assert response.json()["error"]["message"] == "You do not have permission to do that."


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=TEST_URLS)
def test_a_deactivated_session_is_revoked_on_the_next_request(client, staff_login) -> None:
    """Suspension takes effect at once, not at the next sign-in.

    An Owner with a live session is deactivated in the database; the next request must
    be refused even though the cookie is still valid. The answer is 401, from
    ``BarketSessionAuthentication`` and the empty permission set an inactive user gets,
    rather than 403 from the permission class - which is the correct distinction, since
    the session is no longer a valid session.
    """
    user = staff_login(client, Role.Code.OWNER)
    User.objects.filter(pk=user.pk).update(is_active=False)

    response = client.get(APPROVE_PAYROLL_ROUTE)

    assert response.status_code == 401


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _user_with(code: str, **extra: Any) -> User:
    """Return a persisted user holding the given role."""
    seed_roles()
    return User.objects.create_user(
        username=f"a8-{code.lower()}",
        password="pw",
        role=Role.objects.get(code=code),
        **extra,
    )
