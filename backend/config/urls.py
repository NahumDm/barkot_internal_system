"""Root URL configuration for the Barkot backend.

Three surfaces:

- ``/health/...`` - operational probes consumed by Docker and Nginx (spec
  §24.1). Plain Django views, never part of the documented API contract.
- ``/api/...`` - the business API, versioned under ``/api/v1/`` (spec §8.1).
  The schema and docs views sit beside the version rather than inside it: a
  versioned schema would mean a v1 client had to know about v2 to read it.
"""

from django.urls import include, path

from config.api_urls import schema_urlpatterns
from config.errors import not_found
from config.health import health_live, health_ready

#: An unmatched URL under /api/ is answered with the JSON error envelope rather
#: than Django's HTML page, so an API client never has to branch on content type.
handler404 = not_found

urlpatterns = [
    path("health/live", health_live, name="health-live"),
    path("health/ready", health_ready, name="health-ready"),
    path("api/v1/", include("config.api_urls", namespace="v1")),
    path("api/", include(schema_urlpatterns)),
]
