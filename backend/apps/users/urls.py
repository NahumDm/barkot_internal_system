"""Employee register API URLs (spec §5).

Mounted at the API root (``/api/v1/employees/``) because the register belongs to
no business domain — it is the shared roster every domain points at, and Payroll
already owns ``/payroll/employees/``, so a domain prefix here would only invite
confusion between the two. The nested namespace is ``users``, so the Python names
are ``v1:users:employee-list`` and friends.

The router's own api-root route (``^$``) lands on the same path as the project's
``ApiRootView``, which is registered first in :mod:`config.api_urls` and
therefore resolves; the shadowed route is inert (same as ``accounts.urls``).
"""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.users.views import EmployeeViewSet

router = DefaultRouter()
router.register(r"employees", EmployeeViewSet, basename="employee")

app_name = "users"

urlpatterns = [
    path("", include(router.urls)),
]

__all__ = ["urlpatterns"]
