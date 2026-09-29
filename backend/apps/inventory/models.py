"""Inventory documents and the append-only stock ledger (spec §11.2, §12).

The design rule from §12 is simple and everything here serves it: **current
stock is the sum of the movements.** There is no ``Product.stock`` column to
drift out of sync, and no scheduled job to reconcile.

That makes :class:`StockMovement` the most safety-critical table in the system,
which is why it inherits :class:`apps.core.models.AppendOnlyModel`: a movement
can be inserted but never edited or deleted. A wrong receipt is corrected with a
*new* movement, not by fixing the old one.

A cached ``balance_after`` column was considered and rejected. It looks like a
cheap optimisation, but two concurrent receipts would both compute the same
"balance after" from the same snapshot, and the ledger — the one thing that must
be exactly right — would be wrong. Stock levels here are small enough that
``SUM()`` over the ledger is always fast enough.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Case, DecimalField, F, Sum, Value, When
from django.utils.translation import gettext_lazy as _

from apps.core.business_time import now_utc
from apps.core.enums import (
    MovementDirection,
    MovementKind,
    MovementSource,
    ReceiptStatus,
    StockCountStatus,
    direction_for_kind,
)
from apps.core.exceptions import InvalidStateTransition
from apps.core.fields import CurrencyField, MoneyField, QuantityField
from apps.core.models import (
    AllRowsManager,
    AppendOnlyModel,
    TimeStampedModel,
    VoidableManager,
    VoidableModel,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User
    from apps.products.models import Product
    from apps.sales.models import SaleItem

#: Sign applied to an ``OUT`` movement when totalling. Spelled out once so no
#: report has to re-derive it and risk disagreeing with the ledger.
_DIRECTION_SIGN = Case(
    When(direction=MovementDirection.IN, then=Value(1)),
    When(direction=MovementDirection.OUT, then=Value(-1)),
    default=Value(0),
    output_field=DecimalField(),
)


# ── Stock receipts ──────────────────────────────────────────────────────────


class StockReceipt(VoidableModel):
    objects = VoidableManager()
    all_rows = AllRowsManager()

    """A delivery of stock from a supplier (spec §12.1).

    The header records *who* delivered and *when*; the quantities live in
    :class:`StockReceiptItem`. A draft receipt may be edited freely; once
    completed it produces ledger movements and becomes effectively immutable.
    """

    reference = models.CharField(
        _("reference"),
        max_length=64,
        blank=True,
        help_text=_("Supplier's own delivery note number, if they have one."),
    )
    supplier_name = models.CharField(_("supplier"), max_length=150)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=ReceiptStatus.choices,
        default=ReceiptStatus.DRAFT,
    )
    received_at = models.DateTimeField(_("received at"), default=now_utc)
    completed_at = models.DateTimeField(_("completed at"), null=True, blank=True, editable=False)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("stock receipt")
        verbose_name_plural = _("stock receipts")
        ordering = ["-received_at", "-id"]
        permissions = (("receive_stock", "Can receive stock into the bar"),)
        indexes = [models.Index(fields=["-received_at"], name="idx_receipt_received_at")]

    def __str__(self) -> str:
        return f"Receipt #{self.pk} from {self.supplier_name}"

    @property
    def is_completed(self) -> bool:
        """Whether this receipt has already produced stock movements."""
        return self.completed_at is not None

    def complete(self, *, actor: User | None = None) -> None:
        """Mark the receipt as completed.

        Args:
            actor: The user completing the receipt.

        Raises:
            InvalidStateTransition: If already completed, or if it has no items.
                A completed receipt has already moved stock, so completing it a
                second time would double-count the delivery.
        """
        if self.is_completed:
            raise InvalidStateTransition(f"Stock receipt {self.pk} is already completed.")
        if not self.items.exists():
            raise InvalidStateTransition("A stock receipt must have at least one item.")
        self.completed_at = now_utc()
        self.status = ReceiptStatus.COMPLETED
        if actor is not None:
            self.updated_by = actor


class StockReceiptItem(TimeStampedModel):
    """One product line on a receipt, carrying the cost it was bought at."""

    receipt = models.ForeignKey(
        StockReceipt,
        verbose_name=_("receipt"),
        related_name="items",
        on_delete=models.PROTECT,
    )
    product = models.ForeignKey(
        "products.Product",
        verbose_name=_("product"),
        related_name="receipt_items",
        on_delete=models.PROTECT,
    )
    quantity = QuantityField(_("quantity"), validators=[MinValueValidator(Decimal("0.001"))])
    unit_cost = MoneyField(
        _("unit cost"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_("What the bar paid. Used for stock valuation, not for sale pricing."),
    )
    currency = CurrencyField(_("currency"))
    lot_reference = models.CharField(_("lot reference"), max_length=64, blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("stock receipt item")
        verbose_name_plural = _("stock receipt items")
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["receipt", "product"], name="uniq_product_per_receipt")
        ]

    def __str__(self) -> str:
        return f"{self.quantity} x {self.product.sku} @ {self.unit_cost}"

    @property
    def line_cost(self) -> Decimal:
        """Total cost of this line, quantised like every other money value."""
        from apps.core.money import multiply_money

        return multiply_money(self.unit_cost, self.quantity)


# ── The ledger ──────────────────────────────────────────────────────────────


class StockMovementQuerySet(models.QuerySet["StockMovement"]):
    """QuerySet for :class:`StockMovement`."""

    def incoming(self) -> StockMovementQuerySet:
        """Movements that add to stock."""
        return self.filter(direction=MovementDirection.IN)

    def outgoing(self) -> StockMovementQuerySet:
        """Movements that remove from stock."""
        return self.filter(direction=MovementDirection.OUT)

    def for_product(self, product: Product | None) -> StockMovementQuerySet:
        """Movements of one product."""
        return self.filter(product=product) if product is not None else self.none()

    def balance_for(self, product: Product) -> Decimal:
        """Return the ledger-derived current stock of ``product``.

        This is *the* definition of current stock (spec §12). Sign handling lives
        in ``_DIRECTION_SIGN`` so the arithmetic cannot differ between the
        dashboard, a stock report and this method.
        """
        total = self.filter(product=product).aggregate(total=Sum(F("quantity") * _DIRECTION_SIGN))[
            "total"
        ]
        return total if total is not None else Decimal("0.000")


class StockMovement(AppendOnlyModel):
    """One immutable stock change (spec §12.2).

    Every stock change in the system is one of these rows, created by a service
    that also writes the originating document. Exactly one of the four source
    foreign keys must be set, enforced by a database constraint rather than
    application convention — an unattributable movement is an unauditable one.
    """

    product = models.ForeignKey(
        "products.Product",
        verbose_name=_("product"),
        related_name="stock_movements",
        on_delete=models.PROTECT,
    )
    kind = models.CharField(_("kind"), max_length=20, choices=MovementKind.choices)
    direction = models.CharField(
        _("direction"),
        max_length=3,
        choices=MovementDirection.choices,
        editable=False,
        help_text=_("Derived from kind. Never set by hand."),
    )
    quantity = QuantityField(
        _("quantity"),
        validators=[MinValueValidator(Decimal("0.001"))],
        help_text=_("Always positive. The direction carries the sign."),
    )
    source = models.CharField(_("source"), max_length=20, choices=MovementSource.choices)
    occurred_at = models.DateTimeField(_("occurred at"), default=now_utc)
    unit_cost = MoneyField(
        _("unit cost"),
        null=True,
        blank=True,
        help_text=_("Carried for receipts so stock can be valued; null elsewhere."),
    )
    currency = CurrencyField(_("currency"))
    reason = models.TextField(
        _("reason"),
        blank=True,
        help_text=_("Required when source is MANUAL."),
    )
    recorded_by = models.ForeignKey(
        "accounts.User",
        verbose_name=_("recorded by"),
        related_name="stock_movements_recorded",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    # Exactly one of these identifies what caused the movement.
    stock_receipt_item = models.ForeignKey(
        StockReceiptItem,
        verbose_name=_("receipt item"),
        related_name="movements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    sale_item = models.ForeignKey(
        "sales.SaleItem",
        verbose_name=_("sale item"),
        related_name="movements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    breakage_item = models.ForeignKey(
        "BreakageItem",
        verbose_name=_("breakage item"),
        related_name="movements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    stock_count_item = models.ForeignKey(
        "StockCountItem",
        verbose_name=_("stock count item"),
        related_name="movements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    objects = StockMovementQuerySet.as_manager()

    class Meta:
        verbose_name = _("stock movement")
        verbose_name_plural = _("stock movements")
        ordering = ["-occurred_at", "-id"]
        default_permissions = ("add", "view")
        permissions = (("view_inventory", "Can view stock levels and movements"),)
        indexes = [
            models.Index(fields=["product", "-occurred_at"], name="idx_movement_product_time"),
            models.Index(fields=["-occurred_at"], name="idx_movement_time"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        stock_receipt_item__isnull=False,
                        sale_item__isnull=True,
                        breakage_item__isnull=True,
                        stock_count_item__isnull=True,
                    )
                    | models.Q(
                        stock_receipt_item__isnull=True,
                        sale_item__isnull=False,
                        breakage_item__isnull=True,
                        stock_count_item__isnull=True,
                    )
                    | models.Q(
                        stock_receipt_item__isnull=True,
                        sale_item__isnull=True,
                        breakage_item__isnull=False,
                        stock_count_item__isnull=True,
                    )
                    | models.Q(
                        stock_receipt_item__isnull=True,
                        sale_item__isnull=True,
                        breakage_item__isnull=True,
                        stock_count_item__isnull=False,
                    )
                ),
                name="stock_movement_exactly_one_source",
                violation_error_message=(
                    "A stock movement must reference exactly one source document."
                ),
            ),
            models.CheckConstraint(
                condition=~models.Q(source=MovementSource.MANUAL, reason=""),
                name="stock_movement_manual_requires_reason",
                violation_error_message="A manual stock movement must give a reason.",
            ),
        ]

    def __str__(self) -> str:
        sign = "+" if self.direction == MovementDirection.IN else "-"
        return f"{sign}{self.quantity} {self.product.sku} ({self.kind})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Derive ``direction`` from ``kind`` and validate a manual reason.

        Raises:
            ValueError: If the kind/direction combination is not one of
                :data:`apps.core.enums.KIND_DIRECTIONS`, or a manual movement
                has no reason.
        """
        variance = None
        if self.kind == MovementKind.COUNT_VARIANCE:
            variance = self.direction

        self.direction = direction_for_kind(self.kind, variance=variance)

        if self.source == MovementSource.MANUAL and not self.reason.strip():
            raise ValueError("A manual stock movement must give a reason.")
        super().save(*args, **kwargs)

    @classmethod
    def record(
        cls,
        *,
        product: Product,
        kind: str,
        source: str,
        quantity: Decimal,
        occurred_at: datetime | None = None,
        direction: str | None = None,
        unit_cost: Decimal | None = None,
        reason: str = "",
        recorded_by: User | None = None,
        stock_receipt_item: StockReceiptItem | None = None,
        sale_item: SaleItem | None = None,
        breakage_item: BreakageItem | None = None,
        stock_count_item: StockCountItem | None = None,
    ) -> StockMovement:
        """Create one ledger row.

        This is the only supported way to write a movement, so the direction is
        always derived and the source is always supplied.
        """
        return cls.objects.create(
            product=product,
            kind=kind,
            direction=direction or MovementDirection.IN,
            source=source,
            quantity=quantity,
            occurred_at=occurred_at or now_utc(),
            unit_cost=unit_cost,
            reason=reason,
            recorded_by=recorded_by,
            stock_receipt_item=stock_receipt_item,
            sale_item=sale_item,
            breakage_item=breakage_item,
            stock_count_item=stock_count_item,
        )


