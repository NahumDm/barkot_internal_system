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

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import connection, transaction
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
from apps.core.exceptions import (
    IdempotencyInFlight,
    InconsistentTotals,
    InsufficientStock,
    InvalidStateTransition,
    ProductNotPriced,
)
from apps.core.idempotency import SALE_SCOPE, claim_key, replayed_object
from apps.core.money import quantize_money, quantize_quantity, sum_money, validate_whole_quantity
from apps.inventory.models import StockMovement
from apps.products.models import Product, ProductPrice
from apps.sales.models import Payment, Sale, SaleItem, total_of_sale

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User


@dataclass(frozen=True, slots=True)
class SaleLineInput:
    """One product line on a sale.

    ``unit_price`` may be left as ``None`` to take the catalogue price at the
    sale moment. A caller holding ``products.change_prices`` may override it;
    the override is recorded on the line and the catalogue price row is still
    stored so the receipt remains traceable. The API enforces that permission
    before the service is called, and the service itself still refuses an
    override that is negative.
    """

    product: Product
    quantity: Decimal
    unit_price: Decimal | None = None


def advisory_lock_key(prefix: str) -> int:
    """Return the 64-bit advisory-lock key for a reference prefix.

    Hashing the prefix rather than passing the date's ordinal keeps the key stable if
    the reference format ever changes, and keeps it away from the small integers where
    another subsystem's hand-picked key is most likely to collide. Signed, because
    ``bigint`` is what ``pg_advisory_xact_lock`` takes.

    Args:
        prefix: The reference prefix, e.g. ``"S-20260929-"``.

    Returns:
        A 64-bit key derived from the prefix.
    """
    digest = hashlib.sha256(prefix.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=True)


