r"""The E2E seed command, tested for the one thing that could actually hurt.

Roadmap B5's live Playwright suite takes this command's output as given, so a
silent change here changes what the suite proves. The two properties worth holding
are not the same kind of claim.

**The guard is a safety claim.** ``--reset`` calls ``flush``. The only thing
between a mistyped ``DJANGO_DB_NAME`` and an emptied working database is the
suffix check in the command, and a test that did not assert the refusal would be
decorative. It is asserted here against the names that look plausible and are not
safe, not just the obvious one.

**The fixtures are a contract claim.** That a Cashier and a Manager can sign in,
that the product is priced and has stock, and that re-running does not inflate the
opening balance, is exactly what the browser suite takes on faith. A fixture that
silently stopped being signable would otherwise surface as an unexplained 400 on
the sign-in form, halfway through a four-minute end-to-end run.

Note what is *not* here: a test that the browser suite passes. Duplicating it would
be a second thing to keep in step, and the suite already runs it for real on every
invocation.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from io import StringIO
from typing import cast

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import Role, User
from apps.core.enums import EmployeeStatus
from apps.core.management.commands.seed_e2e import (
    CASHIER_USERNAME,
    E2E_PASSWORD,
    MANAGER_USERNAME,
    OPENING_STOCK,
    OWNER_USERNAME,
    PAYROLL_MONTHLY_WAGE,
    PRODUCT_SKU,
    PROFILE_FULL_NAME,
    UNIT_PRICE,
    SeedSummary,
)
from apps.inventory.models import StockMovement
from apps.inventory.services import current_stock
from apps.payroll.models import Employee as PayrollEmployee
from apps.products.models import Product

#: Names that must never be erasable by ``--reset``. The first is the working
#: database; the other two are the near misses a substring check would let through.
UNSAFE_DATABASE_NAMES = ("barket", "barket_e2e_backup", "e2e_barket")


@contextmanager
def database_named(name: str) -> Iterator[None]:
    r"""Make the command read ``name`` as the database name, then put it back.

    Swaps in a **new** dictionary rather than editing the existing one, and that
    detail is the whole reason this is not a one-liner. Django's connection wrapper
    holds a reference to this exact dict as its settings snapshot
    (``connections["default"].settings_dict`` *is* ``settings.DATABASES["default"]``),
    so an in-place edit of ``NAME`` silently repoints the live connection too. Under
    ``transaction=True`` the connection is re-established mid-test, and the run dies
    trying to open a database that does not exist - or worse, succeeds against a
    real ``barket_e2e`` and flushes it. Only the command reads the name; the
    connection must not learn about it.
    """
    original = settings.DATABASES["default"]
    settings.DATABASES["default"] = {**original, "NAME": name}
    try:
        yield
    finally:
        settings.DATABASES["default"] = original


def seed(*args: str) -> str:
    """Run the command with ``--json`` and return everything it printed."""
    out = StringIO()
    call_command("seed_e2e", *args, "--json", stdout=out)
    return out.getvalue()


def seed_json(*args: str) -> SeedSummary:
    """Run the command and parse its output, as the Playwright global setup does.

    The return type is the command's own ``SeedSummary``, not a loose dict: if the
    JSON payload changes, this file stops type-checking rather than failing later on
    a key that is no longer there.
    """
    return cast(SeedSummary, json.loads(seed(*args).strip().splitlines()[-1]))


@pytest.mark.django_db
class TestResetGuard:
    """``--reset`` may only ever erase a database that is named as disposable."""

    @pytest.mark.parametrize("name", UNSAFE_DATABASE_NAMES)
    def test_reset_refuses_a_database_that_is_not_clearly_disposable(self, name: str) -> None:
        with database_named(name), pytest.raises(CommandError, match="Refusing to --reset"):
            call_command("seed_e2e", "--reset")

    def test_reset_refuses_and_says_what_to_do_instead(self) -> None:
        """The error names the database and the way out.

        A bare refusal would leave whoever hit it - a developer, or CI with the
        wrong variable set - with nothing to act on.
        """
        with database_named("barket"), pytest.raises(CommandError) as caught:
            call_command("seed_e2e", "--reset")

        message = str(caught.value)
        assert "'barket'" in message
        assert "barket_e2e" in message

    def test_seeding_without_reset_is_allowed_anywhere(self) -> None:
        """The guard is on erasing, not on seeding.

        Only ``--reset`` can lose data, so only ``--reset`` needs the name check.
        Someone building these fixtures in a scratch database should not have to
        name it ``_e2e`` to get them.
        """
        with database_named("barket"):
            summary = seed_json()

        assert summary["database"] == "barket"
        assert User.objects.filter(username=CASHIER_USERNAME).exists()


@pytest.mark.django_db(transaction=True)
class TestFixtures:
    """What the browser suite signs in and sells against."""

    def test_seeds_a_signable_cashier_and_manager(self) -> None:
        """Both roles exist, with the right one, and can actually authenticate.

        ``check_password`` rather than a look at the stored hash: a fixture that
        reported the right password while storing an unusable one would pass every
        inspection short of trying it, and would first be discovered as an opaque
        400 on the sign-in form.
        """
        with database_named("barket_e2e"):
            summary = seed_json("--reset")

        for username, role_code in (
            (CASHIER_USERNAME, Role.Code.CASHIER),
            (MANAGER_USERNAME, Role.Code.MANAGER),
        ):
            user = User.objects.get(username=username)
            assert user.role.code == role_code
            assert user.check_password(E2E_PASSWORD), f"{username} cannot sign in"

        assert summary["cashier"] == {"username": CASHIER_USERNAME, "password": E2E_PASSWORD}
        assert summary["manager"] == {"username": MANAGER_USERNAME, "password": E2E_PASSWORD}

    def test_seeds_a_payroll_worker_and_the_owner_who_signs_the_run_off(self) -> None:
        """The payroll spec's whole cast is present and able to act.

        The manager generates payroll but cannot approve it, so the second half
        of the browser story needs an Owner. The employee row must carry the
        seeded wage and the ``ACTIVE`` status the generation service includes,
        and the profile must not be archived - otherwise ``is_employable`` is
        false and the run comes out empty.
        """
        with database_named("barket_e2e"):
            summary = seed_json("--reset")

        owner = User.objects.get(username=OWNER_USERNAME)
        assert owner.role.code == Role.Code.OWNER
        assert owner.check_password(E2E_PASSWORD), "the Owner cannot sign in"
        assert summary["owner"] == {"username": OWNER_USERNAME, "password": E2E_PASSWORD}

        employee = PayrollEmployee.objects.get(pk=summary["payroll"]["employee_id"])
        assert employee.full_name == PROFILE_FULL_NAME
        assert employee.status == EmployeeStatus.ACTIVE
        assert employee.monthly_wage == PAYROLL_MONTHLY_WAGE
        assert summary["payroll"] == {
            "profile_id": employee.profile_id,
            "employee_id": employee.id,
            "full_name": PROFILE_FULL_NAME,
            "monthly_wage": str(PAYROLL_MONTHLY_WAGE),
        }

    def test_seeds_one_priced_product_with_stock(self) -> None:
        """Priced through the price table and stocked through the stock ledger.

        Stock is asked of the ledger rather than read off the product, because the
        ledger is what a sale draws down. A fixture that wrote ``40`` straight onto
        the product and no movement would satisfy an assertion on
        ``stock_on_hand`` and still leave a sale with nothing to draw down.
        """
        with database_named("barket_e2e"):
            summary = seed_json("--reset")

        product = Product.objects.get(sku=PRODUCT_SKU)
        assert product.is_active
        assert product.is_stock_tracked
        assert current_stock(product) == OPENING_STOCK
        assert StockMovement.objects.filter(product=product).count() == 1

        assert summary["product"]["sku"] == PRODUCT_SKU
        assert Decimal(summary["product"]["unit_price"]) == UNIT_PRICE
        assert Decimal(summary["product"]["opening_stock"]) == OPENING_STOCK

    def test_two_runs_leave_the_same_state_as_one(self) -> None:
        """A second ``--reset`` must not accumulate.

        The suite resets on every run, so a fixture that topped itself up would
        make the second run of the morning disagree with the first, and the stock
        figures the browser specs compute their expectations from would quietly
        stop meaning anything.
        """
        with database_named("barket_e2e"):
            seed_json("--reset")
            first = current_stock(Product.objects.get(sku=PRODUCT_SKU))

            seed_json("--reset")
            second = current_stock(Product.objects.get(sku=PRODUCT_SKU))

        assert first == second == OPENING_STOCK
        assert StockMovement.objects.count() == 1

    def test_reseeding_without_reset_does_not_top_the_shelf_back_up(self) -> None:
        """The subtle one: the product exists, so no second opening movement.

        Easy to get wrong and invisible until a sale fails for no visible reason.
        The opening movement is created only when the product has no movements at
        all, so running the command twice without ``--reset`` leaves the balance a
        sale draws down as the one the specs computed their expectations from.
        """
        with database_named("barket_e2e"):
            seed_json("--reset")
            opening_movements = StockMovement.objects.count()

            seed_json()
            seed_json()

        assert StockMovement.objects.count() == opening_movements == 1
        assert current_stock(Product.objects.get(sku=PRODUCT_SKU)) == OPENING_STOCK
        assert User.objects.filter(username=CASHIER_USERNAME).count() == 1


@pytest.mark.django_db(transaction=True)
class TestJsonContract:
    """The Playwright global setup parses this output, so its shape is a contract."""

    def test_json_is_a_single_line_and_nothing_else(self) -> None:
        """stdout carries the JSON and only the JSON.

        The command's own ``--json`` help promises "and nothing else". Today's
        reader tolerates extra lines by taking the last one, so a progress message
        leaking onto stdout would pass today and break the next reader - the
        promise is checked rather than relied on.
        """
        with database_named("barket_e2e"):
            printed = seed("--reset")

        assert "\n" not in printed.strip()
        json.loads(printed)  # must not raise

    def test_reports_the_database_it_actually_seeded(self) -> None:
        """The summary names the database, so a misconfigured run is visible.

        The specs log this line before every run. If it named a different database
        than the one under test, that log line would be the only warning, and it
        would be wrong at exactly the moment it was read.
        """
        with database_named("barket_e2e"):
            summary = seed_json("--reset")

        assert summary["database"] == "barket_e2e"
