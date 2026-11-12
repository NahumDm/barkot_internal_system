"""Bono token accountability models.

Bono is a physical token given to a member of staff for one bottle of a product.
It is **not** a payment instrument and it is not a second inventory ledger. The
models here record custody and reconciliation only:

- configuration (``BonoType`` / ``BonoProductPairing``) answers which products
  may share one token identity at the same selling price;
- operational rows (``BonoIssue``, ``BonoTransfer``, ``BonoIncident``) explain
  who held how many tokens and why the number moved;
- a daily ``BonoReport`` freezes what the cashier counted and what the existing
  sales and stock ledgers said at the end of an operational day.

Stock, sales, money and payroll stay in the domains that already own them. A
broken bottle creates the normal inventory breakage movement exactly once; a
lost token never creates a sale, a stock movement, or a payroll deduction by
itself.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.business_time import now_utc
from apps.core.fields import CurrencyField, MoneyField, QuantityField
from apps.core.models import ActorStampedModel, TimeStampedModel
from apps.core.money import ZERO_MONEY

HEX_COLOR_VALIDATOR = RegexValidator(
    regex=r"^#[0-9A-Fa-f]{6}$",
    message=_("Enter a six-digit hexadecimal colour such as #C2410C."),
)


class BonoIssueKind(models.TextChoices):
    """Why tokens entered a staff member's custody."""

    INITIAL = "INITIAL", _("Initial issue")
    ADDITIONAL = "ADDITIONAL", _("Additional issue")


class BonoIncidentKind(models.TextChoices):
    """Physical incidents that explain missing Bono or stock."""

    LOST_BONO = "LOST_BONO", _("Lost Bono")
    BROKEN_BOTTLE = "BROKEN_BOTTLE", _("Broken bottle")


class BonoIncidentResolution(models.TextChoices):
    """How a recorded loss has been dealt with."""

    PENDING = "PENDING", _("Pending review")
    RESOLVED = "RESOLVED", _("Resolved")
    DEDUCTED = "DEDUCTED", _("Deducted through payroll")


class BonoDayStatus(models.TextChoices):
    """Lock state of one operational day."""

    OPEN = "OPEN", _("Open")
    SUBMITTED = "SUBMITTED", _("Report submitted")
    APPROVED = "APPROVED", _("Report approved")


class BonoReportStatus(models.TextChoices):
    """Daily Bono report lifecycle."""

    DRAFT = "DRAFT", _("Draft")
    SUBMITTED = "SUBMITTED", _("Submitted")
    APPROVED = "APPROVED", _("Approved")
    REJECTED = "REJECTED", _("Rejected")


