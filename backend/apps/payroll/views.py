"""Payroll API views (spec §14.1).

Three permissions meet here, and the split between them is the feature rather than
an implementation detail:

- ``payroll.view_payroll`` reads runs, lines and deductions;
- ``payroll.generate_run`` creates a month's run from current wages;
- ``payroll.approve_run`` signs it off, and only the Owner holds it;
- ``payroll.mark_paid`` records disbursement, likewise Owner-only;
- ``payroll.create_deduction`` adds a deduction while a run is still generated;
- ``payroll.manage_payroll_employees`` reads the staff roster and puts someone
  on payroll.

Generation and approval being separate actions on separate grants is what stops one
account producing a payslip nobody else looked at (A8). Both roles could equally
have been given both permissions, and the UI would still have shown two buttons.

The roster read (``profiles``) is not a payroll resource: it lists
:class:`apps.users.models.EmployeeProfile` rows so the create form has options to
offer. It carries ``manage_payroll_employees`` rather than ``view_payroll`` because
the only screen that needs it is the one that adds a payroll employee, and names
with phone numbers are staff data rather than a payslip figure.

No view branches on ``user.role``; :data:`apps.accounts.permissions.ROLE_MATRIX` is
the only mapping, and ``get_permissions`` asks it per action.
"""

from __future__ import annotations

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import (
    CanApprovePayrollRun,
    CanCreateDeduction,
    CanGeneratePayrollRun,
    CanManagePayrollEmployees,
    CanMarkPayrollPaid,
    CanViewPayroll,
)
from apps.core.pagination import BarkotPagination
from apps.payroll.models import Employee, PayrollDeduction, PayrollItem, PayrollRun
from apps.payroll.serializers import (
    PayrollDeductionCreateSerializer,
    PayrollDeductionSerializer,
    PayrollEmployeeCreateSerializer,
    PayrollEmployeeSerializer,
    PayrollItemSerializer,
    PayrollProfileSerializer,
    PayrollRunGenerateSerializer,
    PayrollRunSerializer,
)
from apps.payroll.services import (
    add_deduction,
    add_employee,
    approve_payroll_run,
    generate_payroll_run,
    mark_payroll_run_paid,
)
from apps.users.models import EmployeeProfile


