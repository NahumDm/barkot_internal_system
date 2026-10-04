"""A23.1 through HTTP: the sale vertical, proved where a cashier actually meets it.

Roadmap B5 names its gate as "E2E A23.1: a Cashier records a sale, stock decreases
exactly once, income increases". That gate is about *data*, and until B5 no test in
this repository could assert it:

* ``apps/core/tests/test_idempotency.py`` proves the same guarantees one layer down,
  against :func:`apps.sales.services.complete_sale` directly. Its module docstring
  says why it stops there - A10 was Phase A's last task and no business endpoint
  existed to carry a request, so asserting at the service layer was the honest place.
* The contract suite asserts declared attributes, which is why it happily passed a
  ``/api/v1/products/categories/`` route that resolved to a product retrieve and a
  ``POST .../prices/`` route that answered 405. Both shipped green.
* The Playwright suite stubs ``/auth/me/`` at the network layer because ``next start``
  runs with no Django behind it, so no browser test written in the current harness can
  observe stock or income.

So the layer that is left - the one a cashier's browser actually crosses - was the one
with no coverage. This module posts to ``/api/v1/sales/`` as a signed-in Cashier over a
real session and a real database, and then reads the consequences back through the two
services that own them: :func:`apps.inventory.services.current_stock` for stock on
hand, and :func:`apps.finance.services.income_by_method` for the money.

The assertions are deliberately about *exactly once*. A sale that drew stock down twice
or booked income twice would still satisfy "stock decreases, income increases", and
that is the failure a till actually suffers: a double-tap on a flaky connection, a
retried request, an impatient cashier. Each test below therefore counts ledger rows and
compares a balance, rather than only checking that the numbers moved.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import Role
from apps.core.business_time import business_date, now_utc
from apps.core.enums import (
    MovementDirection,
    MovementKind,
    PaymentMethod,
    PaymentStatus,
    SaleStatus,
)
from apps.core.exceptions import InsufficientStock
from apps.finance.services import income_by_method
from apps.inventory.models import StockMovement
from apps.inventory.services import ReceiptLineInput, current_stock, receive_stock
from apps.products.models import Category, Product, ProductPrice
from apps.sales.models import Sale

pytestmark = pytest.mark.django_db

#: Catalogue price for the fixture product. Deliberately not a round number times a
#: round quantity that lands on a round total, so a total asserted below is evidence
#: of multiplication rather than of a coincidence.
UNIT_PRICE = Decimal("25.00")

#: Received into stock before every test, so a test that fails on quantity fails
#: loudly instead of accidentally passing on an empty ledger.
STOCKED = Decimal("40")

#: How many the cashier sells, and what that is worth.
SOLD = Decimal("3")
EXPECTED_TOTAL = Decimal("75.00")

SALES_URL = "/api/v1/sales/"


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def category() -> Category:
    return Category.objects.create(name="Beverages", display_order=1)


@pytest.fixture
def product(category: Category) -> Product:
    return Product.objects.create(
        category=category,
        name="Coffee 250g",
        sku="BEV-COF-250",
        is_stock_tracked=True,
    )


@pytest.fixture
def stocked(product: Product) -> Product:
    """A product that is priced and on the shelf.

    ``receive_stock`` rather than a hand-written ``StockMovement`` so the opening
    balance is produced by the same ledger the sale draws down, and the starting point
    is one the application would actually recognise.
    """
    ProductPrice.objects.create(
        product=product,
        unit_price=UNIT_PRICE,
        effective_from=now_utc(),
    )
    receive_stock(
        supplier_name="Test Supplier",
        lines=[ReceiptLineInput(product=product, quantity=STOCKED, unit_cost=Decimal("18.00"))],
    )
    return product


# There is deliberately no ``cashier`` or ``manager`` fixture here. ``staff_login``
# creates the user it signs in, and a second fixture creating the same role would
# collide on the username - a failure that reads like a permissions bug and is not one.


# ---------------------------------------------------------------------------- helpers


def sale_body(product: Product, *, quantity: Decimal = SOLD, **extra: Any) -> dict[str, Any]:
    """Return a ``POST /api/v1/sales/`` body for ``quantity`` of ``product``.

    The price is deliberately left out of the body. Supplying ``unit_price`` would let
    the sale bypass price resolution, which is one of the things worth crossing this
    layer to observe.

    Args:
        product: The product being sold.
        quantity: How many units to sell.
        **extra: Further body fields, e.g. ``idempotency_key``.

    Returns:
        A JSON-ready request body.
    """
    return {
        "lines": [{"product": product.pk, "quantity": str(quantity)}],
        "payments": [{"method": PaymentMethod.CASH, "amount": str(EXPECTED_TOTAL)}],
        **extra,
    }


def post_sale(client: Client, product: Product, *, quantity: Decimal = SOLD, **extra: Any) -> Any:
    """Record a sale as the signed-in client and return the response."""
    return client.post(
        SALES_URL,
        data=sale_body(product, quantity=quantity, **extra),
        content_type="application/json",
    )


def today() -> Any:
    """Return today's business-local date, the unit ``income_by_method`` reports in."""
    return business_date(now_utc())


