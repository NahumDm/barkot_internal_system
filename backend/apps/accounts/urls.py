"""Owner account-administration API URLs (roadmap C5).

Mounted at the API root (``/api/v1/users/``, ``/api/v1/roles/``,
``/api/v1/settings/``) because the Owner-facing catalogue has no domain
prefix of its own. The nested namespace is ``admin``, so the Python names are
``v1:admin:user-list`` and friends.

``settings/`` is declared before the router so the fixed segment is claimed
before any route that could swallow it. The router's own api-root route
(``^$``) lands on the same path as the project's ``ApiRootView``, which is
registered first in :mod:`config.api_urls` and therefore resolves; the
shadowed route is inert.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.admin_views import RoleViewSet, SiteSettingsView, UserViewSet

router = DefaultRouter()
router.register(r"users", UserViewSet, basename="user")
router.register(r"roles", RoleViewSet, basename="role")

app_name = "admin"

urlpatterns = [
    path("settings/", SiteSettingsView.as_view(), name="settings"),
    path("", include(router.urls)),
]

__all__ = ["urlpatterns"]
