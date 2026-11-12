"""Serializers for Bono configuration, custody, reports and configuration history."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

from rest_framework import serializers

from apps.audit.models import AuditLog
from apps.bono.models import (
    BonoDayStatus,
    BonoIncident,
    BonoIncidentKind,
    BonoIncidentResolution,
    BonoIssue,
    BonoIssueKind,
    BonoProductPairing,
    BonoReport,
    BonoReportLine,
    BonoReportProductLine,
    BonoReportStatus,
    BonoTransfer,
    BonoType,
)
from apps.core.money import CURRENCY
from apps.payroll.models import PayrollItem
from apps.products.models import Product
from apps.users.models import EmployeeProfile


class BonoTypeNestedSerializer(serializers.ModelSerializer):
    """Minimal Bono identity used inside custody rows."""

    class Meta:
        model = BonoType
        fields = ["id", "code", "name", "color", "selling_price", "currency", "is_active"]
        read_only_fields = fields


class BonoProductPairingSerializer(serializers.ModelSerializer):
    """Current or historical pairing, including an open price review."""

    bono_type = BonoTypeNestedSerializer(read_only=True)
    product = serializers.IntegerField(source="product_id", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    current_price = serializers.SerializerMethodField()
    reviewed_by_name = serializers.CharField(source="reviewed_by.display_name", read_only=True)

    class Meta:
        model = BonoProductPairing
        fields = [
            "id",
            "bono_type",
            "product",
            "product_name",
            "product_sku",
            "is_active",
            "paired_at",
            "unpaired_at",
            "price_at_pairing",
            "currency",
            "current_price",
            "review_required",
            "review_reason",
            "previous_price",
            "new_price",
            "price_effective_from",
            "flagged_at",
            "reviewed_at",
            "reviewed_by_name",
        ]
        read_only_fields = fields

    def get_current_price(self, obj: BonoProductPairing) -> str | None:
        price = obj.product.current_price()
        return str(price.unit_price) if price is not None else None


class BonoTypeSerializer(serializers.ModelSerializer):
    """A Bono identity with its active pairings and review count."""

    active_pairings = serializers.SerializerMethodField()
    pending_review_count = serializers.SerializerMethodField()

    class Meta:
        model = BonoType
        fields = [
            "id",
            "code",
            "name",
            "color",
            "selling_price",
            "currency",
            "is_active",
            "notes",
            "active_pairings",
            "pending_review_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "code",
            "currency",
            "active_pairings",
            "pending_review_count",
            "created_at",
            "updated_at",
        ]

    def _active(self, obj: BonoType) -> list[BonoProductPairing]:
        pairings = getattr(obj, "_active_pairings", None)
        if pairings is not None:
            return list(pairings)
        return list(obj.pairings.filter(is_active=True).select_related("product"))

    def get_active_pairings(self, obj: BonoType) -> list[dict[str, Any]]:
        return cast(
            "list[dict[str, Any]]",
            BonoProductPairingSerializer(
                self._active(obj),
                many=True,
                context=self.context,
            ).data,
        )

    def get_pending_review_count(self, obj: BonoType) -> int:
        return sum(1 for pairing in self._active(obj) if pairing.review_required)


class BonoTypeCreateSerializer(serializers.Serializer):
    """Body for ``POST /bono/types/``."""

    name = serializers.CharField(max_length=100, trim_whitespace=True)
    color = serializers.CharField(max_length=7, default="#111827")
    selling_price = serializers.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0")
    )
    currency = serializers.CharField(max_length=3, default=CURRENCY)
    notes = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)


class BonoTypeUpdateSerializer(serializers.Serializer):
    """Body for ``PATCH /bono/types/{id}/``."""

    name = serializers.CharField(max_length=100, required=False, trim_whitespace=True)
    color = serializers.CharField(max_length=7, required=False)
    is_active = serializers.BooleanField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    confirm_in_progress = serializers.BooleanField(default=False, write_only=True)
    change_reason = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=True, write_only=True
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if not any(key in attrs for key in ("name", "color", "is_active", "notes")):
            raise serializers.ValidationError("Submit at least one field to change.")
        return attrs


class PairingAddSerializer(serializers.Serializer):
    """Body for adding one or more products to a Bono type."""

    products = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), many=True)
    confirm_in_progress = serializers.BooleanField(default=False, write_only=True)
    change_reason = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=True, write_only=True
    )


class PairingRemoveSerializer(serializers.Serializer):
    """Body for retiring a pairing without deleting it."""

    reason = serializers.CharField(trim_whitespace=True)
    confirm_in_progress = serializers.BooleanField(default=False, write_only=True)
    change_reason = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=True, write_only=True
    )


class PairingReviewSerializer(serializers.Serializer):
    """Owner resolution of a price review."""

    resolution = serializers.ChoiceField(choices=["RETAIN", "REASSIGN", "UNPAIR"])
    target_bono_type = serializers.PrimaryKeyRelatedField(
        queryset=BonoType.objects.all(), required=False, allow_null=True
    )
    reason = serializers.CharField(trim_whitespace=True)
    confirm_in_progress = serializers.BooleanField(default=False, write_only=True)


class BonoIssueSerializer(serializers.ModelSerializer):
    bono_type = serializers.IntegerField(source="bono_type_id", read_only=True)
    employee = serializers.IntegerField(source="employee_id", read_only=True)
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    recorded_by_name = serializers.CharField(source="created_by.display_name", read_only=True)

    class Meta:
        model = BonoIssue
        fields = [
            "id",
            "operational_date",
            "bono_type",
            "bono_name_snapshot",
            "bono_color_snapshot",
            "bono_price_snapshot",
            "currency",
            "employee",
            "employee_name",
            "kind",
            "quantity",
            "occurred_at",
            "note",
            "recorded_by_name",
            "created_at",
        ]
        read_only_fields = fields


class BonoIssueCreateSerializer(serializers.Serializer):
    operational_date = serializers.DateField()
    bono_type = serializers.PrimaryKeyRelatedField(queryset=BonoType.objects.all())
    employee = serializers.PrimaryKeyRelatedField(queryset=EmployeeProfile.objects.all())
    kind = serializers.ChoiceField(choices=BonoIssueKind.choices)
    quantity = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)


class BonoTransferSerializer(serializers.ModelSerializer):
    bono_type = serializers.IntegerField(source="bono_type_id", read_only=True)
    from_employee = serializers.IntegerField(source="from_employee_id", read_only=True)
    to_employee = serializers.IntegerField(source="to_employee_id", read_only=True)
    from_employee_name = serializers.CharField(source="from_employee.full_name", read_only=True)
    to_employee_name = serializers.CharField(source="to_employee.full_name", read_only=True)
    recorded_by_name = serializers.CharField(source="created_by.display_name", read_only=True)

    class Meta:
        model = BonoTransfer
        fields = [
            "id",
            "operational_date",
            "bono_type",
            "bono_name_snapshot",
            "bono_color_snapshot",
            "from_employee",
            "from_employee_name",
            "to_employee",
            "to_employee_name",
            "quantity",
            "occurred_at",
            "reason",
            "note",
            "recorded_by_name",
            "created_at",
        ]
        read_only_fields = fields


class BonoTransferCreateSerializer(serializers.Serializer):
    operational_date = serializers.DateField()
    bono_type = serializers.PrimaryKeyRelatedField(queryset=BonoType.objects.all())
    from_employee = serializers.PrimaryKeyRelatedField(queryset=EmployeeProfile.objects.all())
    to_employee = serializers.PrimaryKeyRelatedField(queryset=EmployeeProfile.objects.all())
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(trim_whitespace=True)
    note = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)


class BonoIncidentSerializer(serializers.ModelSerializer):
    bono_type = serializers.IntegerField(source="bono_type_id", read_only=True, allow_null=True)
    product = serializers.IntegerField(source="product_id", read_only=True, allow_null=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    responsible_employee = serializers.IntegerField(
        source="responsible_employee_id", read_only=True, allow_null=True
    )
    responsible_employee_name = serializers.CharField(
        source="responsible_employee.full_name", read_only=True
    )
    recorded_by_name = serializers.CharField(source="created_by.display_name", read_only=True)
    payroll_deduction_amount = serializers.DecimalField(
        source="payroll_deduction.amount",
        max_digits=14,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = BonoIncident
        fields = [
            "id",
            "operational_date",
            "kind",
            "bono_type",
            "bono_name_snapshot",
            "bono_color_snapshot",
            "bono_price_snapshot",
            "currency",
            "product",
            "product_name",
            "responsible_employee",
            "responsible_employee_name",
            "quantity",
            "reason",
            "notes",
            "occurred_at",
            "breakage_record",
            "resolution_status",
            "resolution_notes",
            "payroll_deduction",
            "payroll_deduction_amount",
            "recorded_by_name",
            "created_at",
        ]
        read_only_fields = fields


class BonoIncidentCreateSerializer(serializers.Serializer):
    operational_date = serializers.DateField()
    kind = serializers.ChoiceField(choices=BonoIncidentKind.choices)
    bono_type = serializers.PrimaryKeyRelatedField(
        queryset=BonoType.objects.all(), required=False, allow_null=True
    )
    product = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(), required=False, allow_null=True
    )
    responsible_employee = serializers.PrimaryKeyRelatedField(
        queryset=EmployeeProfile.objects.all(), required=False, allow_null=True
    )
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(trim_whitespace=True)
    notes = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["kind"] == BonoIncidentKind.LOST_BONO:
            if not attrs.get("bono_type") or not attrs.get("responsible_employee"):
                raise serializers.ValidationError(
                    "A lost Bono needs its type and responsible staff member."
                )
            if attrs.get("product"):
                raise serializers.ValidationError({"product": "A lost Bono has no product."})
        elif not attrs.get("product"):
            raise serializers.ValidationError({"product": "A broken bottle needs a product."})
        return attrs


class BonoIncidentResolveSerializer(serializers.Serializer):
    resolution_status = serializers.ChoiceField(choices=BonoIncidentResolution.choices)
    resolution_notes = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)


class BonoIncidentDeductionSerializer(serializers.Serializer):
    payroll_item = serializers.PrimaryKeyRelatedField(queryset=PayrollItem.objects.all())
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.01"))
    reason = serializers.CharField(trim_whitespace=True)


class BonoReportLineSerializer(serializers.ModelSerializer):
    total_issued_quantity = serializers.IntegerField(read_only=True)
    accounted_quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = BonoReportLine
        fields = [
            "id",
            "bono_type",
            "bono_code_snapshot",
            "bono_name_snapshot",
            "bono_color_snapshot",
            "bono_price_snapshot",
            "currency",
            "initial_issued_quantity",
            "additional_issued_quantity",
            "total_issued_quantity",
            "transfers_in_quantity",
            "transfers_out_quantity",
            "lost_quantity",
            "used_quantity",
            "returned_quantity",
            "accounted_quantity",
            "discrepancy_quantity",
            "explanation",
        ]
        read_only_fields = fields


class BonoReportProductLineSerializer(serializers.ModelSerializer):
    product = serializers.IntegerField(source="product_id", read_only=True)

    class Meta:
        model = BonoReportProductLine
        fields = [
            "id",
            "product",
            "product_name_snapshot",
            "product_sku_snapshot",
            "bono_type",
            "bono_name_snapshot",
            "bono_color_snapshot",
            "opening_quantity",
            "received_quantity",
            "other_addition_quantity",
            "sold_quantity",
            "breakage_quantity",
            "other_loss_quantity",
            "expected_closing_quantity",
            "physical_closing_quantity",
            "variance_quantity",
            "explanation",
        ]
        read_only_fields = fields


class BonoReportSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    submitted_by_name = serializers.CharField(source="submitted_by.display_name", read_only=True)
    approved_by_name = serializers.CharField(source="approved_by.display_name", read_only=True)
    rejected_by_name = serializers.CharField(source="rejected_by.display_name", read_only=True)

    class Meta:
        model = BonoReport
        fields = [
            "id",
            "operational_date",
            "revision",
            "corrects",
            "correction_reason",
            "status",
            "status_display",
            "submitted_by_name",
            "submitted_at",
            "approved_by_name",
            "approved_at",
            "rejected_by_name",
            "rejected_at",
            "rejection_reason",
            "notes",
            "sales_total",
            "cash_paid_total",
            "mobile_paid_total",
            "payments_total",
            "currency",
            "activity_generated_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def to_representation(self, instance: BonoReport) -> dict[str, Any]:
        data = super().to_representation(instance)
        if not self.context.get("include_money", True):
            for field in (
                "sales_total",
                "cash_paid_total",
                "mobile_paid_total",
                "payments_total",
                "currency",
            ):
                data.pop(field, None)
        return data


class BonoReportDetailSerializer(BonoReportSerializer):
    bono_lines = BonoReportLineSerializer(many=True, read_only=True)
    product_lines = BonoReportProductLineSerializer(many=True, read_only=True)

    class Meta(BonoReportSerializer.Meta):
        fields = [*BonoReportSerializer.Meta.fields, "bono_lines", "product_lines"]
        read_only_fields = fields


class BonoReportCreateSerializer(serializers.Serializer):
    operational_date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)


class BonoReportBonoLineUpdateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    used_quantity = serializers.IntegerField(min_value=0, required=False)
    returned_quantity = serializers.IntegerField(min_value=0, required=False)
    explanation = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)


class BonoReportProductLineUpdateSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    physical_closing_quantity = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=Decimal("0"), required=False, allow_null=True
    )
    explanation = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)


class BonoReportUpdateSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    bono_lines = BonoReportBonoLineUpdateSerializer(many=True, required=False)
    product_lines = BonoReportProductLineUpdateSerializer(many=True, required=False)


class BonoReportRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(trim_whitespace=True)


class BonoReportCorrectionSerializer(serializers.Serializer):
    reason = serializers.CharField(trim_whitespace=True)


class BonoStaffBalanceSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField()
    employee_name = serializers.CharField()
    employee_position = serializers.CharField()
    bono_type_id = serializers.IntegerField()
    bono_name = serializers.CharField()
    bono_color = serializers.CharField()
    issued = serializers.IntegerField()
    transfers_in = serializers.IntegerField()
    transfers_out = serializers.IntegerField()
    lost = serializers.IntegerField()
    balance = serializers.IntegerField()


class BonoTypeTotalSerializer(serializers.Serializer):
    bono_type_id = serializers.IntegerField()
    bono_code = serializers.CharField()
    bono_name = serializers.CharField()
    bono_color = serializers.CharField()
    initial_issued = serializers.IntegerField()
    additional_issued = serializers.IntegerField()
    total_issued = serializers.IntegerField()
    transfers_in = serializers.IntegerField()
    transfers_out = serializers.IntegerField()
    lost = serializers.IntegerField()


class BonoLatestReportSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    revision = serializers.IntegerField()
    status = serializers.ChoiceField(choices=BonoReportStatus.choices)
    submitted_at = serializers.DateTimeField(allow_null=True)
    approved_at = serializers.DateTimeField(allow_null=True)


class BonoDaySummarySerializer(serializers.Serializer):
    operational_date = serializers.DateField()
    day_status = serializers.ChoiceField(choices=BonoDayStatus.choices)
    operations_locked = serializers.BooleanField()
    bono_totals = BonoTypeTotalSerializer(many=True)
    staff_balances = BonoStaffBalanceSerializer(many=True)
    latest_report = BonoLatestReportSerializer(allow_null=True)
    in_progress_dates = serializers.ListField(child=serializers.DateField())


class BonoConfigHistorySerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.display_name", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "action",
            "actor_name",
            "summary",
            "before",
            "after",
            "created_at",
        ]
        read_only_fields = fields
