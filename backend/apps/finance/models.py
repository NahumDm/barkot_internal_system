"""Expenses and the finance balance basis (spec §11.1, §13.2).

The MVP profit figure is a simple subtraction: income from sales minus recorded
expenses. There is no double-entry ledger and no accrual, and introducing either
now would be scope the client has not asked for (ADR-0003).

Expenses are voided rather than deleted (§20.2). A Manager records them and a
Manager approves them; the two-step exists because a single person recording and
approving their own expense is the most common way petty cash goes missing, and
spec §9.2 gives the Owner the final say on anything financial.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.business_time import now_utc
from apps.core.enums import ExpenseStatus
from apps.core.exceptions import InvalidStateTransition
from apps.core.fields import CurrencyField, MoneyField

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User

from apps.core.models import (
    AllRowsManager,
    TimeStampedModel,
    VoidableManager,
    VoidableModel,
)


class ExpenseCategory(TimeStampedModel):
    """A grouping for expenses, e.g. "Utilities" or "Maintenance"."""

    name = models.CharField(_("name"), max_length=100, unique=True)
    description = models.TextField(_("description"), blank=True)
    is_active = models.BooleanField(_("is active"), default=True)

    class Meta:
        verbose_name = _("expense category")
        verbose_name_plural = _("expense categories")
        ordering = ["name"]
        permissions = (("manage_expense_categories", "Can manage expense categories"),)

    def __str__(self) -> str:
        return self.name


class Expense(VoidableModel):
    objects = VoidableManager()
    all_rows = AllRowsManager()

    """A single recorded expense (spec §13.2)."""

    category = models.ForeignKey(
        ExpenseCategory,
        verbose_name=_("category"),
        related_name="expenses",
        on_delete=models.PROTECT,
    )
    description = models.CharField(_("description"), max_length=255)
    amount = MoneyField(_("amount"), validators=[MinValueValidator(Decimal("0.01"))])
    currency = CurrencyField(_("currency"))
    incurred_on = models.DateField(
        _("incurred on"),
        help_text=_("Business-local date. Reported by day in the business timezone."),
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=ExpenseStatus.choices,
        default=ExpenseStatus.RECORDED,
    )
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True, editable=False)
    approved_by = models.ForeignKey(
        "accounts.User",
        verbose_name=_("approved by"),
        related_name="expenses_approved",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    recorded_at = models.DateTimeField(_("recorded at"), default=now_utc)

    class Meta:
        verbose_name = _("expense")
        verbose_name_plural = _("expenses")
        ordering = ["-incurred_on", "-id"]
        permissions = (
            ("create_expense", "Can record an expense"),
            ("approve_expense", "Can approve an expense"),
            ("view_reports", "Can view finance and management reports"),
        )
        indexes = [models.Index(fields=["-incurred_on"], name="idx_expense_incurred_on")]

    def __str__(self) -> str:
        return f"{self.description} ({self.amount} {self.currency})"

    @property
    def is_approved(self) -> bool:
        """Whether this expense has been approved for the books."""
        return self.approved_at is not None

    def approve(self, *, actor: User | None = None) -> None:
        """Approve this expense.

        Raises:
            InvalidStateTransition: If already approved, or if voided. An
                approved-then-voided expense must be voided first, otherwise the
                approval timestamp describes a row that no longer counts.
        """
        if self.is_approved:
            raise InvalidStateTransition(f"Expense {self.pk} is already approved.")
        if self.is_voided:
            raise InvalidStateTransition(f"Expense {self.pk} is voided and cannot be approved.")
        self.status = ExpenseStatus.APPROVED
        self.approved_at = now_utc()
        if actor is not None:
            self.approved_by = actor


def approved_expenses_between(start: date, end: date) -> models.QuerySet[Expense]:
    """Return approved, non-voided expenses in an inclusive business-date range.

    Only approved expenses count toward the balance. A Manager's income report
    should not shift because someone is still checking a receipt.
    """
    return (
        Expense.objects.filter(
            status=ExpenseStatus.APPROVED,
            incurred_on__gte=start,
            incurred_on__lte=end,
        )
        .select_related("category")
        .order_by("incurred_on", "id")
    )
