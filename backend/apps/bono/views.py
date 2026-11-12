"""Bono API views.

Permissions are enforced by the role matrix, never by a role-name check. The
split is the point of the feature:

- every role holding ``bono.view_bono`` may read the operational picture;
- ``bono.manage_configuration`` is Owner-only;
- ``bono.manage_operations`` records issues, transfers and losses (Manager/Owner);
- ``bono.submit_report`` prepares and submits the cashier's report (Cashier/Owner);
- ``bono.approve_report`` approves, rejects or opens a correction (Owner-only).

A Barman holds only the first grant and therefore cannot reach a write endpoint
or the Sales API.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import (
    CanApproveBonoReport,
    CanCreateDeduction,
    CanManageBonoConfiguration,
    CanManageBonoOperations,
    CanSubmitBonoReport,
    CanViewBono,
)
from apps.bono.models import (
    BonoIncident,
    BonoIssue,
    BonoProductPairing,
    BonoReport,
    BonoTransfer,
    BonoType,
)
from apps.bono.serializers import (
    BonoConfigHistorySerializer,
    BonoDaySummarySerializer,
    BonoIncidentCreateSerializer,
    BonoIncidentDeductionSerializer,
    BonoIncidentResolveSerializer,
    BonoIncidentSerializer,
    BonoIssueCreateSerializer,
    BonoIssueSerializer,
    BonoProductPairingSerializer,
    BonoReportCorrectionSerializer,
    BonoReportCreateSerializer,
    BonoReportDetailSerializer,
    BonoReportRejectSerializer,
    BonoReportSerializer,
    BonoReportUpdateSerializer,
    BonoTransferCreateSerializer,
    BonoTransferSerializer,
    BonoTypeCreateSerializer,
    BonoTypeSerializer,
    BonoTypeUpdateSerializer,
    PairingAddSerializer,
    PairingRemoveSerializer,
    PairingReviewSerializer,
)
from apps.bono.services import (
    add_pairings,
    approve_report,
    config_history,
    create_bono_type,
    create_correction,
    create_incident,
    create_issue,
    create_report,
    create_transfer,
    day_summary,
    record_incident_deduction,
    refresh_report,
    reject_report,
    remove_pairing,
    resolve_incident,
    resolve_pairing_review,
    submit_report,
    today_business_date,
    update_bono_type,
    update_report,
)
from apps.core.pagination import BarkotPagination
from apps.core.query_params import boolean_value


def _can_see_money(user: Any) -> bool:
    """Cashiers need report money; a Barman's read-only Bono view does not."""
    return bool(
        user.has_perm("bono.submit_report")
        or user.has_perm("bono.approve_report")
        or user.has_perm("finance.view_reports")
    )


class BonoTypeViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Owner-managed Bono identities and their product pairings."""

    queryset = BonoType.objects.prefetch_related(
        Prefetch(
            "pairings",
            queryset=BonoProductPairing.objects.filter(is_active=True).select_related("product"),
            to_attr="_active_pairings",
        )
    ).order_by("name", "id")
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_serializer_class(self) -> type[Any]:
        if self.action == "create":
            return BonoTypeCreateSerializer
        if self.action in {"update", "partial_update"}:
            return BonoTypeUpdateSerializer
        return BonoTypeSerializer

    def get_permissions(self) -> list[Any]:
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewBono()]
        return [IsAuthenticated(), CanManageBonoConfiguration()]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bono_type = create_bono_type(
            name=serializer.validated_data["name"],
            color=serializer.validated_data.get("color", "#111827"),
            selling_price=serializer.validated_data["selling_price"],
            currency=serializer.validated_data.get("currency", "ETB"),
            notes=serializer.validated_data.get("notes", ""),
            actor=request.user,
        )
        output = BonoTypeSerializer(bono_type, context=self.get_serializer_context()).data
        return Response(output, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        bono_type = self.get_object()
        serializer = self.get_serializer(bono_type, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        confirm = bool(data.pop("confirm_in_progress", False))
        change_reason = str(data.pop("change_reason", ""))
        updated = update_bono_type(
            bono_type=bono_type,
            changes=data,
            actor=request.user,
            confirm_in_progress=confirm,
            change_reason=change_reason,
        )
        refreshed = self.get_queryset().get(pk=updated.pk)
        return Response(BonoTypeSerializer(refreshed, context=self.get_serializer_context()).data)

    @extend_schema(
        summary="Pair products with a Bono type",
        request=PairingAddSerializer,
        responses={201: BonoTypeSerializer},
        tags=["bono"],
    )
    @action(detail=True, methods=["post"], url_path="products")
    def products(self, request: Request, pk: Any = None) -> Response:
        bono_type = self.get_object()
        body = PairingAddSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        add_pairings(
            bono_type=bono_type,
            products=list(body.validated_data["products"]),
            actor=request.user,
            confirm_in_progress=body.validated_data["confirm_in_progress"],
            change_reason=body.validated_data.get("change_reason", ""),
        )
        refreshed = self.get_queryset().get(pk=bono_type.pk)
        return Response(
            BonoTypeSerializer(refreshed, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Read Bono configuration change history",
        responses=BonoConfigHistorySerializer(many=True),
        tags=["bono"],
    )
    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request: Request, pk: Any = None) -> Response:
        bono_type = self.get_object()
        rows = config_history(bono_type)
        page = self.paginate_queryset(rows)
        if page is not None:
            return self.get_paginated_response(BonoConfigHistorySerializer(page, many=True).data)
        return Response(BonoConfigHistorySerializer(rows, many=True).data)


class BonoPairingViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Read pairings, resolve a price review, or retire a pairing."""

    serializer_class = BonoProductPairingSerializer
    pagination_class = BarkotPagination
    paginator = BarkotPagination()
    queryset = BonoProductPairing.objects.select_related("bono_type", "product").order_by(
        "bono_type__name", "product__name", "-paired_at"
    )

    def get_permissions(self) -> list[Any]:
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewBono()]
        return [IsAuthenticated(), CanManageBonoConfiguration()]

    def get_queryset(self) -> Any:
        queryset = super().get_queryset()
        bono_type = self.request.query_params.get("bono_type")
        if bono_type:
            queryset = queryset.filter(bono_type_id=bono_type)
        active = self.request.query_params.get("active")
        if active is not None:
            queryset = queryset.filter(is_active=boolean_value(active, "active"))
        return queryset

    @extend_schema(
        summary="Resolve a Bono price-change review",
        request=PairingReviewSerializer,
        responses={200: BonoProductPairingSerializer},
        tags=["bono"],
    )
    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request: Request, pk: Any = None) -> Response:
        pairing = self.get_object()
        body = PairingReviewSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        result = resolve_pairing_review(
            pairing=pairing,
            resolution=body.validated_data["resolution"],
            target_bono_type=body.validated_data.get("target_bono_type"),
            reason=body.validated_data["reason"],
            confirm_in_progress=body.validated_data["confirm_in_progress"],
            actor=request.user,
        )
        if isinstance(result, BonoType):
            refreshed = BonoTypeViewSet.queryset.get(pk=result.pk)
            return Response(
                BonoTypeSerializer(refreshed, context=self.get_serializer_context()).data
            )
        return Response(
            BonoProductPairingSerializer(result, context=self.get_serializer_context()).data
        )

    @extend_schema(
        summary="Retire a product pairing without deleting history",
        request=PairingRemoveSerializer,
        responses={200: BonoProductPairingSerializer},
        tags=["bono"],
    )
    @action(detail=True, methods=["post"], url_path="remove")
    def remove(self, request: Request, pk: Any = None) -> Response:
        pairing = self.get_object()
        body = PairingRemoveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        retired = remove_pairing(
            pairing=pairing,
            reason=body.validated_data["reason"],
            confirm_in_progress=body.validated_data["confirm_in_progress"],
            change_reason=body.validated_data.get("change_reason", ""),
            actor=request.user,
        )
        return Response(
            BonoProductPairingSerializer(retired, context=self.get_serializer_context()).data
        )


class BonoIssueViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Append-only token hand-outs. There is deliberately no update or delete."""

    queryset = BonoIssue.objects.select_related("bono_type", "employee", "created_by").order_by(
        "-occurred_at", "-id"
    )
    serializer_class = BonoIssueSerializer
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_permissions(self) -> list[Any]:
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewBono()]
        return [IsAuthenticated(), CanManageBonoOperations()]

    def get_queryset(self) -> Any:
        queryset = super().get_queryset()
        operational_date = self.request.query_params.get("date")
        if operational_date:
            queryset = queryset.filter(operational_date=operational_date)
        if self.request.query_params.get("bono_type"):
            queryset = queryset.filter(bono_type_id=self.request.query_params["bono_type"])
        if self.request.query_params.get("employee"):
            queryset = queryset.filter(employee_id=self.request.query_params["employee"])
        return queryset

    def get_serializer_class(self) -> type[Any]:
        return BonoIssueCreateSerializer if self.action == "create" else BonoIssueSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = BonoIssueCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        issue = create_issue(
            operational_date=body.validated_data["operational_date"],
            bono_type=body.validated_data["bono_type"],
            employee=body.validated_data["employee"],
            kind=body.validated_data["kind"],
            quantity=body.validated_data["quantity"],
            note=body.validated_data.get("note", ""),
            actor=request.user,
        )
        return Response(BonoIssueSerializer(issue).data, status=status.HTTP_201_CREATED)


class BonoTransferViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Append-only custody transfers between staff."""

    queryset = BonoTransfer.objects.select_related(
        "bono_type", "from_employee", "to_employee", "created_by"
    ).order_by("-occurred_at", "-id")
    serializer_class = BonoTransferSerializer
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_permissions(self) -> list[Any]:
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewBono()]
        return [IsAuthenticated(), CanManageBonoOperations()]

    def get_queryset(self) -> Any:
        queryset = super().get_queryset()
        operational_date = self.request.query_params.get("date")
        if operational_date:
            queryset = queryset.filter(operational_date=operational_date)
        if self.request.query_params.get("bono_type"):
            queryset = queryset.filter(bono_type_id=self.request.query_params["bono_type"])
        return queryset

    def get_serializer_class(self) -> type[Any]:
        return BonoTransferCreateSerializer if self.action == "create" else BonoTransferSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = BonoTransferCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        transfer = create_transfer(
            operational_date=body.validated_data["operational_date"],
            bono_type=body.validated_data["bono_type"],
            from_employee=body.validated_data["from_employee"],
            to_employee=body.validated_data["to_employee"],
            quantity=body.validated_data["quantity"],
            reason=body.validated_data["reason"],
            note=body.validated_data.get("note", ""),
            actor=request.user,
        )
        return Response(BonoTransferSerializer(transfer).data, status=status.HTTP_201_CREATED)


class BonoIncidentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Lost tokens and broken bottles, with explicit follow-up outcomes."""

    queryset = BonoIncident.objects.select_related(
        "bono_type",
        "product",
        "responsible_employee",
        "created_by",
        "breakage_record",
        "payroll_deduction",
    ).order_by("-occurred_at", "-id")
    serializer_class = BonoIncidentSerializer
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_permissions(self) -> list[Any]:
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewBono()]
        if self.action == "deduct":
            return [
                IsAuthenticated(),
                CanManageBonoOperations(),
                CanCreateDeduction(),
            ]
        return [IsAuthenticated(), CanManageBonoOperations()]

    def get_queryset(self) -> Any:
        queryset = super().get_queryset()
        operational_date = self.request.query_params.get("date")
        if operational_date:
            queryset = queryset.filter(operational_date=operational_date)
        kind = self.request.query_params.get("kind")
        if kind:
            queryset = queryset.filter(kind=kind)
        return queryset

    def get_serializer_class(self) -> type[Any]:
        return BonoIncidentCreateSerializer if self.action == "create" else BonoIncidentSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = BonoIncidentCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        incident = create_incident(
            operational_date=body.validated_data["operational_date"],
            kind=body.validated_data["kind"],
            quantity=body.validated_data["quantity"],
            reason=body.validated_data["reason"],
            bono_type=body.validated_data.get("bono_type"),
            product=body.validated_data.get("product"),
            responsible_employee=body.validated_data.get("responsible_employee"),
            notes=body.validated_data.get("notes", ""),
            actor=request.user,
        )
        return Response(BonoIncidentSerializer(incident).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Record a lost-Bono resolution outcome",
        request=BonoIncidentResolveSerializer,
        responses={200: BonoIncidentSerializer},
        tags=["bono"],
    )
    @action(detail=True, methods=["post"], url_path="resolve")
    def resolve(self, request: Request, pk: Any = None) -> Response:
        body = BonoIncidentResolveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        incident = resolve_incident(
            incident=self.get_object(),
            resolution_status=body.validated_data["resolution_status"],
            resolution_notes=body.validated_data.get("resolution_notes", ""),
            actor=request.user,
        )
        return Response(BonoIncidentSerializer(incident).data)

    @extend_schema(
        summary="Link an explicit payroll deduction to a lost Bono",
        request=BonoIncidentDeductionSerializer,
        responses={200: BonoIncidentSerializer},
        tags=["bono"],
    )
    @action(detail=True, methods=["post"], url_path="deduct")
    def deduct(self, request: Request, pk: Any = None) -> Response:
        body = BonoIncidentDeductionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        incident = self.get_object()
        record_incident_deduction(
            incident=incident,
            payroll_item=body.validated_data["payroll_item"],
            amount=body.validated_data["amount"],
            reason=body.validated_data["reason"],
            actor=request.user,
        )
        incident.refresh_from_db()
        return Response(BonoIncidentSerializer(incident).data)


class BonoReportViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Daily cashier report lifecycle with an immutable approved state."""

    queryset = BonoReport.objects.select_related(
        "submitted_by", "approved_by", "rejected_by", "corrects"
    ).prefetch_related("bono_lines", "product_lines")
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_serializer_class(self) -> type[Any]:
        if self.action in {"create"}:
            return BonoReportCreateSerializer
        if self.action in {"update", "partial_update"}:
            return BonoReportUpdateSerializer
        if self.action == "retrieve" or self.action in {
            "refresh",
            "submit",
            "approve",
            "reject",
            "correct",
        }:
            return BonoReportDetailSerializer
        return BonoReportSerializer

    def get_serializer_context(self) -> dict[str, Any]:
        context = dict(super().get_serializer_context())
        user = getattr(self.request, "user", None)
        context["include_money"] = bool(user and _can_see_money(user))
        return context

    def get_permissions(self) -> list[Any]:
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewBono()]
        if self.action in {"approve", "reject", "correct"}:
            return [IsAuthenticated(), CanApproveBonoReport()]
        return [IsAuthenticated(), CanSubmitBonoReport()]

    def get_queryset(self) -> Any:
        queryset = super().get_queryset().order_by("-operational_date", "-revision")
        operational_date = self.request.query_params.get("date")
        if operational_date:
            queryset = queryset.filter(operational_date=operational_date)
        report_status = self.request.query_params.get("status")
        if report_status:
            queryset = queryset.filter(status=report_status)
        return queryset

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        body = BonoReportCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        report = create_report(
            operational_date=body.validated_data["operational_date"],
            notes=body.validated_data.get("notes", ""),
            actor=request.user,
        )
        refreshed = self.get_queryset().get(pk=report.pk)
        return Response(
            BonoReportDetailSerializer(refreshed, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        report = self.get_object()
        body = BonoReportUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        updated = update_report(
            report=report,
            notes=body.validated_data.get("notes"),
            bono_lines=body.validated_data.get("bono_lines"),
            product_lines=body.validated_data.get("product_lines"),
            actor=request.user,
        )
        refreshed = self.get_queryset().get(pk=updated.pk)
        return Response(
            BonoReportDetailSerializer(refreshed, context=self.get_serializer_context()).data
        )

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.update(request, *args, **kwargs)

    def _detail_response(
        self, report: BonoReport, *, status_code: int = status.HTTP_200_OK
    ) -> Response:
        refreshed = self.get_queryset().get(pk=report.pk)
        return Response(
            BonoReportDetailSerializer(refreshed, context=self.get_serializer_context()).data,
            status=status_code,
        )

    @extend_schema(
        summary="Refresh draft activity from Bono and stock ledgers",
        request=None,
        responses={200: BonoReportDetailSerializer},
        tags=["bono"],
    )
    @action(detail=True, methods=["post"], url_path="refresh")
    def refresh(self, request: Request, pk: Any = None) -> Response:
        report = refresh_report(
            report=self.get_object(),
            actor=request.user,
        )
        return self._detail_response(report)

    @extend_schema(
        summary="Submit a daily Bono report for Owner review",
        request=None,
        responses={200: BonoReportDetailSerializer},
        tags=["bono"],
    )
    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request: Request, pk: Any = None) -> Response:
        report = submit_report(
            report=self.get_object(),
            actor=request.user,
        )
        return self._detail_response(report)

    @extend_schema(
        summary="Approve a submitted Bono report",
        request=None,
        responses={200: BonoReportDetailSerializer},
        tags=["bono"],
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request: Request, pk: Any = None) -> Response:
        report = approve_report(
            report=self.get_object(),
            actor=request.user,
        )
        return self._detail_response(report)

    @extend_schema(
        summary="Reject a submitted Bono report and reopen the day",
        request=BonoReportRejectSerializer,
        responses={200: BonoReportDetailSerializer},
        tags=["bono"],
    )
    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request: Request, pk: Any = None) -> Response:
        body = BonoReportRejectSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        report = reject_report(
            report=self.get_object(),
            reason=body.validated_data["reason"],
            actor=request.user,
        )
        return self._detail_response(report)

    @extend_schema(
        summary="Open an auditable correction revision for an approved report",
        request=BonoReportCorrectionSerializer,
        responses={201: BonoReportDetailSerializer},
        tags=["bono"],
    )
    @action(detail=True, methods=["post"], url_path="correct")
    def correct(self, request: Request, pk: Any = None) -> Response:
        body = BonoReportCorrectionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        correction = create_correction(
            report=self.get_object(),
            reason=body.validated_data["reason"],
            actor=request.user,
        )
        return self._detail_response(correction, status_code=status.HTTP_201_CREATED)


class BonoDaySummaryView(APIView):
    """Operational hand-over view shared by Managers, Cashiers and Barmen."""

    permission_classes = [IsAuthenticated, CanViewBono]

    @extend_schema(
        summary="Read Bono custody and day status for one operational date",
        responses=BonoDaySummarySerializer,
        tags=["bono"],
    )
    def get(self, request: Request) -> Response:
        raw = request.query_params.get("date")
        if raw:
            try:
                selected = date.fromisoformat(raw)
            except ValueError as exc:
                from rest_framework.exceptions import ValidationError

                raise ValidationError({"date": ["Enter a date as YYYY-MM-DD."]}) from exc
        else:
            selected = today_business_date()
        return Response(BonoDaySummarySerializer(day_summary(selected)).data)


__all__ = [
    "BonoDaySummaryView",
    "BonoIncidentViewSet",
    "BonoIssueViewSet",
    "BonoPairingViewSet",
    "BonoReportViewSet",
    "BonoTransferViewSet",
    "BonoTypeViewSet",
]
