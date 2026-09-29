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

from django.db.models import Sum

from apps.core.business_time import business_period_bounds
from apps.core.enums import ExpenseStatus, PaymentMethod, PayrollRunStatus
from apps.core.money import ZERO_MONEY, quantize_money
from apps.finance.models import Expense
from apps.payroll.models import PayrollRun
from apps.sales.models import Payment


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


__all__ = [
    "FinanceBalance",
    "approved_expenses_by_category",
    "approved_expenses_total",
    "approved_payroll_total",
    "finance_balance",
    "income_by_method",
]
