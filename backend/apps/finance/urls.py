"""Finance API URLs."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.finance.views import (
    AdditionalIncomeViewSet,
    ExpenseCategoryViewSet,
    ExpenseViewSet,
    FinanceBalanceView,
)

router = DefaultRouter()
router.register(r"categories", ExpenseCategoryViewSet, basename="expense-category")
router.register(r"expenses", ExpenseViewSet, basename="expense")
router.register(r"additional-income", AdditionalIncomeViewSet, basename="additional-income")

app_name = "finance"
urlpatterns = [
    path("balance/", FinanceBalanceView.as_view(), name="balance"),
    path("", include(router.urls)),
]
