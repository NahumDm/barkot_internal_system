"""Employees, monthly payroll runs, run lines and deductions (spec §14).

ADR-0003 deviation D5: the person lives in
:class:`apps.users.models.EmployeeProfile`; the monthly-payroll subject lives
here as :class:`Employee`, a one-to-one companion. Spec §6.2 wants the profile in
``users`` and §14.2 wants ``monthly_wage``/``status`` alongside the name. Splitting
them satisfies both without duplicating a field.

The statutory tax and deduction rules are **not** implemented. The client has not
confirmed them (spec §30 items 5 and 6), so a run's net pay is
``gross - deductions entered by a Manager``. Hard-coding a guess would produce
confidently wrong payslips, which is worse than an obviously incomplete feature.
The enum in :mod:`apps.core.enums` carries only deduction kinds the client has
actually asked for.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.business_time import now_utc
from apps.core.enums import (
    EmployeeStatus,
    PayrollDeductionType,
    PayrollItemStatus,
    PayrollRunStatus,
)
from apps.core.exceptions import ExcessiveDeduction, InvalidStateTransition
from apps.core.fields import CurrencyField, MoneyField
from apps.core.models import AllRowsManager, VoidableManager, VoidableModel
from apps.core.money import ZERO_MONEY, sum_money


class Employee(VoidableModel):
    objects = VoidableManager()
    all_rows = AllRowsManager()

    """The monthly-payroll side of a staff member (spec §14.2).

    Not created directly: use :meth:`from_profile` so the one-to-one link and
    the initial status are always set together.
    """

    profile = models.OneToOneField(
        "users.EmployeeProfile",
        verbose_name=_("employee profile"),
        related_name="payroll_employee",
        on_delete=models.PROTECT,
    )
    monthly_wage = MoneyField(
        _("monthly wage"),
        default=ZERO_MONEY,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_("Gross wage for a full month before deductions."),
    )
    currency = CurrencyField(_("currency"))
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=EmployeeStatus.choices,
        default=EmployeeStatus.ACTIVE,
    )
    terminated_on = models.DateField(_("terminated on"), null=True, blank=True)

    class Meta:
        verbose_name = _("employee")
        verbose_name_plural = _("employees")
        ordering = ["profile__full_name"]
        permissions = (("manage_payroll_employees", "Can manage payroll employee records"),)

    def __str__(self) -> str:
        return self.profile.full_name

    @classmethod
    def from_profile(cls, profile: object, *, monthly_wage: Decimal = ZERO_MONEY) -> Employee:
        """Create the payroll subject for an existing profile.

        Args:
            profile: An :class:`apps.users.models.EmployeeProfile`.
            monthly_wage: Gross monthly wage. Zero is allowed and must be set
                deliberately; a missing wage is an open client question
                (spec §30 item 5), not a reason to guess a value.

        Returns:
            The created :class:`Employee`.
        """
        return cls.objects.create(profile=profile, monthly_wage=monthly_wage)

    @property
    def full_name(self) -> str:
        """Convenience accessor for the person's name."""
        return self.profile.full_name

    @property
    def is_employable(self) -> bool:
        """Whether this employee may be included in a new payroll run."""
        return self.status == EmployeeStatus.ACTIVE and not self.profile.is_archived


