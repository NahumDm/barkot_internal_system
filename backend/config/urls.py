"""Root URL configuration for the Barkot backend.

The API surface is versioned under /api/v1/ and is added phase by phase
(spec §8.1). Phase 0A provides only the operational health endpoints.
"""

from django.urls import path

from config.health import health_live, health_ready

urlpatterns = [
    path("health/live", health_live, name="health-live"),
    path("health/ready", health_ready, name="health-ready"),
]