def cash_income() -> Decimal:
    """Return cash income recorded for today across every completed sale."""
    return income_by_method(start=today(), end=today())[PaymentMethod.CASH]


def sale_movements(product: Product) -> Any:
    """Return the outbound movements a sale has written for ``product``."""
    return StockMovement.objects.filter(
        product=product,
        kind=MovementKind.SALE,
        direction=MovementDirection.OUT,
    )


# ------------------------------------------------------------------- 1. the A23.1 gate


def test_a_cashier_records_a_sale_and_stock_drops_exactly_once(
    client: Client, staff_login: Callable[..., Any], stocked: Product
) -> None:
    """The B5 gate, stated the way the roadmap states it.

    A Cashier - the lowest role that may sell - books a sale over HTTP, and the two
    consequences that make a till trustworthy are both visible: stock on hand falls by
    what was sold and no more, and the money appears in income for the day.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as a given role.
        stocked: A priced product with ``STOCKED`` units received.
    """
    staff_login(client, Role.Code.CASHIER)

    assert current_stock(stocked) == STOCKED
    assert cash_income() == Decimal("0.00")

    response = post_sale(client, stocked)

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["status"] == SaleStatus.COMPLETED
    assert body["payment_status"] == PaymentStatus.PAID
    assert Decimal(body["total"]) == EXPECTED_TOTAL
    assert len(body["items"]) == 1
    assert Decimal(body["items"][0]["quantity"]) == SOLD

    # "Exactly once" is the whole claim: the balance moved by the quantity sold, and
    # the ledger holds a single row saying so.
    assert current_stock(stocked) == STOCKED - SOLD
    assert sale_movements(stocked).count() == 1
    assert sale_movements(stocked).get().quantity == SOLD

    assert cash_income() == EXPECTED_TOTAL
    assert Sale.objects.count() == 1


def test_stock_that_is_not_there_is_refused_and_writes_nothing(
    client: Client, staff_login: Callable[..., Any], stocked: Product
) -> None:
    """A refused sale leaves no sale, no movement and no income behind.

    ``complete_sale`` checks stock for every line before it writes anything, so a
    basket that cannot be filled must leave the ledger untouched rather than
    half-drawn. Asserting the absence of rows is what catches a service that validates
    lazily, one line at a time.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as a given role.
        stocked: A priced product with ``STOCKED`` units received.
    """
    staff_login(client, Role.Code.CASHIER)

    response = post_sale(client, stocked, quantity=STOCKED + Decimal("1"))

    # 409, not 400: the request is well formed and the basket is real, it just
    # disagrees with the state of the shelf. The code is asserted as well as the status
    # because the status alone would not tell a client whether to prompt for a smaller
    # quantity or to show a validation error.
    assert response.status_code == InsufficientStock.status_code
    assert response.json()["error"]["code"] == InsufficientStock.code

    assert current_stock(stocked) == STOCKED
    assert sale_movements(stocked).count() == 0
    assert Sale.objects.count() == 0
    assert cash_income() == Decimal("0.00")


