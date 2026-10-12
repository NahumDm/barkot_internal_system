"""C5 account-administration API acceptance tests.

The behaviour under test is the Owner-only admin surface: an anonymous caller
is challenged on every endpoint, a Manager is refused on all of them, and the
Owner can create staff accounts, change their role and active state, and patch
the system settings.

The Manager-refusal tests assert *no side effects*: a refused create leaves the
user table and the audit log exactly as they were, so the guard is not merely
"respond 403" but "respond 403 and change nothing".

Unsafe requests carry a real CSRF token fetched from ``/auth/csrf/``, because
session auth enforces CSRF on every unsafe method (spec §9.1, P09) and a test
would otherwise be measuring the CSRF refusal rather than the permission one.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog

pytestmark = pytest.mark.django_db

CSRF_URL = "/api/v1/auth/csrf/"
USERS_URL = "/api/v1/users/"
ROLES_URL = "/api/v1/roles/"
SETTINGS_URL = "/api/v1/settings/"


def csrf_for(client: Client) -> str:
    """Obtain a CSRF token the way the frontend does, cookie included."""
    return client.get(CSRF_URL).json()["token"]


def post_json(client: Client, url: str, payload: dict[str, Any]) -> Any:
    """POST a JSON body with a valid CSRF token."""
    return client.post(
        url,
        data=payload,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_for(client),
    )


def patch_json(client: Client, url: str, payload: dict[str, Any]) -> Any:
    """PATCH a JSON body with a valid CSRF token."""
    return client.patch(
        url,
        data=payload,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_for(client),
    )


def user_count() -> int:
    """Number of staff accounts, for no-side-effect assertions."""
    return User.objects.count()


def audit_count() -> int:
    """Number of audit entries, for no-side-effect assertions."""
    return AuditLog.objects.count()


# ── Anonymous ──────────────────────────────────────────────────────────────────


def test_anonymous_is_challenged_on_every_admin_endpoint(client: Client) -> None:
    """No session means a 401 before any admin view runs (signed out ≠ forbidden)."""
    assert client.get(USERS_URL).status_code == 401
    assert client.get(f"{USERS_URL}1/").status_code == 401
    assert client.get(ROLES_URL).status_code == 401
    assert client.get(SETTINGS_URL).status_code == 401
    assert post_json(client, USERS_URL, {"username": "x", "role": "OWNER"}).status_code == 401
    assert patch_json(client, f"{USERS_URL}1/", {"is_active": False}).status_code == 401
    assert patch_json(client, SETTINGS_URL, {"session_timeout_minutes": 60}).status_code == 401


# ── Manager refused ─────────────────────────────────────────────────────────────


def test_manager_is_refused_everywhere_without_side_effects(
    client: Client, staff_login: Callable[..., Any]
) -> None:
    """The C5 gate: a Manager holds no ``accounts.*`` grant, and a refusal changes nothing."""
    staff_login(client, Role.Code.MANAGER)
    before_users = user_count()
    before_audit = audit_count()

    assert client.get(USERS_URL).status_code == 403
    assert client.get(ROLES_URL).status_code == 403
    assert client.get(SETTINGS_URL).status_code == 403
    assert (
        post_json(client, USERS_URL, {"username": "sneaky", "role": "CASHIER"}).status_code == 403
    )
    assert patch_json(client, SETTINGS_URL, {"password_max_age_days": 1}).status_code == 403

    assert user_count() == before_users
    assert audit_count() == before_audit


# ── Users: reads ────────────────────────────────────────────────────────────────


def test_owner_lists_users_with_pagination_envelope(
    client: Client, staff_login: Callable[..., Any], make_staff_user: Callable[..., Any]
) -> None:
    """The list is the standard paginated envelope, ordered and role-labelled."""
    owner = staff_login(client, Role.Code.OWNER)
    make_staff_user(Role.Code.BARMAN)
    make_staff_user(Role.Code.CASHIER)

    response = client.get(USERS_URL)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"count", "page_size", "page", "pages", "results"}
    assert body["count"] == 3
    row = next(row for row in body["results"] if row["username"] == owner.username)
    assert row["role"] == "OWNER"
    assert row["is_active"] is True


def test_owner_filters_the_user_list(
    client: Client, staff_login: Callable[..., Any], make_staff_user: Callable[..., Any]
) -> None:
    """``role``, ``active`` and ``search`` narrow the list."""
    staff_login(client, Role.Code.OWNER)
    barman = make_staff_user(Role.Code.BARMAN, suffix="2")
    make_staff_user(Role.Code.CASHIER)

    by_role = client.get(USERS_URL, {"role": "BARMAN"}).json()
    assert by_role["count"] == 1
    assert by_role["results"][0]["username"] == barman.username

    by_active = client.get(USERS_URL, {"active": "true"}).json()
    assert by_active["results"]
    assert all(row["is_active"] for row in by_active["results"])

    by_search = client.get(USERS_URL, {"search": "barman"}).json()
    assert by_search["count"] == 1


# ── Users: create ───────────────────────────────────────────────────────────────


def test_owner_creates_a_temporary_password_staff_account(
    client: Client, staff_login: Callable[..., Any]
) -> None:
    """Creation sets the password, flags it temporary, and audits the write."""
    owner = staff_login(client, Role.Code.OWNER)

    response = post_json(
        client,
        USERS_URL,
        {
            "username": "hanna",
            "role": "MANAGER",
            "email": "hanna@example.com",
            "password": "Temp-Pass-123!",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "hanna"
    assert body["role"] == "MANAGER"
    assert body["is_temporary_password"] is True

    stored = User.objects.get(username="hanna")
    assert stored.check_password("Temp-Pass-123!")

    entry = AuditLog.objects.get(
        object_type="accounts.User",
        object_id=str(stored.pk),
        action=AuditLog.Action.CREATE,
    )
    assert entry.actor == owner
    assert "Created MANAGER account hanna." in entry.summary


def test_owner_creates_a_locked_account_without_a_password(
    client: Client, staff_login: Callable[..., Any]
) -> None:
    """Omitting the password yields an unusable (locked) account, not a 400."""
    staff_login(client, Role.Code.OWNER)

    response = post_json(client, USERS_URL, {"username": "sam", "role": "BARMAN"})

    assert response.status_code == 201
    stored = User.objects.get(username="sam")
    assert not stored.has_usable_password()
    assert stored.is_temporary_password is False


def test_a_non_staff_role_cannot_be_granted_at_creation(
    client: Client, staff_login: Callable[..., Any]
) -> None:
    """A service identity cannot be granted to a login-enabled account."""
    staff_login(client, Role.Code.OWNER)
    Role.objects.create(code="SVC", name="Service bot", is_staff_role=False)

    response = post_json(client, USERS_URL, {"username": "bot", "role": "SVC"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "non_staff_role"
    assert not User.objects.filter(username="bot").exists()


def test_duplicate_username_is_refused(
    client: Client, staff_login: Callable[..., Any], make_staff_user: Callable[..., Any]
) -> None:
    """A login name already in use is a validation error on ``username``."""
    staff_login(client, Role.Code.OWNER)
    make_staff_user(Role.Code.BARMAN, suffix="2")

    response = post_json(client, USERS_URL, {"username": "barman-2", "role": "CASHIER"})

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "username" in error["details"]


def test_a_second_owner_cannot_be_created(client: Client, staff_login: Callable[..., Any]) -> None:
    """Barkot has exactly one Owner; the API refuses a second with a clear code."""
    staff_login(client, Role.Code.OWNER)
    before = user_count()

    response = post_json(client, USERS_URL, {"username": "owner2", "role": "OWNER"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "owner_exists"
    assert user_count() == before
    assert not User.objects.filter(username="owner2").exists()


# ── Users: update ───────────────────────────────────────────────────────────────


def test_owner_can_change_role_and_contact_fields(
    client: Client, staff_login: Callable[..., Any], make_staff_user: Callable[..., Any]
) -> None:
    """A role change updates the row, the audit snapshot, and the summary."""
    owner = staff_login(client, Role.Code.OWNER)
    barman = make_staff_user(Role.Code.BARMAN, suffix="2")

    response = patch_json(
        client,
        f"{USERS_URL}{barman.pk}/",
        {"role": "CASHIER", "email": "new@example.com"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "CASHIER"
    assert body["email"] == "new@example.com"

    entry = AuditLog.objects.get(
        object_type="accounts.User",
        object_id=str(barman.pk),
        action=AuditLog.Action.UPDATE,
    )
    assert entry.actor == owner
    assert entry.before is not None
    assert entry.after is not None
    assert entry.before["role"] == "BARMAN"
    assert entry.after["role"] == "CASHIER"


def test_a_staff_user_cannot_be_promoted_to_a_second_owner(
    client: Client, staff_login: Callable[..., Any], make_staff_user: Callable[..., Any]
) -> None:
    """Changing a role to OWNER when one exists is refused the same way."""
    staff_login(client, Role.Code.OWNER)
    barman = make_staff_user(Role.Code.BARMAN, suffix="2")

    response = patch_json(client, f"{USERS_URL}{barman.pk}/", {"role": "OWNER"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "owner_exists"
    barman.refresh_from_db()
    assert barman.role.code == Role.Code.BARMAN


def test_the_owner_may_resubmit_their_own_role(
    client: Client, staff_login: Callable[..., Any]
) -> None:
    """Re-submitting OWNER for the Owner is not mistaken for a second Owner."""
    owner = staff_login(client, Role.Code.OWNER)

    response = patch_json(client, f"{USERS_URL}{owner.pk}/", {"role": "OWNER"})

    assert response.status_code == 200
    assert response.json()["role"] == "OWNER"


def test_deactivating_turns_off_both_staff_and_active(
    client: Client, staff_login: Callable[..., Any], make_staff_user: Callable[..., Any]
) -> None:
    """Deactivation sets both flags together, and re-activation restores both."""
    staff_login(client, Role.Code.OWNER)
    barman = make_staff_user(Role.Code.BARMAN, suffix="2")
    url = f"{USERS_URL}{barman.pk}/"

    response = patch_json(client, url, {"is_active": False})

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert response.json()["is_staff"] is False
    barman.refresh_from_db()
    assert barman.is_active is False
    assert barman.is_staff is False

    reverted = patch_json(client, url, {"is_active": True})
    assert reverted.status_code == 200
    assert reverted.json()["is_active"] is True
    assert reverted.json()["is_staff"] is True


def test_owner_cannot_change_their_own_role(
    client: Client, staff_login: Callable[..., Any]
) -> None:
    """Changing your own role would let an Owner lock everyone out."""
    owner = staff_login(client, Role.Code.OWNER)

    response = patch_json(client, f"{USERS_URL}{owner.pk}/", {"role": "CASHIER"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cannot_change_own_role"


def test_owner_cannot_deactivate_themselves(
    client: Client, staff_login: Callable[..., Any]
) -> None:
    """There is no 'take it back' button if the only Owner is deactivated."""
    owner = staff_login(client, Role.Code.OWNER)

    response = patch_json(client, f"{USERS_URL}{owner.pk}/", {"is_active": False})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "cannot_change_own_active"


def test_a_no_op_update_touches_nothing_and_audits_nothing(
    client: Client, staff_login: Callable[..., Any], make_staff_user: Callable[..., Any]
) -> None:
    """Resubmitting current values returns the row without writing an entry."""
    staff_login(client, Role.Code.OWNER)
    barman = make_staff_user(Role.Code.BARMAN, suffix="2")
    before = audit_count()

    response = patch_json(client, f"{USERS_URL}{barman.pk}/", {"email": ""})

    assert response.status_code == 200
    assert audit_count() == before


# ── Roles ───────────────────────────────────────────────────────────────────────


def test_owner_reads_the_role_catalogue(client: Client, staff_login: Callable[..., Any]) -> None:
    """Roles list the full seeded catalogue with resolved permission codenames."""
    staff_login(client, Role.Code.OWNER)

    response = client.get(ROLES_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 4
    owner_role = next(row for row in body["results"] if row["code"] == "OWNER")
    assert "accounts.manage_users" in owner_role["permissions"]
    manager_role = next(row for row in body["results"] if row["code"] == "MANAGER")
    assert "accounts.manage_users" not in manager_role["permissions"]


# ── Settings ────────────────────────────────────────────────────────────────────


def test_owner_reads_settings(client: Client, staff_login: Callable[..., Any]) -> None:
    """The singleton row returns its defaults, untouched, on first read."""
    staff_login(client, Role.Code.OWNER)

    response = client.get(SETTINGS_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["session_timeout_minutes"] == 480
    assert body["password_max_age_days"] == 0
    assert body["require_password_change_for_new_users"] is True
    assert body["updated_by"] is None


def test_owner_patches_settings_and_is_recorded(
    client: Client, staff_login: Callable[..., Any]
) -> None:
    """A settings change persists, names the Owner, and writes an audit entry."""
    owner = staff_login(client, Role.Code.OWNER)

    response = patch_json(client, SETTINGS_URL, {"password_max_age_days": 90})

    assert response.status_code == 200
    body = response.json()
    assert body["password_max_age_days"] == 90
    assert body["updated_by"] == owner.username
    assert body["updated_at"] is not None

    entry = AuditLog.objects.get(object_type="accounts.SiteSetting")
    assert entry.actor == owner
    assert entry.before is not None
    assert entry.after is not None
    assert entry.before["password_max_age_days"] == 0
    assert entry.after["password_max_age_days"] == 90


def test_settings_reject_an_invalid_timeout(
    client: Client, staff_login: Callable[..., Any]
) -> None:
    """A zero-minute session timeout cannot be stored."""
    staff_login(client, Role.Code.OWNER)

    response = patch_json(client, SETTINGS_URL, {"session_timeout_minutes": 0})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
