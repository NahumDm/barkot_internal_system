"""C6 dashboard API acceptance tests.

The behaviour under test is that the dashboard is a read-only, role-scoped
summary over already-authoritative data (spec §7.4, §6.2): every tile delegates
to the domain service the source screen already answers with, a section is
present only when the requesting role holds the backing permission, and the
figures reconcile byte for byte to the endpoints that own them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import Role
from apps.core.business_time import business_date, now_utc
from apps.finance.models import ExpenseCategory
from apps.inventory.services import ReceiptLineInput, receive_stock
from apps.products.models import Category, Product, ProductPrice
from apps.sales.models import PaymentMethod
from apps.sales.services import SaleLineInput, complete_sale

pytestmark = pytest.mark.django_db

DASHBOARD_URL = "/api/v1/dashboard/"
BALANCE_URL = "/api/v1/finance/balance/"
STOCK_BALANCE_URL = "/api/v1/reports/inventory/stock-balance/"
FINANCIAL_REPORT_URL = "/api/v1/reports/financial/"
EXPENSES_URL = "/api/v1/finance/expenses/"
RUNS_URL = "/api/v1/payroll/runs/"


def between(start: date, end: date) -> dict[str, str]:
    """A dashboard query string for an inclusive business-date range."""
    return {"start": start.isoformat(), "end": end.isoformat()}


def today() -> date:
    """Today's business-local date, the day newly created rows fall on."""
    return business_date(now_utc())


@pytest.fixture
def beverage() -> Product:
    category = Category.objects.create(name="Beverages", display_order=1)
    return Product.objects.create(
        category=category,
        name="Test Lager",
        sku="DSH-LAGER-001",
        is_stock_tracked=True,
    )


@pytest.fixture
def stocked(beverage: Product) -> Product:
    """A priced, stocked product, so a sale drawn in a test can complete."""
    ProductPrice.objects.create(
        product=beverage, unit_price=Decimal("25.00"), effective_from=now_utc()
    )
    seed_receipt(beverage, quantity="40")
    return beverage


@pytest.fixture
def employee() -> Any:
    from apps.payroll.models import Employee
    from apps.users.models import EmployeeProfile

    profile = EmployeeProfile.objects.create(
        full_name="Selam Bekele",
        position="Head Cashier",
        phone_number="+251911234567",
        start_date="2026-01-05",
    )
    return Employee.from_profile(profile, monthly_wage=Decimal("18000.00"))


def seed_receipt(product: Product, quantity: str = "12") -> None:
    """Give ``product`` an opening ledger through the same service a receipt uses."""
    receive_stock(
        supplier_name="Test Supplier",
        lines=[
            ReceiptLineInput(product=product, quantity=Decimal(quantity), unit_cost=Decimal("18"))
        ],
    )


def generate_run(client: Client) -> dict[str, Any]:
    """Generate an October payroll run as the signed-in user."""
    return client.post(
        RUNS_URL, {"period": "2026-10-09", "notes": "October"}, content_type="application/json"
    ).json()


def test_anonymous_access_is_refused(client: Client) -> None:
    response = client.get(DASHBOARD_URL)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_shopfloor_roles_see_only_the_tiles_they_may_read(client: Client, staff_login: Any) -> None:
    """A Cashier or Barman gets sales and inventory, and a null finance/payroll tile."""
    for role in (Role.Code.CASHIER, Role.Code.BARMAN):
        staff_login(client, role)

        response = client.get(DASHBOARD_URL)

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["sales"] is not None
        assert body["inventory"] is not None
        assert body["finance"] is None
        assert body["payroll"] is None


def test_default_period_is_the_current_month_to_date(client: Client, staff_login: Any) -> None:
    staff_login(client, Role.Code.MANAGER)

    response = client.get(DASHBOARD_URL)

    assert response.status_code == 200, response.content
    period = response.json()["period"]
    assert period["start"] == today().replace(day=1).isoformat()
    assert period["end"] == today().isoformat()


