"""Sales, sale lines and payments (spec §11.1, §13.1, ADR-0003 deviation D4).

A ``Sale`` is always an individual customer transaction (CD-01). There is no
table, tab or open-round model, so a sale is never in a half-finished state: it
is created completed or it does not exist.

Two money rules are enforced structurally rather than by convention:

- :class:`SaleItem` stores the ``unit_price`` it was actually sold at, copied
  from :class:`apps.products.models.ProductPrice` at the moment of the sale.
  Repricing the catalogue later must not rewrite last month's revenue.
- :class:`Payment` is a separate row from the sale rather than two columns on
  it, so a single sale can be settled in more than one tender and the income
  report can split cash against mobile banking (CD-02) without inspecting
  free text.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.business_time import now_utc
from apps.core.enums import PaymentMethod, PaymentStatus, SaleStatus
from apps.core.exceptions import InvalidStateTransition
from apps.core.fields import CurrencyField, MoneyField, QuantityField
from apps.core.models import AllRowsManager, TimeStampedModel, VoidableManager, VoidableModel
from apps.core.money import ZERO_MONEY, sum_money

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User


class Sale(VoidableModel):
    objects = VoidableManager()
    all_rows = AllRowsManager()

    """One individual customer sale (spec §13.1).

    ``subtotal``, ``total`` and ``amount_paid`` are stored, not derived on read.
    They are denormalised on purpose: a receipt reprinted three months later
    must show the same figures even if the catalogue, tax rules or rounding
    logic have changed since. The service layer reconciles them against the line
    items before saving and refuses to persist a mismatch.
    """

    reference = models.CharField(
        _("reference"),
        max_length=32,
        unique=True,
        help_text=_("Human-readable receipt number, e.g. 'S-20260929-0042'."),
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=SaleStatus.choices,
        default=SaleStatus.COMPLETED,
    )
    sold_at = models.DateTimeField(_("sold at"), default=now_utc)
    subtotal = MoneyField(_("subtotal"), default=ZERO_MONEY)
    total = MoneyField(_("total"), default=ZERO_MONEY)
    amount_paid = MoneyField(_("amount paid"), default=ZERO_MONEY)
    currency = CurrencyField(_("currency"))
    payment_status = models.CharField(
        _("payment status"),
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PAID,
    )
    note = models.TextField(_("note"), blank=True)

    class Meta:
        verbose_name = _("sale")
        verbose_name_plural = _("sales")
        ordering = ["-sold_at", "-id"]
        default_permissions = ("add", "change", "view")
        permissions = (
            ("create_sale", "Can record a sale"),
            ("void_sale", "Can void a sale"),
            ("view_sales", "Can view sales"),
        )
        indexes = [
            models.Index(fields=["-sold_at"], name="idx_sale_sold_at"),
            models.Index(fields=["status", "-sold_at"], name="idx_sale_status_time"),
        ]

    def __str__(self) -> str:
        return self.reference

    @property
    def balance_due(self) -> Decimal:
        """Amount still owed on this sale."""
        from apps.core.money import quantize_money

        return quantize_money(self.total - self.amount_paid, field="balance_due")

    @property
    def is_fully_paid(self) -> bool:
        """Whether payments cover the total."""
        return self.amount_paid >= self.total

    @property
    def item_count(self) -> int:
        """Number of distinct product lines on the receipt.

        A list queryset either annotates the same name or prefetches ``items``,
        so counting the prefetched rows does not issue a query per sale. The
        setter accepts the annotation; the fallback keeps the field present on a
        freshly created sale, where no annotation or prefetch exists.
        """
        annotated = getattr(self, "_item_count", None)
        if annotated is not None:
            return annotated
        return len(self.items.all())

    @item_count.setter
    def item_count(self, value: int) -> None:
        self._item_count = value

    def void(self, *, reason: str, actor: User | None = None) -> None:
        """Void the sale and its payments.

        A voided sale stays in the table with a reason (spec §20.2). Its stock
        movements are reversed by the service layer, which appends compensating
        ``SALE`` movements rather than deleting the originals.

        Raises:
            InvalidStateTransition: If the sale is already voided.
        """
        if self.is_voided:
            raise InvalidStateTransition(f"Sale {self.reference} is already voided.")
        super().void(reason=reason, actor=actor)
        self.status = SaleStatus.VOIDED
        self.payment_status = PaymentStatus.VOIDED


class SaleItem(TimeStampedModel):
    """One product line on a sale, with its price frozen at sale time."""

    sale = models.ForeignKey(
        Sale,
        verbose_name=_("sale"),
        related_name="items",
        on_delete=models.PROTECT,
    )
    product = models.ForeignKey(
        "products.Product",
        verbose_name=_("product"),
        related_name="sale_items",
        on_delete=models.PROTECT,
    )
    quantity = QuantityField(_("quantity"), validators=[MinValueValidator(Decimal("0.001"))])
    unit_price = MoneyField(
        _("unit price"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=_("Price at the moment of sale. Copied, never looked up later."),
    )
    line_total = MoneyField(_("line total"), validators=[MinValueValidator(Decimal("0.00"))])
    currency = CurrencyField(_("currency"))
    price_source = models.ForeignKey(
        "products.ProductPrice",
        verbose_name=_("price source"),
        related_name="sale_items",
        on_delete=models.PROTECT,
        help_text=_("The price row this line was priced from, kept for audit."),
    )

    class Meta:
        verbose_name = _("sale item")
        verbose_name_plural = _("sale items")
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["sale", "product"], name="uniq_product_per_sale")
        ]

    def __str__(self) -> str:
        return f"{self.quantity} x {self.product.sku} @ {self.unit_price}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Recompute :attr:`line_total` from quantity and unit price.

        Recomputing here rather than trusting a client-supplied total means a
        tampered or buggy client cannot write a receipt whose lines do not add
        up to its stated total.
        """
        from apps.core.money import multiply_money

        self.line_total = multiply_money(self.unit_price, self.quantity)
        super().save(*args, **kwargs)


