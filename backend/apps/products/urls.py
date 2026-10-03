"""Product catalogue API URLs (spec §11.1).

Registered under ``/api/v1/products/`` with namespace ``v1:products``.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.products.views import CategoryViewSet, ProductViewSet

router = DefaultRouter()
router.register(r"", ProductViewSet, basename="product")
router.register(r"categories", CategoryViewSet, basename="category")

app_name = "products"
urlpatterns = [
    path("", include(router.urls)),
]

__all__ = ["urlpatterns"]
