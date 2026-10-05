"""Serializers for the finance API."""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.finance.models import Expense, ExpenseCategory


class ExpenseCategorySerializer(serializers.ModelSerializer):
    """An expense classification."""

    class Meta:
        model = ExpenseCategory
        fields = ["id", "name", "description", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ExpenseCategoryCreateSerializer(serializers.Serializer):
    """Body for creating an expense category."""

    name = serializers.CharField(max_length=100, trim_whitespace=True)
    description = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if ExpenseCategory.objects.filter(name__iexact=value).exists():
            raise serializers.ValidationError("An expense category with this name already exists.")
        return value


class ExpenseSerializer(serializers.ModelSerializer):
    """An expense and its approval state."""

    category_name = serializers.CharField(source="category.name", read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Expense
        fields = [
            "id",
            "category",
            "category_name",
            "description",
            "amount",
            "currency",
            "incurred_on",
            "status",
            "status_display",
            "approved_at",
            "recorded_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "approved_at",
            "recorded_at",
            "created_at",
            "updated_at",
        ]


class ExpenseCreateSerializer(serializers.Serializer):
    """Body for recording an expense."""

    category = serializers.PrimaryKeyRelatedField(queryset=ExpenseCategory.objects.all())
    description = serializers.CharField(max_length=255, trim_whitespace=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    currency = serializers.CharField(max_length=3, default="ETB")
    incurred_on = serializers.DateField()

    def validate_amount(self, value: Decimal) -> Decimal:
        if value <= 0:
            raise serializers.ValidationError("Expense amount must be greater than zero.")
        return value

    def validate_currency(self, value: str) -> str:
        value = value.strip().upper()
        if value != "ETB":
            raise serializers.ValidationError("Only ETB expenses are supported.")
        return value


class BalanceQuerySerializer(serializers.Serializer):
    """Required business-local reporting period."""

    start = serializers.DateField()
    end = serializers.DateField()

    def validate(self, attrs: dict) -> dict:
        if attrs["end"] < attrs["start"]:
            raise serializers.ValidationError({"end": ["End must be on or after start."]})
        return attrs


class BalanceSerializer(serializers.Serializer):
    """The business balance response."""

    period_start = serializers.DateField()
    period_end = serializers.DateField()
    currency = serializers.CharField()
    income = serializers.DictField()
    expenses_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    expense_breakdown = serializers.DictField()
    payroll_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    net = serializers.DecimalField(max_digits=14, decimal_places=2)
