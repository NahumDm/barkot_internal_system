"""Serializers for the product catalogue (spec §11.1).

These describe the request and response bodies for the product endpoints.
The error envelope is defined in :mod:`apps.core.schemas` and is applied
automatically by the exception handler; these serializers only declare
success shapes.
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.products.models import Category, Product, ProductPrice


class CategorySerializer(serializers.ModelSerializer):
    """A product grouping such as "Beer" or "Spirits"."""

    product_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "description",
            "is_active",
            "display_order",
            "product_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "product_count"]


class CategoryCreateSerializer(serializers.ModelSerializer):
    """Body for ``POST /api/v1/products/categories/``."""

    class Meta:
        model = Category
        fields = ["name", "description", "display_order", "is_active"]

    def validate_name(self, value: str) -> str:
        """Case-insensitive uniqueness."""
        if Category.objects.filter(name__iexact=value.strip()).exists():
            raise serializers.ValidationError("A category with this name already exists.")
        return value.strip()


class ProductPriceSerializer(serializers.ModelSerializer):
    """One price of a product, effective from a point in time."""

    unit_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    currency = serializers.CharField(max_length=3, read_only=True)

    class Meta:
        model = ProductPrice
        fields = [
            "id",
            "unit_price",
            "currency",
            "effective_from",
            "is_active",
            "created_at",
        ]
        read_only_fields = fields


class ProductPriceCreateSerializer(serializers.Serializer):
    """Body for ``POST /api/v1/products/{id}/prices/``."""

    unit_price = serializers.DecimalField(
        max_digits=14, decimal_places=2, help_text="Price per unit (>= 0)."
    )
    currency = serializers.CharField(max_length=3, help_text="3-letter ISO currency code.")
    effective_from = serializers.DateTimeField(
        required=False,
        help_text="When this price takes effect (UTC). Defaults to now.",
    )

    def validate_currency(self, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 3:
            raise serializers.ValidationError("Currency must be a 3-letter ISO code.")
        return value

    def validate_unit_price(self, value: Decimal) -> Decimal:
        if value < 0:
            raise serializers.ValidationError("Price cannot be negative.")
        return value


class ProductSerializer(serializers.ModelSerializer):
    """A sellable item with its current price."""

    category = CategorySerializer(read_only=True)
    current_price = serializers.SerializerMethodField()
    current_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "category",
            "name",
            "sku",
            "unit",
            "is_stock_tracked",
            "is_active",
            "description",
            "current_price",
            "current_stock",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "current_price", "current_stock"]

    def get_current_price(self, obj: Product) -> dict | None:
        """Return the current price if one exists."""
        price = obj.current_price()
        if price is None:
            return None
        return ProductPriceSerializer(price).data

    def get_current_stock(self, obj: Product) -> str | None:
        """Return the current stock level for tracked products."""
        if not obj.is_stock_tracked:
            return None
        # Import here to avoid circular import
        from apps.inventory.services import current_stock

        return str(current_stock(obj))


class ProductListSerializer(serializers.ModelSerializer):
    """Lightweight product representation for list views."""

    category_name = serializers.CharField(source="category.name", read_only=True)
    current_price = serializers.SerializerMethodField()
    current_stock = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "category",
            "category_name",
            "name",
            "sku",
            "unit",
            "is_stock_tracked",
            "is_active",
            "current_price",
            "current_stock",
        ]

    def get_current_price(self, obj: Product) -> dict | None:
        price = obj.current_price()
        if price is None:
            return None
        return ProductPriceSerializer(price).data

    def get_current_stock(self, obj: Product) -> str | None:
        if not obj.is_stock_tracked:
            return None
        from apps.inventory.services import current_stock

        return str(current_stock(obj))


class ProductCreateSerializer(serializers.Serializer):
    """Body for ``POST /api/v1/products/``."""

    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all())
    name = serializers.CharField(max_length=150, trim_whitespace=True)
    sku = serializers.CharField(max_length=64, trim_whitespace=True)
    unit = serializers.CharField(max_length=32, default="bottle", trim_whitespace=True)
    is_stock_tracked = serializers.BooleanField(default=True)
    description = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)

    def validate_sku(self, value: str) -> str:
        """Case-insensitive uniqueness, normalized to uppercase."""
        value = value.strip().upper()
        if Product.objects.filter(sku__iexact=value).exists():
            raise serializers.ValidationError("A product with this SKU already exists.")
        return value

    def validate_name(self, value: str) -> str:
        """Uniqueness within category (checked after category is known)."""
        return value.strip()

    def validate(self, attrs: dict) -> dict:
        """Cross-field validation: name unique within category."""
        category = attrs.get("category")
        name = attrs.get("name")
        if (
            category
            and name
            and Product.objects.filter(category=category, name__iexact=name.strip()).exists()
        ):
            raise serializers.ValidationError({
                "name": f"A product named {name!r} already exists in category {category.name!r}."
            })
        return attrs


class ProductUpdateSerializer(serializers.Serializer):
    """Body for ``PATCH /api/v1/products/{id}/``."""

    name = serializers.CharField(max_length=150, required=False, trim_whitespace=True)
    unit = serializers.CharField(max_length=32, required=False, trim_whitespace=True)
    is_stock_tracked = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)
    description = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if (
            self.instance
            and Product.objects.filter(category=self.instance.category, name__iexact=value)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise serializers.ValidationError(
                f"A product named {value!r} already exists in this category."
            )
        return value


class CategoryUpdateSerializer(serializers.Serializer):
    """Body for ``PATCH /api/v1/products/categories/{id}/``."""

    name = serializers.CharField(max_length=100, required=False, trim_whitespace=True)
    description = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    display_order = serializers.IntegerField(required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if (
            self.instance
            and Category.objects.filter(name__iexact=value).exclude(pk=self.instance.pk).exists()
        ):
            raise serializers.ValidationError(f"A category named {value!r} already exists.")
        return value


__all__ = [
    "CategoryCreateSerializer",
    "CategorySerializer",
    "CategoryUpdateSerializer",
    "ProductCreateSerializer",
    "ProductListSerializer",
    "ProductPriceCreateSerializer",
    "ProductPriceSerializer",
    "ProductSerializer",
    "ProductUpdateSerializer",
]
