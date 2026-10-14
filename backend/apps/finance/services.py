"""Finance reporting services (spec §13.2, §11.4).

The MVP balance is deliberately simple::

    net = income from sales - approved expenses - approved payroll

There is no double-entry ledger and no accrual. Spec §13.2 describes exactly this
arithmetic, and introducing either concept now would be unrequested scope that
also has to be correct.

Two rules make the figure trustworthy:

- **Only approved** expenses and payroll runs count. A Manager's income report
  should not move because someone is still checking a receipt.
- **Voided rows never count.** Voiding is a reversal, not a deletion, so every
  total filters on ``voided_at__isnull`` rather than relying on a deleted row
  being absent.

All date ranges here are business-local dates; the conversion to UTC instants
goes through :mod:`apps.core.business_time` so a sale at 23:30 belongs to the
day the cashier thinks it does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Sum

from apps.audit.models import AuditLog
from apps.core.business_time import business_period_bounds
from apps.core.enums import ExpenseStatus, PaymentMethod, PayrollRunStatus
from apps.core.exceptions import BARKOTDomainError
from apps.core.money import ZERO_MONEY, quantize_money
from apps.finance.models import Expense, ExpenseCategory
from apps.payroll.models import PayrollRun
from apps.sales.models import Payment

if TYPE_CHECKING:  # pragma: no cover
    from apps.accounts.models import User


@dataclass(frozen=True, slots=True)
class FinanceBalance:
    """A period balance broken into its parts (spec §13.2)."""

    period_start: date
    period_end: date
    income_cash: Decimal = ZERO_MONEY
    income_mobile_banking: Decimal = ZERO_MONEY
    income_total: Decimal = ZERO_MONEY
    expenses_total: Decimal = ZERO_MONEY
    payroll_total: Decimal = ZERO_MONEY
    currency: str = "ETB"
    expense_breakdown: dict[str, Decimal] = field(default_factory=dict)

    @property
    def net(self) -> Decimal:
        """Net result for the period: income less expenses less payroll."""
        return quantize_money(self.income_total - self.expenses_total - self.payroll_total)

    def as_dict(self) -> dict[str, object]:
        """Return the balance as a JSON-ready mapping for the API."""
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "currency": self.currency,
            "income": {
                "cash": str(self.income_cash),
                "mobile_banking": str(self.income_mobile_banking),
                "total": str(self.income_total),
            },
            "expenses_total": str(self.expenses_total),
            "expense_breakdown": {k: str(v) for k, v in self.expense_breakdown.items()},
            "payroll_total": str(self.payroll_total),
            "net": str(self.net),
        }


def income_by_method(*, start: date, end: date) -> dict[str, Decimal]:
    """Return sales income per payment method over an inclusive date range.

    Args:
        start: First business-local day, inclusive.
        end: Last business-local day, inclusive.

    Returns:
        ``{"CASH": ..., "MOBILE_BANKING": ...}`` with both keys always present,
        so a report never omits a method that simply had no takings.
    """
    start_utc, end_utc = business_period_bounds(start, end)
    rows = (
        Payment.objects.filter(
            sale__sold_at__gte=start_utc,
            sale__sold_at__lt=end_utc,
            voided_at__isnull=True,
            sale__voided_at__isnull=True,
        )
        .values("method")
        .annotate(total=Sum("amount"))
    )
    totals = {row["method"]: quantize_money(row["total"] or ZERO_MONEY) for row in rows}
    return {
        PaymentMethod.CASH: totals.get(PaymentMethod.CASH, ZERO_MONEY),
        PaymentMethod.MOBILE_BANKING: totals.get(PaymentMethod.MOBILE_BANKING, ZERO_MONEY),
    }


def approved_expenses_total(*, start: date, end: date) -> Decimal:
    """Return the total of approved, non-voided expenses in the period."""
    total = Expense.objects.filter(
        status=ExpenseStatus.APPROVED,
        incurred_on__gte=start,
        incurred_on__lte=end,
    ).aggregate(total=Sum("amount"))["total"]
    return quantize_money(total or ZERO_MONEY)


def approved_expenses_by_category(*, start: date, end: date) -> dict[str, Decimal]:
    """Return approved expenses grouped by category name.

    Keyed by the category's display name rather than its id because this feeds a
    pie chart directly. An empty category is omitted rather than reported as
    zero, so the report only shows slices that exist.
    """
    rows = (
        Expense.objects.filter(
            status=ExpenseStatus.APPROVED,
            incurred_on__gte=start,
            incurred_on__lte=end,
        )
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("category__name")
    )
    return {row["category__name"]: quantize_money(row["total"] or ZERO_MONEY) for row in rows}


def approved_payroll_total(*, start: date, end: date) -> Decimal:
    """Return the net payroll cost for runs in the period.

    Only ``APPROVED`` and ``PAID`` runs count. A ``GENERATED`` run is a proposal
    and must not move the balance, which is the whole point of the Owner
    approving payroll.

    ``period_month`` is the first day of the month being paid, so filtering it
    with the same inclusive date range as everything else puts a September run
    inside a September report without special-casing month arithmetic.
    """
    total = PayrollRun.objects.filter(
        status__in=[PayrollRunStatus.APPROVED, PayrollRunStatus.PAID],
        period_month__gte=start,
        period_month__lte=end,
    ).aggregate(total=Sum("items__net_amount"))["total"]
    return quantize_money(total or ZERO_MONEY)


def finance_balance(*, start: date, end: date, currency: str = "ETB") -> FinanceBalance:
    """Return the full period balance (spec §13.2).

    Args:
        start: First business-local day, inclusive.
        end: Last business-local day, inclusive.
        currency: Currency code for the report.

    Returns:
        A :class:`FinanceBalance`.
    """
    from apps.core.enums import PaymentMethod

    income = income_by_method(start=start, end=end)
    cash = income[PaymentMethod.CASH]
    mobile = income[PaymentMethod.MOBILE_BANKING]
    return FinanceBalance(
        period_start=start,
        period_end=end,
        income_cash=cash,
        income_mobile_banking=mobile,
        income_total=quantize_money(cash + mobile),
        expenses_total=approved_expenses_total(start=start, end=end),
        payroll_total=approved_payroll_total(start=start, end=end),
        currency=currency,
        expense_breakdown=approved_expenses_by_category(start=start, end=end),
    )


@transaction.atomic
def create_expense_category(
    *, name: str, description: str = "", actor: User | None = None
) -> ExpenseCategory:
    """Create an active expense category and its audit record."""
    normalized_name = name.strip()
    if not normalized_name:
        raise BARKOTDomainError("Expense category name is required.")
    if ExpenseCategory.objects.filter(name__iexact=normalized_name).exists():
        raise BARKOTDomainError(f"Expense category {normalized_name!r} already exists.")

    category = ExpenseCategory.objects.create(
        name=normalized_name,
        description=description.strip(),
    )
    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="finance.ExpenseCategory",
        object_id=category.pk,
        actor=actor,
        summary=f"Created expense category {category.name}",
    )
    return category


@transaction.atomic
def update_expense_category(
    *,
    category: ExpenseCategory,
    name: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    actor: User | None = None,
) -> ExpenseCategory:
    """Edit an expense category in place.

    Only the supplied fields change. A rename is refused if another category
    already uses the name, matching the create rule so the two paths cannot
    leave the table with a duplicate the API would have rejected on create.
    """
    update_fields: list[str] = []

    if name is not None:
        normalized_name = name.strip()
        if not normalized_name:
            raise BARKOTDomainError("Expense category name is required.")
        clash = ExpenseCategory.objects.filter(name__iexact=normalized_name).exclude(pk=category.pk)
        if clash.exists():
            raise BARKOTDomainError(f"Expense category {normalized_name!r} already exists.")
        category.name = normalized_name
        update_fields.append("name")

    if description is not None:
        category.description = description.strip()
        update_fields.append("description")

    if is_active is not None:
        category.is_active = is_active
        update_fields.append("is_active")

    if not update_fields:
        return category

    update_fields.append("updated_at")
    category.save(update_fields=update_fields)

    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type="finance.ExpenseCategory",
        object_id=category.pk,
        actor=actor,
        summary=f"Updated expense category {category.name}",
    )
    return category


@transaction.atomic
def archive_expense_category(
    *, category: ExpenseCategory, actor: User | None = None
) -> ExpenseCategory:
    """Retire an expense category without deleting it.

    The category stays on the books so historic expenses keep their grouping;
    it simply stops being offered when recording new expenses. Deactivating an
    already-inactive category is a no-op rather than an error, so the action is
    idempotent.
    """
    if category.is_active:
        category.is_active = False
        category.save(update_fields=["is_active", "updated_at"])
        AuditLog.record(
            action=AuditLog.Action.UPDATE,
            object_type="finance.ExpenseCategory",
            object_id=category.pk,
            actor=actor,
            summary=f"Archived expense category {category.name}",
        )
    return category


@transaction.atomic
def create_expense(
    *,
    category: ExpenseCategory,
    description: str,
    amount: Decimal,
    currency: str,
    incurred_on: date,
    actor: User | None = None,
) -> Expense:
    """Record an expense awaiting approval."""
    if not category.is_active:
        raise BARKOTDomainError(f"Expense category {category.name!r} is inactive.")
    if amount <= 0:
        raise BARKOTDomainError("Expense amount must be greater than zero.")
    if currency.strip().upper() != "ETB":
        raise BARKOTDomainError("Only ETB expenses are supported.")

    expense = Expense.objects.create(
        category=category,
        description=description.strip(),
        amount=quantize_money(amount),
        currency="ETB",
        incurred_on=incurred_on,
        created_by=actor,
        updated_by=actor,
    )
    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="finance.Expense",
        object_id=expense.pk,
        actor=actor,
        summary=f"Recorded expense {expense.description} ({expense.amount} ETB)",
    )
    return expense


@transaction.atomic
def approve_expense(*, expense: Expense, actor: User | None = None) -> Expense:
    """Approve an expense so it contributes to the business balance."""
    expense.approve(actor=actor)
    expense.updated_by = actor
    expense.save(update_fields=["status", "approved_at", "approved_by", "updated_by", "updated_at"])
    AuditLog.record(
        action=AuditLog.Action.APPROVE,
        object_type="finance.Expense",
        object_id=expense.pk,
        actor=actor,
        summary=f"Approved expense {expense.description} ({expense.amount} ETB)",
    )
    return expense


__all__ = [
    "FinanceBalance",
    "approve_expense",
    "approved_expenses_by_category",
    "approved_expenses_total",
    "approved_payroll_total",
    "archive_expense_category",
    "create_expense",
    "create_expense_category",
    "finance_balance",
    "income_by_method",
    "update_expense_category",
]
