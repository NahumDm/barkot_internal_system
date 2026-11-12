"""Custody movements: issues, transfers, losses, breakage and deductions."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.bono.models import (
    BonoIncidentKind,
    BonoIncidentResolution,
    BonoIssue,
    BonoIssueKind,
    BonoTransfer,
)
from apps.bono.services import (
    collect_day_activity,
    create_incident,
    create_issue,
    create_report,
    create_transfer,
    record_incident_deduction,
    resolve_incident,
    staff_balances_for_day,
)
from apps.core.enums import MovementKind
from apps.core.exceptions import (
    BARKOTDomainError,
    BonoAllocationExceeded,
    BonoReportLocked,
    BonoTypeConflict,
)
from apps.inventory.models import BreakageRecord, StockMovement
from apps.inventory.services import current_stock
from apps.payroll.models import Employee, PayrollDeduction
from apps.payroll.services import generate_payroll_run
from apps.sales.models import Sale

pytestmark = pytest.mark.django_db


def test_initial_and_additional_issues_are_recorded_separately(
    paired: Any,
    employee: Any,
    today: Any,
) -> None:
    initial = create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind=BonoIssueKind.INITIAL,
        quantity=4,
        note="Opening hand-out",
    )
    additional = create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind=BonoIssueKind.ADDITIONAL,
        quantity=2,
        note="Busy lunch service",
    )

    assert initial.kind == BonoIssueKind.INITIAL
    assert additional.kind == BonoIssueKind.ADDITIONAL
    assert initial.bono_name_snapshot == paired.name
    assert initial.bono_price_snapshot == Decimal("25.00")
    row = staff_balances_for_day(today)[0]
    assert row["issued"] == 6
    assert row["balance"] == 6

    with pytest.raises(BonoTypeConflict) as excinfo:
        create_issue(
            operational_date=today,
            bono_type=paired,
            employee=employee,
            kind=BonoIssueKind.INITIAL,
            quantity=1,
        )
    assert "initial" in str(excinfo.value).lower()


def test_an_archived_staff_member_cannot_receive_a_bono(
    paired: Any,
    make_employee: Any,
    today: Any,
) -> None:
    archived = make_employee("Former Barman", archived=True)

    with pytest.raises(BARKOTDomainError):
        create_issue(
            operational_date=today,
            bono_type=paired,
            employee=archived,
            kind=BonoIssueKind.INITIAL,
            quantity=1,
        )


def test_a_future_business_date_is_refused(
    paired: Any,
    employee: Any,
    today: Any,
) -> None:
    with pytest.raises(BARKOTDomainError):
        create_issue(
            operational_date=today + timedelta(days=1),
            bono_type=paired,
            employee=employee,
            kind=BonoIssueKind.INITIAL,
            quantity=1,
        )


def test_a_transfer_moves_custody_without_creating_a_new_business_issue(
    paired: Any,
    employee: Any,
    second_employee: Any,
    today: Any,
) -> None:
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind=BonoIssueKind.INITIAL,
        quantity=4,
    )

    transfer = create_transfer(
        operational_date=today,
        bono_type=paired,
        from_employee=employee,
        to_employee=second_employee,
        quantity=2,
        reason="Hand-over for the evening shift",
    )

    assert transfer.from_employee_id == employee.pk
    assert transfer.to_employee_id == second_employee.pk
    assert BonoIssue.objects.filter(bono_type=paired).count() == 1
    assert BonoTransfer.objects.filter(bono_type=paired).count() == 1

    balances = {
        (row["employee_id"], row["bono_type_id"]): row for row in staff_balances_for_day(today)
    }
    assert balances[employee.pk, paired.pk]["balance"] == 2
    assert balances[second_employee.pk, paired.pk]["transfers_in"] == 2
    assert balances[second_employee.pk, paired.pk]["balance"] == 2

    report = create_report(operational_date=today)
    bono_line = report.bono_lines.get()
    assert bono_line.initial_issued_quantity == 4
    assert bono_line.transfers_out_quantity == 2
    assert bono_line.transfers_in_quantity == 2


def test_a_transfer_cannot_overdraw_custody(
    paired: Any,
    employee: Any,
    second_employee: Any,
    today: Any,
) -> None:
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind=BonoIssueKind.INITIAL,
        quantity=2,
    )

    with pytest.raises(BonoAllocationExceeded):
        create_transfer(
            operational_date=today,
            bono_type=paired,
            from_employee=employee,
            to_employee=second_employee,
            quantity=3,
            reason="Too many",
        )

    assert not BonoTransfer.objects.exists()
    assert staff_balances_for_day(today)[0]["balance"] == 2


def test_a_transfer_needs_a_reason_and_two_people(
    paired: Any,
    employee: Any,
    today: Any,
) -> None:
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind=BonoIssueKind.INITIAL,
        quantity=2,
    )

    with pytest.raises(BARKOTDomainError):
        create_transfer(
            operational_date=today,
            bono_type=paired,
            from_employee=employee,
            to_employee=employee,
            quantity=1,
            reason="Self",
        )
    with pytest.raises(BARKOTDomainError):
        create_transfer(
            operational_date=today,
            bono_type=paired,
            from_employee=employee,
            to_employee=employee,
            quantity=1,
            reason="   ",
        )
    assert not BonoTransfer.objects.exists()


def test_a_lost_bono_reduces_custody_without_inventing_an_inventory_or_money_event(
    paired: Any,
    employee: Any,
    today: Any,
) -> None:
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind=BonoIssueKind.INITIAL,
        quantity=3,
    )

    incident = create_incident(
        operational_date=today,
        kind=BonoIncidentKind.LOST_BONO,
        bono_type=paired,
        responsible_employee=employee,
        quantity=1,
        reason="Token lost on the floor",
    )

    assert incident.resolution_status == BonoIncidentResolution.PENDING
    assert incident.breakage_record is None
    assert incident.payroll_deduction is None
    assert not StockMovement.objects.filter(kind=MovementKind.BREAKAGE).exists()
    assert not Sale.objects.exists()
    assert not PayrollDeduction.objects.exists()
    assert staff_balances_for_day(today)[0]["balance"] == 2
    assert collect_day_activity(today).bono[0].lost == 1


def test_losing_more_tokens_than_held_is_refused(
    paired: Any,
    employee: Any,
    today: Any,
) -> None:
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind=BonoIssueKind.INITIAL,
        quantity=1,
    )

    with pytest.raises(BonoAllocationExceeded):
        create_incident(
            operational_date=today,
            kind=BonoIncidentKind.LOST_BONO,
            bono_type=paired,
            responsible_employee=employee,
            quantity=2,
            reason="Impossible",
        )


def test_a_broken_bottle_writes_exactly_one_existing_inventory_movement(
    paired: Any,
    product: Any,
    stocked: Any,
    today: Any,
) -> None:
    before = current_stock(product)

    incident = create_incident(
        operational_date=today,
        kind=BonoIncidentKind.BROKEN_BOTTLE,
        product=product,
        quantity=1,
        reason="Bottle dropped behind the bar",
    )

    assert incident.breakage_record is not None
    assert BreakageRecord.objects.count() == 1
    assert StockMovement.objects.filter(product=product, kind=MovementKind.BREAKAGE).count() == 1
    assert current_stock(product) == before - Decimal("1.000")
    assert not BonoIssue.objects.exists()
    assert not BonoTransfer.objects.exists()


def test_a_lost_bono_deduction_uses_the_existing_payroll_service(
    paired: Any,
    employee: Any,
    today: Any,
) -> None:
    payroll_employee = Employee.from_profile(employee, monthly_wage=Decimal("18000.00"))
    run = generate_payroll_run(period=today, employee_ids=[payroll_employee.pk])
    item = run.items.get()
    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind=BonoIssueKind.INITIAL,
        quantity=2,
    )
    incident = create_incident(
        operational_date=today,
        kind=BonoIncidentKind.LOST_BONO,
        bono_type=paired,
        responsible_employee=employee,
        quantity=1,
        reason="Lost during closing",
    )

    # Recording a loss is not itself a payroll decision.
    assert not PayrollDeduction.objects.exists()
    deduction = record_incident_deduction(
        incident=incident,
        payroll_item=item,
        amount=Decimal("25.00"),
        reason="Replacement value of the lost token",
    )

    incident.refresh_from_db()
    item.refresh_from_db()
    assert deduction.deduction_type == "OTHER"
    assert deduction.amount == Decimal("25.00")
    assert incident.payroll_deduction_id == deduction.pk
    assert incident.resolution_status == BonoIncidentResolution.DEDUCTED
    assert item.total_deductions == Decimal("25.00")

    with pytest.raises(BonoTypeConflict):
        record_incident_deduction(
            incident=incident,
            payroll_item=item,
            amount=Decimal("25.00"),
            reason="Twice",
        )

    other = create_incident(
        operational_date=today,
        kind=BonoIncidentKind.LOST_BONO,
        bono_type=paired,
        responsible_employee=employee,
        quantity=1,
        reason="Second loss",
    )
    with pytest.raises(BARKOTDomainError):
        resolve_incident(
            incident=other,
            resolution_status=BonoIncidentResolution.DEDUCTED,
            resolution_notes="No deduction linked",
        )


def test_a_broken_bottle_cannot_be_turned_into_a_bono_deduction(
    paired: Any,
    product: Any,
    stocked: Any,
    employee: Any,
    today: Any,
) -> None:
    payroll_employee = Employee.from_profile(employee, monthly_wage=Decimal("18000.00"))
    run = generate_payroll_run(period=today, employee_ids=[payroll_employee.pk])
    item = run.items.get()
    incident = create_incident(
        operational_date=today,
        kind=BonoIncidentKind.BROKEN_BOTTLE,
        product=product,
        quantity=1,
        reason="Dropped",
    )

    with pytest.raises(BARKOTDomainError):
        record_incident_deduction(
            incident=incident,
            payroll_item=item,
            amount=Decimal("25.00"),
            reason="Not a lost token",
        )


def test_operations_are_locked_once_the_day_is_submitted(
    paired: Any,
    employee: Any,
    today: Any,
) -> None:
    from apps.bono.services import submit_report, update_report

    create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind=BonoIssueKind.INITIAL,
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

    with pytest.raises(BonoReportLocked):
        create_issue(
            operational_date=today,
            bono_type=paired,
            employee=employee,
            kind=BonoIssueKind.ADDITIONAL,
            quantity=1,
        )
