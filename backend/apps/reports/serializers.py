"""Request and response serializers for the reports API (spec §15).

Report responses are read-only projections, so every serializer here is a plain
:class:`rest_framework.serializers.Serializer` — nothing is saved through them.
Dates arrive as ``YYYY-MM-DD`` and every Decimal travels as its quantised
string, matching how the finance API already speaks money so the frontend has
one formatting path.
"""

from __future__ import annotations

from datetime import date

from rest_framework import serializers


class ReportPeriodQuerySerializer(serializers.Serializer):
    """The date-range filter every period report accepts (spec §15.2).

    Both bounds are required — a report without an explicit end point is a
    report the reader cannot reproduce — and ``end`` must not be earlier than
    ``start``.
    """

    start = serializers.DateField()
    end = serializers.DateField()

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        start = attrs["start"]
        end = attrs["end"]
        if isinstance(start, date) and isinstance(end, date) and end < start:
            raise serializers.ValidationError("end must be on or after start.")
        return attrs


class AsOfQuerySerializer(serializers.Serializer):
    """The as-of filter for the stock balance report (spec §15.2)."""

    date = serializers.DateField()


class StockBalanceRowSerializer(serializers.Serializer):
    """One product on the stock balance report."""

    product_id = serializers.IntegerField()
    sku = serializers.CharField()
    name = serializers.CharField()
    ledger_balance = serializers.CharField()
    last_counted = serializers.CharField(allow_null=True)
    last_counted_on = serializers.DateField(allow_null=True)
    delta = serializers.CharField(allow_null=True)


class StockBalanceReportSerializer(serializers.Serializer):
    """Ledger balance vs latest approved count as of one business date."""

    as_of = serializers.DateField()
    in_stock_total = serializers.CharField()
    products = serializers.IntegerField()
    rows = StockBalanceRowSerializer(many=True)


class StockVarianceRowSerializer(serializers.Serializer):
    """One approved count line whose counted quantity differed from expected."""

    stock_count_id = serializers.IntegerField()
    reference = serializers.CharField()
    status = serializers.CharField()
    product_id = serializers.IntegerField()
    sku = serializers.CharField()
    name = serializers.CharField()
    counted_on = serializers.DateField()
    expected_quantity = serializers.CharField()
    counted_quantity = serializers.CharField()
    variance = serializers.CharField()
    note = serializers.CharField()


class StockVarianceReportSerializer(serializers.Serializer):
    """Approved count variances in a period."""

    start = serializers.DateField()
    end = serializers.DateField()
    lines = serializers.IntegerField()
    expected_total = serializers.CharField()
    counted_total = serializers.CharField()
    variance_total = serializers.CharField()
    rows = StockVarianceRowSerializer(many=True)


class PayrollRunRowSerializer(serializers.Serializer):
    """One payroll run on the payroll report."""

    run_id = serializers.IntegerField()
    period_month = serializers.DateField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    currency = serializers.CharField()
    employees = serializers.IntegerField()
    gross_total = serializers.CharField()
    deduction_total = serializers.CharField()
    net_total = serializers.CharField()


class PayrollStatusBucketSerializer(serializers.Serializer):
    """One run status's share of the period's gross and net pay."""

    status = serializers.CharField()
    status_display = serializers.CharField()
    runs = serializers.IntegerField()
    gross_total = serializers.CharField()
    deduction_total = serializers.CharField()
    net_total = serializers.CharField()


class PayrollReportSerializer(serializers.Serializer):
    """How much is owed and paid for the months in the period."""

    start = serializers.DateField()
    end = serializers.DateField()
    currency = serializers.CharField()
    rows = PayrollRunRowSerializer(many=True)
    summary = serializers.DictField(child=serializers.JSONField())
    deductions = serializers.DictField(child=serializers.CharField())


__all__ = [
    "AsOfQuerySerializer",
    "PayrollReportSerializer",
    "PayrollRunRowSerializer",
    "PayrollStatusBucketSerializer",
    "ReportPeriodQuerySerializer",
    "StockBalanceReportSerializer",
    "StockBalanceRowSerializer",
    "StockVarianceReportSerializer",
    "StockVarianceRowSerializer",
]
