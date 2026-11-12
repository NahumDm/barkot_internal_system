"""C1 finance API acceptance tests."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import Role
from apps.finance.models import Expense, ExpenseCategory

pytestmark = pytest.mark.django_db

BALANCE_URL = "/api/v1/finance/balance/"
CATEGORIES_URL = "/api/v1/finance/categories/"
EXPENSES_URL = "/api/v1/finance/expenses/"
PERIOD = {"start": "2026-10-01", "end": "2026-10-31"}


@pytest.fixture
def category() -> ExpenseCategory:
    return ExpenseCategory.objects.create(name="Utilities")


def test_balance_requires_an_explicit_business_date_range(client: Client, staff_login: Any) -> None:
    staff_login(client, Role.Code.MANAGER)

    response = client.get(BALANCE_URL)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
    assert set(response.json()["error"]["details"]) == {"start", "end"}


def test_manager_can_read_a_business_balance(client: Client, staff_login: Any) -> None:
    staff_login(client, Role.Code.MANAGER)

    response = client.get(BALANCE_URL, PERIOD)

    assert response.status_code == 200, response.content
    assert response.json() == {
        "period_start": PERIOD["start"],
        "period_end": PERIOD["end"],
        "currency": "ETB",
        "income": {"cash": "0.00", "mobile_banking": "0.00", "total": "0.00"},
        "expenses_total": "0.00",
        "expense_breakdown": {},
        "payroll_total": "0.00",
        "net": "0.00",
    }


def test_cashier_cannot_read_finance_reports(client: Client, staff_login: Any) -> None:
    staff_login(client, Role.Code.CASHIER)

    response = client.get(BALANCE_URL, PERIOD)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_manager_records_and_approves_an_expense(
    client: Client, staff_login: Any, category: ExpenseCategory
) -> None:
    manager = staff_login(client, Role.Code.MANAGER)
    create_response = client.post(
        EXPENSES_URL,
        {
            "category": category.pk,
            "description": "Electricity",
            "amount": "125.50",
            "currency": "ETB",
            "incurred_on": "2026-10-10",
        },
        content_type="application/json",
    )

    assert create_response.status_code == 201, create_response.content
    expense_id = create_response.json()["id"]
    expense = Expense.objects.get(pk=expense_id)
    assert expense.created_by == manager
    assert expense.status == "RECORDED"

    approve_response = client.post(f"{EXPENSES_URL}{expense_id}/approve/")

    assert approve_response.status_code == 200, approve_response.content
    assert approve_response.json()["status"] == "APPROVED"
    assert Expense.objects.get(pk=expense_id).approved_by == manager

    balance_response = client.get(BALANCE_URL, PERIOD)
    assert balance_response.status_code == 200
    assert Decimal(balance_response.json()["expenses_total"]) == Decimal("125.50")
    assert Decimal(balance_response.json()["net"]) == Decimal("-125.50")


def test_cashier_cannot_record_an_expense(
    client: Client, staff_login: Any, category: ExpenseCategory
) -> None:
    staff_login(client, Role.Code.CASHIER)

    response = client.post(
        EXPENSES_URL,
        {
            "category": category.pk,
            "description": "Electricity",
            "amount": "125.50",
            "currency": "ETB",
            "incurred_on": "2026-10-10",
        },
        content_type="application/json",
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_owner_can_create_an_expense_category(client: Client, staff_login: Any) -> None:
    staff_login(client, Role.Code.OWNER)

    response = client.post(
        CATEGORIES_URL,
        {"name": "Maintenance", "description": "Repairs and upkeep"},
        content_type="application/json",
    )

    assert response.status_code == 201, response.content
    assert response.json()["name"] == "Maintenance"
