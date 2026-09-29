"""Sale and payment write services (spec §13.1, ADR-0003 deviation D4).

A sale is recorded already-completed (CD-01: individual sales, no open rounds),
so :func:`complete_sale` creates the sale, its lines, its payments and the stock
movements it causes, all in one transaction. There is deliberately no
"create then complete" pair of operations, because a half-recorded sale is a
state the cashier must never be able to leave behind.

Stock is drawn down here and only here. :func:`void_sale` reverses it by
*appending* compensating movements, because the ledger is append-only: a voided
sale leaves the original movements in place with the reversal beside them, so an
auditor can see both what happened and why it was undone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Sum

from apps.audit.models import AuditLog
from apps.core.business_time import business_date, now_utc
from apps.core.enums import (
    MovementKind,
    MovementSource,
    PaymentMethod,
    PaymentStatus,
    SaleStatus,
)
from apps.core.exceptions import InconsistentTotals, InsufficientStock, InvalidStateTransition
from apps.core.money import quantize_money, quantize_quantity, sum_money
from apps.inventory.models import StockMovement
from apps.products.models import Product, ProductPrice
from apps.sales.models import Payment, Sale, SaleItem, total_of_sale

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User


@dataclass(frozen=True, slots=True)
class SaleLineInput:
    """One product line on a sale.

    ``unit_price`` may be left as ``None`` to take the current catalogue price.
    Cashiers may also override it (a manager-authorised discount), but the
    override is recorded rather than inferred, and the price row it relates to
    is still stored so the receipt can be traced back to the catalogue.
    """

    product: Product
    quantity: Decimal
    unit_price: Decimal | None = None


def next_sale_reference(*, on: date | None = None) -> str:
    """Return the next receipt reference for a business-local day.

    Format ``S-YYYYMMDD-NNNN``. The counter is derived from the day's existing
    sales rather than a sequence, so a reference is never skipped and the number
    a customer quotes on the phone can be found by date alone.

    Args:
        on: The business-local day. Defaults to today.

    Returns:
        A reference not yet used.
    """
    day = on or business_date(now_utc())
    prefix = f"S-{day:%Y%m%d}-"
    used = Sale.all_rows.filter(reference__startswith=prefix).count()
    return f"{prefix}{used + 1:04d}"


@transaction.atomic
def complete_sale(
    *,
    lines: list[SaleLineInput],
    payments: list[tuple[PaymentMethod, Decimal]],
    actor: User | None = None,
    sold_at: datetime | None = None,
    note: str = "",
) -> Sale:
    """Record a completed individual sale and draw down stock (spec §13.1).

    Args:
        lines: The product lines. Must not be empty.
        payments: ``(method, amount)`` tenders. Must not be empty; their sum
            must equal the sale total.
        actor: The cashier (permission ``sales.create_sale``).
        sold_at: When the sale happened. Defaults to now.
        note: Optional note printed on the receipt.

    Returns:
        The saved :class:`Sale` with items and payments loaded.

    Raises:
        ValueError: If ``lines`` or ``payments`` is empty, a product repeats, a
            quantity is not positive, or a product is unpriceable.
        InvalidStateTransition: If a product is inactive or not sellable.
        InsufficientStock: If a stock-tracked product does not have enough.
            Stock is checked for *every* line before anything is written, so a
            failed sale leaves no partial stock movement behind.
        InconsistentTotals: If the payments do not equal the computed total.
    """
    if not lines:
        raise ValueError("A sale must have at least one line.")
    if not payments:
        raise ValueError("A sale must have at least one payment.")

    moment = sold_at or now_utc()

    # ---- validate everything before writing anything -----------------------
    seen: set[int] = set()
    resolved: list[tuple[SaleLineInput, ProductPrice, Decimal]] = []

    for line in lines:
        product = line.product
        if product.pk in seen:
            raise ValueError(f"Product {product.sku!r} appears twice. Combine the lines instead.")
        seen.add(product.pk)
        if not product.is_active:
            raise InvalidStateTransition(f"Product {product.sku!r} is inactive and cannot be sold.")
        if not product.category.is_active:
            raise InvalidStateTransition(
                f"Category {product.category.name!r} is inactive, so "
                f"{product.sku!r} cannot be sold."
            )

        quantity = quantize_quantity(line.quantity, field="quantity")
        if quantity <= 0:
            raise ValueError(f"Quantity for {product.sku!r} must be greater than zero.")

        price = product.price_at(moment)
        unit_price = (
            price.unit_price
            if line.unit_price is None
            else quantize_money(line.unit_price, field="unit_price")
        )
        if unit_price < 0:
            raise ValueError(f"Unit price for {product.sku!r} cannot be negative.")

        resolved.append((line, price, unit_price))
        if product.is_stock_tracked:
            on_hand = StockMovement.objects.balance_for(product)
            if on_hand < quantity:
                raise InsufficientStock(
                    f"Only {on_hand} of {product.sku!r} in stock, but {quantity} requested."
                )

    subtotal = sum_money(
        quantize_money(unit_price * quantize_quantity(line.quantity, field="quantity"))
        for line, _price, unit_price in resolved
    )

    paid = sum_money(amount for _method, amount in payments)
    if paid != subtotal:
        raise InconsistentTotals(f"Payments total {paid} but the sale totals {subtotal}.")

    for method, amount in payments:
        if not method:
            raise ValueError("Every payment must state a method.")
        if amount <= 0:
            raise ValueError("Every payment amount must be greater than zero.")

    # ---- write ------------------------------------------------------------
    sale = Sale.objects.create(
        reference=next_sale_reference(on=business_date(moment)),
        status=SaleStatus.COMPLETED,
        sold_at=moment,
        subtotal=subtotal,
        total=subtotal,
        amount_paid=paid,
        payment_status=PaymentStatus.PAID,
        note=note,
        created_by=actor,
        updated_by=actor,
    )

    for line, price, unit_price in resolved:
        item = SaleItem.objects.create(
            sale=sale,
            product=line.product,
            quantity=quantize_quantity(line.quantity, field="quantity"),
            unit_price=unit_price,
            price_source=price,
        )
        if line.product.is_stock_tracked:
            StockMovement.record(
                product=line.product,
                kind=MovementKind.SALE,
                source=MovementSource.SALE,
                quantity=item.quantity,
                occurred_at=moment,
                recorded_by=actor,
                sale_item=item,
            )

    for method, amount in payments:
        Payment.objects.create(
            sale=sale,
            method=method,
            amount=quantize_money(amount),
            received_at=moment,
            created_by=actor,
            updated_by=actor,
        )

    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="sales.Sale",
        object_id=sale.pk,
        actor=actor,
        summary=f"Sale {sale.reference} for {subtotal}",
    )
    return sale


@transaction.atomic
def void_sale(*, sale: Sale, reason: str, actor: User | None = None) -> Sale:
    """Void a sale and return its stock to the ledger (spec §13.1, §20.2).

    The sale row is retained with a reason; its payments are voided; and
    compensating ``SALE_VOID`` movements are appended for every line that drew stock
    down. Nothing is deleted, so both the sale and its reversal stay visible.

    Args:
        sale: The sale to void.
        reason: Why. Required.
        actor: The user voiding (permission ``sales.void_sale``).

    Returns:
        The voided :class:`Sale`.

    Raises:
        InvalidStateTransition: If the sale is already voided.
        ValueError: If ``reason`` is blank.
    """
    if sale.is_voided:
        raise InvalidStateTransition(f"Sale {sale.reference} is already voided.")
    if not reason.strip():
        raise ValueError("A void reason is required.")

    for payment in sale.payments.filter(voided_at__isnull=True):
        payment.void(reason=reason, actor=actor)
        payment.save(
            update_fields=["voided_at", "voided_by", "void_reason", "status", "updated_at"]
        )

    for item in sale.items.all():
        if not item.product.is_stock_tracked:
            continue
        # SALE_VOID, not SALE: the ledger derives direction from the kind, and
        # SALE is pinned to OUT. Recording the reversal as SALE would draw the
        # stock down a second time.
        StockMovement.record(
            product=item.product,
            kind=MovementKind.SALE_VOID,
            source=MovementSource.SALE,
            quantity=item.quantity,
            occurred_at=now_utc(),
            reason=f"Void of sale {sale.reference}: {reason.strip()}",
            recorded_by=actor,
            sale_item=item,
        )

    sale.void(reason=reason, actor=actor)
    sale.save(
        update_fields=[
            "status",
            "payment_status",
            "voided_at",
            "voided_by",
            "void_reason",
            "updated_at",
            "updated_by",
        ]
    )

    AuditLog.record(
        action=AuditLog.Action.VOID,
        object_type="sales.Sale",
        object_id=sale.pk,
        actor=actor,
        summary=f"Voided sale {sale.reference}: {reason.strip()}",
        before={"reference": sale.reference, "total": str(total_of_sale(sale))},
    )
    return sale


def sales_totals(*, start: datetime, end: datetime) -> dict[PaymentMethod | str, Decimal]:
    """Return income by payment method over a UTC instant range (spec §13.1).

    Voided sales and voided payments are excluded, so this is the figure a
    manager reconciles cash against.

    Args:
        start: Inclusive UTC start.
        end: Exclusive UTC end.

    Returns:
        ``{method: total}`` for every method present, plus ``"TOTAL"``.
    """
    rows = (
        Payment.objects.filter(
            sale__sold_at__gte=start,
            sale__sold_at__lt=end,
            voided_at__isnull=True,
            sale__voided_at__isnull=True,
        )
        .values("method")
        .annotate(total=Sum("amount"))
        .order_by("method")
    )
    result: dict[PaymentMethod | str, Decimal] = {}
    for row in rows:
        result[row["method"]] = quantize_money(row["total"] or Decimal("0"))
    result["TOTAL"] = sum_money(result.values())
    return result


__all__ = [
    "SaleLineInput",
    "complete_sale",
    "next_sale_reference",
    "sales_totals",
    "void_sale",
]
