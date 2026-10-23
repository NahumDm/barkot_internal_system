"""Serializers for the inventory API."""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.inventory.models import (
    BreakageRecord,
    StockCount,
    StockMovement,
    StockReceipt,
)
from apps.products.models import Product


class ReceiptLineInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=2)
    currency = serializers.CharField(max_length=3, default="ETB")
    lot_reference = serializers.CharField(max_length=64, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_quantity(self, value: Decimal) -> Decimal:
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than zero.")
        return value

    def validate_unit_cost(self, value: Decimal) -> Decimal:
        if value < 0:
            raise serializers.ValidationError("Unit cost cannot be negative.")
        return value

    def validate_currency(self, value: str) -> str:
        value = value.strip().upper()
        if value != "ETB":
            raise serializers.ValidationError("Only ETB stock costs are supported.")
        return value


class ReceiptCreateSerializer(serializers.Serializer):
    supplier_name = serializers.CharField(max_length=150, trim_whitespace=True)
    reference = serializers.CharField(max_length=64, required=False, allow_blank=True)
    received_at = serializers.DateTimeField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=64, required=False, allow_blank=True)
    lines = ReceiptLineInputSerializer(many=True)

    def validate(self, attrs: dict) -> dict:
        if not attrs["lines"]:
            raise serializers.ValidationError({"lines": ["A receipt must have at least one line."]})
        product_ids = [line["product"].pk for line in attrs["lines"]]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError({"lines": ["A product may appear only once."]})
        return attrs


class GroupedReceiptLineSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    crates = serializers.DecimalField(max_digits=12, decimal_places=3)
    crate_cost = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True
    )
    unit_cost = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, allow_null=True
    )
    lot_reference = serializers.CharField(max_length=64, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_crates(self, value: Decimal) -> Decimal:
        if value <= 0:
            raise serializers.ValidationError("Crate quantity must be greater than zero.")
        return value


class GroupedReceiptCreateSerializer(serializers.Serializer):
    supplier_name = serializers.CharField(max_length=150, trim_whitespace=True)
    selling_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    reference = serializers.CharField(max_length=64, required=False, allow_blank=True)
    received_at = serializers.DateTimeField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=64, required=False, allow_blank=True)
    lines = GroupedReceiptLineSerializer(many=True)

    def validate_selling_price(self, value: Decimal) -> Decimal:
        if value < 0:
            raise serializers.ValidationError("Selling price cannot be negative.")
        return value

    def validate(self, attrs: dict) -> dict:
        lines = attrs.get("lines", [])
        if not lines:
            raise serializers.ValidationError({"lines": ["A receipt must have at least one line."]})

        selling_price = attrs["selling_price"]
        product_ids = [line["product"].pk for line in lines]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError({
                "lines": ["A product may appear only once on a receipt."]
            })

        for line in lines:
            prod = line["product"]
            if not prod.is_stock_tracked:
                raise serializers.ValidationError({
                    "lines": [f"Product '{prod.name}' is not stock tracked and cannot be received."]
                })
            if not prod.is_active:
                raise serializers.ValidationError({
                    "lines": [f"Product '{prod.name}' is inactive and cannot be received."]
                })
            if not prod.is_crated:
                raise serializers.ValidationError({
                    "lines": [
                        f"Product '{prod.name}' has no bottles-per-crate conversion "
                        "configured and cannot be received in a grouped receipt."
                    ]
                })

            current_price = prod.current_price()
            if current_price is None:
                raise serializers.ValidationError({
                    "lines": [f"Product '{prod.name}' has no active selling price configured."]
                })

            if current_price.unit_price != selling_price:
                raise serializers.ValidationError({
                    "lines": [
                        f"Product '{prod.name}' selling price ({current_price.unit_price} ETB) "
                        f"does not match the selected price group ({selling_price} ETB)."
                    ]
                })

            crate_cost = line.get("crate_cost")
            unit_cost = line.get("unit_cost")
            if crate_cost is None and unit_cost is None:
                raise serializers.ValidationError({
                    "lines": [f"Product '{prod.name}' requires either a crate cost or a unit cost."]
                })
            if crate_cost is not None and crate_cost < 0:
                raise serializers.ValidationError({
                    "lines": [f"Crate cost for '{prod.name}' cannot be negative."]
                })
            if unit_cost is not None and unit_cost < 0:
                raise serializers.ValidationError({
                    "lines": [f"Unit cost for '{prod.name}' cannot be negative."]
                })

        return attrs


class ReceiptItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    product = serializers.IntegerField(source="product_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    currency = serializers.CharField(read_only=True)
    line_cost = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)


class ReceiptSerializer(serializers.ModelSerializer):
    items = ReceiptItemSerializer(many=True, read_only=True)

    class Meta:
        model = StockReceipt
        fields = [
            "id",
            "reference",
            "supplier_name",
            "status",
            "received_at",
            "completed_at",
            "notes",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class BreakageLineInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3)

    def validate_quantity(self, value: Decimal) -> Decimal:
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than zero.")
        return value


class BreakageCreateSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=150, trim_whitespace=True)
    reference = serializers.CharField(max_length=64, required=False, allow_blank=True)
    occurred_at = serializers.DateTimeField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    lines = BreakageLineInputSerializer(many=True)

    def validate(self, attrs: dict) -> dict:
        if not attrs["lines"]:
            raise serializers.ValidationError({
                "lines": ["A breakage must have at least one line."]
            })
        product_ids = [line["product"].pk for line in attrs["lines"]]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError({"lines": ["A product may appear only once."]})
        return attrs


class BreakageItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    product = serializers.IntegerField(source="product_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)


class BreakageSerializer(serializers.ModelSerializer):
    items = BreakageItemSerializer(many=True, read_only=True)

    class Meta:
        model = BreakageRecord
        fields = [
            "id",
            "reference",
            "reason",
            "occurred_at",
            "notes",
            "items",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class StockCountCreateSerializer(serializers.Serializer):
    products = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), many=True)
    counted_at = serializers.DateTimeField(required=False)
    reference = serializers.CharField(max_length=64, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_products(self, value: list[Product]) -> list[Product]:
        if not value:
            raise serializers.ValidationError("A stock count must cover at least one product.")
        if len(value) != len({product.pk for product in value}):
            raise serializers.ValidationError("A product may appear only once on a count.")
        return value


class StockCountItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    product = serializers.IntegerField(source="product_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    expected_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    counted_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    variance = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    note = serializers.CharField(read_only=True)


class StockCountSerializer(serializers.ModelSerializer):
    items = StockCountItemSerializer(many=True, read_only=True)
    total_expected = serializers.SerializerMethodField()
    total_counted = serializers.SerializerMethodField()
    total_variance = serializers.SerializerMethodField()

    class Meta:
        model = StockCount
        fields = [
            "id",
            "reference",
            "status",
            "counted_at",
            "completed_at",
            "approved_at",
            "notes",
            "items",
            "total_expected",
            "total_counted",
            "total_variance",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_total_expected(self, obj: StockCount) -> str:
        return str(
            sum((item.expected_quantity for item in obj.items.all()), Decimal("0.000")).quantize(
                Decimal("0.001")
            )
        )

    def get_total_counted(self, obj: StockCount) -> str:
        return str(
            sum((item.counted_quantity for item in obj.items.all()), Decimal("0.000")).quantize(
                Decimal("0.001")
            )
        )

    def get_total_variance(self, obj: StockCount) -> str:
        return str(
            sum((item.variance for item in obj.items.all()), Decimal("0.000")).quantize(
                Decimal("0.001")
            )
        )


class StockCountCompleteSerializer(serializers.Serializer):
    items = serializers.ListField(child=serializers.DictField())

    def validate_items(self, value: list[dict]) -> list[dict]:
        if not value:
            raise serializers.ValidationError("Counted items are required.")
        normalized = []
        for item in value:
            if "item" not in item or "counted_quantity" not in item:
                raise serializers.ValidationError(
                    "Each counted item requires item and counted_quantity."
                )
            try:
                item_id = int(item["item"])
                quantity = Decimal(str(item["counted_quantity"]))
            except (TypeError, ValueError, ArithmeticError) as exc:
                raise serializers.ValidationError("Counted quantities must be numeric.") from exc
            if quantity < 0:
                raise serializers.ValidationError("Counted quantity cannot be negative.")
            normalized.append({"item": item_id, "counted_quantity": quantity})
        return normalized


class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "kind",
            "direction",
            "quantity",
            "source",
            "occurred_at",
            "unit_cost",
            "currency",
            "reason",
            "recorded_by",
        ]
        read_only_fields = fields
