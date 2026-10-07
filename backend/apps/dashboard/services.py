"""Dashboard summary service (spec §7.4).

The dashboard never owns source truth. It answers "what is the state of the
business today" by delegating each tile to the same service the source screen
uses, and only while the requesting user's role actually grants that domain
read:

- **Finance** delegates to ``finance_balance`` — the exact number the C1
  balance screen and the C4 financial report show.
- **Payroll** shows the latest run through ``PayrollRunSerializer``, the same
  shape the payroll screen reads.
- **Sales** reuses ``sales_totals`` (reconciliation-strict: voided rows never
  count) plus a bounded recent slice of the sales ledger.
- **Inventory** reuses the C4 stock-balance query so the count of units on the
  shelf agrees with the reports page character for character.

Gating per section with ``user.has_perm`` against the same codenames the
permission classes require keeps the server authoritative: a Cashier gets a
``null`` finance section, not a lazily crafted number.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from django.db.models import Count

from apps.accounts.permissions import (
    CanViewInventory,
    CanViewPayroll,
    CanViewReports,
    CanViewSales,
)
from apps.core.business_time import business_period_bounds
from apps.core.enums import PaymentMethod
from apps.core.money import ZERO_MONEY
from apps.finance.serializers import BalanceSerializer
from apps.finance.services import finance_balance
from apps.payroll.models import PayrollRun
from apps.payroll.serializers import PayrollRunSerializer
from apps.reports.services import inventory_stock_balance
from apps.sales.models import Sale
from apps.sales.serializers import SaleListSerializer
from apps.sales.services import sales_totals

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User


def dashboard_summary(*, start: date, end: date, user: User) -> dict[str, Any]:
    """Return the role-scoped dashboard for an inclusive business-date range.

    Args:
        start: First business-local day, inclusive.
        end: Last business-local day, inclusive.
        user: The requesting user; sections are included only when the role
            grants the backing domain read.

    Returns:
        A JSON-ready mapping with ``period`` always present and each section
        present only when permitted.
    """
    payload: dict[str, Any] = {
        "period": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "currency": "ETB",
        }
    }

    if user.has_perm(CanViewReports.required_permission):
        balance = finance_balance(start=start, end=end)
        payload["finance"] = BalanceSerializer(balance.as_dict()).data

    if user.has_perm(CanViewPayroll.required_permission):
        latest = PayrollRun.objects.order_by("-period_month", "-id").first()
        payload["payroll"] = PayrollRunSerializer(latest).data if latest is not None else None

    if user.has_perm(CanViewSales.required_permission):
        start_utc, end_utc = business_period_bounds(start, end)
        totals = sales_totals(start=start_utc, end=end_utc)
        sales_intraday = (
            Sale.objects.filter(sold_at__gte=start_utc, sold_at__lt=end_utc)
            .annotate(item_count=Count("items"))
            .order_by("-sold_at", "-id")
        )
        payload["sales"] = {
            "total": str(totals["TOTAL"]),
            "cash": str(totals.get(PaymentMethod.CASH.value, ZERO_MONEY)),
            "mobile_banking": str(totals.get(PaymentMethod.MOBILE_BANKING.value, ZERO_MONEY)),
            "transactions": sales_intraday.count(),
            "recent": SaleListSerializer(sales_intraday[:5], many=True).data,
        }

    if user.has_perm(CanViewInventory.required_permission):
        report = inventory_stock_balance(as_of=end)
        payload["inventory"] = {
            "as_of": report.as_of.isoformat(),
            "in_stock_total": str(report.in_stock_total),
            "products": len(report.rows),
        }

    return payload


__all__ = ["dashboard_summary"]
