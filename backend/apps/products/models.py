"""Product catalogue (spec §11.1, ADR-0003 deviation D2).

Scope is sellable products — primarily beverages (CD-03). There is deliberately
**no ingredient, recipe or BOM model** in this app. Adding one is a new client
decision, not an extension of this schema.

Pricing is versioned in :class:`ProductPrice` rather than stored on
:class:`Product`. Spec §13.1 requires a sale line to keep the price it was sold
at, and the only reliable way to guarantee that is for the price to be a row
with a validity window that a sale can point at.

Stock is *not* modelled here. It lives entirely in
``apps.inventory.models.StockMovement`` (spec §12), so the catalogue has no
back-reference to stock and cannot drift out of sync with the ledger.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.business_time import now_utc
from apps.core.fields import CurrencyField, MoneyField
from apps.core.models import TimeStampedModel


class Category(TimeStampedModel):
    """A product grouping such as "Beer" or "Spirits" (spec §11.1)."""

    name = models.CharField(_("name"), max_length=100, unique=True)
    description = models.TextField(_("description"), blank=True)
    is_active = models.BooleanField(
        _("is active"),
        default=True,
        help_text=_("Inactive categories are hidden from pickers but keep their history."),
    )
    display_order = models.PositiveIntegerField(_("display order"), default=0)

    class Meta:
        verbose_name = _("category")
        verbose_name_plural = _("categories")
        ordering = ["display_order", "name"]
        permissions = (("manage_categories", "Can manage product categories"),)

    def __str__(self) -> str:
        return self.name

    @property
    def product_count(self) -> int:
        """Number of products in this category.

        The list view annotates ``_product_count`` for a single-query page.
        The fallback keeps the serializer correct for an instance returned by
        ``create`` or ``update``, where no annotation has been applied.
        """
        annotated = getattr(self, "_product_count", None)
        if annotated is not None:
            return annotated
        return self.products.count()


class ProductQuerySet(models.QuerySet["Product"]):
    """QuerySet for :class:`Product`."""

    def sellable(self) -> ProductQuerySet:
        """Products that may appear on a sale (spec §13.1)."""
        return self.filter(is_active=True, category__is_active=True)

    def stock_tracked(self) -> ProductQuerySet:
        """Products whose quantity is controlled by the stock ledger (spec §12)."""
        return self.filter(is_stock_tracked=True)


class Product(TimeStampedModel):
    """A sellable item (spec §11.1).

    ``is_stock_tracked`` is a per-product switch even though the client
    currently controls all stock. A preparation served from a bottle is a
    stocked unit, but a garnish or an already-portioned item is not, and a
    ledger that was never asked for would either over-count or block a sale on
    an untracked item.
    """

    category = models.ForeignKey(
        Category,
        verbose_name=_("category"),
        related_name="products",
        on_delete=models.PROTECT,
    )
    name = models.CharField(_("name"), max_length=150)
    sku = models.CharField(
        _("SKU"),
        max_length=64,
        unique=True,
        help_text=_("Stable internal code. Never reused, so a receipt stays traceable."),
    )
    unit = models.CharField(
        _("unit"),
        max_length=32,
        default="bottle",
        help_text=_("Selling and stocking unit, e.g. bottle, crate, kg, litre."),
    )
    quantity_mode = models.CharField(
        _("quantity mode"),
        max_length=10,
        choices=[("WHOLE", _("Whole units")), ("FRACTIONAL", _("Fractional units"))],
        default="WHOLE",
        help_text=_(
            "Whole units are counted in whole numbers (e.g. crates, bottles); "
            "fractional units allow decimals (e.g. kg, litre)."
        ),
    )
    bottles_per_crate = models.PositiveSmallIntegerField(
        _("bottles per crate"),
        null=True,
        blank=True,
        validators=[MinValueValidator(2)],
        help_text=_(
            "How many bottles one crate holds, e.g. 24. The bar receives this "
            "product by the crate and sells it by the bottle. Leave blank if the "
            "product is not counted in crates."
        ),
    )
    is_stock_tracked = models.BooleanField(_("is stock tracked"), default=True)
    is_active = models.BooleanField(
        _("is active"),
        default=True,
        help_text=_("Inactive products cannot be sold but keep their price and movement history."),
    )
    description = models.TextField(_("description"), blank=True)

    class Meta:
        verbose_name = _("product")
        verbose_name_plural = _("products")
        ordering = ["category__display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["category", "name"], name="uniq_product_name_per_category"
            )
        ]
        permissions = (
            ("manage_products", "Can manage products"),
            ("view_products", "Can view the product catalogue"),
        )
        indexes = [models.Index(fields=["sku"], name="idx_product_sku")]

    objects = ProductQuerySet.as_manager()

    def __str__(self) -> str:
        return f"{self.name} ({self.unit})"

    @property
    def requires_whole_quantity(self) -> bool:
        """Whether quantities of this product must be whole numbers.

        A ``WHOLE`` product (crates, bottles) cannot be sold or stocked in
        fractions; a ``FRACTIONAL`` product (kg, litre) can.
        """
        return self.quantity_mode == "WHOLE"

    @property
    def is_crated(self) -> bool:
        """Whether this product is counted in crates.

        A crated product is received in crates and sold in bottles, so the
        screens convert between the two with :attr:`bottles_per_crate`. Products
        with no crate size (spirits, soft drinks) stay in their own unit.
        """
        return bool(self.bottles_per_crate and self.bottles_per_crate > 1)

    def current_price(self, *, at: datetime | None = None) -> ProductPrice | None:
        """Return the price in effect at ``at`` (default: now).

        The rule is "the newest price whose ``effective_from`` has passed". A
        separate ``effective_to`` would require window-overlap validation for no
        benefit, because the catalogue only ever changes a price going forward.
        """
        moment = at or now_utc()
        return (
            self.price_history.filter(effective_from__lte=moment)
            .order_by("-effective_from", "-id")
            .first()
        )

    def price_at(self, moment: datetime) -> ProductPrice:
        """Return the price in effect at ``moment`` or raise.

        Raises:
            ProductPrice.DoesNotExist: If the product has never been priced, or
                had no price at that moment. A sale cannot be recorded without
                a price, so this must fail loudly rather than default to zero —
                a free sale is a real possibility that must be deliberate.
        """
        price = self.current_price(at=moment)
        if price is None:
            raise ProductPrice.DoesNotExist(
                f"Product {self.sku!r} has no price effective at {moment.isoformat()}."
            )
        return price


class ProductPrice(TimeStampedModel):
    """One price of a product, effective from a point in time (spec §13.1).

    A price is never edited once a sale references it. A correction is a new row
    with a later ``effective_from``, which leaves the price the sale actually
    used intact and reconstructable.
    """

    product = models.ForeignKey(
        Product,
        verbose_name=_("product"),
        related_name="price_history",
        on_delete=models.PROTECT,
    )
    unit_price = MoneyField(_("unit price"), validators=[MinValueValidator(Decimal("0.00"))])
    currency = CurrencyField(_("currency"))
    effective_from = models.DateTimeField(
        _("effective from"),
        help_text=_("UTC. This price applies to sales at or after this instant."),
    )
    is_active = models.BooleanField(_("is active"), default=True)

    class Meta:
        verbose_name = _("product price")
        verbose_name_plural = _("product prices")
        ordering = ["-effective_from", "-id"]
        permissions = (("change_prices", "Can set new product prices"),)
        indexes = [
            models.Index(fields=["product", "-effective_from"], name="idx_price_product_from")
        ]

    def __str__(self) -> str:
        return (
            f"{self.product.sku} @ {self.unit_price} {self.currency} "
            f"from {self.effective_from:%Y-%m-%d}"
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Normalise ``effective_from`` to UTC before saving.

        Django only warns about naive datetimes; a naive price start date is an
        off-by-hours bug in every subsequent report, so it is coerced here rather
        than trusted.
        """
        if timezone.is_naive(self.effective_from):
            self.effective_from = timezone.make_aware(self.effective_from, UTC)
        super().save(*args, **kwargs)


__all__ = ["Category", "Product", "ProductPrice"]