def test_start_and_end_must_be_supplied_together(client: Client, staff_login: Any) -> None:
    staff_login(client, Role.Code.MANAGER)

    one_bound = client.get(DASHBOARD_URL, {"start": today().isoformat()})
    assert one_bound.status_code == 400
    assert one_bound.json()["error"]["code"] == "validation_error"

    reversed_period = client.get(DASHBOARD_URL, between(today(), today().replace(day=1)))
    assert reversed_period.status_code == 400
    assert reversed_period.json()["error"]["code"] == "validation_error"


def test_dashboard_finance_matches_the_balance_endpoint_exactly(
    client: Client, staff_login: Any, stocked: Product
) -> None:
    """The finance tile reuses ``finance_balance``; it must not re-derive anything."""
    staff_login(client, Role.Code.MANAGER)
    complete_sale(
        lines=[SaleLineInput(product=stocked, quantity=Decimal("3"))],
        payments=[(PaymentMethod.CASH, Decimal("75.00"))],
    )
    period = between(today(), today())

    response = client.get(DASHBOARD_URL, period)
    assert response.status_code == 200, response.content
    balance = client.get(BALANCE_URL, period)
    report = client.get(FINANCIAL_REPORT_URL, period)

    assert response.json()["finance"] == balance.json() == report.json()


def test_dashboard_inventory_matches_the_stock_balance_report(
    client: Client, staff_login: Any, beverage: Product
) -> None:
    """The inventory tile reuses the C4 stock-balance query."""
    staff_login(client, Role.Code.MANAGER)
    seed_receipt(beverage, quantity="12")

    response = client.get(DASHBOARD_URL, between(today(), today()))
    assert response.status_code == 200, response.content
    report = client.get(STOCK_BALANCE_URL, {"date": today().isoformat()})

    inventory = response.json()["inventory"]
    assert inventory == {
        "as_of": report.json()["as_of"],
        "in_stock_total": report.json()["in_stock_total"],
        "products": report.json()["products"],
    }
    assert inventory["in_stock_total"] == "12.000"


def test_owner_sees_reconciled_tiles_for_a_seeded_period(
    client: Client, staff_login: Any, stocked: Product, employee: Any
) -> None:
    # Generating a run is the Owner's grant (spec §9.2), so the whole seeded
    # period is set up from one Owner session rather than mixed roles.
    staff_login(client, Role.Code.OWNER)
    complete_sale(
        lines=[SaleLineInput(product=stocked, quantity=Decimal("3"))],
        payments=[(PaymentMethod.CASH, Decimal("75.00"))],
    )
    category = ExpenseCategory.objects.create(name="Utilities")
    recorded = client.post(
        EXPENSES_URL,
        {
            "category": category.pk,
            "description": "Electricity",
            "amount": "125.50",
            "currency": "ETB",
            "incurred_on": today().isoformat(),
        },
        content_type="application/json",
    )
    assert recorded.status_code == 201
    assert client.post(f"{EXPENSES_URL}{recorded.json()['id']}/approve/").status_code == 200
    generate_run(client)

    response = client.get(DASHBOARD_URL)
    assert response.status_code == 200, response.content
    body = response.json()

    sales = body["sales"]
    assert sales["total"] == "75.00"
    assert sales["cash"] == "75.00"
    assert sales["mobile_banking"] == "0.00"
    assert sales["transactions"] == 1
    assert len(sales["recent"]) == 1
    assert sales["recent"][0]["reference"].startswith("S-")
    assert sales["recent"][0]["total"] == "75.00"

    inventory = body["inventory"]
    assert inventory["products"] == 1
    assert inventory["in_stock_total"] == "37.000"

    finance = body["finance"]
    assert finance["period_start"] == today().replace(day=1).isoformat()
    assert finance["income"]["total"] == "75.00"
    assert finance["expenses_total"] == "125.50"
    # A GENERATED run is a proposal and must not move the balance.
    assert finance["payroll_total"] == "0.00"
    assert finance["net"] == "-50.50"

    payroll = body["payroll"]
    assert payroll["status"] == "GENERATED"
    assert payroll["period_month"] == "2026-10-01"
    assert payroll["gross_total"] == "18000.00"
    assert payroll["net_total"] == "18000.00"
    assert payroll["approved_by"] is None
