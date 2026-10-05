"""Inventory API URLs."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.inventory.views import (
    BreakageViewSet,
    StockCountViewSet,
    StockMovementViewSet,
    StockReceiptViewSet,
)

router = DefaultRouter()
router.register(r"receipts", StockReceiptViewSet, basename="stock-receipt")
router.register(r"breakages", BreakageViewSet, basename="breakage")
router.register(r"counts", StockCountViewSet, basename="stock-count")
router.register(r"movements", StockMovementViewSet, basename="stock-movement")

app_name = "inventory"
urlpatterns = [
    path("", include(router.urls)),
]
