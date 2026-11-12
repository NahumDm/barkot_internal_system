"""Seed the database the Playwright suite drives a real browser against.

Roadmap B5 asks for end-to-end coverage, and an end-to-end test that stubs the
network is a test of the frontend's imagination of the backend. The browser has
to cross the same seam a cashier does: a real session cookie, a real CSRF token,
real JSON over real HTTP, and a real Postgres row at the end of it. That needs a
database with known contents, and this command is what puts it there.

It is deliberately not a pytest fixture. pytest builds a test database and tears
it down; the E2E run needs a long-lived database that a browser, a Django
``runserver`` and a Next.js proxy are all pointed at simultaneously, so it has to
be created from outside pytest's lifecycle.

Two properties matter more than convenience here.

**Isolation.** The fixture database is a different database from the one a
developer works in, named by the caller through ``DJANGO_DB_NAME``. ``--reset``
erases rows, so the command refuses to run at all unless the database name ends
in ``_e2e``. A seed command that can empty a development database because someone
typed the wrong environment variable is a much worse thing to have than no seed
command.

**Determinism.** Every fixture is addressed by a constant, not a lookup of
"whatever is first", so a test can name the product it wants without caring what
order rows arrived in. ``--json`` prints those constants on stdout so the
Playwright specs and this command cannot drift apart by duplicating them: the
specs read the ids and passwords from here rather than hard-coding a second copy
of the same literals.

Usage::

    DJANGO_DB_NAME=barket_e2e python manage.py seed_e2e --reset --json
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, TypedDict

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.accounts.role_seeding import seed_roles
from apps.core.enums import EmployeeStatus
from apps.inventory.models import StockMovement
from apps.inventory.services import ReceiptLineInput, receive_stock
from apps.payroll.models import Employee as PayrollEmployee
from apps.products.models import Category, Product, ProductPrice
from apps.users.models import EmployeeProfile

#: Database-name suffix without which ``--reset`` refuses to erase anything.
#: See the module docstring.
REQUIRED_DB_SUFFIX = "_e2e"

#: Credentials the specs sign in with. Not secrets: this database is created by
#: the test run, thrown away afterwards, and never listens anywhere but localhost.
E2E_PASSWORD = "e2e-cashier-pw"

CASHIER_USERNAME = "e2e-cashier"
MANAGER_USERNAME = "e2e-manager"
OWNER_USERNAME = "e2e-owner"
BARMAN_USERNAME = "e2e-barman"

CATEGORY_NAME = "E2E Drinks"
PRODUCT_NAME = "E2E Coffee"
PRODUCT_SKU = "E2E-COFFEE"

UNIT_PRICE = Decimal("25.00")
UNIT_COST = Decimal("18.00")
OPENING_STOCK = Decimal("40.000")

#: The one staff member the payroll specs pay. A single employee keeps the
#: browser story readable - the gross, deduction and net figures on screen and
#: over HTTP all come from this one row.
PROFILE_FULL_NAME = "Seble Worku"
PROFILE_POSITION = "Waitstaff"
PROFILE_PHONE = "+251911220033"
PROFILE_START_DATE = date(2024, 1, 15)
PAYROLL_MONTHLY_WAGE = Decimal("12000.00")


class SeededUserSummary(TypedDict):
    """One account the specs can sign in as."""

    username: str
    password: str


class SeededCategorySummary(TypedDict):
    """The category the seeded product sits in."""

    id: int
    name: str


class SeededProductSummary(TypedDict):
    """The product the specs sell, and the figures their expectations come from."""

    id: int
    name: str
    sku: str
    #: Deliberately a string. The specs parse it with ``Number()``, and a JSON
    #: number here would round-trip through JavaScript as a float - which is the
    #: whole class of bug a money column should not have to worry about.
    unit_price: str
    opening_stock: str


class SeededPayrollSummary(TypedDict):
    """The one staff member the payroll specs generate, approve and pay."""

    profile_id: int
    employee_id: int
    full_name: str
    #: A string for the same reason ``SeededProductSummary.unit_price`` is.
    monthly_wage: str


class SeedSummary(TypedDict):
    """The whole ``--json`` payload.

    This is the contract between this command and
    ``frontend/tests/live/environment.ts``, which declares the same shape as a
    TypeScript interface. It is named here, in one place, so the two can be
    compared rather than rediscovered.
    """

    database: str
    cashier: SeededUserSummary
    manager: SeededUserSummary
    owner: SeededUserSummary
    barman: SeededUserSummary
    category: SeededCategorySummary
    product: SeededProductSummary
    payroll: SeededPayrollSummary


class Command(BaseCommand):
    """Create the fixtures the live Playwright suite signs in and sells against."""

    help = (
        "Seed the E2E database with a Cashier, a Manager, an Owner, a Barman, "
        "one sellable product and one staff member on the payroll."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Erase existing rows before seeding. Refuses to run unless the "
                f"database name ends in {REQUIRED_DB_SUFFIX!r}."
            ),
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help=(
                "Print the seeded identifiers and credentials as JSON on stdout, and nothing else."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        database_name = self._database_name()
        self._assert_safe_database(database_name, should_reset=bool(options["reset"]))

        if options["reset"]:
            # Roles are recreated by the post_migrate receiver and re-granted here,
            # so flushing everything and rebuilding is simpler than trying to work
            # out which of the seeded rows survived the last run.
            call_command("flush", "--no-input", verbosity=0)
            seed_roles()

        cashier = self._upsert_user(CASHIER_USERNAME, Role.Code.CASHIER)
        manager = self._upsert_user(MANAGER_USERNAME, Role.Code.MANAGER)
        owner = self._upsert_user(OWNER_USERNAME, Role.Code.OWNER)
        barman = self._upsert_user(BARMAN_USERNAME, Role.Code.BARMAN)
        category, product = self._upsert_product()
        profile, payroll = self._upsert_payroll()

        summary: SeedSummary = {
            "database": database_name,
            "cashier": {"username": cashier.username, "password": E2E_PASSWORD},
            "manager": {"username": manager.username, "password": E2E_PASSWORD},
            "owner": {"username": owner.username, "password": E2E_PASSWORD},
            "barman": {"username": barman.username, "password": E2E_PASSWORD},
            "category": {"id": category.id, "name": category.name},
            "product": {
                "id": product.id,
                "name": product.name,
                "sku": product.sku,
                "unit_price": str(UNIT_PRICE),
                "opening_stock": str(OPENING_STOCK),
            },
            "payroll": {
                "profile_id": profile.id,
                "employee_id": payroll.id,
                "full_name": profile.full_name,
                "monthly_wage": str(payroll.monthly_wage),
            },
        }

        if options["json"]:
            # Plain stdout, because Playwright parses this line. Progress messages
            # would corrupt it, which is why nothing else writes to stdout above.
            self.stdout.write(json.dumps(summary))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {summary['database']}: cashier={CASHIER_USERNAME} "
                f"manager={MANAGER_USERNAME} owner={OWNER_USERNAME} "
                f"barman={BARMAN_USERNAME} "
                f"product={PRODUCT_SKU} (id={product.id}) "
                f"payroll={profile.full_name} (id={payroll.id})"
            )
        )

    def _database_name(self) -> str:
        """The configured default database name, as a string.

        Read once and passed around rather than re-read at each use, because the
        guard checks it and the summary reports it: two reads of the same setting
        could in principle disagree, and a guard that validates one value while the
        summary prints another is worse than no guard.
        """
        return str(settings.DATABASES["default"]["NAME"] or "")

    def _assert_safe_database(self, name: str, *, should_reset: bool) -> None:
        """Refuse to erase rows in a database that is not clearly a test one.

        Args:
            name: The configured default database name.
            should_reset: Whether ``--reset`` was passed.

        Raises:
            CommandError: If ``--reset`` was asked for against a database whose
                name does not identify it as disposable.
        """
        if should_reset and not name.endswith(REQUIRED_DB_SUFFIX):
            raise CommandError(
                f"Refusing to --reset {name!r}: the E2E database name must end in "
                f"{REQUIRED_DB_SUFFIX!r} so it cannot be confused with a working "
                f"database. Point DJANGO_DB_NAME at a dedicated database, for "
                f"example DJANGO_DB_NAME=barket{REQUIRED_DB_SUFFIX}."
            )

    def _upsert_user(self, username: str, role_code: str) -> User:
        """Create or re-password a staff user, so the suite can sign in as them.

        Args:
            username: Login name.
            role_code: The business role to grant.

        Returns:
            The user, with :data:`E2E_PASSWORD` set.
        """
        role = Role.objects.for_code(role_code)
        user, created = User.objects.get_or_create(username=username, defaults={"role": role})
        if not created and user.role_id != role.id:
            user.role = role
        user.set_password(E2E_PASSWORD)
        user.save()
        return user

    @transaction.atomic
    def _upsert_product(self) -> tuple[Category, Product]:
        """Create the category and product the specs sell, priced and in stock.

        Stock goes on through :func:`receive_stock` rather than a hand-written
        ``StockMovement``, so the opening balance is produced by the same ledger
        the sale draws down. A fixture that fakes the starting state can hide a
        service that disagrees with it.

        Returns:
            The category and product.
        """
        category, _ = Category.objects.get_or_create(name=CATEGORY_NAME)
        product, _ = Product.objects.get_or_create(
            sku=PRODUCT_SKU,
            defaults={"category": category, "name": PRODUCT_NAME, "unit": "cup"},
        )
        product.name = PRODUCT_NAME
        product.category = category
        product.is_active = True
        product.is_stock_tracked = True
        product.save()

        if not ProductPrice.objects.filter(product=product).exists():
            ProductPrice.objects.create(
                product=product,
                unit_price=UNIT_PRICE,
                effective_from=timezone.now() - timedelta(days=1),
            )

        # Asked of the ledger rather than of `created`, so re-running against a
        # database where the product already exists still tops the stock back up
        # instead of leaving a sale with nothing to draw down.
        if not StockMovement.objects.filter(product=product).exists():
            receive_stock(
                supplier_name="E2E Supplier",
                lines=[
                    ReceiptLineInput(
                        product=product,
                        quantity=OPENING_STOCK,
                        unit_cost=UNIT_COST,
                    )
                ],
            )

        return category, product

    @transaction.atomic
    def _upsert_payroll(self) -> tuple[EmployeeProfile, PayrollEmployee]:
        """Create the staff profile and its payroll record the specs pay.

        Built through :meth:`PayrollEmployee.from_profile` rather than a
        hand-written ``PayrollEmployee``, because the one-to-one link and the
        initial status are exactly the two things the payroll API's contract
        depends on. Idempotent: a profile that already exists is refreshed, and
        an existing employee row is re-priced rather than duplicated — a second
        ``from_profile`` call would violate the one-to-one and the whole point
        of the command is that re-running it leaves the same state as one run.

        Returns:
            The profile and its payroll employee.
        """
        profile, _ = EmployeeProfile.objects.get_or_create(
            full_name=PROFILE_FULL_NAME,
            defaults={
                "position": PROFILE_POSITION,
                "phone_number": PROFILE_PHONE,
                "start_date": PROFILE_START_DATE,
            },
        )
        profile.position = PROFILE_POSITION
        profile.phone_number = PROFILE_PHONE
        profile.start_date = PROFILE_START_DATE
        profile.is_archived = False
        profile.save()

        payroll = PayrollEmployee.objects.filter(profile=profile).first()
        if payroll is None:
            payroll = PayrollEmployee.from_profile(profile, monthly_wage=PAYROLL_MONTHLY_WAGE)
        else:
            payroll.monthly_wage = PAYROLL_MONTHLY_WAGE
            payroll.status = EmployeeStatus.ACTIVE
            payroll.terminated_on = None
            payroll.save()

        return profile, payroll
