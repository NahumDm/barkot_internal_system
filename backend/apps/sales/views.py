"""Sales API views (spec §13.1).

Endpoints:

- ``/api/v1/sales/`` - list and create sales
- ``/api/v1/sales/{id}/`` - retrieve a sale
- ``/api/v1/sales/{id}/void/`` - void a sale

Permissions are enforced through the role matrix (:mod:`apps.accounts.permissions`):
- ``CanViewSales`` for list/retrieve (all staff roles)
- ``CanCreateSale`` for create (Cashier, Manager, Owner)
- ``CanVoidSale`` for void (Manager, Owner)

All list endpoints use :class:`apps.core.pagination.BarkotPagination` and return
the standard envelope: ``{count, page_size, page, pages, results}``.
"""

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import CanCreateSale, CanViewSales, CanVoidSale
from apps.core.pagination import BarkotPagination
from apps.sales.models import Sale
from apps.sales.serializers import (
    SaleCreateSerializer,
    SaleListSerializer,
    SaleSerializer,
    VoidSaleSerializer,
)
from apps.sales.services import void_sale as svc_void_sale


@extend_schema_view(
    list=extend_schema(
        summary="List sales",
        description=(
            "Paginated list of sales. Supports filtering by ``?status=`` (completed/voided), "
            "``?payment_status=``, date range ``?sold_after=``/``?sold_before=``, "
            "and search via ``?search=`` (matches reference). "
            "Requires ``sales.view_sales`` (all staff roles)."
        ),
        tags=["sales"],
    ),
    retrieve=extend_schema(
        summary="Get a sale",
        description="Single sale with all items and payments. Requires ``sales.view_sales``.",
        tags=["sales"],
    ),
    create=extend_schema(
        summary="Record a sale",
        description=(
            "Create a completed sale with lines and payments, drawing down stock. "
            "Requires ``sales.create_sale`` (Cashier, Manager, Owner). "
            "Supply an ``idempotency_key`` to make the call safe to retry (spec §10.2)."
        ),
        tags=["sales"],
    ),
)
class SaleViewSet(viewsets.ModelViewSet):
    """CRUD for sales (list, retrieve, create, void)."""

    queryset = (
        Sale.objects.prefetch_related("items__product", "payments")
        .order_by("-sold_at", "-id")
    )
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_serializer_class(self):
        if self.action == "create":
            return SaleCreateSerializer
        if self.action == "list":
            return SaleListSerializer
        return SaleSerializer

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [IsAuthenticated(), CanViewSales()]
        if self.action == "void_sale":
            return [IsAuthenticated(), CanVoidSale()]
        return [IsAuthenticated(), CanCreateSale()]

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        payment_status = self.request.query_params.get("payment_status")
        if payment_status:
            qs = qs.filter(payment_status=payment_status)
        sold_after = self.request.query_params.get("sold_after")
        if sold_after:
            qs = qs.filter(sold_at__gte=sold_after)
        sold_before = self.request.query_params.get("sold_before")
        if sold_before:
            qs = qs.filter(sold_at__lt=sold_before)
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(reference__icontains=search)
        return qs

    def perform_create(self, serializer):
        from apps.core.enums import PaymentMethod
        from apps.products.models import Product
        from apps.sales.services import SaleLineInput, complete_sale

        lines_data = serializer.validated_data["lines"]

        lines = [
            SaleLineInput(
                product=Product.objects.get(pk=line["product"].pk),
                quantity=line["quantity"],
                unit_price=line.get("unit_price"),
            )
            for line in lines_data
        ]

        payments = [
            (PaymentMethod(payment["method"]), payment["amount"])
            for payment in serializer.validated_data["payments"]
        ]

        sale = complete_sale(
            lines=lines,
            payments=payments,
            actor=self.request.user,  # type: ignore[arg-type]
            sold_at=serializer.validated_data.get("sold_at"),
            note=serializer.validated_data.get("note", ""),
            idempotency_key=serializer.validated_data.get("idempotency_key"),
        )
        # Store the created sale on the serializer for the response
        self._created_sale = sale

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # Return the full sale representation
        sale = getattr(self, "_created_sale", None)
        if sale is None:
            # serializer.instance is guaranteed to exist after perform_create
            instance = serializer.instance
            assert instance is not None
            sale = (
                Sale.objects.prefetch_related("items__product", "payments")
                .get(pk=instance.pk)
            )
        return Response(SaleSerializer(sale).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Void a sale",
        description=(
            "Void a completed sale, reverse its payments, and return stock to the ledger. "
            "Requires ``sales.void_sale`` (Manager, Owner)."
        ),
        request=VoidSaleSerializer,
        responses={200: None},
        tags=["sales"],
    )
    @action(detail=True, methods=["post"], url_path="void")
    def void_sale(self, request: Request, pk: int | None = None) -> Response:
        """Void a sale and reverse its stock movements."""
        serializer = VoidSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        sale = self.get_object()
        svc_void_sale(sale=sale, reason=serializer.validated_data["reason"], actor=request.user)  # type: ignore[arg-type]

        return Response(status=status.HTTP_204_NO_CONTENT)


__all__ = ["SaleViewSet"]
