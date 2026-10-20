from __future__ import annotations

from datetime import date

from django.http import HttpResponse

from apps.reports.pdf.builders import _build_pdf
from apps.reports.pdf.utils import format_date
from apps.reports.services import payroll_report


def payroll_report_pdf(*, start: date, end: date) -> HttpResponse:
    report = payroll_report(start=start, end=end)
    data = report.as_dict()

    summary_rows = [
        ("Period", f"{format_date(data['start'])} – {format_date(data['end'])}"),
        ("Currency", data["currency"]),
        ("Runs", str(data["summary"]["runs"])),
        ("Gross total", f"{data['summary']['gross_total']} {data['currency']}"),
        ("Deduction total", f"{data['summary']['deduction_total']} {data['currency']}"),
        ("Net total", f"{data['summary']['net_total']} {data['currency']}"),
    ]

    headers = ["Period month", "Status", "Employees", "Gross total", "Deduction total", "Net total", "Currency"]
    rows = []
    for row in data["rows"]:
        rows.append(
            [
                format_date(row["period_month"]),
                row["status_display"],
                str(row["employees"]),
                f"{row['gross_total']} {row['currency']}",
                f"{row['deduction_total']} {row['currency']}",
                f"{row['net_total']} {row['currency']}",
                row["currency"],
            ]
        )

    return _build_pdf(
        title="Payroll Report",
        description="Payroll runs, statuses and totals for the months in the selected period.",
        report_type="Payroll",
        start=start,
        end=end,
        summary_rows=summary_rows,
        headers=headers,
        rows=rows,
        empty_message="No payroll runs found for the selected period.",
        filename=f"payroll-{start.isoformat()}-{end.isoformat()}",
    )
