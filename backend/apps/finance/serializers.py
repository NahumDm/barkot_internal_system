"""Serializers for the finance API."""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.core.enums import PaymentMethod
from apps.finance.models import AdditionalIncome, Expense, ExpenseCategory


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


class ExpenseCategoryUpdateSerializer(serializers.Serializer):
    """Body for editing an expense category.

    Every field is optional so a caller can rename, re-describe, or archive a
    category on its own. A rename must still be unique, but the category's own
    current name is not a clash with itself.
    """

    name = serializers.CharField(max_length=100, trim_whitespace=True, required=False)
    description = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    is_active = serializers.BooleanField(required=False)

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Expense category name is required.")
        existing = ExpenseCategory.objects.filter(name__iexact=value)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
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


class AdditionalIncomeSerializer(serializers.ModelSerializer):
    """An additional income record."""
    created_by_name = serializers.CharField(
        source="created_by.get_full_name", read_only=True, default=""
    )

    class Meta:
        model = AdditionalIncome
        fields = [
            "id",
            "source",
            "amount",
            "currency",
            "income_date",
            "note",
            "payment_method",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
            "voided_at",
            "voided_by",
            "void_reason",
        ]
        read_only_fields = [
            "id",
            "currency",
            "created_by",
            "created_by_name",
            "created_at",
            "updated_at",
            "voided_at",
            "voided_by",
            "void_reason",
        ]


class AdditionalIncomeCreateSerializer(serializers.Serializer):
    source = serializers.CharField(max_length=255, trim_whitespace=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    currency = serializers.CharField(max_length=3, default="ETB")
    income_date = serializers.DateField()
    note = serializers.CharField(trim_whitespace=True)
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )

    def validate_source(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Income source is required.")
        return value

    def validate_note(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Source / description note is required.")
        return value

    def validate_amount(self, value: Decimal) -> Decimal:
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    def validate_currency(self, value: str) -> str:
        value = value.strip().upper()
        if value != "ETB":
            raise serializers.ValidationError("Only ETB is supported.")
        return value


class AdditionalIncomeUpdateSerializer(serializers.Serializer):
    source = serializers.CharField(max_length=255, trim_whitespace=True, required=False)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    currency = serializers.CharField(max_length=3, required=False)
    income_date = serializers.DateField(required=False)
    note = serializers.CharField(trim_whitespace=True, required=False)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices, required=False)

    def validate_source(self, value: str) -> str:
        if value is not None:
            value = value.strip()
            if not value:
                raise serializers.ValidationError("Income source is required.")
        return value

    def validate_note(self, value: str) -> str:
        if value is not None:
            value = value.strip()
            if not value:
                raise serializers.ValidationError("Source / description note is required.")
        return value

    def validate_amount(self, value: Decimal) -> Decimal:
        if value is not None and value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value

    def validate_currency(self, value: str) -> str:
        if value is not None:
            value = value.strip().upper()
            if value != "ETB":
                raise serializers.ValidationError("Only ETB is supported.")
        return value
