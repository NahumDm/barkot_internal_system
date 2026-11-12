"""Tests for the ``create_owner`` command (roadmap A7).

The gate is "creates a working Owner; the password is not logged", and the
second half is the half worth testing. A password leak in a bootstrap command
is invisible in normal use: the command works perfectly, the Owner is created,
and the only symptom is a secret sitting in a CI log or a shell history that
somebody has to notice months later. So the leak assertions come first and
cover every channel a password could plausibly escape through.
"""

from __future__ import annotations

import io
import sys
from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth import password_validation
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.accounts.management.commands.create_owner import generate_password
from apps.accounts.models import Role, User

pytestmark = pytest.mark.django_db

GOOD_PASSWORD = "correct-horse-battery-staple-9"

#: Stands in for ``sys.stdin`` during a test. ``call_command`` has no ``stdin``
#: parameter and the command reads ``sys.stdin`` directly, so replacing the
#: module attribute is the only seam a test has.
Stdin = Callable[[pytest.MonkeyPatch, str | None], None]


@pytest.fixture
def supply_stdin() -> Stdin:
    """Return a helper that points ``sys.stdin`` at one line.

    Returns:
        A callable taking ``(monkeypatch, password)``; ``password=None`` supplies
        an empty stream, which is how the "no input piped in" path is reached.
    """

    def _supply(monkeypatch: pytest.MonkeyPatch, password: str | None) -> None:
        text = "" if password is None else f"{password}\n"
        monkeypatch.setattr(sys, "stdin", io.StringIO(text))

    return _supply


def _call(*args: str, **kwargs: Any) -> tuple[str, str]:
    """Run the command, returning ``(stdout, stderr)``.

    Args:
        *args: Positional arguments to the command.
        **kwargs: Keyword arguments to the command.

    Returns:
        Whatever the command wrote to each stream.
    """
    out, err = io.StringIO(), io.StringIO()
    call_command("create_owner", *args, stdout=out, stderr=err, **kwargs)
    return out.getvalue(), err.getvalue()


