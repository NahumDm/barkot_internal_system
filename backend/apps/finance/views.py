"""Finance API views."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import (
    CanApproveExpense,
    CanCreateExpense,
    CanManageExpenseCategories,
    CanViewReports,
)
from apps.core.pagination import BarkotPagination
from apps.finance.models import Expense, ExpenseCategory
from apps.finance.serializers import (
    BalanceQuerySerializer,
    BalanceSerializer,
    ExpenseCategoryCreateSerializer,
    ExpenseCategorySerializer,
    ExpenseCategoryUpdateSerializer,
    ExpenseCreateSerializer,
    ExpenseSerializer,
)
from apps.finance.services import (
    approve_expense,
    archive_expense_category,
    create_expense,
    create_expense_category,
    finance_balance,
    update_expense_category,
)


class FinanceBalanceView(APIView):
    """Read the business balance for an explicit local-date period."""

    permission_classes = [IsAuthenticated, CanViewReports]

    @extend_schema(
        summary="Get business balance",
        parameters=[BalanceQuerySerializer],
        responses=BalanceSerializer,
        tags=["finance"],
    )
    def get(self, request: Request) -> Response:
        query = BalanceQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        balance = finance_balance(**query.validated_data)
        return Response(BalanceSerializer(balance.as_dict()).data)


@extend_schema_view(
    list=extend_schema(summary="List expense categories", tags=["finance"]),
    retrieve=extend_schema(summary="Get an expense category", tags=["finance"]),
    create=extend_schema(summary="Create an expense category", tags=["finance"]),
    update=extend_schema(summary="Edit an expense category", tags=["finance"]),
    archive=extend_schema(
        summary="Archive an expense category",
        request=None,
        responses=ExpenseCategorySerializer,
        tags=["finance"],
    ),
)
class ExpenseCategoryViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = ExpenseCategory.objects.all().order_by("name")
    serializer_class = ExpenseCategorySerializer
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewReports()]
        return [IsAuthenticated(), CanManageExpenseCategories()]

    def get_serializer_class(self):
        if self.action == "create":
            return ExpenseCategoryCreateSerializer
        if self.action in {"update", "partial_update"}:
            return ExpenseCategoryUpdateSerializer
        return ExpenseCategorySerializer

    def perform_create(self, serializer):
        self._created_category = create_expense_category(
            name=serializer.validated_data["name"],
            description=serializer.validated_data.get("description", ""),
            actor=self.request.user,  # type: ignore[arg-type]
        )

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            ExpenseCategorySerializer(self._created_category).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request: Request, *args, **kwargs) -> Response:
        category = self.get_object()
        serializer = ExpenseCategoryUpdateSerializer(
            instance=category,
            data=request.data,
            partial=kwargs.pop("partial", False),
        )
        serializer.is_valid(raise_exception=True)
        updated = update_expense_category(
            category=category,
            name=serializer.validated_data.get("name"),
            description=serializer.validated_data.get("description"),
            is_active=serializer.validated_data.get("is_active"),
            actor=request.user,  # type: ignore[arg-type]
        )
        return Response(ExpenseCategorySerializer(updated).data)

    @action(detail=True, methods=["post"], url_path="archive")
    def archive(self, request: Request, pk: int | None = None) -> Response:
        category = self.get_object()
        archived = archive_expense_category(
            category=category,
            actor=request.user,  # type: ignore[arg-type]
        )
        return Response(ExpenseCategorySerializer(archived).data)


@extend_schema_view(
    list=extend_schema(summary="List expenses", tags=["finance"]),
    retrieve=extend_schema(summary="Get an expense", tags=["finance"]),
    create=extend_schema(summary="Record an expense", tags=["finance"]),
)
class ExpenseViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Expense.objects.select_related("category").order_by("-incurred_on", "-id")
    serializer_class = ExpenseSerializer
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewReports()]
        if self.action == "approve":
            return [IsAuthenticated(), CanApproveExpense()]
        return [IsAuthenticated(), CanCreateExpense()]

    def get_serializer_class(self):
        if self.action == "create":
            return ExpenseCreateSerializer
        return ExpenseSerializer

    def perform_create(self, serializer):
        self._created_expense = create_expense(
            category=serializer.validated_data["category"],
            description=serializer.validated_data["description"],
            amount=serializer.validated_data["amount"],
            currency=serializer.validated_data["currency"],
            incurred_on=serializer.validated_data["incurred_on"],
            actor=self.request.user,  # type: ignore[arg-type]
        )

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            ExpenseSerializer(self._created_expense).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Approve an expense",
        responses=ExpenseSerializer,
        tags=["finance"],
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request: Request, pk: int | None = None) -> Response:
        expense = self.get_object()
        approved = approve_expense(expense=expense, actor=request.user)  # type: ignore[arg-type]
        return Response(ExpenseSerializer(approved).data)
