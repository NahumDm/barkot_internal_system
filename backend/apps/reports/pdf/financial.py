from __future__ import annotations

from datetime import date

from django.http import HttpResponse

from apps.finance.services import finance_balance
from apps.reports.pdf.builders import _build_pdf
from apps.reports.pdf.utils import format_period


def financial_report_pdf(*, start: date, end: date) -> HttpResponse:
    balance = finance_balance(start=start, end=end)
    b = balance.as_dict()

    summary_rows = [
        ("Period", format_period(start, end)),
        ("Income (cash)", f"{b['income_cash']} {b['currency']}"),
        ("Income (mobile banking)", f"{b['income_mobile_banking']} {b['currency']}"),
        ("Income (total)", f"{b['income_total']} {b['currency']}"),
        ("Expenses (total)", f"{b['expenses_total']} {b['currency']}"),
        ("Payroll (total)", f"{b['payroll_total']} {b['currency']}"),
        ("Net", f"{b['net']} {b['currency']}"),
    ]

    headers = ["Item", "Amount (ETB)" if b["currency"] == "ETB" else "Amount"]
    rows = [
        ["Income (cash)", f"{b['income_cash']} {b['currency']}"],
        ["Income (mobile banking)", f"{b['income_mobile_banking']} {b['currency']}"],
        ["Income (total)", f"{b['income_total']} {b['currency']}"],
        ["Expenses (total)", f"{b['expenses_total']} {b['currency']}"],
        ["Payroll (total)", f"{b['payroll_total']} {b['currency']}"],
        ["Net", f"{b['net']} {b['currency']}"],
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
