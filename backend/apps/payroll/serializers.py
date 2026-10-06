"""Serializers for the payroll API (spec §14.2).

Every shape here is deliberately thin. Net pay is computed by
:meth:`apps.payroll.models.PayrollItem.save` and the run totals by
:class:`apps.payroll.models.PayrollRun`; this layer reports what those already
decided rather than recomputing a figure of its own. A second implementation of
the arithmetic is a second opinion nobody asked for, and the two would disagree
the first time a rounding rule changed.

The statutory deductions the client has not yet confirmed (spec §30 items 5-6) do
not appear here. There is no field for a tax rate because there is no confirmed
rule to put in it.
"""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.payroll.models import Employee, PayrollDeduction, PayrollItem, PayrollRun
from apps.users.models import EmployeeProfile


class PayrollProfileSerializer(serializers.ModelSerializer):
    """A staff profile that can still be put on monthly payroll.

    Exposed only to whoever may add a payroll employee, because a roster of
    names and phone numbers is staff data and the only screen that needs it is
    the form that fills ``PayrollEmployeeCreateSerializer.profile``. Without it
    that form would have no options to offer: ``apps.users`` has no API of its
    own, and payroll reaching into a different app's read surface would put the
    dependency in the wrong direction.
    """

    class Meta:
        model = EmployeeProfile
        fields = [
            "id",
            "full_name",
            "position",
            "phone_number",
            "start_date",
        ]
        read_only_fields = fields


class PayrollEmployeeSerializer(serializers.ModelSerializer):
    """A monthly-payroll subject, named via its staff profile.

    ``full_name``, ``position``, ``phone_number`` and ``start_date`` come from
    :class:`apps.users.models.EmployeeProfile` because that is where the person
    lives; payroll owns only the pay (ADR-0003 D5). The two dates and the phone
    are reported rather than copied into payroll so there is one place to update
    when a staff member's details change.
    """

    full_name = serializers.CharField(source="profile.full_name", read_only=True)
    position = serializers.CharField(source="profile.position", read_only=True)
    phone_number = serializers.CharField(source="profile.phone_number", read_only=True)
    start_date = serializers.DateField(source="profile.start_date", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Employee
        fields = [
            "id",
            "profile",
            "full_name",
            "position",
            "phone_number",
            "start_date",
            "monthly_wage",
            "currency",
            "status",
            "status_display",
            "terminated_on",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "terminated_on",
            "created_at",
            "updated_at",
        ]


class PayrollEmployeeCreateSerializer(serializers.Serializer):
    """Body for putting an existing staff profile onto payroll."""

    profile = serializers.PrimaryKeyRelatedField(queryset=EmployeeProfile.objects.all())
    monthly_wage = serializers.DecimalField(max_digits=14, decimal_places=2)
    currency = serializers.CharField(max_length=3, default="ETB")

    def validate_monthly_wage(self, value: Decimal) -> Decimal:
        if value < 0:
            raise serializers.ValidationError("A monthly wage cannot be negative.")
        return value

    def validate_currency(self, value: str) -> str:
        value = value.strip().upper()
        if value != "ETB":
            raise serializers.ValidationError("Only ETB payroll is supported.")
        return value

    def validate_profile(self, value: EmployeeProfile) -> EmployeeProfile:
        """Refuse a second payroll record for one person.

        Checked against ``all_rows`` rather than ``objects`` so a voided record still
        blocks the create: the link is a ``OneToOne``, so the database would reject
        the insert anyway, and refusing here turns an IntegrityError into a field
        error the form can render.
        """
        if Employee.all_rows.filter(profile=value).exists():
            raise serializers.ValidationError("This person already has a payroll employee record.")
        return value


class PayrollRunSerializer(serializers.ModelSerializer):
    """A monthly run and where it sits in its lifecycle."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    gross_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    deduction_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    net_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    approved_by = serializers.IntegerField(source="approved_by_id", read_only=True)
    # ``allow_null`` because an unapproved run has no approver. Without it DRF would
    # drop the key entirely on a GENERATED run and the field would be absent rather
    # than null, so the client would need two different shapes to read.
    approved_by_username = serializers.CharField(
        source="approved_by.username", read_only=True, allow_null=True
    )

    class Meta:
        model = PayrollRun
        fields = [
            "id",
            "period_month",
            "status",
            "status_display",
            "currency",
            "gross_total",
            "deduction_total",
            "net_total",
            "generated_at",
            "approved_at",
            "approved_by",
            "approved_by_username",
            "paid_at",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PayrollRunGenerateSerializer(serializers.Serializer):
    """Body for generating a month of payroll.

    Only the month is chosen here. Gross pay is read from each employee's
    ``monthly_wage`` rather than typed in, because a figure typed into a generate
    request would be a second place for a wage to live and the two would drift.
    """

    period = serializers.DateField()
    employee_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=False,
    )
    notes = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)


class PayrollItemSerializer(serializers.ModelSerializer):
    """One employee's line in a run."""

    full_name = serializers.CharField(source="employee.profile.full_name", read_only=True)
    position = serializers.CharField(source="employee.profile.position", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PayrollItem
        fields = [
            "id",
            "run",
            "employee",
            "full_name",
            "position",
            "gross_amount",
            "total_deductions",
            "net_amount",
            "currency",
            "status",
            "status_display",
            "paid_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PayrollDeductionSerializer(serializers.ModelSerializer):
    """A single deduction, kept with the reason it was taken.

    ``reason`` is reported rather than hidden because a payslip line with no
    explanation is the thing an employee will query, and a UI that cannot show the
    reason cannot answer them.
    """

    run = serializers.IntegerField(source="payroll_item.run_id", read_only=True)
    employee_name = serializers.CharField(source="payroll_item.employee.full_name", read_only=True)
    deduction_type_display = serializers.CharField(
        source="get_deduction_type_display", read_only=True
    )
    currency = serializers.CharField(source="payroll_item.currency", read_only=True)

    class Meta:
        model = PayrollDeduction
        fields = [
            "id",
            "payroll_item",
            "run",
            "employee_name",
            "deduction_type",
            "deduction_type_display",
            "amount",
            "currency",
            "reason",
            "occurred_on",
            "created_at",
        ]
        read_only_fields = fields


class PayrollDeductionCreateSerializer(serializers.Serializer):
    """Body for recording a deduction against one payroll line."""

    payroll_item = serializers.PrimaryKeyRelatedField(queryset=PayrollItem.objects.all())
    deduction_type = serializers.ChoiceField(
        choices=[
            ("ADVANCE", "Salary advance"),
            ("ABSENCE", "Absence"),
            ("LATE", "Tardiness"),
            ("OTHER", "Other"),
        ]
    )
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    reason = serializers.CharField(
        max_length=255, required=False, allow_blank=True, trim_whitespace=True
    )
    occurred_on = serializers.DateField(required=False)


__all__ = [
    "PayrollDeductionCreateSerializer",
    "PayrollDeductionSerializer",
    "PayrollEmployeeCreateSerializer",
    "PayrollEmployeeSerializer",
    "PayrollItemSerializer",
    "PayrollProfileSerializer",
    "PayrollRunGenerateSerializer",
    "PayrollRunSerializer",
]
