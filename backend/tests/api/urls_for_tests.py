r"""A URLconf used only by the API base tests, via ``override_settings``.

Exercising 401 versus 403 through real middleware needs a real URL, real
sessions and a real ``AuthenticationMiddleware``. Building that inline in a
test would mean re-deriving the request by hand and asserting against a
construction rather than against how the server actually behaves, so these
routes live here instead of in ``config/urls.py``.

They are deliberately not part of the shipped API. A placeholder protected
endpoint in the real URLconf would exist only to be tested, and the first real
domain endpoint in Phase B would have to delete it.

The permission they enforce is *not* local to this file. Earlier versions defined
``HasPermission`` here, which meant the "a Cashier cannot approve payroll" gate
was asserting against the test's own copy of the rule rather than against the code
the application ships: nothing in ``apps/`` consulted ``ROLE_MATRIX`` at request
time. The classes now come from :mod:`apps.accounts.permissions`, so the same
gate fails if the shipped enforcement drifts from the matrix.
"""

from __future__ import annotations

from django.urls import path
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import CanApprovePayrollRun


class ProtectedView(APIView):
    """Any signed-in member of staff. Used to test 401 versus 403."""

    def get(self, request: Request) -> Response:
        """Return a marker so the test can prove the view body was reached."""
        return Response({"reached": "protected"})


class ApprovePayrollView(ProtectedView):
    """Owner only. Used to test that a Cashier is refused.

    Both entries are shipped classes. ``IsAuthenticated`` is listed first so a
    signed-out request is answered 401 and the caller can redirect to login,
    rather than 403, which would read as "you are signed in, but not allowed".

    The real payroll endpoints arrive in a later phase and inherit this
    behaviour; until then this view is how the refusal is observed over real
    HTTP without a placeholder living in the shipped URLconf.
    """

    permission_classes = [IsAuthenticated, CanApprovePayrollRun]


urlpatterns = [
    path("api/v1/anything/", ProtectedView.as_view(), name="test-protected"),
    path(
        "api/v1/payroll/approve/",
        ApprovePayrollView.as_view(),
        name="test-approve-payroll",
    ),
]