def test_the_same_idempotency_key_twice_draws_down_stock_once(
    client: Client, staff_login: Callable[..., Any], stocked: Product
) -> None:
    """A retried request replays the first sale instead of selling again.

    The double-tap that a real till produces. Both responses describe the same sale,
    and the till is drawn down once.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as a given role.
        stocked: A priced product with ``STOCKED`` units received.
    """
    staff_login(client, Role.Code.CASHIER)

    first = post_sale(client, stocked, idempotency_key="pos-1-0001")
    second = post_sale(client, stocked, idempotency_key="pos-1-0001")

    assert first.status_code == 201, first.content
    assert second.status_code == 201, second.content
    assert second.json()["reference"] == first.json()["reference"]

    assert current_stock(stocked) == STOCKED - SOLD
    assert sale_movements(stocked).count() == 1
    assert cash_income() == EXPECTED_TOTAL
    assert Sale.objects.count() == 1


# ------------------------------------------------------------- 2. the reversal, and who


def test_voiding_a_sale_returns_the_stock_once_and_withdraws_the_income(
    client: Client, staff_login: Callable[..., Any], stocked: Product
) -> None:
    """A void is an audited reversal, not a delete, and it lands in the ledger once.

    ``SALE_VOID`` is a distinct kind from ``SALE`` precisely so the return cannot be
    recorded as a second sale and subtract the stock twice. That is asserted here by
    counting rows rather than by trusting the name.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as a given role.
        stocked: A priced product with ``STOCKED`` units received.
    """
    staff_login(client, Role.Code.CASHIER)
    created = post_sale(client, stocked)
    assert created.status_code == 201, created.content
    body = created.json()
    # The detail route is keyed on the id, not the human reference. Asking for the
    # reference 404s, which is worth stating here because the reference is what the
    # UI shows and the id is what the API needs.
    void_url = f"{SALES_URL}{body['id']}/void/"
    assert body["reference"].startswith("S-")

    # A Cashier may sell but not void; the reversal is a Manager's decision.
    refused = client.post(
        void_url,
        data={"reason": "customer changed their mind"},
        content_type="application/json",
    )
    assert refused.status_code == 403

    staff_login(client, Role.Code.MANAGER)
    voided = client.post(
        void_url,
        data={"reason": "customer changed their mind"},
        content_type="application/json",
    )

    assert voided.status_code == 204, voided.content

    assert current_stock(stocked) == STOCKED
    returns = StockMovement.objects.filter(
        product=stocked,
        kind=MovementKind.SALE_VOID,
        direction=MovementDirection.IN,
    )
    assert returns.count() == 1
    assert returns.get().quantity == SOLD

    assert cash_income() == Decimal("0.00")
    # The sale is still on file, marked voided: an audit trail beats a missing row.
    # The default manager hides voided sales, so both halves of that are asserted -
    # ``all_rows`` still has it, and the everyday queryset does not offer it up again.
    assert Sale.all_rows.count() == 1
    assert Sale.all_rows.get().status == SaleStatus.VOIDED
    assert Sale.objects.count() == 0


def test_a_sale_is_listed_with_its_total_for_a_cashier(
    client: Client, staff_login: Callable[..., Any], stocked: Product
) -> None:
    """The recorded sale is readable by the role that recorded it.

    The vertical is not finished when the write succeeds: the cashier needs the sale
    back in the day's list, with the payment state the till will reconcile against.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as a given role.
        stocked: A priced product with ``STOCKED`` units received.
    """
    staff_login(client, Role.Code.CASHIER)
    assert post_sale(client, stocked).status_code == 201

    listed = client.get(SALES_URL)

    assert listed.status_code == 200, listed.content
    page = listed.json()
    assert page["count"] == 1
    row = page["results"][0]
    assert row["payment_status"] == PaymentStatus.PAID
    assert row["payment_status_display"]
    assert Decimal(row["total"]) == EXPECTED_TOTAL
