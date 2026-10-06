"""Payroll write services (spec §14.1).

The run lifecycle is ``GENERATED`` → ``APPROVED`` → ``PAID``, and each transition
has exactly one caller permission:

- a Manager *generates* a run (spec §9.2);
- the Owner *approves* it;
- the Owner marks it *paid*.

Generation and approval are separate steps for the reason the spec gives: the
person who calculates the run should not also be the person who signs it off.
Splitting them in code — not just in the UI — is what stops a single account
producing an unchallenged payslip.

Deduction rules are **not** computed. The client has not confirmed the
statutory calculation (spec §30 items 5 and 6), so net pay is
``gross - deductions a Manager has entered``. Guessing at Ethiopian payroll tax
would produce confidently wrong payslips.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Max

from apps.audit.models import AuditLog
from apps.core.enums import PayrollDeductionType, PayrollItemStatus, PayrollRunStatus
from apps.core.exceptions import (
    ExcessiveDeduction,
    InvalidDeductionAmount,
    InvalidStateTransition,
)
from apps.core.money import ZERO_MONEY, quantize_money
from apps.payroll.models import Employee, PayrollDeduction, PayrollItem, PayrollRun


def _first_of_month(day: date) -> date:
    """Return the first day of ``day``'s month.

    ``PayrollRun.period_month`` is stored as the first of the month so a run is
    uniquely identified by month and sorts naturally.
    """
    return day.replace(day=1)


@transaction.atomic
def generate_payroll_run(
    *,
    period: date,
    employee_ids: list[int] | None = None,
    actor: Any | None = None,
    notes: str = "",
) -> PayrollRun:
    """Create a payroll run for a month from current employee wages.

    Args:
        period: Any date within the month being paid.
        employee_ids: Restrict to these employees. ``None`` means every
            currently employable employee.
        actor: The Manager generating it (permission ``payroll.generate_run``).
        notes: Header note.

    Returns:
        The created :class:`PayrollRun` in ``GENERATED`` with its items.

    Raises:
        InvalidStateTransition: If a run already exists for that month, or if no
            employees are eligible. An empty run cannot be approved and would
            only be a mistake.
    """
    month = _first_of_month(period)

    if PayrollRun.all_rows.filter(period_month=month).exists():
        raise InvalidStateTransition(f"A payroll run already exists for {month:%Y-%m}.")

    employees = Employee.objects.select_related("profile").filter(status="ACTIVE")
    if employee_ids is not None:
        employees = employees.filter(pk__in=employee_ids)
    employees = [emp for emp in employees if emp.is_employable]

    if not employees:
        raise InvalidStateTransition("No active employees are available for this payroll run.")

    run = PayrollRun.objects.create(
        period_month=month,
        status=PayrollRunStatus.GENERATED,
        notes=notes,
        created_by=actor,
        updated_by=actor,
    )

    for employee in employees:
        PayrollItem.objects.create(
            run=run,
            employee=employee,
            gross_amount=quantize_money(employee.monthly_wage, field="gross_amount"),
            total_deductions=ZERO_MONEY,
            currency=employee.currency,
            status=PayrollItemStatus.PENDING,
            created_by=actor,
            updated_by=actor,
        )

    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="payroll.PayrollRun",
        object_id=run.pk,
        actor=actor,
        summary=f"Generated payroll for {month:%Y-%m} with {len(employees)} employee(s)",
    )
    return run


@transaction.atomic
def add_deduction(
    *,
    payroll_item: PayrollItem,
    deduction_type: str,
    amount: Decimal,
    reason: str = "",
    occurred_on: date | None = None,
    actor: Any | None = None,
) -> PayrollDeduction:
    """Record a deduction and roll it into the line's total.

    Args:
        payroll_item: The payroll line to deduct from.
        deduction_type: A :class:`apps.core.enums.PayrollDeductionType` value.
        amount: Positive amount to deduct.
        reason: Why. Optional but strongly recommended.
        occurred_on: Business-local date the deduction relates to.
        actor: The Manager recording it (permission ``payroll.create_deduction``).

    Returns:
        The created :class:`PayrollDeduction`.

    Raises:
        InvalidStateTransition: If the run is already approved or paid. A signed
            payslip is not edited; the correction goes in the next run.
        InvalidDeductionAmount: If ``amount`` is zero or negative.
        ExcessiveDeduction: If the deduction would exceed gross pay. A negative
            payslip is always a data-entry error, and storing it would quietly
            flow into the finance balance.
    """
    if payroll_item.run.status != PayrollRunStatus.GENERATED:
        raise InvalidStateTransition(
            f"Payroll run {payroll_item.run_id} is {payroll_item.run.get_status_display()}; "
            "deductions can only be added while it is generated."
        )

    amount = quantize_money(amount, field="amount")
    if amount <= 0:
        raise InvalidDeductionAmount

    new_total = quantize_money(payroll_item.total_deductions + amount, field="total_deductions")
    if new_total > payroll_item.gross_amount:
        raise ExcessiveDeduction(
            f"Deductions ({new_total}) would exceed gross pay ({payroll_item.gross_amount}) "
            f"for {payroll_item.employee.full_name}."
        )

    deduction = PayrollDeduction.objects.create(
        payroll_item=payroll_item,
        deduction_type=deduction_type,
        amount=amount,
        reason=reason,
        occurred_on=occurred_on or payroll_item.run.period_month,
        created_by=actor,
        updated_by=actor,
    )

    payroll_item.total_deductions = new_total
    payroll_item.save(update_fields=["total_deductions", "net_amount", "updated_at", "updated_by"])

    return deduction


@transaction.atomic
def approve_payroll_run(*, run: PayrollRun, actor: Any | None = None) -> PayrollRun:
    """Approve a generated run (spec §14.1). Owner-only in the role matrix."""
    run.approve(actor=actor)
    run.save(update_fields=["status", "approved_at", "approved_by", "updated_at", "updated_by"])

    PayrollItem.objects.filter(run=run).update(status=PayrollItemStatus.APPROVED)

    AuditLog.record(
        action=AuditLog.Action.APPROVE,
        object_type="payroll.PayrollRun",
        object_id=run.pk,
        actor=actor,
        summary=f"Approved payroll for {run.period_month:%Y-%m}",
    )
    return run


@transaction.atomic
def mark_payroll_run_paid(*, run: PayrollRun, actor: Any | None = None) -> PayrollRun:
    """Mark an approved run as paid and every line with it."""
    run.mark_paid(actor=actor)
    run.save(update_fields=["status", "paid_at", "updated_at", "updated_by"])

    PayrollItem.objects.filter(run=run).update(status=PayrollItemStatus.PAID, paid_at=run.paid_at)

    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type="payroll.PayrollRun",
        object_id=run.pk,
        actor=actor,
        summary=f"Marked payroll paid for {run.period_month:%Y-%m}",
    )
    return run


def latest_run_period() -> date | None:
    """Return the most recent run's month, or ``None`` if there are none.

    Used to pre-fill the payroll screen's period field.
    """
    latest = PayrollRun.all_rows.aggregate(most_recent=Max("period_month"))["most_recent"]
    return latest


__all__ = [
    "PayrollDeductionType",
    "add_deduction",
    "approve_payroll_run",
    "generate_payroll_run",
    "latest_run_period",
    "mark_payroll_run_paid",
]
