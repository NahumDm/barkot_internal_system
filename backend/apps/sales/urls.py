"""Sales API URLs (spec §13.1).

Registered under ``/api/v1/sales/`` with namespace ``v1:sales``.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.sales.views import SaleViewSet

router = DefaultRouter()
router.register(r"", SaleViewSet, basename="sale")

app_name = "sales"
urlpatterns = [
    path("", include(router.urls)),
]

__all__ = ["urlpatterns"]