@extend_schema_view(
    list=extend_schema(summary="List payroll employees", tags=["payroll"]),
    retrieve=extend_schema(summary="Get a payroll employee", tags=["payroll"]),
    create=extend_schema(summary="Add a staff profile to payroll", tags=["payroll"]),
)
class PayrollEmployeeViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Monthly-payroll records for staff who already have a profile.

    Read-only beyond creation on purpose: there is no service that changes a wage
    or an employment status, and adding an endpoint that edits the model directly
    would be the first write in this app to skip
    :mod:`apps.payroll.services` — which is where the audit entry and the
    validation live.
    """

    queryset = Employee.objects.select_related("profile").all()
    serializer_class = PayrollEmployeeSerializer
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewPayroll()]
        return [IsAuthenticated(), CanManagePayrollEmployees()]

    def get_serializer_class(self):
        if self.action == "create":
            return PayrollEmployeeCreateSerializer
        return PayrollEmployeeSerializer

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # ``add_employee`` is the documented way to build this pair, so the
        # one-to-one link, the initial status and the audit entry are always
        # set together (roadmap D1).
        employee = add_employee(
            profile=serializer.validated_data["profile"],
            monthly_wage=serializer.validated_data["monthly_wage"],
            actor=request.user,
        )
        return Response(
            PayrollEmployeeSerializer(employee).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    list=extend_schema(summary="List payroll runs", tags=["payroll"]),
    retrieve=extend_schema(summary="Get a payroll run", tags=["payroll"]),
    create=extend_schema(summary="Generate a payroll run", tags=["payroll"]),
)
class PayrollRunViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Monthly runs and their lifecycle.

    Ordered newest first on ``period_month`` so the screen opens on the current
    month, with ``-id`` as a tiebreak because a period is unique but the ordering
    still has to be total for pagination to be stable.
    """

    queryset = PayrollRun.objects.all().order_by("-period_month", "-id")
    serializer_class = PayrollRunSerializer
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_permissions(self):
        if self.action in {"list", "retrieve", "items"}:
            return [IsAuthenticated(), CanViewPayroll()]
        if self.action == "approve":
            return [IsAuthenticated(), CanApprovePayrollRun()]
        if self.action == "mark_paid":
            return [IsAuthenticated(), CanMarkPayrollPaid()]
        return [IsAuthenticated(), CanGeneratePayrollRun()]

    def get_serializer_class(self):
        if self.action == "create":
            return PayrollRunGenerateSerializer
        return PayrollRunSerializer

    def get_queryset(self) -> QuerySet[PayrollRun]:
        queryset = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = generate_payroll_run(
            period=serializer.validated_data["period"],
            employee_ids=serializer.validated_data.get("employee_ids"),
            actor=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(PayrollRunSerializer(run).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Approve a generated payroll run",
        responses=PayrollRunSerializer,
        tags=["payroll"],
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request: Request, pk: int | None = None) -> Response:
        approved = approve_payroll_run(run=self.get_object(), actor=request.user)
        return Response(PayrollRunSerializer(approved).data)

    @extend_schema(
        summary="Mark an approved payroll run as paid",
        responses=PayrollRunSerializer,
        tags=["payroll"],
    )
    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request: Request, pk: int | None = None) -> Response:
        paid = mark_payroll_run_paid(run=self.get_object(), actor=request.user)
        return Response(PayrollRunSerializer(paid).data)

    @extend_schema(
        summary="List the payslip lines in a run",
        responses=PayrollItemSerializer(many=True),
        tags=["payroll"],
    )
    @action(detail=True, methods=["get"], url_path="items")
    def items(self, request: Request, pk: int | None = None) -> Response:
        """Return one page of this run's employee lines.

        Paginated as its own endpoint rather than nested inside the run body: a run
        has a line per employee, so embedding the collection would make the run list
        unbounded in size and would silently load every payslip on the screen that
        only wanted this month's header.
        """
        run = self.get_object()
        lines = PayrollItem.objects.select_related("employee__profile").filter(run=run)
        page = self.paginate_queryset(lines)
        serializer = PayrollItemSerializer(page if page is not None else lines, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(summary="List payroll deductions", tags=["payroll"]),
    retrieve=extend_schema(summary="Get a payroll deduction", tags=["payroll"]),
    create=extend_schema(summary="Record a payroll deduction", tags=["payroll"]),
)
class PayrollDeductionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Deductions against payroll lines, each with the reason it was taken."""

    queryset = PayrollDeduction.objects.select_related(
        "payroll_item__employee__profile", "payroll_item__run"
    ).order_by("-occurred_on", "-id")
    serializer_class = PayrollDeductionSerializer
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewPayroll()]
        return [IsAuthenticated(), CanCreateDeduction()]

    def get_serializer_class(self):
        if self.action == "create":
            return PayrollDeductionCreateSerializer
        return PayrollDeductionSerializer

    def get_queryset(self) -> QuerySet[PayrollDeduction]:
        queryset = super().get_queryset()
        payroll_item = self.request.query_params.get("payroll_item")
        if payroll_item:
            queryset = queryset.filter(payroll_item_id=payroll_item)
        run = self.request.query_params.get("run")
        if run:
            queryset = queryset.filter(payroll_item__run_id=run)
        return queryset

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        deduction = add_deduction(
            payroll_item=serializer.validated_data["payroll_item"],
            deduction_type=serializer.validated_data["deduction_type"],
            amount=serializer.validated_data["amount"],
            reason=serializer.validated_data.get("reason", ""),
            occurred_on=serializer.validated_data.get("occurred_on"),
            actor=request.user,
        )
        return Response(
            PayrollDeductionSerializer(deduction).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    list=extend_schema(
        summary="List staff profiles available for payroll",
        tags=["payroll"],
    ),
)
class PayrollProfileViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Active staff profiles that are not on payroll yet.

    This is the options list behind ``POST /payroll/employees/``: ``apps.users``
    has no API of its own, so a form that asked for a ``profile`` id would have
    nothing to offer. The field is written here rather than in ``users`` so the
    dependency points at payroll's own need instead of payroll reaching into a
    different app's read surface.

    A profile stays off the list once it has any payroll row, voided or not. The
    link is a ``OneToOne``, so a voided employee still occupies it, and offering
    the name again would only earn a create the server refuses.

    Archived profiles are excluded for the reason archiving exists: it records
    that someone left, so putting them back on a new month's payroll would be
    paying a person who is no longer employed.
    """

    serializer_class = PayrollProfileSerializer
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_queryset(self) -> QuerySet[EmployeeProfile]:
        already_on_payroll = Employee.all_rows.values("profile_id")
        return EmployeeProfile.objects.filter(is_archived=False).exclude(pk__in=already_on_payroll)

    def get_permissions(self):
        return [IsAuthenticated(), CanManagePayrollEmployees()]


__all__ = [
    "PayrollDeductionViewSet",
    "PayrollEmployeeViewSet",
    "PayrollProfileViewSet",
    "PayrollRunViewSet",
]