def next_sale_reference(*, on: date | None = None) -> str:
    """Return the next receipt reference for a business-local day.

    Format ``S-YYYYMMDD-NNNN``. The counter is derived from the day's existing
    sales rather than a sequence, so a reference is never skipped and the number
    a customer quotes on the phone can be found by date alone.

    Deriving from a ``COUNT()`` is what makes the no-skipped-numbers promise
    possible, and it is also what made this racy. Two concurrent sales both read
    "3 used" and both return ``S-20260929-0004``; the ``unique`` constraint on
    :attr:`~apps.sales.models.Sale.reference` then lets exactly one commit and
    turns the other into an ``IntegrityError`` - a 500 for a cashier who did nothing
    wrong, and a number burned on a sale that never landed.

    So the count is taken under a lock that serialises allocation for the day, and
    the uniqueness of the row stays the final authority. The lock is what makes the
    count trustworthy; the constraint is what makes the guarantee true even if this
    is bypassed.

    **Why an advisory lock and not a counter table.** A daily counter row is the
    more familiar pattern. It also needs the row to exist before the first sale of
    the day, which turns "create the row" into a race of its own and needs the same
    retry logic this function now has, in a second place. Deriving the number from
    the sales that already exist keeps the single source of truth in the sales table,
    which is also what lets a reference be recovered from the sales alone after a
    restore or an audit.

    **The lock is released at commit, not at return.** It is transaction-scoped, so a
    caller that allocates and then fails rolls the whole thing back and leaves no gap.
    That is the behaviour the original docstring promised, and it only holds because
    the lock lives inside the caller's transaction.

    ``pg_advisory_xact_lock`` is PostgreSQL-specific. The project is PostgreSQL-only
    by decision (spec P02; every settings branch refuses SQLite), so a portable
    fallback would be an untested second path rather than insurance.

    Args:
        on: The business-local day. Defaults to today.

    Returns:
        A reference not yet used by any sale, voided ones included: a voided sale
        keeps its number, because the receipt was already printed.
    """
    day = on or business_date(now_utc())
    prefix = f"S-{day:%Y%m%d}-"

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", (advisory_lock_key(prefix),))
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
    idempotency_key: str | None = None,
) -> Sale:
    """Record a completed individual sale and draw down stock (spec §13.1).

    Args:
        lines: The product lines. Must not be empty.
        payments: ``(method, amount)`` tenders. Must not be empty; their sum
            must equal the sale total.
        actor: The cashier (permission ``sales.create_sale``).
        sold_at: When the sale happened. Defaults to now.
        note: Optional note printed on the receipt.
        idempotency_key: Client-supplied key making the call safe to retry (spec
            §10.2). A repeat with the same key returns the first sale instead of
            creating a second one. ``None`` performs no de-duplication, which is
            correct for a caller that has no retry story - a management command
            running once does not need it, and refusing to record a sale because
            no key was supplied would be worse than the duplicate it prevents.

    Returns:
        The saved :class:`Sale` with items and payments loaded, or on an idempotent
        replay the sale the first call created.

    Raises:
        ValueError: If ``lines`` or ``payments`` is empty, a product repeats, a
            quantity is not positive, or a product is unpriceable.
        InvalidStateTransition: If a product is inactive or not sellable.
        InsufficientStock: If a stock-tracked product does not have enough.
            Stock is checked for *every* line before anything is written, so a
            failed sale leaves no partial stock movement behind.
        InconsistentTotals: If the payments do not equal the computed total.
        IdempotencyKeyReuse: If the key was already used for a different sale.
        IdempotencyInFlight: If an identical sale is still being recorded under
            the same key.
    """
    if not lines:
        raise ValueError("A sale must have at least one line.")
    if not payments:
        raise ValueError("A sale must have at least one payment.")

    moment = sold_at or now_utc()

    claim = claim_key(
        scope=SALE_SCOPE,
        key=idempotency_key,
        # Fingerprints the caller's ``sold_at``, not ``moment``. Hashing the resolved
        # value would make every retry that omitted it a *different* request, because
        # ``now_utc()`` returns a different instant each time - the double-click this
        # mechanism exists to absorb would come back as a key-reuse error.
        body=_sale_fingerprint_body(lines=lines, payments=payments, sold_at=sold_at, note=note),
    )
    if claim.replayed:
        existing = replayed_object(claim, Sale)
        if existing is not None:
            return existing
        # The claim points at a sale that no longer exists. Continuing would create a
        # sale nobody asked for, so the key stays spent and the caller is told why.
        raise IdempotencyInFlight(
            f"Idempotency key {idempotency_key!r} refers to a sale that no longer "
            f"exists. Record the sale under a new key."
        )

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
        validate_whole_quantity(quantity, product=product)
        if quantity <= 0:
            raise ValueError(f"Quantity for {product.sku!r} must be greater than zero.")

        try:
            price = product.price_at(moment)
        except ProductPrice.DoesNotExist as exc:
            raise ProductNotPriced(str(exc)) from exc
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
    # Inside the same transaction as the sale, so the claim and the thing it claims
    # to describe can never disagree.
    claim.produced(sale)
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


def _sale_fingerprint_body(
    *,
    lines: list[SaleLineInput],
    payments: list[tuple[PaymentMethod, Decimal]],
    sold_at: datetime | None,
    note: str,
) -> dict[str, object]:
    """Return the request body an idempotency key is fingerprinted over.

    Deliberately *not* the resolved arguments. The fields that decide what gets
    written are the lines and the payments; ``sold_at`` and ``note`` are included
    because a retry that omitted them would produce a different receipt. The actor
    is excluded, because a retry arriving after a re-authentication is still the
    same sale, and a cashier's own pk changing would refuse an honest retry.

    Two choices here are load-bearing.

    ``sold_at`` is hashed as the caller passed it, ``None`` included, and *not* as
    the ``moment`` the sale ends up with. Otherwise a client that never sends
    ``sold_at`` - the normal case - fingerprints a fresh timestamp on every attempt
    and can never replay its own first attempt.

    Amounts are handed over as ``Decimal`` objects rather than strings, because
    :func:`~apps.core.idempotency.canonical` normalises ``Decimal("2")`` and
    ``Decimal("2.00")`` to the same thing. Stringifying them here first would
    defeat that, and a POS that sends ``2.00`` on one attempt and ``2`` on the next
    would be told its own retry was a different sale (§10.3 - never compare money as
    float).
    """
    return {
        "lines": [
            {
                "sku": line.product.sku,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
            }
            for line in lines
        ],
        "payments": [[method, amount] for method, amount in payments],
        "sold_at": sold_at,
        "note": note,
    }


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
    "advisory_lock_key",
    "complete_sale",
    "next_sale_reference",
    "sales_totals",
    "void_sale",
]
