"""HTTP-level Bono tests: role gates, response shapes and the full report flow."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import Role
from apps.bono.models import BonoReportStatus
from apps.bono.services import (
    create_issue,
    create_report,
    submit_report,
    update_report,
)
from apps.core.enums import PaymentMethod
from apps.core.money import CURRENCY
from apps.products.services import set_product_price
from apps.sales.services import SaleLineInput, complete_sale

pytestmark = pytest.mark.django_db

TYPES_URL = "/api/v1/bono/types/"
PAIRINGS_URL = "/api/v1/bono/pairings/"
ISSUES_URL = "/api/v1/bono/issues/"
REPORTS_URL = "/api/v1/bono/reports/"
SUMMARY_URL = "/api/v1/bono/summary/"
SALES_URL = "/api/v1/sales/"


def _create_type(client: Client, name: str = "API Bono") -> Any:
    response = client.post(
        TYPES_URL,
        {"name": name, "color": "#0F766E", "selling_price": "25.00"},
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    return response.json()


def _pair(client: Client, bono_type_id: int, product: Any) -> Any:
    response = client.post(
        f"{TYPES_URL}{bono_type_id}/products/",
        {"products": [product.pk]},
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    return response.json()


def _prepare_report(
    *,
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
    receive: Any,
    yesterday: Any,
) -> Any:
    from datetime import timedelta

    from apps.core.business_time import business_day_bounds

    start, _end = business_day_bounds(yesterday)
    receive(product, Decimal("40"), at=start + timedelta(hours=12))
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind="INITIAL",
        quantity=2,
    )
    complete_sale(
        lines=[SaleLineInput(product=product, quantity=Decimal("2"))],
        payments=[(PaymentMethod.CASH, Decimal("50.00"))],
    )
    report = create_report(operational_date=today)
    bono_line = report.bono_lines.get()
    product_line = report.product_lines.get()
    update_report(
        report=report,
        bono_lines=[{"id": bono_line.pk, "used_quantity": 2}],
        product_lines=[{"id": product_line.pk, "physical_closing_quantity": "38.000"}],
    )
    return report


def test_the_owner_creates_a_type_and_pairs_an_equal_price_product(
    client: Client,
    staff_login: Any,
    make_product: Any,
) -> None:
    staff_login(client, Role.Code.OWNER)
    product = make_product(name="API Beer", sku="API-BEER-001")

    created = _create_type(client, name="API House Bono")
    paired = _pair(client, created["id"], product)

    assert created["code"]
    assert created["selling_price"] == "25.00"
    assert created["currency"] == CURRENCY
    assert len(paired["active_pairings"]) == 1
    assert paired["active_pairings"][0]["product"] == product.pk
    assert paired["active_pairings"][0]["price_at_pairing"] == "25.00"


@pytest.mark.parametrize(
    "role",
    [Role.Code.MANAGER, Role.Code.CASHIER, Role.Code.BARMAN],
)
def test_configuration_is_owner_only(
    client: Client,
    staff_login: Any,
    role: str,
) -> None:
    staff_login(client, role)

    response = client.post(
        TYPES_URL,
        {"name": f"{role} Bono", "selling_price": "25.00"},
        content_type="application/json",
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_a_manager_records_issues_but_a_cashier_or_barman_cannot(
    client: Client,
    staff_login: Any,
    paired: Any,
    employee: Any,
    today: Any,
) -> None:
    staff_login(client, Role.Code.MANAGER)
    created = client.post(
        ISSUES_URL,
        {
            "operational_date": today.isoformat(),
            "bono_type": paired.pk,
            "employee": employee.pk,
            "kind": "INITIAL",
            "quantity": 3,
        },
        content_type="application/json",
    )
    assert created.status_code == 201, created.content
    assert created.json()["quantity"] == 3

    client.logout()
    staff_login(client, Role.Code.CASHIER)
    refused = client.post(
        ISSUES_URL,
        {
            "operational_date": today.isoformat(),
            "bono_type": paired.pk,
            "employee": employee.pk,
            "kind": "ADDITIONAL",
            "quantity": 1,
        },
        content_type="application/json",
    )
    assert refused.status_code == 403

    client.logout()
    staff_login(client, Role.Code.BARMAN)
    refused = client.post(
        ISSUES_URL,
        {
            "operational_date": today.isoformat(),
            "bono_type": paired.pk,
            "employee": employee.pk,
            "kind": "ADDITIONAL",
            "quantity": 1,
        },
        content_type="application/json",
    )
    assert refused.status_code == 403


def test_the_cashier_prepares_the_report_and_the_manager_cannot_submit_it(
    client: Client,
    staff_login: Any,
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
    yesterday: Any,
    receive: Any,
) -> None:
    _prepare_report(
        paired=paired,
        product=product,
        employee=employee,
        today=today,
        receive=receive,
        yesterday=yesterday,
    )

    staff_login(client, Role.Code.CASHIER)
    response = client.post(
        REPORTS_URL,
        {"operational_date": (today.isoformat())},
        content_type="application/json",
    )
    # A draft already exists from the service setup, so the API refusal here is
    # the conflict a second report must get, not a permission failure.
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "bono_type_conflict"

    client.logout()
    staff_login(client, Role.Code.MANAGER)
    response = client.post(
        REPORTS_URL,
        {"operational_date": today.isoformat()},
        content_type="application/json",
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_only_the_owner_approves_and_corrects_reports(
    client: Client,
    staff_login: Any,
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
    yesterday: Any,
    receive: Any,
) -> None:
    report = _prepare_report(
        paired=paired,
        product=product,
        employee=employee,
        today=today,
        receive=receive,
        yesterday=yesterday,
    )
    submit_report(report=report)

    staff_login(client, Role.Code.CASHIER)
    refused = client.post(f"{REPORTS_URL}{report.pk}/approve/")
    assert refused.status_code == 403

    client.logout()
    staff_login(client, Role.Code.MANAGER)
    refused = client.post(f"{REPORTS_URL}{report.pk}/approve/")
    assert refused.status_code == 403

    client.logout()
    staff_login(client, Role.Code.OWNER)
    approved = client.post(f"{REPORTS_URL}{report.pk}/approve/")
    assert approved.status_code == 200, approved.content
    assert approved.json()["status"] == "APPROVED"

    locked = client.patch(
        f"{REPORTS_URL}{report.pk}/",
        {"notes": "edited after approval"},
        content_type="application/json",
    )
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "bono_report_locked"

    corrected = client.post(
        f"{REPORTS_URL}{report.pk}/correct/",
        {"reason": "Correct the used count"},
        content_type="application/json",
    )
    assert corrected.status_code == 201, corrected.content
    assert corrected.json()["revision"] == 2
    assert corrected.json()["corrects"] == report.pk


def test_a_barman_reads_bono_operations_but_not_report_money_or_sales(
    client: Client,
    staff_login: Any,
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
    yesterday: Any,
    receive: Any,
) -> None:
    report = _prepare_report(
        paired=paired,
        product=product,
        employee=employee,
        today=today,
        receive=receive,
        yesterday=yesterday,
    )

    staff_login(client, Role.Code.BARMAN)
    summary = client.get(SUMMARY_URL, {"date": today.isoformat()})
    assert summary.status_code == 200, summary.content
    assert summary.json()["staff_balances"][0]["balance"] == 2

    assert client.get(ISSUES_URL).status_code == 200
    assert client.get(PAIRINGS_URL).status_code == 200
    assert client.get(TYPES_URL).status_code == 200

    detail = client.get(f"{REPORTS_URL}{report.pk}/")
    assert detail.status_code == 200, detail.content
    body = detail.json()
    assert body["bono_lines"]
    assert "sales_total" not in body
    assert "cash_paid_total" not in body
    assert "mobile_paid_total" not in body
    assert "payments_total" not in body

    assert client.get(SALES_URL).status_code == 403


def test_a_manager_can_read_reports_with_money_but_cannot_configure(
    client: Client,
    staff_login: Any,
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
    yesterday: Any,
    receive: Any,
) -> None:
    report = _prepare_report(
        paired=paired,
        product=product,
        employee=employee,
        today=today,
        receive=receive,
        yesterday=yesterday,
    )

    staff_login(client, Role.Code.MANAGER)
    detail = client.get(f"{REPORTS_URL}{report.pk}/")
    assert detail.status_code == 200
    assert detail.json()["sales_total"] == "50.00"

    history = client.get(f"{TYPES_URL}{paired.pk}/history/")
    assert history.status_code == 403


def test_a_manager_cannot_submit_a_cashier_report(
    client: Client,
    staff_login: Any,
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
    yesterday: Any,
    receive: Any,
) -> None:
    report = _prepare_report(
        paired=paired,
        product=product,
        employee=employee,
        today=today,
        receive=receive,
        yesterday=yesterday,
    )

    staff_login(client, Role.Code.MANAGER)
    refused = client.post(f"{REPORTS_URL}{report.pk}/submit/")
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "permission_denied"

    client.logout()
    staff_login(client, Role.Code.CASHIER)
    submitted = client.post(f"{REPORTS_URL}{report.pk}/submit/")
    assert submitted.status_code == 200, submitted.content
    assert submitted.json()["status"] == "SUBMITTED"


def test_owner_resolves_a_price_review_through_the_api(
    client: Client,
    staff_login: Any,
    paired: Any,
    product: Any,
) -> None:
    pairing = paired.pairings.get(product=product)
    set_product_price(
        product=product,
        unit_price=Decimal("30.00"),
        currency=CURRENCY,
    )

    staff_login(client, Role.Code.OWNER)
    response = client.post(
        f"{PAIRINGS_URL}{pairing.pk}/review/",
        {"resolution": "RETAIN", "reason": "New menu price"},
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    assert response.json()["selling_price"] == "30.00"
    pairing.refresh_from_db()
    assert pairing.review_required is False
    assert pairing.price_at_pairing == Decimal("30.00")


def test_a_cashier_can_open_a_draft_with_its_activity_lines(
    client: Client,
    staff_login: Any,
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
) -> None:
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind="INITIAL",
        quantity=1,
    )
    staff_login(client, Role.Code.CASHIER)

    response = client.post(
        REPORTS_URL,
        {"operational_date": today.isoformat()},
        content_type="application/json",
    )

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["status"] == BonoReportStatus.DRAFT
    assert body["sales_total"] == "0.00"
    assert body["bono_lines"]
    assert body["product_lines"][0]["product"] == product.pk
    assert body["product_lines"][0]["physical_closing_quantity"] is None


def test_an_anonymous_request_is_refused(client: Client) -> None:
    assert client.get(SUMMARY_URL).status_code == 401
    assert client.get(REPORTS_URL).status_code == 401