class TestCreatesAWorkingOwner:
    """The positive path: the account exists and can actually log in."""

    def test_it_creates_a_user_with_the_owner_role(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A working Owner, per the A7 gate."""
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        _call("owner", password_stdin=True)
        assert User.objects.get(username="owner").role.code == Role.Code.OWNER

    def test_the_password_authenticates(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Usable password: the account is not created with an unusable hash.

        ``create_staff_user`` accepts ``password=None`` for a new hire who has
        no password yet. If that leaked into this path the Owner would exist and
        be unable to log in, which is the worst outcome a bootstrap command can
        produce.
        """
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        _call("owner", password_stdin=True)
        owner = User.objects.get(username="owner")
        assert owner.has_usable_password()
        assert owner.check_password(GOOD_PASSWORD)

    def test_the_stored_password_is_not_plaintext(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The database holds a hash, never the secret itself."""
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        _call("owner", password_stdin=True)
        owner = User.objects.get(username="owner")
        assert GOOD_PASSWORD not in owner.password
        assert owner.password.startswith(("pbkdf2_", "argon2", "bcrypt"))

    def test_the_owner_receives_the_whole_permission_catalogue(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Authority comes from the matrix, so the Owner can actually act.

        The app label is ``accounts`` (which holds login accounts), not
        ``users`` (which holds staff business profiles). Asserting against a
        permission that does not exist would pass for the wrong reason on a
        lenient backend, so this checks a real codename from the matrix.
        """
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        _call("owner", password_stdin=True)
        owner = User.objects.get(username="owner")
        granted = owner.role.effective_permissions()
        assert granted, "the Owner role holds no permissions"
        assert "manage_users" in granted
        assert owner.has_perm("accounts.manage_users")

    def test_it_is_not_a_django_superuser(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``is_superuser`` stays off so the role matrix remains the enforcer.

        A superuser short-circuits ``has_perm`` entirely. If the Owner were one,
        a later edit to ``ROLE_MATRIX`` would not restrict them, and the matrix
        would stop being the single source of authority (P06).
        """
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        _call("owner", password_stdin=True)
        assert User.objects.get(username="owner").is_superuser is False

    def test_optional_fields_are_stored(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Email and display name are optional, and recorded when given."""
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        _call(
            "owner",
            password_stdin=True,
            email="owner@example.com",
            full_name="Tesfaye Owner",
        )
        owner = User.objects.get(username="owner")
        assert owner.email == "owner@example.com"
        assert owner.first_name == "Tesfaye Owner"

    def test_it_is_active_and_staff(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Django's own login gate requires both flags."""
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        _call("owner", password_stdin=True)
        owner = User.objects.get(username="owner")
        assert owner.is_active
        assert owner.is_staff

    def test_the_account_is_not_temporary_when_the_password_was_chosen(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A hand-chosen password needs no forced change at first login."""
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        _call("owner", password_stdin=True)
        assert User.objects.get(username="owner").is_temporary_password is False


class TestThePasswordIsNotLogged:
    """The half of the A7 gate that is easy to regress silently."""

    def test_the_password_is_absent_from_stdout_stderr_and_logs(
        self,
        supply_stdin: Stdin,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Nothing the command emits contains the secret.

        Args:
            supply_stdin: Stdin seam.
            monkeypatch: pytest's patcher.
            caplog: pytest's log capture, so the assertion covers the logging
                subsystem and not only the two console streams.
        """
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        out, err = _call("owner", password_stdin=True)
        assert GOOD_PASSWORD not in out
        assert GOOD_PASSWORD not in err
        assert GOOD_PASSWORD not in caplog.text

    def test_the_generated_password_is_printed_once_and_nowhere_else(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A generated secret reaches the operator exactly once, on stdout.

        Printing it is unavoidable - a generated password nobody can see locks
        the operator out - so the requirement is that stdout is the *only*
        channel. If it also reached a log file it would outlive the terminal
        session that legitimately displayed it.

        Args:
            caplog: pytest's log capture.
        """
        out, err = _call("owner", generate_password=True)
        assert out.count("shown once") == 1, "expected exactly one disclosure block"
        secret = [
            line.strip()
            for line in out.splitlines()
            if line.strip()
            and not line.strip().startswith((
                "Generated password",
                "Owner",
                "Log in",
                "The Owner must change",
            ))
        ]
        assert len(secret) == 1, f"expected one printed secret line, got {secret}"
        generated = secret[0]
        assert generated not in err
        assert generated not in caplog.text
        # The printed secret is the one that works, which is what makes printing
        # it correct rather than merely convenient.
        assert User.objects.get(username="owner").check_password(generated)

    def test_a_generated_password_is_flagged_for_forced_change(self) -> None:
        """The window in which the printed secret is live is bounded.

        ``is_temporary_password`` is what A6 turns into a forced change at first
        login. Without it, a generated password would be a permanent credential
        that was once written to a terminal.
        """
        _call("owner", generate_password=True)
        assert User.objects.get(username="owner").is_temporary_password is True

    def test_the_password_never_reaches_the_database_as_plaintext(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No column of the user row holds the secret.

        The row is read raw rather than trusting ``check_password``, so a future
        field that stored a copy would be caught here.
        """
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        _call("owner", password_stdin=True)
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT * FROM {User._meta.db_table} WHERE username = %s",
                ["owner"],
            )
            columns = [col[0] for col in cursor.description]
            row = dict(zip(columns, cursor.fetchone(), strict=True))
        assert GOOD_PASSWORD not in " ".join(str(v) for v in row.values())


class TestRefusesUnsafeInput:
    """The command must fail loudly rather than create a broken account."""

    def test_it_refuses_an_empty_stdin(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty secret is a mistake, not an Owner with no password."""
        supply_stdin(monkeypatch, None)
        with pytest.raises(CommandError, match="empty"):
            _call("owner", password_stdin=True)

    def test_it_refuses_a_weak_password(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Django's validators are applied, not bypassed."""
        supply_stdin(monkeypatch, "short")
        with pytest.raises(CommandError, match="requirements"):
            _call("owner", password_stdin=True)

    def test_it_refuses_a_password_similar_to_the_username(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The similarity validator runs against the real username.

        This is the check that cannot work at generation time, which is why the
        password is re-validated against the username before the user is made.
        """
        supply_stdin(monkeypatch, "ownerowner-x9")
        with pytest.raises(CommandError, match="requirements"):
            _call("ownerowner", password_stdin=True)

    def test_it_refuses_a_duplicate_username(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Never silently reset an existing account's role or password."""
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        _call("owner", password_stdin=True)
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        with pytest.raises(CommandError, match="already exists"):
            _call("owner", password_stdin=True)

    def test_it_refuses_a_second_owner(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second Owner is refused; there is no flag that creates one."""
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        _call("owner", password_stdin=True)
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        with pytest.raises(CommandError, match="already exists"):
            _call("owner2", password_stdin=True)
        assert User.objects.filter(role__code=Role.Code.OWNER).count() == 1

    def test_there_is_no_force_escape_hatch(self) -> None:
        """``--force`` is gone: a second Owner cannot be minted from the CLI.

        Pinned because the flag was the one documented way around the invariant,
        and re-introducing it would quietly restore the ability to create a
        second account with full payroll and configuration authority.
        """
        with pytest.raises(TypeError, match="force"):
            _call("owner2", password_stdin=True, force=True)

    def test_the_email_is_prompted_for_on_a_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An interactive setup asks for the email before it asks for the password.

        The two values share stdin in this test, in the order the command reads
        them: the email line first, then the password line. That order is the
        behaviour under test - a password prompt that came first would consume
        the address as the secret.
        """
        stream = io.StringIO(f"owner@example.com\n{GOOD_PASSWORD}\n")
        monkeypatch.setattr(sys, "stdin", stream)
        monkeypatch.setattr(stream, "isatty", lambda: True, raising=False)
        _call("owner", password_stdin=True)
        owner = User.objects.get(username="owner")
        assert owner.email == "owner@example.com"
        assert owner.check_password(GOOD_PASSWORD)

    def test_a_non_interactive_run_leaves_the_email_blank(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CI and piped runs never block waiting for a value nobody will type."""
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        _call("owner", password_stdin=True)
        assert User.objects.get(username="owner").email == ""

    def test_stdin_and_generate_together_are_refused(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two sources for one secret means one of them is being ignored."""
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        with pytest.raises(CommandError, match="both supply"):
            _call("owner", password_stdin=True, generate_password=True)

    def test_it_refuses_when_roles_are_not_seeded(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Say what to run, rather than failing on a missing foreign key.

        Roles are seeded by ``post_migrate``, so this is the failure a developer
        hits when the receiver was skipped; the message names the fix.
        """
        Role.objects.all().delete()
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        with pytest.raises(CommandError, match="bootstrap_roles"):
            _call("owner", password_stdin=True)

    def test_it_refuses_to_create_without_a_username(self) -> None:
        """An Owner needs a login name; the error should say how to get one.

        ``username`` is optional at the parser level only so that ``--check``
        can run alone. Creating without one has to fail with a pointer to
        ``--check``, not with argparse's generic "required" message.
        """
        with pytest.raises(CommandError, match="username is required"):
            _call(password_stdin=True)
        assert User.objects.count() == 0


class TestCheckMode:
    """``--check`` mirrors ``bootstrap_roles`` for CI."""

    def test_it_reports_ready_when_no_owner_exists(self) -> None:
        """The CI-facing signal for a freshly migrated database."""
        out, _ = _call("owner", check=True)
        assert "No Owner yet" in out

    def test_it_runs_without_a_username(self) -> None:
        """A preflight must work as `create_owner --check`, with no arguments.

        This is the form CI and the deployment runbook actually use: it asks
        whether the bootstrap has happened, so it has nothing to say about which
        Owner to create. A required username would make the check impossible to
        run on its own.
        """
        out, _ = _call(check=True)
        assert "No Owner yet" in out

    def test_it_fails_once_an_owner_exists(
        self, supply_stdin: Stdin, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CI can assert the bootstrap has happened."""
        supply_stdin(monkeypatch, GOOD_PASSWORD)
        _call("owner", password_stdin=True)
        with pytest.raises(CommandError, match="already exists"):
            _call("owner", check=True)
        with pytest.raises(CommandError, match="already exists"):
            _call(check=True)

    def test_it_creates_nothing(self) -> None:
        """A reporting mode that wrote rows would not be a reporting mode."""
        _call(check=True)
        assert User.objects.count() == 0

    def test_it_fails_when_roles_are_unseeded(self) -> None:
        """Distinguishes "no Owner yet" from "the database is not ready"."""
        Role.objects.all().delete()
        with pytest.raises(CommandError, match="not seeded"):
            _call("owner", check=True)


class TestGeneratedPasswords:
    """Properties of the generator itself."""

    def test_generated_passwords_pass_the_validators(self) -> None:
        """A generated password that fails validation would be unusable."""
        password_validation.validate_password(generate_password())

    def test_they_are_long_and_varied(self) -> None:
        """Length and alphabet width are what make the randomness meaningful."""
        first, second = generate_password(), generate_password()
        assert len(first) >= 12, "below the configured minimum length"
        assert first != second, "two generated passwords collided"
        assert len(set(first)) > 5, "insufficient character variety"

    def test_they_avoid_ambiguous_characters(self) -> None:
        """A password read off a terminal must not contain 0/O or 1/l/I.

        These are the pairs an operator reliably transcribes into each other,
        and a bootstrap password mistyped once looks like a broken system rather
        than a typo.
        """
        for _ in range(20):
            password = generate_password()
            for char in "0O1lI":
                assert char not in password, f"ambiguous character {char!r} in {password!r}"
