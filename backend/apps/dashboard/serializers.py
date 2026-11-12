"""Request and response serializers for the dashboard API (spec §7.4).

The dashboard is a read-only summary: it owns no data and computes nothing of
its own. The response reuses the exact serializers the domain screens already
answer with (finance balance, latest payroll run, recent sales, stock balance)
so the summary card and its source screen cannot drift apart. The period is
optional and defaults to the current business month-to-date, which is the only
default a "right now" summary can honestly claim.
"""

from __future__ import annotations

from datetime import date

from rest_framework import serializers

from apps.core.business_time import business_date, now_utc
from apps.finance.serializers import BalanceSerializer
from apps.sales.serializers import SaleListSerializer


class DashboardQuerySerializer(serializers.Serializer):
    """The optional date range the dashboard summarises.

    Both bounds must be supplied together. Absent both, the range defaults to
    the current business month-to-date (the first of the month through today).
    A period without an explicit end point would be a summary the reader cannot
    reproduce, so a single bound is refused rather than guessed at.
    """

    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)

    def validate(self, attrs: dict[str, object]) -> dict[str, object]:
        start = attrs.get("start")
        end = attrs.get("end")
        if start is None and end is not None:
            raise serializers.ValidationError("start and end must be provided together.")
        if start is not None and end is None:
            raise serializers.ValidationError("start and end must be provided together.")
        if isinstance(start, date) and isinstance(end, date) and end < start:
            raise serializers.ValidationError("end must be on or after start.")
        today = business_date(now_utc())
        attrs["start"] = attrs.get("start") or today.replace(day=1)
        attrs["end"] = attrs.get("end") or today
        return attrs


class DashboardPeriodSerializer(serializers.Serializer):
    """The period the summary covers."""

    start = serializers.DateField()
    end = serializers.DateField()
    currency = serializers.CharField()


class DashboardSalesSectionSerializer(serializers.Serializer):
    """Sales income and the latest transactions in the period (spec §13.1)."""

    total = serializers.CharField()
    cash = serializers.CharField()
    mobile_banking = serializers.CharField()
    transactions = serializers.IntegerField()
    recent = SaleListSerializer(many=True)


class DashboardAdditionalIncomeSectionSerializer(serializers.Serializer):
    total = serializers.CharField()


class DashboardInventorySectionSerializer(serializers.Serializer):
    """What the ledger says should be on the shelf as of the end of the period."""

    as_of = serializers.DateField()
    in_stock_total = serializers.CharField()
    products = serializers.IntegerField()


class DashboardPayrollSerializer(serializers.Serializer):
    """The latest payroll run and where it sits in its lifecycle (spec §14.2)."""

    id = serializers.IntegerField()
    period_month = serializers.DateField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    gross_total = serializers.CharField()
    deduction_total = serializers.CharField()
    net_total = serializers.CharField()
    generated_at = serializers.DateTimeField(allow_null=True)
    approved_at = serializers.DateTimeField(allow_null=True)
    approved_by = serializers.IntegerField(allow_null=True)
    approved_by_username = serializers.CharField(allow_null=True)
    paid_at = serializers.DateTimeField(allow_null=True)


class DashboardSerializer(serializers.Serializer):
    """The role-scoped dashboard summary.

    Sections are ``null`` when the requesting user's role does not grant the
    underlying domain read: a Cashier's dashboard carries ``sales`` and
    ``inventory`` and ``null`` ``finance`` and ``payroll``, so the screen never
    needs to ask for a number the server refused to stand behind and the wire
    shape stays stable for every role.
    """

    period = DashboardPeriodSerializer()
    sales = DashboardSalesSectionSerializer(required=False, allow_null=True)
    additional_income = DashboardAdditionalIncomeSectionSerializer(required=False, allow_null=True)
    inventory = DashboardInventorySectionSerializer(required=False, allow_null=True)
    finance = BalanceSerializer(required=False, allow_null=True)
    payroll = DashboardPayrollSerializer(required=False, allow_null=True)


__all__ = [
    "DashboardInventorySectionSerializer",
    "DashboardPayrollSerializer",
    "DashboardPeriodSerializer",
    "DashboardQuerySerializer",
    "DashboardSalesSectionSerializer",
    "DashboardSerializer",
]