class BonoType(ActorStampedModel):
    """One independently managed Bono identity.

    ``code`` is the stable identity. The label and colour are presentation only,
    so changing either never changes what a historical transaction refers to.
    Transaction and report rows additionally snapshot the label/colour/price;
    that is what keeps an old report from appearing to have used today's colour.
    """

    code = models.UUIDField(_("code"), default=uuid4, unique=True, editable=False)
    name = models.CharField(_("name"), max_length=100, unique=True)
    color = models.CharField(
        _("display colour"),
        max_length=7,
        default="#111827",
        validators=[HEX_COLOR_VALIDATOR],
        help_text=_("Six-digit hex colour used to distinguish this Bono on screen."),
    )
    selling_price = MoneyField(
        _("applicable selling price"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_("Every product paired to this Bono must currently sell at this price."),
    )
    currency = CurrencyField(_("currency"))
    is_active = models.BooleanField(
        _("is active"),
        default=True,
        help_text=_("Inactive types keep their history and cannot receive new pairings or issues."),
    )
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("Bono type")
        verbose_name_plural = _("Bono types")
        ordering = ["name", "id"]
        default_permissions = ("view",)
        permissions = (
            ("view_bono", "Can view Bono operations and reports"),
            ("manage_configuration", "Can configure Bono types and product pairings"),
        )
        indexes = [models.Index(fields=["is_active", "name"], name="idx_bono_type_active_name")]

    def __str__(self) -> str:
        return self.name


class BonoProductPairing(ActorStampedModel):
    """Active or historical membership of one product in one Bono type.

    Rows are retired, never deleted. ``is_active`` is the current membership and
    the timestamps are what let a report for a past operational day know which
    products shared the type on that day.
    """

    bono_type = models.ForeignKey(
        BonoType,
        verbose_name=_("Bono type"),
        related_name="pairings",
        on_delete=models.PROTECT,
    )
    product = models.ForeignKey(
        "products.Product",
        verbose_name=_("product"),
        related_name="bono_pairings",
        on_delete=models.PROTECT,
    )
    is_active = models.BooleanField(_("is active"), default=True)
    paired_at = models.DateTimeField(_("paired at"), default=now_utc)
    unpaired_at = models.DateTimeField(_("unpaired at"), null=True, blank=True)
    price_at_pairing = MoneyField(_("price at pairing"))
    currency = CurrencyField(_("currency"))
    review_required = models.BooleanField(
        _("owner review required"),
        default=False,
        help_text=_("Set when the product price changes under an active pairing."),
    )
    review_reason = models.TextField(_("review reason"), blank=True)
    previous_price = MoneyField(_("previous price"), null=True, blank=True)
    new_price = MoneyField(_("new price"), null=True, blank=True)
    price_effective_from = models.DateTimeField(
        _("price effective from"),
        null=True,
        blank=True,
        help_text=_("When the reviewed price change takes effect."),
    )
    flagged_at = models.DateTimeField(_("flagged at"), null=True, blank=True)
    reviewed_at = models.DateTimeField(_("reviewed at"), null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "accounts.User",
        verbose_name=_("reviewed by"),
        related_name="bono_pairing_reviews",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("Bono product pairing")
        verbose_name_plural = _("Bono product pairings")
        ordering = ["bono_type__name", "product__name"]
        default_permissions = ("view",)
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=models.Q(is_active=True),
                name="uniq_active_bono_pairing_per_product",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_active=True, unpaired_at__isnull=True)
                    | models.Q(is_active=False, unpaired_at__isnull=False)
                ),
                name="bono_pairing_active_matches_unpaired_at",
                violation_error_message=_(
                    "An active pairing has no unpaired time; a retired pairing has one."
                ),
            ),
        ]
        indexes = [
            models.Index(fields=["bono_type", "is_active"], name="idx_bono_pair_type_active"),
            models.Index(fields=["product", "is_active"], name="idx_bono_pair_product_active"),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} → {self.bono_type.name}"


class BonoDay(TimeStampedModel):
    """One row per operational date, used as the serialization lock for writes.

    All allocation, transfer, loss and report transitions for a date lock this
    row first. That makes an overdrawn transfer impossible even when two managers
    submit at the same instant, without inventing an advisory lock or a second
    source of token balances.
    """

    operational_date = models.DateField(_("operational date"), unique=True)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=BonoDayStatus.choices,
        default=BonoDayStatus.OPEN,
    )

    class Meta:
        verbose_name = _("Bono operational day")
        verbose_name_plural = _("Bono operational days")
        ordering = ["-operational_date"]
        default_permissions = ("view",)

    def __str__(self) -> str:
        return f"{self.operational_date:%Y-%m-%d} ({self.get_status_display()})"


class BonoSnapshotMixin(models.Model):
    """Snapshot of the Bono label/colour/price at the time of an event.

    Abstract. The snapshot is deliberately duplicated on every operational row
    and frozen report line rather than joined at read time, because configuration
    labels are allowed to change and old records must not follow them.
    """

    bono_code_snapshot = models.UUIDField(_("Bono code snapshot"), editable=False)
    bono_name_snapshot = models.CharField(_("Bono name snapshot"), max_length=100, editable=False)
    bono_color_snapshot = models.CharField(_("Bono colour snapshot"), max_length=7, editable=False)
    bono_price_snapshot = MoneyField(_("Bono price snapshot"), editable=False)
    currency = CurrencyField(_("currency"), editable=False)

    class Meta:
        abstract = True

    @classmethod
    def snapshot_from(cls, bono_type: BonoType) -> dict[str, Any]:
        """Return the field values that freeze ``bono_type``'s current appearance."""
        return {
            "bono_code_snapshot": bono_type.code,
            "bono_name_snapshot": bono_type.name,
            "bono_color_snapshot": bono_type.color,
            "bono_price_snapshot": bono_type.selling_price,
            "currency": bono_type.currency,
        }


