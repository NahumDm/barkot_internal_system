r"""A URLconf used only by the API base tests, via ``override_settings``.

Exercising 401 versus 403 through real middleware needs a real URL, real
sessions and a real ``AuthenticationMiddleware``. Building that inline in a
test would mean re-deriving the request by hand and asserting against a
construction rather than against how the server actually behaves, so these
routes live here instead of in ``config/urls.py``.

They are deliberately not part of the shipped API. A placeholder protected
endpoint in the real URLconf would exist only to be tested, and the first real
domain endpoint in Phase B would have to delete it.
"""

from __future__ import annotations

from typing import Any

from django.urls import path
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

#: A real catalogue permission, so the 403 test proves the role matrix is
#: reached through the session rather than that a hard-coded check fired.
APPROVE_PAYROLL = "payroll.approve_run"


class HasPermission(BasePermission):
    """Requires one permission from the role matrix, checked the normal way.

    ``user.has_perm`` is the single enforcement point for Barkot (spec §9.2,
    P06): the permissions come from ``Role.permissions_granted`` via
    ``RolePermissionBackend``. Using it here means the test exercises that
    chain instead of asserting against a stand-in.

    The required permission is a class attribute rather than a constructor
    argument because DRF instantiates each entry in ``permission_classes`` with
    no arguments, so ``partial``-style configuration is not available.
    """

    permission: str = ""

    def has_permission(self, request: Request, view: Any) -> bool:
        """Return whether the requesting user holds the required permission."""
        user = request.user
        return bool(user and user.is_authenticated and user.has_perm(self.permission))


class HasApprovePayrollPermission(HasPermission):
    """Approving payroll is a Manager and Owner capability, not a Cashier's."""

    permission = APPROVE_PAYROLL


class ProtectedView(APIView):
    """Any signed-in member of staff. Used to test 401 versus 403."""

    def get(self, request: Request) -> Response:
        """Return a marker so the test can prove the view body was reached."""
        return Response({"reached": "protected"})


class ApprovePayrollView(ProtectedView):
    """Owner and Manager only. Used to test that a Cashier is refused."""

    permission_classes = [IsAuthenticated, HasApprovePayrollPermission]


urlpatterns = [
    path("api/v1/anything/", ProtectedView.as_view(), name="test-protected"),
    path(
        "api/v1/payroll/approve/",
        ApprovePayrollView.as_view(),
        name="test-approve-payroll",
    ),
]
