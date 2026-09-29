"""The API root: ``GET /api/v1/``.

Answers one question for a client that has just booted: "am I talking to the
API I think I am?" The frontend calls this on start-up and compares ``version``
against the version its bundle was built against, which turns a
stale-bundle-after-deploy mismatch into a clear message instead of a stream of
404s from every screen.

It is a DRF view rather than a plain Django one so it appears in the generated
schema. The health endpoints deliberately do not: they are infrastructure
probes consumed by Docker and Nginx, not part of the business contract, and
documenting them would invite the frontend to depend on them.
"""

from __future__ import annotations

from django.urls import NoReverseMatch, reverse
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.schemas import ApiRootSerializer

#: Bumped when a breaking change lands in ``/api/v1/``. A non-breaking addition
#: does not bump it: the frontend only needs to care when the meaning of a path
#: it already calls has changed.
API_VERSION = "v1"


class ApiRootView(APIView):
    """Identify the service and point at its schema.

    ``AllowAny`` is a deliberate exception to the global ``IsAuthenticated``
    default (spec §9.2). This endpoint returns no business data and no user
    data - a service name and a version string that are already visible in the
    JavaScript bundle and the access log - and requiring a session to read it
    would mean an expired session produces a login redirect with no
    explanation of why the page was empty.
    """

    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    @extend_schema(
        summary="Identify the API and return its version",
        description=(
            "Returns the service name, the API version this URL is serving, and "
            "the path to the OpenAPI schema. Called by the frontend at start-up "
            "to detect a stale bundle after a deploy. Requires no authentication "
            "and returns no business data."
        ),
        responses={200: ApiRootSerializer},
        tags=["meta"],
    )
    def get(self, request: Request) -> Response:
        """Return the service identity and a link to the schema.

        Args:
            request: The incoming request. Unused; present because DRF passes it.

        Returns:
            A 200 with the service name, version and schema path.
        """
        # reverse() can raise NoReverseMatch if urlpatterns are swapped at
        # runtime, which some deployments do to disable docs. Reporting a
        # broken docs link is better than a 500 on the version check the whole
        # client depends on.
        try:
            documentation = reverse("schema")
        except NoReverseMatch:  # pragma: no cover - only under reconfigured routing
            documentation = ""
        return Response({
            "service": "Barkot Bar & Restaurant API",
            "version": API_VERSION,
            "documentation": documentation,
        })
