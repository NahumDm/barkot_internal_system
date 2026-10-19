"""Payroll write services (spec §14.1).

The run lifecycle is ``GENERATED`` → ``APPROVED`` → ``PAID``, and each transition
has exactly one caller permission, all three held by the Owner (spec §9.2 as the
role matrix now enforces it):

- the Owner *generates* a run from current wages;
- the Owner *approves* it;
- the Owner marks it *paid*.

Generation and approval are separate steps for the reason the spec gives: the
person who calculates the run should not also be the person who signs it off.
They are separate grants even though one role holds both, so splitting them
remains a matter of changing the matrix rather than the code — and a Manager,
who may read payroll and record deductions, still cannot produce a run at all.

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
from apps.users.models import EmployeeProfile


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

    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="payroll.PayrollDeduction",
        object_id=deduction.pk,
        actor=actor,
        summary=(
            f"Deducted {deduction.amount} {deduction.deduction_type} from "
            f"{payroll_item.employee.full_name}"
        ),
    )
    return deduction


@transaction.atomic
def update_deduction(
    *,
    deduction: PayrollDeduction,
    changes: dict[str, Any],
    actor: Any | None = None,
) -> PayrollDeduction:
    """Correct a deduction that has already been recorded.

    The caller's ``validated_data`` *is* the change set: the update serializer
    declares exactly the four fields a recorded deduction may be edited with, so
    passing the whole of it means there is no second list of editable fields to
    keep in step. ``payroll_item`` is not one of them — the correction belongs
    to the line it was taken from.

    The line's total moves by the *difference* between the old and new amounts
    rather than being recomputed from the deductions, so one correction cannot
    quietly absorb another row that changed underneath it.

    Args:
        deduction: The deduction to correct.
        changes: Field name to new value. Empty means nothing was submitted, and
            is a no-op rather than an empty audit entry.
        actor: The staff member making the correction (permission
            ``payroll.create_deduction``).

    Returns:
        The corrected :class:`PayrollDeduction`.

    Raises:
        InvalidStateTransition: If the run is already approved or paid. A signed
            payslip is not edited; the correction goes in the next run.
        InvalidDeductionAmount: If ``amount`` is zero or negative.
        ExcessiveDeduction: If the corrected total would exceed gross pay.
    """
    if not changes:
        return deduction

    payroll_item = deduction.payroll_item
    if payroll_item.run.status != PayrollRunStatus.GENERATED:
        raise InvalidStateTransition(
            f"Payroll run {payroll_item.run_id} is {payroll_item.run.get_status_display()}; "
            "deductions can only be edited while it is generated."
        )

    new_amount = deduction.amount
    if "amount" in changes:
        new_amount = quantize_money(changes["amount"], field="amount")
        if new_amount <= 0:
            raise InvalidDeductionAmount

    new_total = quantize_money(
        payroll_item.total_deductions - deduction.amount + new_amount,
        field="total_deductions",
    )
    if new_total > payroll_item.gross_amount:
        raise ExcessiveDeduction(
            f"Deductions ({new_total}) would exceed gross pay ({payroll_item.gross_amount}) "
            f"for {payroll_item.employee.full_name}."
        )

    for field, value in changes.items():
        setattr(deduction, field, value)
    deduction.amount = new_amount
    deduction.updated_by = actor
    deduction.save(update_fields=[*changes, "amount", "updated_by", "updated_at"])

    payroll_item.total_deductions = new_total
    payroll_item.updated_by = actor
    payroll_item.save(update_fields=["total_deductions", "net_amount", "updated_at", "updated_by"])

    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type="payroll.PayrollDeduction",
        object_id=deduction.pk,
        actor=actor,
        summary=(
            f"Updated {deduction.deduction_type} deduction to {deduction.amount} on "
            f"{payroll_item.employee.full_name}"
        ),
    )
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


@transaction.atomic
def add_employee(
    *,
    employee: EmployeeProfile,
    monthly_wage: Decimal,
    actor: Any | None = None,
) -> Employee:
    """Put a register record onto payroll (roadmap D1).

    The subject is an :class:`~apps.users.models.EmployeeProfile` rather than a
    login account because the register is the roster of who works here (spec
    §5): a new hire is registered on day one whether or not an account exists,
    and payroll attaches the wage to that record. Nothing is created or revived
    on the person side — the register row already exists, and archiving is the
    register's own business.

    Args:
        employee: The register record to pay.
        monthly_wage: Gross monthly wage. Zero is allowed and must be fixed in
            a later decision (spec §30 item 5), not guessed here.
        actor: The staff member adding it (permission
            ``payroll.manage_payroll_employees``).

    Returns:
        The created :class:`Employee`.

    Raises:
        IntegrityError: If the record already has a payroll row; the serializer
            refuses that case before the service runs.
    """
    record = Employee.from_profile(employee, monthly_wage=monthly_wage)

    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="payroll.Employee",
        object_id=record.pk,
        actor=actor,
        summary=f"Added {record.full_name} to payroll at {monthly_wage}/month",
    )
    return record


def latest_run_period() -> date | None:
    """Return the most recent run's month, or ``None`` if there are none.

    Used to pre-fill the payroll screen's period field.
    """
    latest = PayrollRun.all_rows.aggregate(most_recent=Max("period_month"))["most_recent"]
    return latest


__all__ = [
    "PayrollDeductionType",
    "add_deduction",
    "add_employee",
    "approve_payroll_run",
    "generate_payroll_run",
    "latest_run_period",
    "mark_payroll_run_paid",
]
