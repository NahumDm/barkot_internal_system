r"""Shared pytest fixtures for the Barkot backend.

pytest-django configuration lives in pyproject.toml
([tool.pytest.ini_options]); ``DJANGO_SETTINGS_MODULE`` points at
``config.settings.dev``.

Tests that need the database ask for it with ``@pytest.mark.django_db`` or
``pytestmark``. The factories here exist because testing session auth means
making real authenticated requests: an unauthenticated 401 and an
authenticated 403 cannot be told apart from a mocked user, and building a user
inline in every test would leave four different ways of making one member of
staff.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.accounts.models import Role
from apps.accounts.role_seeding import seed_roles

User = get_user_model()

#: Satisfies every configured AUTH_PASSWORD_VALIDATOR, so a test about
#: permissions is not also a test about password policy.
TEST_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def make_staff_user(db: None) -> Callable[..., Any]:
    """Return a factory that creates a login-enabled user for a given role.

    Roles are seeded here, so a test can ask for any of the four business roles
    by code without repeating the setup::

        cashier = make_staff_user(Role.Code.CASHIER)

    Args:
        db: pytest-django's database fixture.

    Returns:
        A callable taking a role code and returning the created ``User``, which
        has a password of :data:`TEST_PASSWORD`.
    """
    seed_roles()

    def _make(role_code: str, password: str = TEST_PASSWORD, **extra: Any) -> Any:
        role = Role.objects.get(code=role_code)
        return User.objects.create_user(
            username=f"{role_code.lower()}-{extra.pop('suffix', '1')}",
            password=password,
            role=role,
            **extra,
        )

    return _make


@pytest.fixture
def staff_login(make_staff_user: Callable[..., Any]) -> Callable[..., Any]:
    """Return a factory that signs a client in as a given role.

    Used instead of ``client.login(...)`` so the password is not restated in
    every test: a test that hard-codes a password fails on the password policy
    change rather than on the thing it was written to check.

    Args:
        make_staff_user: The user factory.

    Returns:
        A callable taking a ``Client`` and a role code, signing that client in
        and returning the user.
    """

    def _login(client: Client, role_code: str) -> Any:
        user = make_staff_user(role_code)
        assert client.login(username=user.username, password=TEST_PASSWORD)
        return user

    return _login