# ── Breakage / waste ────────────────────────────────────────────────────────


class BreakageRecord(VoidableModel):
    objects = VoidableManager()
    all_rows = AllRowsManager()

    """Stock written off as broken, spilled or expired (spec §12.1).

    Separate from a manual ``STOCK_OUT`` because breakage is a normal, frequent
    event with no commercial value attached, while a stock-out is a deliberate
    removal that someone may need to justify. Collapsing them would make the
    "why did we lose this stock" report meaningless.
    """

    reference = models.CharField(_("reference"), max_length=64, blank=True)
    reason = models.CharField(
        _("reason"),
        max_length=150,
        help_text=_("Broken, spilled, expired, misplaced..."),
    )
    occurred_at = models.DateTimeField(_("occurred at"), default=now_utc)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("breakage record")
        verbose_name_plural = _("breakage records")
        ordering = ["-occurred_at", "-id"]
        permissions = (("record_breakage", "Can record stock breakage or waste"),)
        indexes = [models.Index(fields=["-occurred_at"], name="idx_breakage_time")]

    def __str__(self) -> str:
        return f"Breakage #{self.pk}: {self.reason}"


class BreakageItem(TimeStampedModel):
    """One product line on a breakage record."""

    record = models.ForeignKey(
        BreakageRecord,
        verbose_name=_("breakage record"),
        related_name="items",
        on_delete=models.PROTECT,
    )
    product = models.ForeignKey(
        "products.Product",
        verbose_name=_("product"),
        related_name="breakage_items",
        on_delete=models.PROTECT,
    )
    quantity = QuantityField(_("quantity"), validators=[MinValueValidator(Decimal("0.001"))])
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("breakage item")
        verbose_name_plural = _("breakage items")
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["record", "product"], name="uniq_product_per_breakage")
        ]


