"""Inventory API views."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import (
    CanApproveAdjustment,
    CanCompleteStockCount,
    CanReceiveStock,
    CanRecordBreakage,
    CanViewInventory,
)
from apps.core.pagination import BarkotPagination
from apps.inventory.models import BreakageRecord, StockCount, StockMovement, StockReceipt
from apps.inventory.serializers import (
    BreakageCreateSerializer,
    BreakageSerializer,
    GroupedReceiptCreateSerializer,
    ReceiptCreateSerializer,
    ReceiptSerializer,
    StockCountCompleteSerializer,
    StockCountCreateSerializer,
    StockCountSerializer,
    StockMovementSerializer,
)
from apps.inventory.services import (
    GroupedReceiptLineInput,
    ReceiptLineInput,
    approve_stock_count,
    complete_stock_count,
    open_stock_count,
    receive_grouped_stock,
    receive_stock,
    record_breakage,
)
from apps.products.models import Product


@extend_schema_view(
    list=extend_schema(summary="List stock receipts", tags=["inventory"]),
    retrieve=extend_schema(summary="Get a stock receipt", tags=["inventory"]),
    create=extend_schema(summary="Receive stock", tags=["inventory"]),
)
class StockReceiptViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    pagination_class = BarkotPagination
    paginator = BarkotPagination()
    queryset = StockReceipt.objects.prefetch_related("items__product").order_by(
        "-received_at", "-id"
    )
    serializer_class = ReceiptSerializer

    def get_permissions(self):
        if self.action in {"list", "retrieve", "price_groups"}:
            return [IsAuthenticated(), CanViewInventory()]
        return [IsAuthenticated(), CanReceiveStock()]

    def get_serializer_class(self):
        return ReceiptCreateSerializer if self.action == "create" else ReceiptSerializer

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        receipt = receive_stock(
            supplier_name=data["supplier_name"],
            reference=data.get("reference", ""),
            received_at=data.get("received_at"),
            notes=data.get("notes", ""),
            idempotency_key=data.get("idempotency_key"),
            actor=request.user,  # type: ignore[arg-type]
            lines=[
                ReceiptLineInput(
                    product=line["product"],
                    quantity=line["quantity"],
                    unit_cost=line["unit_cost"],
                    lot_reference=line.get("lot_reference", ""),
                    notes=line.get("notes", ""),
                )
                for line in data["lines"]
            ],
        )
        return Response(ReceiptSerializer(receipt).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Receive grouped stock",
        request=GroupedReceiptCreateSerializer,
        responses={201: ReceiptSerializer},
        tags=["inventory"],
    )
    @action(detail=False, methods=["post"], url_path="grouped")
    def receive_grouped(self, request: Request) -> Response:
        serializer = GroupedReceiptCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            receipt = receive_grouped_stock(
                supplier_name=data["supplier_name"],
                selling_price=data["selling_price"],
                reference=data.get("reference", ""),
                received_at=data.get("received_at"),
                notes=data.get("notes", ""),
                idempotency_key=data.get("idempotency_key"),
                actor=request.user,  # type: ignore[arg-type]
                lines=[
                    GroupedReceiptLineInput(
                        product=line["product"],
                        crates=line["crates"],
                        crate_cost=line.get("crate_cost"),
                        unit_cost=line.get("unit_cost"),
                        lot_reference=line.get("lot_reference", ""),
                        notes=line.get("notes", ""),
                    )
                    for line in data["lines"]
                ],
            )
        except ValueError as exc:
            # The service re-validates at save time. A ValueError here means a
            # rule changed between serializer validation and the write (for
            # example a price edit); return a useful 400 instead of a 500.
            raise ValidationError(str(exc)) from exc
        return Response(ReceiptSerializer(receipt).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="List product price groups", tags=["inventory"])
    @action(detail=False, methods=["get"], url_path="price-groups")
    def price_groups(self, request: Request) -> Response:
        products = Product.objects.filter(is_active=True, is_stock_tracked=True).prefetch_related(
            "price_history"
        )
        groups: dict = {}
        for p in products:
            curr = p.current_price()
            if curr is None:
                continue
            groups.setdefault(curr.unit_price, []).append({
                "id": p.id,
                "name": p.name,
                "sku": p.sku,
                "bottles_per_crate": p.bottles_per_crate,
                "is_crated": p.is_crated,
                "unit": p.unit,
                "selling_price": str(curr.unit_price),
                "currency": curr.currency,
            })

        result = [
            {
                "selling_price": str(price),
                "currency": prods[0]["currency"],
                "product_count": len(prods),
                "products": prods,
            }
            for price, prods in sorted(groups.items(), key=lambda x: x[0])
        ]
        return Response(result)


@extend_schema_view(
    list=extend_schema(summary="List breakage records", tags=["inventory"]),
    retrieve=extend_schema(summary="Get a breakage record", tags=["inventory"]),
    create=extend_schema(summary="Record breakage or waste", tags=["inventory"]),
)
class BreakageViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    pagination_class = BarkotPagination
    paginator = BarkotPagination()
    queryset = BreakageRecord.objects.prefetch_related("items__product").order_by(
        "-occurred_at", "-id"
    )
    serializer_class = BreakageSerializer

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewInventory()]
        return [IsAuthenticated(), CanRecordBreakage()]

    def get_serializer_class(self):
        return BreakageCreateSerializer if self.action == "create" else BreakageSerializer

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        record = record_breakage(
            reason=data["reason"],
            reference=data.get("reference", ""),
            occurred_at=data.get("occurred_at"),
            notes=data.get("notes", ""),
            actor=request.user,  # type: ignore[arg-type]
            lines=[(line["product"], line["quantity"]) for line in data["lines"]],
        )
        return Response(BreakageSerializer(record).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    list=extend_schema(summary="List stock counts", tags=["inventory"]),
    retrieve=extend_schema(summary="Get a stock count", tags=["inventory"]),
    create=extend_schema(summary="Open a stock count", tags=["inventory"]),
)
class StockCountViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    pagination_class = BarkotPagination
    paginator = BarkotPagination()
    queryset = StockCount.objects.prefetch_related("items__product").order_by("-counted_at", "-id")
    serializer_class = StockCountSerializer

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewInventory()]
        if self.action == "approve":
            return [IsAuthenticated(), CanApproveAdjustment()]
        return [IsAuthenticated(), CanCompleteStockCount()]

    def get_serializer_class(self):
        if self.action == "create":
            return StockCountCreateSerializer
        if self.action == "complete":
            return StockCountCompleteSerializer
        return StockCountSerializer

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        count = open_stock_count(
            lines=data["products"],
            counted_at=data.get("counted_at"),
            reference=data.get("reference", ""),
            notes=data.get("notes", ""),
            actor=request.user,  # type: ignore[arg-type]
        )
        return Response(StockCountSerializer(count).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Complete a stock count", responses=StockCountSerializer, tags=["inventory"]
    )
    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request: Request, pk: int | None = None) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = complete_stock_count(
            stock_count=self.get_object(),
            counted_quantities={
                item["item"]: item["counted_quantity"]
                for item in serializer.validated_data["items"]
            },
            actor=request.user,  # type: ignore[arg-type]
        )
        return Response(StockCountSerializer(count).data)

    @extend_schema(
        summary="Approve stock count variance", responses=StockCountSerializer, tags=["inventory"]
    )
    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request: Request, pk: int | None = None) -> Response:
        count = approve_stock_count(
            stock_count=self.get_object(),
            actor=request.user,  # type: ignore[arg-type]
        )
        return Response(StockCountSerializer(count).data)


@extend_schema_view(
    list=extend_schema(summary="List stock movements", tags=["inventory"]),
    retrieve=extend_schema(summary="Get a stock movement", tags=["inventory"]),
)
class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    pagination_class = BarkotPagination
    paginator = BarkotPagination()
    queryset = StockMovement.objects.select_related("product").order_by("-occurred_at", "-id")
    serializer_class = StockMovementSerializer

    def get_permissions(self):
        return [IsAuthenticated(), CanViewInventory()]

    def get_queryset(self):
        queryset = super().get_queryset()
        product = self.request.query_params.get("product")
        if product:
            queryset = queryset.filter(product_id=product)
        kind = self.request.query_params.get("kind")
        if kind:
            queryset = queryset.filter(kind=kind)
        return queryset
