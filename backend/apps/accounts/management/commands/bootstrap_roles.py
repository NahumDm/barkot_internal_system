"""Create the four business roles and grant them their permissions (spec §9.2).

Roles are normally seeded automatically by a ``post_migrate`` receiver, so a
plain ``migrate`` already leaves the database correct. This command exists for
the two cases that signal cannot cover:

- ``--check``, to assert the seeded state still matches the matrix (for CI);
- re-seeding after the matrix changes, when the migration files are untouched.

The real work lives in :mod:`apps.accounts.role_seeding` so the command and the
``post_migrate`` receiver cannot drift apart.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.permissions import ALL_PERMISSIONS, ROLE_MATRIX
from apps.accounts.role_seeding import check_roles, resolve_permissions, seed_roles


class Command(BaseCommand):
    """Seed :class:`apps.accounts.models.Role` rows from the matrix."""

    help = "Create the business roles and grant their permissions (spec §9.2)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--check",
            action="store_true",
            help=(
                "Verify the seeded roles match ROLE_MATRIX without writing. "
                "Exits non-zero if they do not. Intended for CI."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["check"]:
            problems = check_roles()
            if problems:
                raise CommandError(
                    "Role seeding is out of date. Run: python manage.py bootstrap_roles\n  "
                    + "\n  ".join(problems)
                )
            self.stdout.write(self.style.SUCCESS("Roles and permissions match ROLE_MATRIX."))
            return

        missing = [name for name in ALL_PERMISSIONS if name not in resolve_permissions()]
        if missing:
            raise CommandError(
                "These permissions are declared in the matrix but do not exist. "
                "Check that the owning model still declares them in Meta.permissions, "
                "then re-run migrate:\n  " + "\n  ".join(sorted(missing))
            )

        seed_roles()
        self.stdout.write(
            self.style.SUCCESS(
                f"Roles ready ({len(ROLE_MATRIX)} roles, "
                f"{len(ALL_PERMISSIONS)} permissions declared)."
            )
        )
