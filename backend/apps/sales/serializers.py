"""Serializers for sales (spec §13.1).

These describe the request and response bodies for the sales endpoints.
The error envelope is defined in :mod:`apps.core.schemas` and is applied
automatically by the exception handler; these serializers only declare
success shapes.
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.products.models import Product
from apps.sales.models import Payment, Sale, SaleItem


class SaleItemSerializer(serializers.ModelSerializer):
    """One product line on a sale, with its price frozen at sale time."""

    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    line_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    currency = serializers.CharField(max_length=3, read_only=True)

    class Meta:
        model = SaleItem
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "quantity",
            "unit_price",
            "line_total",
            "currency",
            "price_source",
        ]
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    """One tender against a sale."""

    method_display = serializers.CharField(source="get_method_display", read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    currency = serializers.CharField(max_length=3, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "method",
            "method_display",
            "amount",
            "currency",
            "status",
            "status_display",
            "received_at",
            "reference",
            "voided_at",
            "void_reason",
        ]
        read_only_fields = fields


class SaleSerializer(serializers.ModelSerializer):
    """One individual customer sale with all lines and payments."""

    items = SaleItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    payment_status_display = serializers.CharField(
        source="get_payment_status_display", read_only=True
    )
    subtotal = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    amount_paid = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    currency = serializers.CharField(max_length=3, read_only=True)
    balance_due = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Sale
        fields = [
            "id",
            "reference",
            "status",
            "status_display",
            "sold_at",
            "subtotal",
            "total",
            "amount_paid",
            "currency",
            "payment_status",
            "payment_status_display",
            "balance_due",
            "note",
            "items",
            "payments",
            "voided_at",
            "void_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class SaleItemInputSerializer(serializers.Serializer):
    """One product line input for creating a sale."""

    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)

    def validate_quantity(self, value: Decimal) -> Decimal:
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than zero.")
        return value

    def validate_unit_price(self, value: Decimal) -> Decimal:
        if value is not None and value < 0:
            raise serializers.ValidationError("Unit price cannot be negative.")
        return value


class PaymentInputSerializer(serializers.Serializer):
    """One payment input for creating a sale."""

    method = serializers.ChoiceField(
        choices=[
            ("CASH", "Cash"),
            ("MOBILE_BANKING", "Mobile Banking"),
        ]
    )
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)

    def validate_amount(self, value: Decimal) -> Decimal:
        if value <= 0:
            raise serializers.ValidationError("Payment amount must be greater than zero.")
        return value


class SaleCreateSerializer(serializers.Serializer):
    """Body for ``POST /api/v1/sales/``."""

    lines = SaleItemInputSerializer(many=True)
    payments = PaymentInputSerializer(many=True)
    note = serializers.CharField(required=False, allow_blank=True)
    sold_at = serializers.DateTimeField(required=False)
    idempotency_key = serializers.CharField(max_length=64, required=False)

    def validate(self, attrs: dict) -> dict:
        lines = attrs.get("lines", [])
        payments = attrs.get("payments", [])

        if not lines:
            raise serializers.ValidationError({"lines": ["A sale must have at least one line."]})
        if not payments:
            raise serializers.ValidationError({
                "payments": ["A sale must have at least one payment."]
            })

        # Check for duplicate products in lines
        seen = set()
        for line in lines:
            product = line["product"]
            if product.pk in seen:
                raise serializers.ValidationError({
                    "lines": [f"Product {product.sku!r} appears twice. Combine the lines instead."]
                })
            seen.add(product.pk)

        return attrs


class SaleListSerializer(serializers.ModelSerializer):
    """Lightweight sale representation for list views."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    payment_status_display = serializers.CharField(
        source="get_payment_status_display", read_only=True
    )
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    currency = serializers.CharField(max_length=3, read_only=True)
    item_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Sale
        fields = [
            "id",
            "reference",
            "status",
            "status_display",
            "sold_at",
            "total",
            "currency",
            "payment_status",
            "item_count",
            "created_at",
        ]
        read_only_fields = fields


class VoidSaleSerializer(serializers.Serializer):
    """Body for ``POST /api/v1/sales/{id}/void/``."""

    reason = serializers.CharField(trim_whitespace=True)

    def validate_reason(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("A void reason is required.")
        return value.strip()


__all__ = [
    "PaymentInputSerializer",
    "PaymentSerializer",
    "SaleCreateSerializer",
    "SaleItemInputSerializer",
    "SaleItemSerializer",
    "SaleListSerializer",
    "SaleSerializer",
    "VoidSaleSerializer",
]
