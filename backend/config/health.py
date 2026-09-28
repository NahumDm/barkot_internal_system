"""Operational health endpoints (spec §24.1).

- /health/live — the process is alive.
- /health/ready — the application can serve (database reachable).

These are ops infrastructure, intentionally free of business logic and
domain dependencies. Nginx and Docker Compose healthchecks depend on them.
"""

from django.db import connection
from django.http import HttpRequest, JsonResponse


def health_live(request: HttpRequest) -> JsonResponse:
    """Return 200 while the WSGI/ASGI process is responding."""
    return JsonResponse({"status": "ok"})


def health_ready(request: HttpRequest) -> JsonResponse:
    """Return 200 when ready to serve a request, else 503."""
    try:
        connection.ensure_connection()
    except Exception as exc:  # pragma: no cover - exercised against a live DB
        return JsonResponse(
            {"status": "error", "detail": "database unreachable", "reason": str(exc)},
            status=503,
        )
    return JsonResponse({"status": "ok", "checks": {"database": "ok"}})
