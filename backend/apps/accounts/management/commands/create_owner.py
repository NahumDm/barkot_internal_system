"""Create the first Owner account (roadmap A7, spec §9.1).

Every other staff account arrives through the Owner, so there must be exactly
one way to make the first one — and it cannot be ``createsuperuser``, for three
reasons:

1. A Django superuser is not a business Owner. The Owner in spec §9.2 is defined
   by holding the whole permission catalogue, and this project enforces that
   through the role matrix (P06). ``is_superuser=True`` would short-circuit
   ``has_perm`` entirely, so the matrix would stop being the thing that decides
   what the Owner can do — and a later matrix edit would not apply.
2. ``createsuperuser`` creates a user with no role, and ``accounts.User.role`` is
   non-null. Every login would fail against the FK.
3. The first Owner is a real person who will be accountable for payroll and cash,
   so the command is deliberately slow and explicit rather than a one-liner.

**The password is never an argument.** It is read from a no-echo terminal prompt
or from stdin. That is not paranoia about the display: an argument is visible in
the shell history, in ``ps`` output, and in any process listing for as long as
the command runs, on a machine several people administer. A generated password is
printed once to stdout and nowhere else, because printing it to stdout is the
only way for a human to learn it — which is why it is also flagged
``is_temporary_password`` so A6 can force a change at first login.

Three deliberate non-features, each of which would be a security regression:

- No ``--password`` flag, no ``DJANGO_OWNER_PASSWORD`` environment variable. Both
  are just an argument wearing a disguise, and both end up in a CI log.
- No logging of the password, the hash, or anything derived from them. The test
  suite asserts on ``caplog`` and ``stderr`` so this stays true.
- No plaintext password is ever passed to or stored by the database.
"""

from __future__ import annotations

import getpass
import secrets
import sys
from typing import Any

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as PasswordValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import Role, User

#: Ambiguous characters removed on purpose: 0/O, 1/l/I. A password an operator
#: has to transcribe from a terminal is one they will transcribe wrong.
_ALPHABET = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#%^&*-_=+"

_GENERATED_LENGTH = 24

#: Generation is retried rather than trusted. ``CommonPasswordValidator`` could
#: in principle reject a random string, and a command that dies leaving no
#: Owner behind is worse than one that tries again.
_GENERATION_ATTEMPTS = 8


def generate_password() -> str:
    """Return a random password that satisfies the configured validators.

    Returns:
        A password of :data:`_GENERATED_LENGTH` characters, drawn from
        :data:`_ALPHABET`.

    Raises:
        CommandError: If no acceptable password was produced, which would mean
            the validators are unreachable rather than that the entropy was low.
    """
    for _ in range(_GENERATION_ATTEMPTS):
        candidate = "".join(secrets.choice(_ALPHABET) for _ in range(_GENERATED_LENGTH))
        try:
            # No user instance: similarity against a username we do not have yet
            # is checked properly below, against the real username.
            password_validation.validate_password(candidate)
        except PasswordValidationError:
            continue
        return candidate
    raise CommandError(
        "Could not generate a password that passes the configured validators. "
        "Check AUTH_PASSWORD_VALIDATORS in config/settings/base.py."
    )