class Payment(VoidableModel):
    objects = VoidableManager()
    all_rows = AllRowsManager()

    """One tender against a sale (spec §13.1, CD-02).

    ``method`` is mandatory and closed to :class:`apps.core.enums.PaymentMethod`.
    ``MOBILE_BANKING`` records money received into the restaurant's account; it
    is not a gateway transaction and carries no provider reference in this
    version (ADR-0003 deviation D1).
    """

    sale = models.ForeignKey(
        Sale,
        verbose_name=_("sale"),
        related_name="payments",
        on_delete=models.PROTECT,
    )
    method = models.CharField(_("method"), max_length=20, choices=PaymentMethod.choices)
    amount = MoneyField(_("amount"), validators=[MinValueValidator(Decimal("0.01"))])
    currency = CurrencyField(_("currency"))
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PAID,
    )
    received_at = models.DateTimeField(_("received at"), default=now_utc)
    reference = models.CharField(
        _("reference"),
        max_length=64,
        blank=True,
        help_text=_("Mobile-banking transaction reference, if the customer supplies one."),
    )

    class Meta:
        verbose_name = _("payment")
        verbose_name_plural = _("payments")
        ordering = ["received_at", "id"]
        default_permissions = ("add", "change", "view")
        indexes = [
            models.Index(fields=["method", "-received_at"], name="idx_payment_method_time"),
        ]

    def __str__(self) -> str:
        return f"{self.get_method_display()} {self.amount} for {self.sale.reference}"

    def void(self, *, reason: str, actor: User | None = None) -> None:
        """Void this tender."""
        super().void(reason=reason, actor=actor)
        self.status = PaymentStatus.VOIDED


def total_of_sale(sale: Sale) -> Decimal:
    """Return the sum of a sale's line totals.

    Reads the persisted line totals rather than recomputing from prices, so the
    result agrees with the printed receipt by construction.

    Args:
        sale: The sale to total. Pass ``sale.all_rows``-level data for a voided
            sale, whose items are retained for audit.
    """
    return sum_money(sale.items.values_list("line_total", flat=True))
