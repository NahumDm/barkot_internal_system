from __future__ import annotations

from datetime import date

from django.http import HttpResponse

from apps.reports.pdf.builders import _build_pdf
from apps.reports.pdf.utils import format_date
from apps.reports.services import inventory_stock_balance, inventory_variance


def stock_balance_pdf(*, as_of: date) -> HttpResponse:
    report = inventory_stock_balance(as_of=as_of)
    data = report.as_dict()

    summary_rows = [
        ("As of", format_date(data["as_of"])),
        ("In stock total", f"{data['in_stock_total']}"),
        ("Products", str(data["products"])),
    ]

    headers = ["SKU", "Product", "Ledger balance", "Last counted", "Last counted on", "Delta"]
    rows = []
    for row in data["rows"]:
        rows.append([
            row["sku"],
            row["name"],
            str(row["ledger_balance"]),
            str(row["last_counted"]) if row["last_counted"] is not None else "",
            format_date(row["last_counted_on"]) if row["last_counted_on"] else "",
            str(row["delta"]) if row["delta"] is not None else "",
        ])

    return _build_pdf(
        title="Inventory Stock Balance Report",
        description="Ledger stock levels compared with the latest approved physical count.",
        report_type="Inventory",
        as_of=as_of,
        summary_rows=summary_rows,
        headers=headers,
        rows=rows,
        empty_message="No stock movements before this date.",
        landscape_layout=True,
        filename=f"stock-balance-{as_of.isoformat()}-{as_of.isoformat()}",
    )


def stock_variance_pdf(*, start: date, end: date) -> HttpResponse:
    report = inventory_variance(start=start, end=end)
    data = report.as_dict()

    summary_rows = [
        ("Period", f"{format_date(data['start'])} - {format_date(data['end'])}"),
        ("Lines", str(data["lines"])),
        ("Expected total", str(data["expected_total"])),
        ("Counted total", str(data["counted_total"])),
        ("Variance total", str(data["variance_total"])),
    ]

    headers = [
        "Count reference",
        "Status",
        "Counted on",
        "SKU",
        "Product",
        "Expected",
        "Counted",
        "Variance",
        "Note",
    ]
    rows = []
    for row in data["rows"]:
        rows.append([
            row["reference"],
            row["status"],
            format_date(row["counted_on"]),
            row["sku"],
            row["name"],
            str(row["expected_quantity"]),
            str(row["counted_quantity"]),
            str(row["variance"]),
            row.get("note") or "",
        ])

    return _build_pdf(
        title="Inventory Variance Report",
        description="Approved physical count variances for the selected period.",
        report_type="Inventory",
        start=start,
        end=end,
        summary_rows=summary_rows,
        headers=headers,
        rows=rows,
        empty_message="No approved variances found for the selected period.",
        landscape_layout=True,
        filename=f"stock-variance-{start.isoformat()}-{end.isoformat()}",
    )