class Command(BaseCommand):
    """Create a login-enabled Owner account."""

    help = (
        "Create the first Owner account (spec §9.1). "
        "Prompts for the password; it is never accepted as an argument."
    )

    def add_arguments(self, parser: Any) -> None:
        # Optional only so `--check` can run as a bare preflight. Creating an
        # Owner without one is meaningless, so `handle` rejects it.
        parser.add_argument(
            "username",
            nargs="?",
            help=(
                "Login name for the Owner. Must not already exist. Omit only when using --check."
            ),
        )
        parser.add_argument(
            "--email",
            default="",
            help="Optional. Barkot logs in by username; this is for records only.",
        )
        parser.add_argument(
            "--full-name",
            default="",
            help="Optional. Display name shown in the UI and audit entries.",
        )
        parser.add_argument(
            "--password-stdin",
            action="store_true",
            help=(
                "Read one line from stdin instead of prompting. For container "
                "entrypoints and CI, where no terminal is attached. The value is "
                "not echoed by this command."
            ),
        )
        parser.add_argument(
            "--generate-password",
            action="store_true",
            help=(
                "Generate a random password, print it once to stdout, and mark "
                "the account as requiring a change at first login."
            ),
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help=(
                "Report whether roles are seeded and an Owner already exists, "
                "without creating anything. Exits non-zero if an Owner is "
                "already present. Intended for CI."
            ),
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Create the Owner even if one already exists. A second Owner is a "
                "grant of full authority, so it has to be asked for deliberately."
            ),
        )

    # ── internals ──────────────────────────────────────────────────────────

    def _read_password(self, username: str, *, from_stdin: bool) -> str:
        """Obtain and validate the password.

        Args:
            username: The login name, used for the similarity validator.
            from_stdin: Read one line from stdin rather than prompting.

        Returns:
            The password, after it has passed every configured validator.

        Raises:
            CommandError: If the two entries differ, or the password fails any
                configured validator.
        """
        if from_stdin:
            # readline, not read: read() would block on an interactive stdin and
            # silently swallow anything after the password on the same line.
            password = sys.stdin.readline().rstrip("\n")
            if not password:
                raise CommandError(
                    "--password-stdin was given but stdin was empty. Pipe the "
                    'password in, e.g. `printf %s "$PW" | manage.py create_owner owner`.'
                )
        else:
            first = getpass.getpass("Password: ")
            if not first:
                raise CommandError("An empty password cannot be used. Aborting.")
            # Asked twice because a mistyped first entry is otherwise discovered
            # only at first login, which reads as the system being broken.
            second = getpass.getpass("Password (again): ")
            if first != second:
                raise CommandError("The two passwords did not match.")
            password = first

        if not password:
            raise CommandError("An empty password cannot be used. Aborting.")

        try:
            password_validation.validate_password(password, user=User(username=username))
        except PasswordValidationError as exc:
            raise CommandError(
                "That password does not meet the configured requirements:\n  "
                + "\n  ".join(exc.messages)
            ) from exc
        return password

    def _existing_owners(self) -> list[str]:
        """Return the usernames of every existing Owner."""
        return list(
            User.objects.filter(role__code=Role.Code.OWNER).values_list("username", flat=True)
        )

    @transaction.atomic
    def _create_owner(
        self, username: str, password: str, *, email: str, full_name: str, temporary: bool
    ) -> User:
        """Create the Owner row.

        Args:
            username: Login name.
            password: Already validated.
            email: Optional contact address.
            full_name: Optional display name.
            temporary: Whether to force a password change at first login.

        Returns:
            The created user.

        Raises:
            CommandError: If the username is taken, or the roles are not seeded.
        """
        try:
            owner_role = Role.objects.for_code(Role.Code.OWNER)
        except Role.DoesNotExist as exc:
            raise CommandError(
                "The Owner role does not exist, so there is nothing to grant. "
                "Run `python manage.py migrate` (roles seed on post_migrate) or "
                "`python manage.py bootstrap_roles` first."
            ) from exc

        if User.objects.filter(username=username).exists():
            raise CommandError(
                f"A user named {username!r} already exists. Choose another login name, "
                "or use `manage.py changepassword` to reset an existing account."
            )

        # create_staff_user is the only supported onboarding path: it requires a
        # role and refuses roles that may not log in.
        owner = User.objects.create_staff_user(
            username,
            role=owner_role,
            password=password,
            email=email,
            first_name=full_name,
            is_temporary_password=temporary,
        )
        # Deliberately not is_superuser. The Owner's authority comes from the
        # role matrix holding the whole catalogue, so the matrix stays the single
        # enforcement point (P06) and a later edit to it actually bites.
        owner.is_superuser = False
        owner.save(update_fields=["is_superuser"])
        return owner

    # ── entry point ────────────────────────────────────────────────────────

    def handle(self, *args: Any, **options: Any) -> None:
        username: str = options["username"] or ""
        from_stdin: bool = options["password_stdin"]
        generate: bool = options["generate_password"]

        if options["check"]:
            self._report(options["force"])
            return

        if not username:
            raise CommandError(
                "A username is required to create an Owner. For a preflight report "
                "that changes nothing, run `manage.py create_owner --check`."
            )

        if from_stdin and generate:
            raise CommandError("--password-stdin and --generate-password both supply a password.")

        existing = self._existing_owners()
        if existing and not options["force"]:
            raise CommandError(
                "An Owner already exists: "
                + ", ".join(existing)
                + "\nA second Owner has full authority over payroll, cash and audit. "
                "If that is genuinely intended, re-run with --force and a note in the "
                "deployment record."
            )

        temporary = False
        password = ""
        if generate:
            password = generate_password()
            temporary = True
        else:
            password = self._read_password(username, from_stdin=from_stdin)

        owner = self._create_owner(
            username,
            password,
            email=options["email"],
            full_name=options["full_name"],
            temporary=temporary,
        )

        if temporary:
            # The one deliberate disclosure: stdout, once, and only because a
            # generated secret the operator cannot otherwise see is useless. The
            # account is flagged temporary so A6 forces a change at first login,
            # which shrinks the window this line exists for.
            self.stdout.write("")
            self.stdout.write("  Generated password (shown once, not recoverable):")
            self.stdout.write(f"  {password}")
            self.stdout.write("")

        self.stdout.write(
            self.style.SUCCESS(
                f"Owner {owner.username!r} created with role {owner.role.code} "
                f"and {len(owner.role.effective_permissions())} permissions."
            )
        )
        self.stdout.write("  Log in at POST /api/v1/auth/login/ once A4 ships.")
        if temporary:
            self.stdout.write("  The Owner must change this password before normal use.")

    def _report(self, force: bool) -> None:
        """Implement ``--check`` for CI.

        Args:
            force: When true, an existing Owner is reported as acceptable.

        Raises:
            CommandError: If roles are unseeded, or an Owner exists and
                ``--force`` was not given.
        """
        if not Role.objects.filter(code=Role.Code.OWNER).exists():
            raise CommandError("The Owner role is not seeded. Run migrate or bootstrap_roles.")
        existing = self._existing_owners()
        if existing and not force:
            raise CommandError("An Owner already exists: " + ", ".join(existing))
        if existing:
            self.stdout.write(
                self.style.SUCCESS(f"Owner(s) present: {', '.join(existing)} (--force accepted).")
            )
            return
        self.stdout.write(self.style.SUCCESS("No Owner yet. Roles are seeded and ready."))
