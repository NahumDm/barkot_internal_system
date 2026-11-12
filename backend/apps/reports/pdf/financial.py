from __future__ import annotations

from datetime import date

from django.http import HttpResponse

from apps.finance.services import finance_balance
from apps.reports.pdf.builders import _build_pdf
from apps.reports.pdf.utils import format_period


def financial_report_pdf(*, start: date, end: date) -> HttpResponse:
    balance = finance_balance(start=start, end=end)
    currency = balance.currency

    summary_rows = [
        ("Period", format_period(start, end)),
        ("Income (cash)", f"{balance.income_cash} {currency}"),
        ("Income (mobile banking)", f"{balance.income_mobile_banking} {currency}"),
        ("Income (total)", f"{balance.income_total} {currency}"),
        ("Expenses (total)", f"{balance.expenses_total} {currency}"),
        ("Payroll (total)", f"{balance.payroll_total} {currency}"),
        ("Net", f"{balance.net} {currency}"),
    ]

    headers = ["Item", "Amount (ETB)" if currency == "ETB" else "Amount"]
    rows = [
        ["Income (cash)", f"{balance.income_cash} {currency}"],
        ["Income (mobile banking)", f"{balance.income_mobile_banking} {currency}"],
        ["Income (total)", f"{balance.income_total} {currency}"],
        ["Expenses (total)", f"{balance.expenses_total} {currency}"],
        ["Payroll (total)", f"{balance.payroll_total} {currency}"],
        ["Net", f"{balance.net} {currency}"],
    ]

    return _build_pdf(
        title="Financial Report",
        description="Income, expenses, payroll and net result for the selected period.",
        report_type="Financial",
        start=start,
        end=end,
        summary_rows=summary_rows,
        headers=headers,
        rows=rows,
        empty_message="No financial data found for the selected period.",
        filename=f"financial-{start.isoformat()}-{end.isoformat()}",
    )
