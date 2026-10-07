"""Dashboard API views (spec §7.4).

One read-only endpoint returns the whole summary. It accepts no body, writes
nothing, and owns no data; every tile is a projection of what another domain
already decided, so the dashboard cannot disagree with the screen it links to.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dashboard.serializers import DashboardQuerySerializer, DashboardSerializer
from apps.dashboard.services import dashboard_summary


class DashboardView(APIView):
    """The role-scoped dashboard summary (spec §7.4)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get the dashboard summary for a local-date period",
        description=(
            "Returns sales, inventory, finance and payroll tiles for the period, "
            "each present only when the requesting role grants that domain read. "
            "``start`` and ``end`` must be supplied together and default to the "
            "current business month-to-date. All figures delegate to the "
            "authoritative domain services; nothing is recomputed here."
        ),
        parameters=[DashboardQuerySerializer],
        responses=DashboardSerializer,
        tags=["dashboard"],
    )
    def get(self, request: Request) -> Response:
        query = DashboardQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        period = query.validated_data
        payload = dashboard_summary(
            start=period["start"],
            end=period["end"],
            user=request.user,  # type: ignore[arg-type]
        )
        return Response(DashboardSerializer(payload).data)


__all__ = ["DashboardView"]
