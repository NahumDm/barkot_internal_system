"""Finance API URLs."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.finance.views import ExpenseCategoryViewSet, ExpenseViewSet, FinanceBalanceView

router = DefaultRouter()
router.register(r"categories", ExpenseCategoryViewSet, basename="expense-category")
router.register(r"expenses", ExpenseViewSet, basename="expense")

app_name = "finance"
urlpatterns = [
    path("balance/", FinanceBalanceView.as_view(), name="balance"),
    path("", include(router.urls)),
]
