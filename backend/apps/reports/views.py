"""Read-only report views (spec §15).

Every endpoint is a GET on the same shape: a validated date filter, the answer
projected from the domain that owns it, and a ``?export=csv`` escape hatch that
returns the same cells as an attachment instead of JSON (§15.3). None of them
accept a body, write anything, or own data; a report is a read-only query
service, never a mutator (§6.2).

The financial report deliberately returns ``BalanceSerializer`` — the exact
number the C1 balance screen shows — because authority over "what is net pay"
belongs to ``finance``. A reports endpoint that recomputed it would be the
second source of truth the spec forbids.
"""

from __future__ import annotations

from datetime import date

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import CanViewReports
from apps.finance.serializers import BalanceSerializer
from apps.finance.services import finance_balance
from apps.reports.pdf.financial import financial_report_pdf
from apps.reports.pdf.inventory import stock_balance_pdf, stock_variance_pdf
from apps.reports.pdf.payroll import payroll_report_pdf
from apps.reports.serializers import (
    AsOfQuerySerializer,
    PayrollReportSerializer,
    ReportPeriodQuerySerializer,
    StockBalanceReportSerializer,
    StockVarianceReportSerializer,
)
from apps.reports.services import (
    inventory_stock_balance,
    inventory_variance,
    payroll_report,
)


class FinancialReportView(APIView):
    """The balance sheet part of the reports page (spec §15.1).

    Reuses ``finance.services.finance_balance``: the CSV and the finance screen
    answer "what was the net result for October" with the same subtraction, so
    the two surfaces cannot drift apart.
    """

    permission_classes = [IsAuthenticated, CanViewReports]

    @extend_schema(
        summary="Get financial report for a local-date period",
        parameters=[ReportPeriodQuerySerializer],
        responses=BalanceSerializer,
        tags=["reports"],
    )
    def get(self, request: Request) -> Response | HttpResponse:
        query = ReportPeriodQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        period = query.validated_data
        balance = finance_balance(**period)
        export = request.query_params.get("export")
        if export in {"csv", "pdf"}:
            return financial_report_pdf(start=period["start"], end=period["end"])
        return Response(BalanceSerializer(balance.as_dict()).data)


class StockBalanceReportView(APIView):
    """What the ledger says should exist, per product, as of one business day."""

    permission_classes = [IsAuthenticated, CanViewReports]

    @extend_schema(
        summary="Get inventory stock balance as of a business date",
        parameters=[AsOfQuerySerializer],
        responses=StockBalanceReportSerializer,
        tags=["reports"],
    )
    def get(self, request: Request) -> Response | HttpResponse:
        query = AsOfQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        report = inventory_stock_balance(as_of=query.validated_data["date"])
        export = request.query_params.get("export")
        if export in {"csv", "pdf"}:
            return stock_balance_pdf(as_of=query.validated_data["date"])
        return Response(StockBalanceReportSerializer(report.as_dict()).data)


class StockVarianceReportView(APIView):
    """Approved physical-count variances in a local-date period (spec §15.1)."""

    permission_classes = [IsAuthenticated, CanViewReports]

    @extend_schema(
        summary="Get inventory count variances for a local-date period",
        parameters=[ReportPeriodQuerySerializer],
        responses=StockVarianceReportSerializer,
        tags=["reports"],
    )
    def get(self, request: Request) -> Response | HttpResponse:
        query = ReportPeriodQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        period = query.validated_data
        report = inventory_variance(**period)
        export = request.query_params.get("export")
        if export in {"csv", "pdf"}:
            return stock_variance_pdf(start=period["start"], end=period["end"])
        return Response(StockVarianceReportSerializer(report.as_dict()).data)


class PayrollReportView(APIView):
    """Runs, statuses and deductions for the months in the period (spec §15.1)."""

    permission_classes = [IsAuthenticated, CanViewReports]

    @extend_schema(
        summary="Get payroll report for the months in a local-date period",
        parameters=[ReportPeriodQuerySerializer],
        responses=PayrollReportSerializer,
        tags=["reports"],
    )
    def get(self, request: Request) -> Response | HttpResponse:
        query = ReportPeriodQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        period = query.validated_data
        report = payroll_report(**period)
        export = request.query_params.get("export")
        if export in {"csv", "pdf"}:
            return payroll_report_pdf(start=period["start"], end=period["end"])
        return Response(PayrollReportSerializer(report.as_dict()).data)


def _filename(kind: str, start: date, end: date) -> str:
    """A spreadsheet-friendly CSV filename containing the period asked for."""
    return f"{kind}-{start.isoformat()}-{end.isoformat()}"


__all__ = [
    "FinancialReportView",
    "PayrollReportView",
    "StockBalanceReportView",
    "StockVarianceReportView",
]
