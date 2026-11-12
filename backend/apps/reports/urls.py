"""Reports API URLs."""

from django.urls import path

from apps.reports.views import (
    FinancialReportView,
    PayrollReportView,
    StockBalanceReportView,
    StockVarianceReportView,
)

app_name = "reports"

urlpatterns = [
    path("financial/", FinancialReportView.as_view(), name="financial"),
    path("inventory/stock-balance/", StockBalanceReportView.as_view(), name="stock-balance"),
    path("inventory/variance/", StockVarianceReportView.as_view(), name="stock-variance"),
    path("payroll/", PayrollReportView.as_view(), name="payroll"),
]
