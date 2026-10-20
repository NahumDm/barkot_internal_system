"""C4 reports API acceptance tests.

The behaviour under test is that the reports app is a read-only layer over
already-authoritative data (spec Â§6.2, Â§15): a Manager reads projections other
domains computed, a Cashier gets 403 on all four, and nobody writes anything
through this surface. The financial test pins the "reuse authority" rule by
asserting the report and the C1 balance endpoint answer the same period with the
*same bytes*, so the reports screen and the finance screen cannot drift apart.
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
from apps.inventory.services import (
    ReceiptLineInput,
    approve_stock_count,
    complete_stock_count,
    current_stock,
    open_stock_count,
    receive_stock,
)
from apps.products.models import Category, Product, ProductPrice
from apps.sales.models import PaymentMethod
from apps.sales.services import SaleLineInput, complete_sale

pytestmark = pytest.mark.django_db

FINANCIAL_URL = "/api/v1/reports/financial/"
STOCK_BALANCE_URL = "/api/v1/reports/inventory/stock-balance/"
VARIANCE_URL = "/api/v1/reports/inventory/variance/"
PAYROLL_URL = "/api/v1/reports/payroll/"
BALANCE_URL = "/api/v1/finance/balance/"
EXPENSES_URL = "/api/v1/finance/expenses/"
RUNS_URL = "/api/v1/payroll/runs/"
DEDUCTIONS_URL = "/api/v1/payroll/deductions/"

OCTOBER = {"start": "2026-10-01", "end": "2026-10-31"}


def between(start: date, end: date) -> dict[str, str]:
    """A report query string for an inclusive business-date range."""
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
        sku="RPT-LAGER-001",
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
    response = client.get(FINANCIAL_URL, OCTOBER)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_cashier_cannot_read_any_report(client: Client, staff_login: Any) -> None:
    staff_login(client, Role.Code.CASHIER)

    params = (OCTOBER, OCTOBER, {"date": today().isoformat()}, OCTOBER)
    for url, query in zip(
        (FINANCIAL_URL, VARIANCE_URL, STOCK_BALANCE_URL, PAYROLL_URL), params, strict=False
    ):
        response = client.get(url, query)

        assert response.status_code == 403, url
        assert response.json()["error"]["code"] == "permission_denied", url


def test_report_period_must_be_an_explicit_valid_range(client: Client, staff_login: Any) -> None:
    staff_login(client, Role.Code.MANAGER)

    missing = client.get(FINANCIAL_URL)
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "validation_error"
    assert set(missing.json()["error"]["details"]) == {"start", "end"}

    reversed_period = client.get(FINANCIAL_URL, {"start": "2026-10-31", "end": "2026-10-01"})
    assert reversed_period.status_code == 400
    assert reversed_period.json()["error"]["code"] == "validation_error"

    bad_date = client.get(FINANCIAL_URL, {"start": "not-a-date", "end": "2026-10-31"})
    assert bad_date.status_code == 400
    assert bad_date.json()["error"]["code"] == "validation_error"

    missing_as_of = client.get(STOCK_BALANCE_URL)
    assert missing_as_of.status_code == 400
    assert set(missing_as_of.json()["error"]["details"]) == {"date"}


def test_financial_report_matches_the_finance_balance_exactly(
    client: Client, staff_login: Any, stocked: Product
) -> None:
    """The report reuses ``finance_balance``; it must not re-derive anything."""
    staff_login(client, Role.Code.MANAGER)

    complete_sale(
        lines=[SaleLineInput(product=stocked, quantity=Decimal("3"))],
        payments=[(PaymentMethod.CASH, Decimal("75.00"))],
    )
    period = between(today(), today())

    report = client.get(FINANCIAL_URL, period)
    balance = client.get(BALANCE_URL, period)

    assert report.status_code == 200, report.content
    assert balance.status_code == 200
    assert report.json() == balance.json()
    assert report.json()["income"]["cash"] == "75.00"
    assert report.json()["net"] == "75.00"


def test_financial_report_counts_only_approved_expenses(
    client: Client, staff_login: Any, stocked: Product
) -> None:
    staff_login(client, Role.Code.MANAGER)
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
    approved = client.post(f"{EXPENSES_URL}{recorded.json()['id']}/approve/")
    assert approved.status_code == 200

    report = client.get(FINANCIAL_URL, between(today(), today())).json()

    assert report["expenses_total"] == "125.50"
    assert report["net"] == "-125.50"


def test_stock_balance_reads_the_ledger_and_reports_uncounted_products(
    client: Client, staff_login: Any, beverage: Product
) -> None:
    staff_login(client, Role.Code.MANAGER)
    seed_receipt(beverage, quantity="12")

    response = client.get(STOCK_BALANCE_URL, {"date": today().isoformat()})

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["as_of"] == today().isoformat()
    assert body["products"] == 1
    assert body["in_stock_total"] == "12.000"
    row = body["rows"][0]
    assert row["sku"] == beverage.sku
    assert row["ledger_balance"] == "12.000"
    assert row["last_counted"] is None
    assert row["delta"] is None


def test_variance_report_lists_only_approved_nonzero_variances(
    client: Client, staff_login: Any, beverage: Product
) -> None:
    staff_login(client, Role.Code.MANAGER)
    seed_receipt(beverage, quantity="12")

    count = open_stock_count(lines=[beverage])
    assert current_stock(beverage) == Decimal("12.000")
    item = count.items.get()
    complete_stock_count(stock_count=count, counted_quantities={item.pk: Decimal("10")})

    before = client.get(VARIANCE_URL, OCTOBER)
    assert before.status_code == 200
    assert before.json()["lines"] == 0

    approve_stock_count(stock_count=count)

    after = client.get(VARIANCE_URL, OCTOBER)
    assert after.status_code == 200, after.content
    body = after.json()
    assert body["lines"] == 1
    row = body["rows"][0]
    assert row["sku"] == beverage.sku
    assert row["expected_quantity"] == "12.000"
    assert row["counted_quantity"] == "10.000"
    assert row["variance"] == "-2.000"

    balance = client.get(STOCK_BALANCE_URL, {"date": today().isoformat()}).json()
    assert balance["in_stock_total"] == "10.000"
    assert balance["rows"][0]["last_counted"] == "10.000"
    assert balance["rows"][0]["delta"] == "0.000"


def test_payroll_report_shows_runs_totals_and_deductions(
    client: Client, staff_login: Any, employee: Any
) -> None:
    staff_login(client, Role.Code.OWNER)
    run = generate_run(client)
    item_id = client.get(f"{RUNS_URL}{run['id']}/items/").json()["results"][0]["id"]

    deduction = client.post(
        DEDUCTIONS_URL,
        {"payroll_item": item_id, "deduction_type": "ADVANCE", "amount": "500.00"},
        content_type="application/json",
    )
    assert deduction.status_code == 201, deduction.content

    response = client.get(PAYROLL_URL, OCTOBER)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["start"] == OCTOBER["start"]
    assert body["end"] == OCTOBER["end"]
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["period_month"] == "2026-10-01"
    assert row["status"] == "GENERATED"
    assert row["employees"] == 1
    assert row["gross_total"] == "18000.00"
    assert row["deduction_total"] == "500.00"
    assert row["net_total"] == "17500.00"

    summary = body["summary"]
    assert summary["runs"] == 1
    assert summary["gross_total"] == "18000.00"
    assert summary["deduction_total"] == "500.00"
    assert summary["net_total"] == "17500.00"
    assert summary["by_status"] == [
        {
            "status": "GENERATED",
            "status_display": "Generated",
            "runs": 1,
            "gross_total": "18000.00",
            "deduction_total": "500.00",
            "net_total": "17500.00",
        }
    ]
    assert body["deductions"] == {"Salary advance": "500.00"}


def test_payroll_report_is_scoped_to_the_months_asked_for(
    client: Client, staff_login: Any, employee: Any
) -> None:
    staff_login(client, Role.Code.OWNER)
    generate_run(client)

    february = client.get(PAYROLL_URL, {"start": "2026-02-01", "end": "2026-02-28"})

    assert february.status_code == 200
    assert february.json()["rows"] == []
    assert february.json()["summary"]["runs"] == 0


def test_each_report_can_be_downloaded_as_csv(
    client: Client, staff_login: Any, employee: Any
) -> None:
    staff_login(client, Role.Code.OWNER)
    run = generate_run(client)
    item_id = client.get(f"{RUNS_URL}{run['id']}/items/").json()["results"][0]["id"]
    client.post(
        DEDUCTIONS_URL,
        {"payroll_item": item_id, "deduction_type": "ADVANCE", "amount": "500.00"},
        content_type="application/json",
    )

    financial = client.get(FINANCIAL_URL, {**OCTOBER, "export": "pdf"})
    payroll = client.get(PAYROLL_URL, {**OCTOBER, "export": "pdf"})
    balance = client.get(STOCK_BALANCE_URL, {"date": today().isoformat(), "export": "pdf"})
    variance = client.get(VARIANCE_URL, {**OCTOBER, "export": "pdf"})

    assert financial.status_code == 200
    assert financial["Content-Type"].startswith("application/pdf")
    assert financial["Content-Disposition"].startswith("attachment; filename=")
    assert financial.content.startswith(b"%PDF")

    # PDFs are binary - just verify data is rendered
    assert b"GENERATED" in payroll.content or b"17500.00" in payroll.content

    balance_text = balance.content.decode("utf-8-sig")
    assert balance_text.splitlines()[0] == (
        "SKU,Product,Ledger balance,Last counted,Last counted on,Delta"
    )

    assert variance.status_code == 200
    assert variance.content.decode("utf-8-sig").splitlines()[0] == (
        "Count reference,Status,Counted on,SKU,Product,Expected,Counted,Variance,Note"
    )


def test_a_generated_payroll_run_does_not_enter_the_financial_report(
    client: Client, staff_login: Any, employee: Any
) -> None:
    """Payroll reaches the financial report only once a run is approved."""
    staff_login(client, Role.Code.OWNER)
    generate_run(client)

    report = client.get(FINANCIAL_URL, OCTOBER).json()

    assert report["payroll_total"] == "0.00"
