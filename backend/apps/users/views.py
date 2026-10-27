"""Employee register API (spec §5).

Every action on this viewset — reading included — is gated by the existing
``users.manage_employees`` grant, because a register of who works here, what
they are paid for and when their contract ends is staff data rather than a
public catalogue. The matrix grants that permission to the Owner and the
Manager and withholds it from the shopfloor roles, which is enforced here the
same way it is everywhere else: ``get_permissions`` asks the permission class,
the class asks ``has_perm``, and ``has_perm`` reads
:func:`apps.accounts.permissions.ROLE_MATRIX`. Nothing in this module branches
on a role name.

Documents are uploaded to ``POST /employees/{id}/document/`` as multipart and
are never served back: the response is the register record, which says whether
one is on file and what it is called, not a URL for it.

No view writes a model directly. The register's state changes live in
:mod:`apps.users.services` so the row and its audit entry commit together (P06).
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import CanManageEmployees
from apps.core.pagination import BarkotPagination
from apps.users.models import EmployeeProfile
from apps.users.serializers import (
    EmployeeCreateSerializer,
    EmployeeDocumentSerializer,
    EmployeeSerializer,
    EmployeeUpdateSerializer,
)
from apps.users.services import (
    archive_employee,
    create_employee,
    restore_employee,
    store_document,
    update_employee,
)


@extend_schema_view(
    list=extend_schema(summary="List employees", tags=["employees"]),
    retrieve=extend_schema(summary="Get an employee", tags=["employees"]),
    create=extend_schema(summary="Register an employee", tags=["employees"]),
    update=extend_schema(summary="Edit an employee", tags=["employees"]),
    partial_update=extend_schema(summary="Edit an employee", tags=["employees"]),
    archive=extend_schema(
        summary="Archive an employee",
        request=None,
        responses=EmployeeSerializer,
        tags=["employees"],
    ),
    restore=extend_schema(
        summary="Restore an archived employee",
        request=None,
        responses=EmployeeSerializer,
        tags=["employees"],
    ),
    upload_document=extend_schema(
        summary="Upload an employee contract document (PDF)",
        request=EmployeeDocumentSerializer,
        responses=EmployeeSerializer,
        tags=["employees"],
    ),
)
class EmployeeViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """The employee register: create, edit, archive, restore, document.

    There is no destroy action, and that is the point rather than an omission.
    Payroll runs, payslip lines and audit rows all reference the person, so the
    only way to stop counting someone is :meth:`archive`, which keeps the row
    and records when they left. A ``DELETE`` would have to either refuse
    (a lie of an endpoint) or cascade into history (a data-loss bug).
    """

    # ``select_related`` because every row reports its linked login name: the
    # list would otherwise ask the accounts table once per person on the page.
    queryset = EmployeeProfile.objects.select_related("user").all()
    serializer_class = EmployeeSerializer
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_permissions(self) -> list[Any]:
        """One gate for every action, including the reads.

        The register is not a phone book: a Cashier or Barman has no business
        listing staff names, positions and contract dates, and the only screens
        that show them are the register itself and the payroll form behind it.
        """
        return [IsAuthenticated(), CanManageEmployees()]

    def get_queryset(self) -> Any:
        """Optionally narrow the register to archived or current records.

        ``?archived=true`` lists only people who have left and ``false`` only
        people who have not. Omitted means both, because the register is the
        history: hiding archived rows by default is a view choice, and making it
        impossible to see them at all would undo what archiving is for.
        """
        queryset = super().get_queryset()
        archived = self.request.query_params.get("archived")
        if archived in {"true", "false"}:
            queryset = queryset.filter(is_archived=archived == "true")
        return queryset

    def get_serializer_class(self) -> type[Any]:
        """The write bodies are narrower than the read body."""
        if self.action == "create":
            return EmployeeCreateSerializer
        if self.action in {"update", "partial_update"}:
            return EmployeeUpdateSerializer
        return EmployeeSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = create_employee(
            full_name=serializer.validated_data["full_name"],
            position=serializer.validated_data["position"],
            start_date=serializer.validated_data["start_date"],
            phone_number=serializer.validated_data.get("phone_number", ""),
            contract_type=serializer.validated_data["contract_type"],
            contract_end_date=serializer.validated_data.get("contract_end_date"),
            notes=serializer.validated_data.get("notes", ""),
            address=serializer.validated_data.get("address", ""),
            emergency_contact=serializer.validated_data.get("emergency_contact", ""),
            actor=request.user,  # type: ignore[arg-type]
        )
        return Response(
            EmployeeSerializer(profile).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Apply a PATCH or PUT through the service layer.

        The serializer declares only the fields a person record may be edited
        with, so its ``validated_data`` *is* the change set — which is why the
        whole of it is handed over rather than a hand-copied list of keys. A
        field nobody is allowed to edit cannot reach the service that way.
        """
        profile = self.get_object()
        serializer = EmployeeUpdateSerializer(
            instance=profile,
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)
        updated = update_employee(
            profile=profile,
            changes=dict(serializer.validated_data),
            actor=request.user,  # type: ignore[arg-type]
        )
        return Response(EmployeeSerializer(updated).data)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request: Request, pk: Any = None) -> Response:
        """Archive a staff member who has left, keeping their history."""
        profile = archive_employee(
            profile=self.get_object(),
            actor=request.user,  # type: ignore[arg-type]
        )
        return Response(EmployeeSerializer(profile).data)

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request: Request, pk: Any = None) -> Response:
        """Bring an archived staff member back onto the register."""
        profile = restore_employee(
            profile=self.get_object(),
            actor=request.user,  # type: ignore[arg-type]
        )
        return Response(EmployeeSerializer(profile).data)

    # Multipart only, and only here. The rest of the API is JSON by contract,
    # so the parsers are narrowed on the action rather than widened on the view:
    # an endpoint that accepted multipart bodies everywhere would be one
    # CSRF-shaped surprise on every other route.
    @action(
        detail=True,
        methods=["post"],
        url_path="document",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_document(self, request: Request, pk: Any = None) -> Response:
        """Store a contract PDF against this record, replacing any previous one."""
        serializer = EmployeeDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = store_document(
            profile=self.get_object(),
            document=serializer.validated_data["document"],
            actor=request.user,  # type: ignore[arg-type]
        )
        return Response(EmployeeSerializer(profile).data)


__all__ = ["EmployeeViewSet"]
