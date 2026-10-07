"""The versioned API surface (spec §8.1).

The version lives in the URL path (``/api/v1/``) rather than in an ``Accept``
header because the only client is a same-origin browser bundle that cannot set
headers on a navigation, and because a path is what a human can read out of an
access log when working out which call produced a 500.

Each router is included as one line as it is built, so adding a resource never
means editing the root URLconf.
"""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from config.api_root import ApiRootView

#: Namespaced so ``reverse("v1:...")`` cannot collide with a future ``v2:``.
app_name = "v1"

urlpatterns = [
    path("", ApiRootView.as_view(), name="root"),
    path("auth/", include("apps.accounts.auth_urls")),
    path("products/", include("apps.products.urls")),
    path("sales/", include("apps.sales.urls")),
    path("finance/", include("apps.finance.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("payroll/", include("apps.payroll.urls")),
    path("reports/", include("apps.reports.urls")),
    # C5: Owner account administration lives at the root of the version
    # (/users/, /roles/, /settings/). Included last so the more specific
    # domain prefixes above always win on their own paths.
    path("", include("apps.accounts.urls")),
]

#: Wired in ``config/urls.py``. The schema is mounted beside the version rather
#: than inside it: a v1 client that had to name v2 to read the schema would
#: defeat the point of versioning, which is to let both exist during a migration.
schema_urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