# ── Stock counts ────────────────────────────────────────────────────────────


class StockCount(VoidableModel):
    objects = VoidableManager()
    all_rows = AllRowsManager()

    """A physical stock count and its approval (spec §12.3).

    Lifecycle: ``DRAFT`` while being counted, ``COMPLETED`` once variances are
    submitted, ``APPROVED`` once a Manager accepts them. Only approval writes
    ``COUNT_VARIANCE`` movements, so a count can be re-checked before it
    changes any stock.
    """

    reference = models.CharField(_("reference"), max_length=64, blank=True)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=StockCountStatus.choices,
        default=StockCountStatus.DRAFT,
    )
    counted_at = models.DateTimeField(_("counted at"), default=now_utc)
    completed_at = models.DateTimeField(_("completed at"), null=True, blank=True, editable=False)
    approved_at = models.DateTimeField(_("approved at"), null=True, blank=True, editable=False)
    approved_by = models.ForeignKey(
        "accounts.User",
        verbose_name=_("approved by"),
        related_name="stock_counts_approved",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("stock count")
        verbose_name_plural = _("stock counts")
        ordering = ["-counted_at", "-id"]
        permissions = (
            ("complete_stock_count", "Can perform and complete stock counts"),
            ("approve_adjustment", "Can approve stock count variances"),
        )
        indexes = [models.Index(fields=["-counted_at"], name="idx_stockcount_time")]

    def __str__(self) -> str:
        return f"Stock count #{self.pk}"

    @property
    def is_approved(self) -> bool:
        """Whether variances have been approved and written to the ledger."""
        return self.approved_at is not None


class StockCountItem(TimeStampedModel):
    """One counted product, with the expected quantity snapshotted at entry.

    ``expected_quantity`` is captured when the count line is created, not when
    it is approved. Approving against the quantity from *approval* time would
    mean stock that moved during the count is silently absorbed into the
    variance, which is exactly the discrepancy the count existed to find.
    """

    stock_count = models.ForeignKey(
        StockCount,
        verbose_name=_("stock count"),
        related_name="items",
        on_delete=models.PROTECT,
    )
    product = models.ForeignKey(
        "products.Product",
        verbose_name=_("product"),
        related_name="stock_count_items",
        on_delete=models.PROTECT,
    )
    expected_quantity = QuantityField(
        _("expected quantity"),
        help_text=_("Ledger balance at the moment this count line was created."),
    )
    counted_quantity = QuantityField(
        _("counted quantity"),
        validators=[MinValueValidator(Decimal("0.000"))],
    )
    variance = QuantityField(
        _("variance"),
        help_text=_("Counted minus expected. Negative means stock is missing."),
    )
    note = models.TextField(_("note"), blank=True)

    class Meta:
        verbose_name = _("stock count item")
        verbose_name_plural = _("stock count items")
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["stock_count", "product"], name="uniq_product_per_stock_count"
            )
        ]

    def __str__(self) -> str:
        return (
            f"{self.product.sku}: expected {self.expected_quantity}, "
            f"counted {self.counted_quantity}"
        )

    @property
    def has_variance(self) -> bool:
        """Whether the count disagrees with the ledger."""
        return self.variance != Decimal("0.000")

    def compute_variance(self) -> Decimal:
        """Recalculate and store :attr:`variance` from the two quantities."""
        from apps.core.money import quantize_quantity

        self.variance = quantize_quantity(
            self.counted_quantity - self.expected_quantity, field="variance"
        )
        return self.variance
