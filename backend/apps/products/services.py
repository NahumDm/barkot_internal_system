"""Product catalogue write services (spec §11.1).

The catalogue is read-heavy and write-light. The services here handle the
writes that change the product set: creating products, setting prices, and
retiring items. Reads are expressed as QuerySet methods on the models.

Every write does the same three things, in this order, inside one transaction:

1. checks the business preconditions and raises a
   :class:`apps.core.exceptions.BarkotDomainError` if they fail;
2. writes the model row;
3. writes an audit log entry.

The audit log is written last and only for successful writes. A product
without its audit trail would be unexplained; an audit entry without its
product would be unattributable. Doing both in one ``atomic`` block makes
the pair all-or-nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import QuerySet

from apps.audit.models import AuditLog
from apps.core.business_time import now_utc
from apps.core.exceptions import BARKOTDomainError
from apps.core.money import quantize_money
from apps.products.models import Category, Product, ProductPrice

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User


@dataclass(frozen=True, slots=True)
class ProductCreateInput:
    """Input for creating a new product.

    Attributes:
        category: The category the product belongs to.
        name: The product name (unique within its category).
        sku: Stable internal code, never reused.
        unit: Selling and stocking unit (e.g. "bottle", "crate", "kg").
        quantity_mode: "WHOLE" for whole-number units, "FRACTIONAL" for decimals.
        is_stock_tracked: Whether inventory ledger tracks this product.
        description: Free-text description.
    """

    category: Category
    name: str
    sku: str
    unit: str = "bottle"
    quantity_mode: str = "WHOLE"
    bottles_per_crate: int | None = None
    is_stock_tracked: bool = True
    description: str = ""


@dataclass(frozen=True, slots=True)
class PriceCreateInput:
    """Input for setting a new product price.

    Attributes:
        product: The product to price.
        unit_price: Price per unit.
        currency: Currency code (e.g. "ETB").
        effective_from: When this price takes effect (UTC). Defaults to now.
    """

    product: Product
    unit_price: Decimal
    currency: str
    effective_from: datetime | None = None


def products_queryset() -> QuerySet[Product]:
    """Return all products ordered by category display order then name."""
    return Product.objects.select_related("category").order_by("category__display_order", "name")


def sellable_products_queryset() -> QuerySet[Product]:
    """Return products that may appear on a sale (spec §13.1)."""
    return products_queryset().filter(is_active=True, category__is_active=True)


def categories_queryset() -> QuerySet[Category]:
    """Return all categories ordered by display order then name."""
    return Category.objects.order_by("display_order", "name")


def active_categories_queryset() -> QuerySet[Category]:
    """Return active categories only."""
    return categories_queryset().filter(is_active=True)


@transaction.atomic
def create_product(
    *,
    category: Category,
    name: str,
    sku: str,
    unit: str = "bottle",
    quantity_mode: str = "WHOLE",
    bottles_per_crate: int | None = None,
    is_stock_tracked: bool = True,
    description: str = "",
    actor: User | None = None,
) -> Product:
    """Create a new product.

    Args:
        category: The category the product belongs to.
        name: The product name (unique within its category).
        sku: Stable internal code, never reused.
        unit: Selling and stocking unit.
        quantity_mode: "WHOLE" or "FRACTIONAL" - whether quantities must be whole.
        bottles_per_crate: How many bottles one crate holds, e.g. 24. ``None``
            when the product is not counted in crates.
        is_stock_tracked: Whether inventory ledger tracks this product.
        description: Free-text description.
        actor: The staff member creating the product (permission
            ``products.manage_products``).

    Returns:
        The created :class:`Product`.

    Raises:
        BarkotDomainError: If the SKU already exists, the name is duplicated
            within the category, or the category is inactive.
    """
    if not category.is_active:
        raise BARKOTDomainError(f"Cannot create product in inactive category {category.name!r}.")

    if Product.objects.filter(sku__iexact=sku).exists():
        raise BARKOTDomainError(f"SKU {sku!r} is already in use.")

    if Product.objects.filter(category=category, name__iexact=name).exists():
        raise BARKOTDomainError(f"Product {name!r} already exists in category {category.name!r}.")

    product = Product.objects.create(
        category=category,
        name=name.strip(),
        sku=sku.strip().upper(),
        unit=unit.strip(),
        quantity_mode=quantity_mode,
        bottles_per_crate=bottles_per_crate,
        is_stock_tracked=is_stock_tracked,
        description=description.strip(),
    )

    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="products.Product",
        object_id=product.pk,
        actor=actor,
        summary=f"Created product {product.sku} ({product.name}) in {category.name}",
    )
    return product


@transaction.atomic
def set_product_price(
    *,
    product: Product,
    unit_price: Decimal,
    currency: str,
    effective_from: datetime | None = None,
    actor: User | None = None,
) -> ProductPrice:
    """Set a new price for a product (spec §13.1).

    A price is never edited once a sale references it. A correction is a new
    row with a later ``effective_from``, which leaves the price the sale
    actually used intact and reconstructable.

    Args:
        product: The product to price.
        unit_price: Price per unit (must be >= 0).
        currency: Currency code (e.g. "ETB").
        effective_from: When this price takes effect (UTC). Defaults to now.
        actor: The staff member setting the price (permission
            ``products.change_prices``).

    Returns:
        The created :class:`ProductPrice`.

    Raises:
        BarkotDomainError: If the price is negative or the currency is invalid.
    """
    if unit_price < 0:
        raise BARKOTDomainError("Price cannot be negative.")

    currency = currency.strip().upper()
    if len(currency) != 3:
        raise BARKOTDomainError(f"Currency {currency!r} must be a 3-letter ISO code.")

    moment = effective_from or now_utc()

    price = ProductPrice.objects.create(
        product=product,
        unit_price=quantize_money(unit_price),
        currency=currency,
        effective_from=moment,
    )

    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="products.ProductPrice",
        object_id=price.pk,
        actor=actor,
        summary=(
            f"Set price for {product.sku}: {price.unit_price} "
            f"{price.currency} from {moment:%Y-%m-%d}"
        ),
    )
    return price


@transaction.atomic
def retire_product(
    *,
    product: Product,
    actor: User | None = None,
) -> Product:
    """Retire (deactivate) a product.

    A retired product cannot be sold but keeps its price and movement history.

    Args:
        product: The product to retire.
        actor: The staff member retiring it (permission ``products.manage_products``).

    Returns:
        The retired :class:`Product`.

    Raises:
        BARKOTDomainError: If the product is already inactive.
    """
    if not product.is_active:
        raise BARKOTDomainError(f"Product {product.sku!r} is already inactive.")

    product.is_active = False
    product.save(update_fields=["is_active", "updated_at"])

    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type="products.Product",
        object_id=product.pk,
        actor=actor,
        summary=f"Retired product {product.sku} ({product.name})",
    )
    return product


@transaction.atomic
def create_category(
    *,
    name: str,
    description: str = "",
    display_order: int = 0,
    is_active: bool = True,
    actor: User | None = None,
) -> Category:
    """Create a new product category.

    Args:
        name: The category name (unique).
        description: Free-text description.
        display_order: Order in pickers and lists.
        is_active: Whether the category is active.
        actor: The staff member creating it (permission ``products.manage_categories``).

    Returns:
        The created :class:`Category`.

    Raises:
        BARKOTDomainError: If a category with this name already exists.
    """
    if Category.objects.filter(name__iexact=name.strip()).exists():
        raise BARKOTDomainError(f"Category {name!r} already exists.")

    category = Category.objects.create(
        name=name.strip(),
        description=description.strip(),
        display_order=display_order,
        is_active=is_active,
    )

    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="products.Category",
        object_id=category.pk,
        actor=actor,
        summary=f"Created category {category.name}",
    )
    return category


@transaction.atomic
def update_product(
    *,
    product: Product,
    actor: User | None = None,
    **changed: Any,
) -> Product:
    """Apply a maintenance edit to a product (PUT/PATCH ``/products/{id}/``).

    This loop used to live in the view, which made product editing the one
    product write with no audit entry beside it (roadmap D1). A body that
    changes nothing still touches ``updated_at`` - matching the admin update
    path's no-op behaviour - but writes no audit row, so the log never claims
    a change that did not happen.

    Args:
        product: The product being edited.
        actor: The staff member editing it (permission ``products.manage_products``).
        **changed: Field name to new value, already validated by
            ``ProductUpdateSerializer``.

    Returns:
        The updated :class:`Product`.
    """
    for field, value in changed.items():
        setattr(product, field, value)
    product.save(update_fields=[*changed, "updated_at"])

    if changed:
        AuditLog.record(
            action=AuditLog.Action.UPDATE,
            object_type="products.Product",
            object_id=product.pk,
            actor=actor,
            summary=f"Updated {', '.join(sorted(changed))} on product {product.sku}",
        )
    return product


@transaction.atomic
def update_category(
    *,
    category: Category,
    actor: User | None = None,
    **changed: Any,
) -> Category:
    """Apply an edit to a product category (PUT/PATCH ``/products/categories/{id}/``).

    The same shape and the same no-op rule as :func:`update_product`: the
    change and its audit entry commit together or not at all.

    Args:
        category: The category being edited.
        actor: The staff member editing it (permission ``products.manage_categories``).
        **changed: Field name to new value, already validated by
            ``CategoryUpdateSerializer``.

    Returns:
        The updated :class:`Category`.
    """
    for field, value in changed.items():
        setattr(category, field, value)
    category.save(update_fields=[*changed, "updated_at"])

    if changed:
        AuditLog.record(
            action=AuditLog.Action.UPDATE,
            object_type="products.Category",
            object_id=category.pk,
            actor=actor,
            summary=f"Updated {', '.join(sorted(changed))} on category {category.name}",
        )
    return category


@transaction.atomic
def delete_category(*, category: Category, actor: User | None = None) -> None:
    """Delete an unreferenced product category (roadmap D1).

    Categories are reference data, so unlike financial records they are really
    deleted rather than voided - but the deletion used to write nothing, which
    is exactly the evidence P06 asks for. The audit row is written after the
    row is gone and keeps the id the table no longer has.

    Args:
        category: The category, checked by the view to have no products.
        actor: The staff member deleting it (permission ``products.manage_categories``).
    """
    name = category.name
    pk = category.pk
    category.delete()

    AuditLog.record(
        action=AuditLog.Action.DELETE,
        object_type="products.Category",
        object_id=pk,
        actor=actor,
        summary=f"Deleted category {name}",
    )


__all__ = [
    "PriceCreateInput",
    "ProductCreateInput",
    "active_categories_queryset",
    "categories_queryset",
    "create_category",
    "create_product",
    "delete_category",
    "products_queryset",
    "retire_product",
    "sellable_products_queryset",
    "set_product_price",
    "update_category",
    "update_product",
]