class BonoIssue(BonoSnapshotMixin, ActorStampedModel):
    """Tokens handed to a member of staff for an operational day."""

    operational_date = models.DateField(_("operational date"))
    bono_type = models.ForeignKey(
        BonoType,
        verbose_name=_("Bono type"),
        related_name="issues",
        on_delete=models.PROTECT,
    )
    employee = models.ForeignKey(
        "users.EmployeeProfile",
        verbose_name=_("staff member"),
        related_name="bono_issues",
        on_delete=models.PROTECT,
        help_text=_("The person physically accountable for these tokens."),
    )
    kind = models.CharField(_("issue kind"), max_length=20, choices=BonoIssueKind.choices)
    quantity = models.PositiveIntegerField(_("quantity"), validators=[MinValueValidator(1)])
    occurred_at = models.DateTimeField(_("issued at"), default=now_utc)
    note = models.TextField(_("note"), blank=True)

    class Meta:
        verbose_name = _("Bono issue")
        verbose_name_plural = _("Bono issues")
        ordering = ["-occurred_at", "-id"]
        default_permissions = ("view",)
        permissions = (("manage_operations", "Can record Bono issues, transfers and losses"),)
        constraints = [
            models.UniqueConstraint(
                fields=["operational_date", "employee", "bono_type"],
                condition=models.Q(kind=BonoIssueKind.INITIAL),
                name="uniq_initial_bono_issue_per_staff_type_day",
            )
        ]
        indexes = [
            models.Index(fields=["operational_date", "bono_type"], name="idx_bono_issue_day_type"),
            models.Index(fields=["operational_date", "employee"], name="idx_bono_issue_day_staff"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.quantity} x {self.bono_name_snapshot}"


class BonoTransfer(BonoSnapshotMixin, ActorStampedModel):
    """Custody movement between two staff members. Never a new business issue."""

    operational_date = models.DateField(_("operational date"))
    bono_type = models.ForeignKey(
        BonoType,
        verbose_name=_("Bono type"),
        related_name="transfers",
        on_delete=models.PROTECT,
    )
    from_employee = models.ForeignKey(
        "users.EmployeeProfile",
        verbose_name=_("from staff member"),
        related_name="bono_transfers_out",
        on_delete=models.PROTECT,
    )
    to_employee = models.ForeignKey(
        "users.EmployeeProfile",
        verbose_name=_("to staff member"),
        related_name="bono_transfers_in",
        on_delete=models.PROTECT,
    )
    quantity = models.PositiveIntegerField(_("quantity"), validators=[MinValueValidator(1)])
    occurred_at = models.DateTimeField(_("transferred at"), default=now_utc)
    reason = models.TextField(_("reason"))
    note = models.TextField(_("note"), blank=True)

    class Meta:
        verbose_name = _("Bono transfer")
        verbose_name_plural = _("Bono transfers")
        ordering = ["-occurred_at", "-id"]
        default_permissions = ("view",)
        indexes = [
            models.Index(
                fields=["operational_date", "bono_type"], name="idx_bono_transfer_day_type"
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.quantity} x {self.bono_name_snapshot}: "
            f"{self.from_employee.full_name} → {self.to_employee.full_name}"
        )


class BonoIncident(BonoSnapshotMixin, ActorStampedModel):
    """A lost token or a broken bottle requiring an explicit explanation.

    A broken-bottle row is linked to the normal inventory ``BreakageRecord``; the
    movement was already written by ``inventory.services.record_breakage`` and is
    never duplicated here. A lost-token row is only a token custody record: it
    does not become a sale, breakage or payroll deduction until an authorised
    person chooses the latter explicitly.
    """

    operational_date = models.DateField(_("operational date"))
    kind = models.CharField(_("kind"), max_length=20, choices=BonoIncidentKind.choices)
    bono_type = models.ForeignKey(
        BonoType,
        verbose_name=_("Bono type"),
        related_name="incidents",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    product = models.ForeignKey(
        "products.Product",
        verbose_name=_("product"),
        related_name="bono_incidents",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    responsible_employee = models.ForeignKey(
        "users.EmployeeProfile",
        verbose_name=_("responsible staff member"),
        related_name="bono_incidents",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    quantity = models.PositiveIntegerField(_("quantity"), validators=[MinValueValidator(1)])
    reason = models.TextField(_("reason"))
    notes = models.TextField(_("notes"), blank=True)
    occurred_at = models.DateTimeField(_("occurred at"), default=now_utc)
    breakage_record = models.OneToOneField(
        "inventory.BreakageRecord",
        verbose_name=_("inventory breakage record"),
        related_name="bono_incident",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
    )
    resolution_status = models.CharField(
        _("resolution"),
        max_length=20,
        choices=BonoIncidentResolution.choices,
        default=BonoIncidentResolution.PENDING,
    )
    resolution_notes = models.TextField(_("resolution notes"), blank=True)
    payroll_deduction = models.OneToOneField(
        "payroll.PayrollDeduction",
        verbose_name=_("payroll deduction"),
        related_name="bono_incident",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        verbose_name = _("Bono incident")
        verbose_name_plural = _("Bono incidents")
        ordering = ["-occurred_at", "-id"]
        default_permissions = ("view",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind=BonoIncidentKind.LOST_BONO,
                        bono_type__isnull=False,
                        product__isnull=True,
                        breakage_record__isnull=True,
                        responsible_employee__isnull=False,
                    )
                    | models.Q(
                        kind=BonoIncidentKind.BROKEN_BOTTLE,
                        product__isnull=False,
                        breakage_record__isnull=False,
                    )
                ),
                name="bono_incident_kind_matches_references",
                violation_error_message=_(
                    "A Bono incident must reference the records its kind needs."
                ),
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""),
                name="bono_incident_requires_reason",
                violation_error_message=_("An incident must explain what happened."),
            ),
        ]
        indexes = [
            models.Index(fields=["operational_date", "kind"], name="idx_bono_incident_day_kind"),
            models.Index(
                fields=["operational_date", "bono_type"], name="idx_bono_incident_day_type"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.quantity} on {self.operational_date}"


class BonoReport(ActorStampedModel):
    """The cashier's end-of-day Bono and product reconciliation for one date.

    An approved report is immutable. A correction is a new revision that points
    at the approved report through ``corrects``; the original and all its lines
    remain unchanged for audit.
    """

    operational_date = models.DateField(_("operational date"))
    revision = models.PositiveIntegerField(_("revision"), default=1)
    corrects = models.ForeignKey(
        "self",
        verbose_name=_("corrects report"),
        related_name="corrections",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=BonoReportStatus.choices,
        default=BonoReportStatus.DRAFT,
    )
    submitted_by = models.ForeignKey(
        "accounts.User",
        verbose_name=_("submitted by"),
        related_name="bono_reports_submitted",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    submitted_at = models.DateTimeField(_("submitted at"), null=True, blank=True)
    approved_by = models.ForeignKey(
        "accounts.User",
        verbose_name=_("approved by"),
        related_name="bono_reports_approved",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True)
    rejected_by = models.ForeignKey(
        "accounts.User",
        verbose_name=_("rejected by"),
        related_name="bono_reports_rejected",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    rejected_at = models.DateTimeField(_("rejected at"), null=True, blank=True)
    rejection_reason = models.TextField(_("rejection reason"), blank=True)
    correction_reason = models.TextField(_("correction reason"), blank=True)
    notes = models.TextField(_("notes"), blank=True)

    # Frozen monetary facts from the existing sales/payment domains. Stored so an
    # approved report cannot change when a sale or payment is voided later.
    sales_total = MoneyField(_("sales total"), default=ZERO_MONEY)
    cash_paid_total = MoneyField(_("cash payments"), default=ZERO_MONEY)
    mobile_paid_total = MoneyField(_("mobile banking payments"), default=ZERO_MONEY)
    payments_total = MoneyField(_("payments total"), default=ZERO_MONEY)
    currency = CurrencyField(_("currency"))
    activity_generated_at = models.DateTimeField(_("activity generated at"), default=now_utc)

    class Meta:
        verbose_name = _("Bono daily report")
        verbose_name_plural = _("Bono daily reports")
        ordering = ["-operational_date", "-revision"]
        default_permissions = ("view",)
        permissions = (
            ("submit_report", "Can prepare and submit a Bono daily report"),
            ("approve_report", "Can approve, reject or correct a Bono daily report"),
        )
        constraints = [
            models.UniqueConstraint(
                fields=["operational_date", "revision"], name="uniq_bono_report_date_revision"
            )
        ]
        indexes = [
            models.Index(fields=["operational_date", "status"], name="idx_bono_report_day_status"),
        ]

    def __str__(self) -> str:
        return f"Bono report {self.operational_date:%Y-%m-%d} r{self.revision}"

    @property
    def is_immutable(self) -> bool:
        """Whether the report has been signed off and may no longer be edited."""
        return self.status == BonoReportStatus.APPROVED


class BonoReportLine(models.Model):
    """Per-Bono-type quantities for one daily report, with frozen snapshots."""

    report = models.ForeignKey(
        BonoReport,
        verbose_name=_("report"),
        related_name="bono_lines",
        on_delete=models.CASCADE,
    )
    bono_type = models.ForeignKey(
        BonoType,
        verbose_name=_("Bono type"),
        related_name="report_lines",
        on_delete=models.PROTECT,
    )
    bono_code_snapshot = models.UUIDField(_("Bono code snapshot"), editable=False)
    bono_name_snapshot = models.CharField(_("Bono name snapshot"), max_length=100, editable=False)
    bono_color_snapshot = models.CharField(_("Bono colour snapshot"), max_length=7, editable=False)
    bono_price_snapshot = MoneyField(_("Bono price snapshot"), editable=False)
    currency = CurrencyField(_("currency"), editable=False)

    initial_issued_quantity = models.PositiveIntegerField(_("initial issued"), default=0)
    additional_issued_quantity = models.PositiveIntegerField(_("additional issued"), default=0)
    transfers_in_quantity = models.PositiveIntegerField(_("transfers in"), default=0)
    transfers_out_quantity = models.PositiveIntegerField(_("transfers out"), default=0)
    lost_quantity = models.PositiveIntegerField(_("lost Bonos"), default=0)
    used_quantity = models.PositiveIntegerField(_("used Bonos"), default=0)
    returned_quantity = models.PositiveIntegerField(_("unused Bonos returned"), default=0)
    discrepancy_quantity = models.IntegerField(_("discrepancy"), default=0, editable=False)
    explanation = models.TextField(_("explanation"), blank=True)

    class Meta:
        verbose_name = _("Bono report line")
        verbose_name_plural = _("Bono report lines")
        ordering = ["bono_name_snapshot", "id"]
        default_permissions = ("view",)
        constraints = [
            models.UniqueConstraint(
                fields=["report", "bono_type"], name="uniq_bono_line_per_report"
            )
        ]

    def __str__(self) -> str:
        total = self.initial_issued_quantity + self.additional_issued_quantity
        return f"{self.bono_name_snapshot}: {total}"

    @property
    def total_issued_quantity(self) -> int:
        """All tokens issued to staff for the type, excluding transfers."""
        return self.initial_issued_quantity + self.additional_issued_quantity

    @property
    def accounted_quantity(self) -> int:
        """Used, returned and explicitly recorded lost tokens."""
        return self.used_quantity + self.returned_quantity + self.lost_quantity

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Keep the discrepancy aligned with the quantities on every save."""
        self.discrepancy_quantity = self.total_issued_quantity - self.accounted_quantity
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = {*update_fields, "discrepancy_quantity"}
        super().save(*args, **kwargs)


class BonoReportProductLine(models.Model):
    """Independent stock reconciliation for one product that shared a Bono type.

    A Bono is one bottle, but two products sharing a type may hold completely
    different stock. These rows are never merged: each product keeps its own
    opening, receipts, sales, breakage, physical count and variance.
    """

    report = models.ForeignKey(
        BonoReport,
        verbose_name=_("report"),
        related_name="product_lines",
        on_delete=models.CASCADE,
    )
    product = models.ForeignKey(
        "products.Product",
        verbose_name=_("product"),
        related_name="bono_report_lines",
        on_delete=models.PROTECT,
    )
    bono_type = models.ForeignKey(
        BonoType,
        verbose_name=_("Bono type"),
        related_name="product_report_lines",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    product_name_snapshot = models.CharField(
        _("product name snapshot"), max_length=150, editable=False
    )
    product_sku_snapshot = models.CharField(_("SKU snapshot"), max_length=64, editable=False)
    bono_name_snapshot = models.CharField(_("Bono name snapshot"), max_length=100, blank=True)
    bono_color_snapshot = models.CharField(_("Bono colour snapshot"), max_length=7, blank=True)

    opening_quantity = QuantityField(_("opening stock"))
    received_quantity = QuantityField(_("received stock"), default=Decimal("0.000"))
    other_addition_quantity = QuantityField(_("other additions"), default=Decimal("0.000"))
    sold_quantity = QuantityField(_("sold quantity"), default=Decimal("0.000"))
    breakage_quantity = QuantityField(_("breakage quantity"), default=Decimal("0.000"))
    other_loss_quantity = QuantityField(_("other approved losses"), default=Decimal("0.000"))
    expected_closing_quantity = QuantityField(_("expected closing stock"), editable=False)
    physical_closing_quantity = QuantityField(_("physical closing stock"), null=True, blank=True)
    variance_quantity = QuantityField(_("variance"), null=True, blank=True, editable=False)
    explanation = models.TextField(_("explanation"), blank=True)

    class Meta:
        verbose_name = _("Bono report product line")
        verbose_name_plural = _("Bono report product lines")
        ordering = ["product_name_snapshot", "id"]
        default_permissions = ("view",)
        constraints = [
            models.UniqueConstraint(
                fields=["report", "product"], name="uniq_product_line_per_bono_report"
            )
        ]

    def __str__(self) -> str:
        return f"{self.product_name_snapshot} ({self.expected_closing_quantity})"

    @property
    def calculated_variance(self) -> Decimal | None:
        """Physical minus expected, or ``None`` before the cashier counts it."""
        if self.physical_closing_quantity is None:
            return None
        return self.physical_closing_quantity - self.expected_closing_quantity

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Derive expected closing stock and variance from the independent facts."""
        expected = (
            self.opening_quantity
            + self.received_quantity
            + self.other_addition_quantity
            - self.sold_quantity
            - self.breakage_quantity
            - self.other_loss_quantity
        )
        self.expected_closing_quantity = expected
        self.variance_quantity = self.calculated_variance
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = {
                *update_fields,
                "expected_closing_quantity",
                "variance_quantity",
            }
        super().save(*args, **kwargs)


__all__ = [
    "BonoDay",
    "BonoDayStatus",
    "BonoIncident",
    "BonoIncidentKind",
    "BonoIncidentResolution",
    "BonoIssue",
    "BonoIssueKind",
    "BonoProductPairing",
    "BonoReport",
    "BonoReportLine",
    "BonoReportProductLine",
    "BonoReportStatus",
    "BonoTransfer",
    "BonoType",
]
