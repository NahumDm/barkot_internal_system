"""Daily reconciliation and report lifecycle."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.bono.models import (
    BonoIncidentKind,
    BonoReportProductLine,
    BonoReportStatus,
)
from apps.bono.services import (
    add_pairings,
    approve_report,
    create_correction,
    create_incident,
    create_issue,
    create_report,
    refresh_report,
    reject_report,
    submit_report,
    update_report,
)
from apps.core.business_time import business_day_bounds
from apps.core.enums import PaymentMethod
from apps.core.exceptions import (
    BARKOTDomainError,
    BonoReportIncomplete,
    BonoReportLocked,
    BonoReportStale,
    BonoTypeConflict,
)
from apps.core.money import CURRENCY
from apps.sales.services import SaleLineInput, complete_sale, void_sale

pytestmark = pytest.mark.django_db


def _receive_yesterday(receive: Any, product: Any, yesterday: Any, quantity: int = 40) -> None:
    start, _end = business_day_bounds(yesterday)
    receive(product, Decimal(quantity), at=start + timedelta(hours=12))


def _sell(
    product: Any,
    *,
    quantity: int = 2,
    payments: list[tuple[PaymentMethod, Decimal]] | None = None,
) -> Any:
    payments = payments or [(PaymentMethod.CASH, Decimal("50.00"))]
    return complete_sale(
        lines=[SaleLineInput(product=product, quantity=Decimal(quantity))],
        payments=payments,
    )


def _prepare_draft(
    *,
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
    receive: Any,
    yesterday: Any,
) -> Any:
    _receive_yesterday(receive, product, yesterday)
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind="INITIAL",
        quantity=5,
    )
    create_incident(
        operational_date=today,
        kind=BonoIncidentKind.LOST_BONO,
        bono_type=paired,
        responsible_employee=employee,
        quantity=1,
        reason="Lost on the floor",
    )
    _sell(product)
    return create_report(operational_date=today)


def test_the_report_reconciles_opening_receipts_sales_breakage_and_physical_stock(
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
    yesterday: Any,
    receive: Any,
) -> None:
    _receive_yesterday(receive, product, yesterday, quantity=40)
    start, _end = business_day_bounds(today)
    receive(product, Decimal("10"), at=start + timedelta(hours=9))
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind="INITIAL",
        quantity=4,
    )
    sale = _sell(product, quantity=2)
    create_incident(
        operational_date=today,
        kind=BonoIncidentKind.BROKEN_BOTTLE,
        product=product,
        quantity=1,
        reason="Dropped a bottle",
    )

    report = create_report(operational_date=today)
    line = report.product_lines.get(product=product)

    assert line.opening_quantity == Decimal("40.000")
    assert line.received_quantity == Decimal("10.000")
    assert line.sold_quantity == Decimal("2.000")
    assert line.breakage_quantity == Decimal("1.000")
    assert line.expected_closing_quantity == Decimal("47.000")
    assert line.physical_closing_quantity is None
    assert report.sales_total == sale.total
    assert report.cash_paid_total == sale.total
    assert report.mobile_paid_total == Decimal("0.00")
    assert report.payments_total == sale.total
    assert report.currency == CURRENCY
    assert report.status == BonoReportStatus.DRAFT


def test_products_sharing_a_bono_type_keep_independent_stock_and_sales_rows(
    paired: Any,
    product: Any,
    second_product: Any,
    employee: Any,
    today: Any,
    yesterday: Any,
    receive: Any,
) -> None:
    add_pairings(bono_type=paired, products=[second_product])
    _receive_yesterday(receive, product, yesterday, quantity=40)
    _receive_yesterday(receive, second_product, yesterday, quantity=20)
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind="INITIAL",
        quantity=4,
    )
    _sell(product, quantity=3, payments=[(PaymentMethod.CASH, Decimal("75.00"))])
    _sell(second_product, quantity=1, payments=[(PaymentMethod.MOBILE_BANKING, Decimal("25.00"))])

    report = create_report(operational_date=today)
    lines = {line.product_id: line for line in report.product_lines.all()}

    assert lines[product.pk].sold_quantity == Decimal("3.000")
    assert lines[product.pk].expected_closing_quantity == Decimal("37.000")
    assert lines[second_product.pk].sold_quantity == Decimal("1.000")
    assert lines[second_product.pk].expected_closing_quantity == Decimal("19.000")
    # The shared token total is not allocated across products.
    assert report.bono_lines.get().initial_issued_quantity == 4
    assert report.cash_paid_total == Decimal("75.00")
    assert report.mobile_paid_total == Decimal("25.00")
    assert report.payments_total == Decimal("100.00")


def test_a_complete_report_is_priced_and_submitted_without_losing_manual_counts(
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
    yesterday: Any,
    receive: Any,
) -> None:
    report = _prepare_draft(
        paired=paired,
        product=product,
        employee=employee,
        today=today,
        receive=receive,
        yesterday=yesterday,
    )
    bono_line = report.bono_lines.get()
    product_line = report.product_lines.get()

    update_report(
        report=report,
        bono_lines=[
            {
                "id": bono_line.pk,
                "used_quantity": 2,
                "returned_quantity": 2,
                "explanation": "",
            }
        ],
        product_lines=[
            {
                "id": product_line.pk,
                "physical_closing_quantity": "38.000",
            }
        ],
    )

    submitted = submit_report(report=report)

    assert submitted.status == BonoReportStatus.SUBMITTED
    line = submitted.bono_lines.get()
    assert line.used_quantity == 2
    assert line.returned_quantity == 2
    assert line.lost_quantity == 1
    assert line.discrepancy_quantity == 0
    product_row = submitted.product_lines.get()
    assert product_row.physical_closing_quantity == Decimal("38.000")
    assert product_row.variance_quantity == Decimal("0.000")


def test_submission_refuses_a_missing_count_or_an_unexplained_variance(
    paired: Any,
    employee: Any,
    today: Any,
) -> None:
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind="INITIAL",
        quantity=5,
    )
    report = create_report(operational_date=today)
    bono_line = report.bono_lines.get()
    product_line = report.product_lines.get()

    update_report(
        report=report,
        bono_lines=[{"id": bono_line.pk, "used_quantity": 4, "returned_quantity": 0}],
        product_lines=[{"id": product_line.pk, "physical_closing_quantity": "0.000"}],
    )
    with pytest.raises(BonoReportIncomplete):
        submit_report(report=report)

    update_report(
        report=report,
        bono_lines=[
            {
                "id": bono_line.pk,
                "used_quantity": 4,
                "returned_quantity": 1,
                "explanation": "",
            }
        ],
    )
    submit_report(report=report)


def test_a_stale_draft_is_refused_until_it_is_refreshed(
    paired: Any,
    employee: Any,
    today: Any,
) -> None:
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind="INITIAL",
        quantity=5,
    )
    report = create_report(operational_date=today)
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind="ADDITIONAL",
        quantity=1,
    )

    with pytest.raises(BonoReportStale):
        submit_report(report=report)

    refreshed = refresh_report(report=report)
    line = refreshed.bono_lines.get()
    assert line.total_issued_quantity == 6
    product_line = refreshed.product_lines.get()
    update_report(
        report=refreshed,
        bono_lines=[
            {
                "id": line.pk,
                "used_quantity": 6,
                "returned_quantity": 0,
                "explanation": "All six were used",
            }
        ],
        product_lines=[{"id": product_line.pk, "physical_closing_quantity": "0.000"}],
    )
    submit_report(report=refreshed)


def test_approval_refuses_a_report_whose_sales_changed_after_submission(
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
    yesterday: Any,
    receive: Any,
) -> None:
    _receive_yesterday(receive, product, yesterday)
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind="INITIAL",
        quantity=5,
    )
    create_incident(
        operational_date=today,
        kind=BonoIncidentKind.LOST_BONO,
        bono_type=paired,
        responsible_employee=employee,
        quantity=1,
        reason="Lost on the floor",
    )
    sale = _sell(product)
    report = create_report(operational_date=today)
    bono_line = report.bono_lines.get()
    product_line = report.product_lines.get()
    update_report(
        report=report,
        bono_lines=[
            {
                "id": bono_line.pk,
                "used_quantity": 2,
                "returned_quantity": 2,
            }
        ],
        product_lines=[{"id": product_line.pk, "physical_closing_quantity": "38.000"}],
    )
    submit_report(report=report)

    void_sale(sale=sale, reason="Cashier mistyped the order")

    with pytest.raises(BonoReportStale):
        approve_report(report=report)


def test_owner_approval_locks_the_report_and_a_correction_is_a_new_revision(
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
    yesterday: Any,
    receive: Any,
) -> None:
    report = _prepare_draft(
        paired=paired,
        product=product,
        employee=employee,
        today=today,
        receive=receive,
        yesterday=yesterday,
    )
    bono_line = report.bono_lines.get()
    product_line = report.product_lines.get()
    update_report(
        report=report,
        bono_lines=[
            {
                "id": bono_line.pk,
                "used_quantity": 2,
                "returned_quantity": 2,
            }
        ],
        product_lines=[{"id": product_line.pk, "physical_closing_quantity": "38.000"}],
    )
    submit_report(report=report)
    approved = approve_report(report=report)
    original_used = approved.bono_lines.get().used_quantity

    with pytest.raises(BonoReportLocked):
        update_report(
            report=approved,
            bono_lines=[{"id": bono_line.pk, "used_quantity": 1}],
        )

    correction = create_correction(
        report=approved,
        reason="Cashier corrected the used token count",
    )

    assert correction.pk != approved.pk
    assert correction.revision == approved.revision + 1
    assert correction.corrects_id == approved.pk
    assert correction.status == BonoReportStatus.DRAFT
    assert correction.bono_lines.get().used_quantity == original_used

    approved.refresh_from_db()
    assert approved.status == BonoReportStatus.APPROVED
    assert approved.bono_lines.get().used_quantity == original_used

    correction_line = correction.bono_lines.get()
    update_report(
        report=correction,
        bono_lines=[
            {
                "id": correction_line.pk,
                "used_quantity": 1,
                "returned_quantity": 3,
            }
        ],
    )
    submit_report(report=correction)
    completed = approve_report(report=correction)

    approved.refresh_from_db()
    correction.refresh_from_db()
    assert approved.status == BonoReportStatus.APPROVED
    assert approved.bono_lines.get().used_quantity == original_used
    assert completed.status == BonoReportStatus.APPROVED
    assert completed.bono_lines.get().used_quantity == 1


def test_a_rejected_report_is_editable_and_can_be_resubmitted(
    paired: Any,
    employee: Any,
    today: Any,
) -> None:
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind="INITIAL",
        quantity=2,
    )
    report = create_report(operational_date=today)
    line = report.bono_lines.get()
    product_line = report.product_lines.get()
    update_report(
        report=report,
        bono_lines=[{"id": line.pk, "used_quantity": 2}],
        product_lines=[{"id": product_line.pk, "physical_closing_quantity": "0.000"}],
    )
    submit_report(report=report)
    rejected = reject_report(report=report, reason="Count does not match the till")

    assert rejected.status == BonoReportStatus.REJECTED
    assert rejected.rejection_reason == "Count does not match the till"

    update_report(
        report=rejected,
        bono_lines=[{"id": line.pk, "used_quantity": 1, "returned_quantity": 1}],
    )
    submit_report(report=rejected)
    approve_report(report=rejected)
    rejected.refresh_from_db()
    assert rejected.status == BonoReportStatus.APPROVED


def test_rejection_needs_a_reason(paired: Any, employee: Any, today: Any) -> None:
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind="INITIAL",
        quantity=1,
    )
    report = create_report(operational_date=today)
    line = report.bono_lines.get()
    product_line = report.product_lines.get()
    update_report(
        report=report,
        bono_lines=[{"id": line.pk, "used_quantity": 1}],
        product_lines=[{"id": product_line.pk, "physical_closing_quantity": "0.000"}],
    )
    submit_report(report=report)

    with pytest.raises(BARKOTDomainError):
        reject_report(report=report, reason="   ")


def test_a_correction_cannot_start_while_one_is_already_in_progress(
    paired: Any,
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
    report = create_report(operational_date=today)
    line = report.bono_lines.get()
    product_line = report.product_lines.get()
    update_report(
        report=report,
        bono_lines=[{"id": line.pk, "used_quantity": 1}],
        product_lines=[{"id": product_line.pk, "physical_closing_quantity": "0.000"}],
    )
    submit_report(report=report)
    approve_report(report=report)

    create_correction(report=report, reason="First correction")

    with pytest.raises(BonoTypeConflict):
        create_correction(report=report, reason="Second correction")


def test_draft_product_rows_keep_their_own_identity(
    paired: Any,
    product: Any,
    second_product: Any,
    today: Any,
) -> None:
    # The report fixture stores one row per product and never merges them.
    add_pairings(bono_type=paired, products=[second_product])
    report = create_report(operational_date=today)
    rows = BonoReportProductLine.objects.filter(report=report)

    assert rows.count() == 2
    assert rows.values_list("product_id", flat=True).distinct().count() == 2
