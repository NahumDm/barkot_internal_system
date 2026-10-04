"""Product catalogue API URLs (spec §11.1).

Registered under ``/api/v1/products/`` with namespace ``v1:products``.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.products.views import CategoryViewSet, ProductViewSet

router = DefaultRouter()
# Order matters and cannot be expressed any other way. The product detail route is
# ``products/<pk>/`` and the router's default lookup regex matches any token without
# a slash, so registering products first makes ``products/categories/`` resolve as a
# product retrieve with pk="categories": the category list and create endpoints then
# answer 404/405 and nothing about the catalogue below them is reachable. Registering
# the fixed segment first claims that path before the wildcard can.
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"", ProductViewSet, basename="product")

app_name = "products"
urlpatterns = [
    path("", include(router.urls)),
]

__all__ = ["urlpatterns"]