class PayrollRun(VoidableModel):
    objects = VoidableManager()
    all_rows = AllRowsManager()

    """A monthly payroll run (spec §14.1).

    Lifecycle: ``GENERATED`` by a Manager, ``APPROVED`` by the Owner,
    ``PAID`` once the money has gone out. Only ``APPROVED`` runs count toward
    the finance balance, so money is never reported as spent before the Owner has
    seen it.
    """

    period_month = models.DateField(
        _("period month"),
        help_text=_("First day of the month being paid, e.g. 2026-09-01."),
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=PayrollRunStatus.choices,
        default=PayrollRunStatus.GENERATED,
    )
    currency = CurrencyField(_("currency"))
    generated_at = models.DateTimeField(_("generated at"), default=now_utc)
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True, editable=False)
    approved_by = models.ForeignKey(
        "accounts.User",
        verbose_name=_("approved by"),
        related_name="payroll_runs_approved",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    paid_at = models.DateTimeField(_("paid at"), null=True, blank=True, editable=False)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("payroll run")
        verbose_name_plural = _("payroll runs")
        ordering = ["-period_month", "-id"]
        permissions = (
            ("view_payroll", "Can view payroll"),
            ("generate_run", "Can generate a payroll run"),
            ("approve_run", "Can approve a payroll run"),
            ("mark_paid", "Can mark a payroll run as paid"),
        )
        constraints = [
            models.UniqueConstraint(fields=["period_month"], name="uniq_payroll_run_per_month")
        ]

    def __str__(self) -> str:
        return f"Payroll {self.period_month:%Y-%m}"

    @property
    def gross_total(self) -> Decimal:
        """Sum of the run's gross amounts."""
        return sum_money(self.items.values_list("gross_amount", flat=True))

    @property
    def deduction_total(self) -> Decimal:
        """Sum of every deduction across the run's lines."""
        return sum_money(
            self.items.values_list("total_deductions", flat=True),
        )

    @property
    def net_total(self) -> Decimal:
        """Sum of the run's net (take-home) amounts."""
        return sum_money(self.items.values_list("net_amount", flat=True))

    def approve(self, *, actor: Any | None = None) -> None:
        """Approve the run.

        Raises:
            InvalidStateTransition: If not in ``GENERATED`` state, or if it has
                no lines.
        """
        if self.status != PayrollRunStatus.GENERATED:
            raise InvalidStateTransition(
                f"Payroll run {self.pk} is {self.get_status_display()}, not awaiting approval."
            )
        if not self.items.exists():
            raise InvalidStateTransition("An empty payroll run cannot be approved.")
        self.status = PayrollRunStatus.APPROVED
        self.approved_at = now_utc()
        if actor is not None:
            self.approved_by = actor

    def mark_paid(self, *, actor: Any | None = None) -> None:
        """Mark the run as paid.

        Raises:
            InvalidStateTransition: If the run is not approved. Money cannot be
                reported as spent on an unapproved run.
        """
        if self.status != PayrollRunStatus.APPROVED:
            raise InvalidStateTransition(
                f"Payroll run {self.pk} must be approved before it can be marked paid."
            )
        self.status = PayrollRunStatus.PAID
        self.paid_at = now_utc()
        if actor is not None:
            self.updated_by = actor


class PayrollItem(VoidableModel):
    objects = VoidableManager()
    all_rows = AllRowsManager()

    """One employee's pay for one run (spec §14.2).

    ``gross_amount``, ``total_deductions`` and ``net_amount`` are stored. Once a
    run is approved the line is frozen: a correction is a new run, because
    rewriting an approved payslip is indistinguishable from falsifying one.
    """

    run = models.ForeignKey(
        PayrollRun,
        verbose_name=_("payroll run"),
        related_name="items",
        on_delete=models.PROTECT,
    )
    employee = models.ForeignKey(
        Employee,
        verbose_name=_("employee"),
        related_name="payroll_items",
        on_delete=models.PROTECT,
    )
    gross_amount = MoneyField(_("gross amount"), validators=[MinValueValidator(Decimal("0.00"))])
    total_deductions = MoneyField(
        _("total deductions"), default=ZERO_MONEY, validators=[MinValueValidator(Decimal("0.00"))]
    )
    net_amount = MoneyField(_("net amount"), validators=[MinValueValidator(Decimal("0.00"))])
    currency = CurrencyField(_("currency"))
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=PayrollItemStatus.choices,
        default=PayrollItemStatus.PENDING,
    )
    paid_at = models.DateTimeField(_("paid at"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("payroll item")
        verbose_name_plural = _("payroll items")
        ordering = ["employee__profile__full_name"]
        constraints = [
            models.UniqueConstraint(fields=["run", "employee"], name="uniq_employee_per_run")
        ]

    def __str__(self) -> str:
        return f"{self.employee.full_name} — {self.net_amount} net"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Recompute :attr:`net_amount` and refuse to over-deduct.

        Raises:
            ExcessiveDeduction: If deductions exceed gross. A negative payslip is
                always a data-entry error, and storing it would quietly flow into
                the finance balance.
        """
        from apps.core.money import quantize_money

        if self.total_deductions > self.gross_amount:
            raise ExcessiveDeduction(
                f"Deductions ({self.total_deductions}) exceed gross pay "
                f"({self.gross_amount}) for employee {self.employee_id}."
            )
        self.net_amount = quantize_money(self.gross_amount - self.total_deductions, field="net")
        super().save(*args, **kwargs)


class PayrollDeduction(VoidableModel):
    objects = VoidableManager()
    all_rows = AllRowsManager()

    """A single deduction against a payroll line (spec §14.2)."""

    payroll_item = models.ForeignKey(
        PayrollItem,
        verbose_name=_("payroll item"),
        related_name="deductions",
        on_delete=models.PROTECT,
    )
    deduction_type = models.CharField(
        _("type"), max_length=20, choices=PayrollDeductionType.choices
    )
    amount = MoneyField(_("amount"), validators=[MinValueValidator(Decimal("0.01"))])
    reason = models.CharField(_("reason"), max_length=255, blank=True)
    occurred_on = models.DateField(
        _("occurred on"),
        help_text=_("Business-local date the deduction relates to, usually in the run period."),
    )

    class Meta:
        verbose_name = _("payroll deduction")
        verbose_name_plural = _("payroll deductions")
        ordering = ["-occurred_on", "-id"]
        permissions = (("create_deduction", "Can record a payroll deduction"),)
        indexes = [models.Index(fields=["-occurred_on"], name="idx_deduction_date")]

    def __str__(self) -> str:
        return f"{self.get_deduction_type_display()} {self.amount}"
