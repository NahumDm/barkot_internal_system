"""Inventory write services (spec §12).

Every function here that changes stock does the same three things, in this order,
inside one transaction:

1. checks the business preconditions and raises a
   :class:`apps.core.exceptions.BarkotDomainError` if they fail;
2. writes the human-readable document (receipt, breakage, count) that explains
   *why* stock changed;
3. appends the corresponding :class:`~apps.inventory.models.StockMovement` rows.

The ledger is written last and only ever appended. A document without its
movements would leave stock wrong; movements without their document would be
unattributable, which the database constraint on :class:`StockMovement` forbids.
Doing both in one ``atomic`` block is what makes the pair all-or-nothing.

Viewsets and serializers call these. Nothing else should write
:class:`StockMovement` directly.
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
from apps.core.enums import (
    MovementDirection,
    MovementKind,
    MovementSource,
    StockCountStatus,
)
from apps.core.exceptions import (
    IdempotencyInFlight,
    InsufficientStock,
    InvalidStateTransition,
)
from apps.core.idempotency import claim_key, replayed_object
from apps.core.money import quantize_money, quantize_quantity, validate_whole_quantity
from apps.inventory.models import (
    BreakageItem,
    BreakageRecord,
    StockCount,
    StockCountItem,
    StockMovement,
    StockReceipt,
    StockReceiptItem,
)
from apps.products.models import Product

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User


RECEIPT_SCOPE = "inventory.receive_stock"


def _receipt_fingerprint_body(
    lines: list[ReceiptLineInput],
    supplier_name: str,
    received_at: datetime | None,
    reference: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "supplier_name": supplier_name,
        "received_at": received_at.isoformat() if received_at else None,
        "reference": reference,
        "notes": notes,
        "lines": [
            {
                "product": line.product.pk,
                "quantity": str(line.quantity),
                "unit_cost": str(line.unit_cost),
                "lot_reference": line.lot_reference,
            }
            for line in lines
        ],
    }


@dataclass(frozen=True, slots=True)
class GroupedReceiptLineInput:
    product: Product
    crates: Decimal
    crate_cost: Decimal | None = None
    unit_cost: Decimal | None = None
    lot_reference: str = ""
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ReceiptLineInput:
    """One product line to receive.

    Attributes:
        product: The product being received.
        quantity: How many units arrived.
        unit_cost: What was paid per unit, for stock valuation.
        lot_reference: Supplier lot or batch code, if any.
        notes: Free-text line note.
    """

    product: Product
    quantity: Decimal
    unit_cost: Decimal
    lot_reference: str = ""
    notes: str = ""


def current_stock(product: Product) -> Decimal:
    """Return the ledger-derived stock of ``product`` (spec §12).

    This is the authoritative stock figure. An unapproved stock count reserves
    nothing, so this number is also what a sale may draw down: a count that has
    not been approved has deliberately not changed stock yet.
    """
    return StockMovement.objects.balance_for(product)


@transaction.atomic
def receive_stock(
    *,
    supplier_name: str,
    lines: list[ReceiptLineInput],
    actor: User | None = None,
    received_at: datetime | None = None,
    reference: str = "",
    notes: str = "",
    idempotency_key: str | None = None,
) -> StockReceipt:
    """Record a supplier delivery and add the stock to the ledger.

    Args:
        supplier_name: Who delivered. Required.
        lines: The product lines. Must not be empty.
        actor: The staff member receiving (permission ``inventory.receive_stock``).
        received_at: When the delivery arrived. Defaults to now.
        reference: The supplier's delivery note number, if any.
        notes: Header note.

    Returns:
        The completed :class:`StockReceipt`.

    Raises:
        ValueError: If ``lines`` is empty, repeats a product, or has a
            non-positive quantity.
        InvalidStateTransition: If a line names a product that is not stock
            tracked or is inactive.
    """
    if not lines:
        raise ValueError("A stock receipt must have at least one line.")

    claim = claim_key(
        scope=RECEIPT_SCOPE,
        key=idempotency_key,
        body=_receipt_fingerprint_body(
            lines=lines,
            supplier_name=supplier_name,
            received_at=received_at,
            reference=reference,
            notes=notes,
        ),
    )
    if claim.replayed:
        existing = replayed_object(claim, StockReceipt)
        if existing is not None:
            return existing
        raise IdempotencyInFlight(
            f"Idempotency key {idempotency_key!r} refers to a receipt that no longer exists."
        )

    seen: set[int] = set()
    for line in lines:
        if line.product.pk in seen:
            raise ValueError(
                f"Product {line.product.sku!r} appears twice. Combine the lines instead."
            )
        seen.add(line.product.pk)
        if not line.product.is_stock_tracked:
            raise InvalidStateTransition(
                f"Product {line.product.sku!r} is not stock tracked and cannot be received."
            )
        if not line.product.is_active:
            raise InvalidStateTransition(
                f"Product {line.product.sku!r} is inactive and cannot be received."
            )
        if line.quantity <= 0:
            raise ValueError(f"Quantity for {line.product.sku!r} must be greater than zero.")
        validate_whole_quantity(line.quantity, product=line.product)

    moment = received_at or now_utc()
    receipt = StockReceipt.objects.create(
        supplier_name=supplier_name,
        reference=reference,
        received_at=moment,
        notes=notes,
        created_by=actor,
        updated_by=actor,
    )

    for line in lines:
        item = StockReceiptItem.objects.create(
            receipt=receipt,
            product=line.product,
            quantity=quantize_quantity(line.quantity, field="quantity"),
            unit_cost=line.unit_cost,
            lot_reference=line.lot_reference,
            notes=line.notes,
        )
        StockMovement.record(
            product=line.product,
            kind=MovementKind.RECEIPT,
            source=MovementSource.STOCK_RECEIPT,
            quantity=item.quantity,
            occurred_at=moment,
            unit_cost=item.unit_cost,
            recorded_by=actor,
            stock_receipt_item=item,
        )

    receipt.complete(actor=actor)
    receipt.save(update_fields=["status", "completed_at", "updated_at", "updated_by"])

    claim.produced(receipt)

    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="inventory.StockReceipt",
        object_id=receipt.pk,
        actor=actor,
        summary=f"Received {len(lines)} line(s) from {supplier_name}",
    )
    return receipt


@transaction.atomic
def receive_grouped_stock(
    *,
    supplier_name: str,
    selling_price: Decimal,
    lines: list[GroupedReceiptLineInput],
    actor: User | None = None,
    received_at: datetime | None = None,
    reference: str = "",
    notes: str = "",
    idempotency_key: str | None = None,
) -> StockReceipt:
    """Receive multiple products sharing a selling-price group in a single transaction.

    Authoritatively validates each product's current selling price against
    ``selling_price``, calculates authoritative bottle quantities and per-bottle
    costs using each product's configured ``bottles_per_crate``, and atomically
    creates individual receipt lines and stock movements.
    """
    if not lines:
        raise ValueError("A grouped stock receipt must have at least one line.")

    receipt_lines: list[ReceiptLineInput] = []
    seen: set[int] = set()

    for line in lines:
        product = line.product
        if product.pk in seen:
            raise ValueError(f"Product {product.sku!r} appears twice. Combine the lines instead.")
        seen.add(product.pk)

        if not product.is_stock_tracked:
            raise InvalidStateTransition(
                f"Product {product.sku!r} is not stock tracked and cannot be received."
            )
        if not product.is_active:
            raise InvalidStateTransition(
                f"Product {product.sku!r} is inactive and cannot be received."
            )
        if not product.is_crated:
            raise ValueError(
                f"Product {product.sku!r} has no bottles-per-crate conversion configured "
                "and cannot be received in a grouped receipt."
            )
        if line.crates <= 0:
            raise ValueError(f"Crate quantity for {product.sku!r} must be greater than zero.")

        # Authoritative backend validation of selling price group
        current_price = product.current_price()
        if current_price is None:
            raise ValueError(f"Product {product.sku!r} has no active selling price configured.")
        if current_price.unit_price != selling_price:
            raise ValueError(
                f"Product {product.sku!r} selling price ({current_price.unit_price} ETB) "
                f"does not match the selected price group ({selling_price} ETB)."
            )

        # Authoritative bottle conversion factor strictly from backend model
        if product.is_crated and product.bottles_per_crate:
            conversion_factor = Decimal(product.bottles_per_crate)
            bottle_quantity = quantize_quantity(line.crates * conversion_factor, field="quantity")
            if line.crate_cost is not None:
                if line.crate_cost < 0:
                    raise ValueError(f"Crate cost for {product.sku!r} cannot be negative.")
                unit_cost = quantize_money(line.crate_cost / conversion_factor, field="unit_cost")
            elif line.unit_cost is not None:
                if line.unit_cost < 0:
                    raise ValueError(f"Unit cost for {product.sku!r} cannot be negative.")
                unit_cost = quantize_money(line.unit_cost, field="unit_cost")
            else:
                raise ValueError(f"A crate cost or unit cost must be provided for {product.sku!r}.")
            crate_note = f"{line.crates} crate(s) ({product.bottles_per_crate} btl/crate)"
        else:
            conversion_factor = Decimal(1)
            bottle_quantity = quantize_quantity(line.crates, field="quantity")
            if line.crate_cost is not None:
                unit_cost = quantize_money(line.crate_cost, field="unit_cost")
            elif line.unit_cost is not None:
                unit_cost = quantize_money(line.unit_cost, field="unit_cost")
            else:
                raise ValueError(f"A cost must be provided for {product.sku!r}.")
            crate_note = f"{line.crates} unit(s)"

        line_notes = f"Grouped line: {crate_note}. {line.notes}".strip()
        receipt_lines.append(
            ReceiptLineInput(
                product=product,
                quantity=bottle_quantity,
                unit_cost=unit_cost,
                lot_reference=line.lot_reference,
                notes=line_notes,
            )
        )

    receipt_note = f"Grouped receipt (Selling price group: {selling_price} ETB). {notes}".strip()

    return receive_stock(
        supplier_name=supplier_name,
        lines=receipt_lines,
        actor=actor,
        received_at=received_at,
        reference=reference,
        notes=receipt_note,
        idempotency_key=idempotency_key,
    )


@transaction.atomic
def record_breakage(
    *,
    reason: str,
    lines: list[tuple[Product, Decimal]],
    actor: User | None = None,
    occurred_at: datetime | None = None,
    reference: str = "",
    notes: str = "",
) -> BreakageRecord:
    """Write off broken, spilled or expired stock (spec §12.1).

    Breakage is kept separate from a manual ``STOCK_OUT`` because it is a normal,
    frequent event with no commercial value attached, while a stock-out is a
    deliberate removal someone may need to justify. Collapsing them would make
    the "why did we lose this stock" report meaningless.

    Args:
        reason: Why the stock was lost. Required.
        lines: ``(product, quantity)`` pairs.
        actor: The staff member recording it (permission
            ``inventory.record_breakage``).
        occurred_at: When it happened. Defaults to now.
        reference: Free-text reference.
        notes: Header note.

    Returns:
        The created :class:`BreakageRecord`.

    Raises:
        ValueError: If ``lines`` is empty, repeats a product, has a non-positive
            quantity, or ``reason`` is blank.
        InsufficientStock: If a line would drive stock below zero. Breakage is a
            write-off, so it must still be covered by stock that exists —
            otherwise a typo silently creates stock.
    """
    if not lines:
        raise ValueError("A breakage record must have at least one line.")
    if not reason.strip():
        raise ValueError("A breakage reason is required.")

    moment = occurred_at or now_utc()
    balances: dict[int, Decimal] = {}
    seen: set[int] = set()
    for product, quantity in lines:
        if product.pk in seen:
            raise ValueError(f"Product {product.sku!r} appears twice on this breakage record.")
        seen.add(product.pk)
        quantised = quantize_quantity(quantity, field="quantity")
        validate_whole_quantity(quantised, product=product)
        if quantised <= 0:
            raise ValueError(f"Quantity for {product.sku!r} must be greater than zero.")
        balance = balances.get(product.pk, None)
        if balance is None:
            balance = current_stock(product)
        remaining = balance - quantised
        if remaining < 0:
            raise InsufficientStock(
                f"Cannot write off {quantised} of {product.sku!r}: only {balance} in stock."
            )
        balances[product.pk] = remaining

    record = BreakageRecord.objects.create(
        reason=reason.strip(),
        reference=reference,
        occurred_at=moment,
        notes=notes,
        created_by=actor,
        updated_by=actor,
    )

    for product, quantity in lines:
        item = BreakageItem.objects.create(
            record=record,
            product=product,
            quantity=quantize_quantity(quantity, field="quantity"),
        )
        StockMovement.record(
            product=product,
            kind=MovementKind.BREAKAGE,
            source=MovementSource.BREAKAGE,
            quantity=item.quantity,
            occurred_at=moment,
            recorded_by=actor,
            breakage_item=item,
        )

    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="inventory.BreakageRecord",
        object_id=record.pk,
        actor=actor,
        summary=f"Recorded breakage: {reason.strip()}",
    )
    return record


@transaction.atomic
def open_stock_count(
    *,
    lines: list[Product],
    actor: User | None = None,
    counted_at: datetime | None = None,
    reference: str = "",
    notes: str = "",
) -> StockCount:
    """Start a count, snapshotting expected quantities for each product.

    ``expected_quantity`` is captured *now* so that stock sold while the count is
    in progress is not silently absorbed into the variance.

    Args:
        lines: The products being counted.
        actor: The staff member counting (permission
            ``inventory.complete_stock_count``).
        counted_at: When the count was taken. Defaults to now.
        reference: Free-text reference.
        notes: Header note.

    Returns:
        The created :class:`StockCount` in ``DRAFT``.

    Raises:
        ValueError: If ``lines`` is empty or repeats a product.
    """
    if not lines:
        raise ValueError("A stock count must cover at least one product.")

    seen: set[int] = set()
    for product in lines:
        if product.pk in seen:
            raise ValueError(f"Product {product.sku!r} appears twice on this count.")
        seen.add(product.pk)

    count = StockCount.objects.create(
        reference=reference,
        counted_at=counted_at or now_utc(),
        notes=notes,
        created_by=actor,
        updated_by=actor,
    )
    for product in lines:
        StockCountItem.objects.create(
            stock_count=count,
            product=product,
            expected_quantity=current_stock(product),
            # Placeholders: nothing has been counted yet. `variance` is NOT NULL
            # with no default, so it must be written explicitly here and is
            # recomputed by complete_stock_count().
            counted_quantity=Decimal("0.000"),
            variance=Decimal("0.000"),
        )

    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="inventory.StockCount",
        object_id=count.pk,
        actor=actor,
        summary=f"Opened stock count covering {len(lines)} product(s)",
    )
    return count


@transaction.atomic
def complete_stock_count(
    *,
    stock_count: StockCount,
    counted_quantities: dict[int, Decimal],
    actor: User | None = None,
    note: str = "",
) -> StockCount:
    """Record what was physically counted and compute variances.

    This does **not** change stock. Approval does, so a count can be re-checked
    before it alters the ledger.

    Args:
        stock_count: The count to complete.
        counted_quantities: ``{stock_count_item_id: counted_quantity}``. Must
            cover the count's items exactly.
        actor: The staff member completing it.
        note: Optional note stored on each line.

    Returns:
        The updated :class:`StockCount` in ``COMPLETED``.

    Raises:
        InvalidStateTransition: If the count is not ``DRAFT``, or if the
            supplied ids do not match the count's items exactly. A partial id
            set is a client bug that must not silently count fewer products than
            the cashier actually did.
        ValueError: If a counted quantity is negative.
    """
    if stock_count.status != StockCountStatus.DRAFT:
        raise InvalidStateTransition(
            f"Stock count {stock_count.pk} is {stock_count.get_status_display()} "
            "and can no longer be completed."
        )

    items = {item.pk: item for item in stock_count.items.all()}
    if set(counted_quantities) != set(items):
        unknown = sorted(set(counted_quantities) - set(items))
        missing = sorted(set(items) - set(counted_quantities))
        raise InvalidStateTransition(
            "The counted quantities must match the count's items exactly. "
            f"Unknown ids: {unknown}. Missing ids: {missing}."
        )

    for item_id, raw in counted_quantities.items():
        item = items[item_id]
        counted = quantize_quantity(raw, field="counted_quantity")
        validate_whole_quantity(counted, product=item.product, field="counted_quantity")
        if counted < 0:
            raise ValueError(f"Counted quantity for {item.product.sku!r} cannot be negative.")
        item.counted_quantity = counted
        item.compute_variance()
        if note:
            item.note = note
        item.save(update_fields=["counted_quantity", "variance", "note", "updated_at"])

    stock_count.status = StockCountStatus.COMPLETED
    stock_count.completed_at = now_utc()
    stock_count.updated_by = actor
    stock_count.save(update_fields=["status", "completed_at", "updated_at", "updated_by"])

    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type="inventory.StockCount",
        object_id=stock_count.pk,
        actor=actor,
        summary="Completed stock count",
    )
    return stock_count


@transaction.atomic
def approve_stock_count(
    *,
    stock_count: StockCount,
    actor: User | None = None,
) -> StockCount:
    """Write a completed count's variances to the ledger (spec §12.3).

    A Manager or Owner with ``inventory.approve_adjustment`` may do this. A count
    with no variance produces no movements at all, which is the correct outcome —
    an empty ledger is not a record of "everything matched".

    Args:
        stock_count: The count to approve.
        actor: The approving user.

    Returns:
        The approved :class:`StockCount`.

    Raises:
        InvalidStateTransition: If the count is not ``COMPLETED``, or was
            already approved. Approving twice would write every variance twice.
    """
    if stock_count.is_approved:
        raise InvalidStateTransition(f"Stock count {stock_count.pk} is already approved.")
    if stock_count.status != StockCountStatus.COMPLETED:
        raise InvalidStateTransition(
            f"Stock count {stock_count.pk} must be completed before approval."
        )

    variance_items = [item for item in stock_count.items.all() if item.has_variance]

    for item in variance_items:
        # The ledger stores a positive quantity; the direction carries the sign.
        direction = MovementDirection.IN if item.variance > 0 else MovementDirection.OUT
        StockMovement.record(
            product=item.product,
            kind=MovementKind.COUNT_VARIANCE,
            direction=direction,
            source=MovementSource.STOCK_COUNT,
            quantity=abs(item.variance),
            occurred_at=stock_count.counted_at,
            reason=(
                f"Stock count #{stock_count.pk}: expected {item.expected_quantity}, "
                f"counted {item.counted_quantity}"
            ),
            recorded_by=actor,
            stock_count_item=item,
        )

    stock_count.status = StockCountStatus.APPROVED
    stock_count.approved_at = now_utc()
    stock_count.approved_by = actor
    stock_count.updated_by = actor
    stock_count.save(
        update_fields=["status", "approved_at", "approved_by", "updated_at", "updated_by"]
    )

    AuditLog.record(
        action=AuditLog.Action.APPROVE,
        object_type="inventory.StockCount",
        object_id=stock_count.pk,
        actor=actor,
        summary=f"Approved stock count with {len(variance_items)} variance(s)",
    )
    return stock_count


@transaction.atomic
def manual_stock_adjustment(
    *,
    product: Product,
    kind: str,
    quantity: Decimal,
    reason: str,
    actor: User | None = None,
    occurred_at: datetime | None = None,
) -> StockMovement:
    """Append a manual stock in/out with a mandatory reason (spec §12.2).

    Args:
        product: The product to adjust.
        kind: ``MovementKind.STOCK_IN`` or ``MovementKind.STOCK_OUT``.
        quantity: Positive amount.
        reason: Why. Required — a manual movement without one is unattributable.
        actor: The staff member adjusting.
        occurred_at: When. Defaults to now.

    Returns:
        The created :class:`StockMovement`.

    Raises:
        ValueError: If ``kind`` is not a manual kind, ``reason`` is blank, or
            the quantity is not positive.
        InsufficientStock: If a stock-out would go below zero.
    """
    if kind not in {MovementKind.STOCK_IN, MovementKind.STOCK_OUT}:
        raise ValueError(f"{kind!r} is not a manual adjustment kind.")
    if not reason.strip():
        raise ValueError("A manual stock adjustment must give a reason.")

    quantised = quantize_quantity(quantity, field="quantity")
    if quantised <= 0:
        raise ValueError("Quantity must be greater than zero.")
    validate_whole_quantity(quantised, product=product)
    if kind == MovementKind.STOCK_OUT and current_stock(product) < quantised:
        raise InsufficientStock(
            f"Cannot remove {quantised} of {product.sku!r}: only {current_stock(product)} in stock."
        )

    movement = StockMovement.record(
        product=product,
        kind=kind,
        source=MovementSource.MANUAL,
        quantity=quantised,
        occurred_at=occurred_at or now_utc(),
        reason=reason.strip(),
        recorded_by=actor,
    )
    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type="inventory.StockMovement",
        object_id=movement.pk,
        actor=actor,
        summary=f"Manual {kind} of {quantised} {product.sku}",
    )
    return movement


def movements_queryset(product: Product | None = None) -> QuerySet[StockMovement]:
    """Return ledger rows, newest first, optionally for one product."""
    queryset = StockMovement.objects.select_related("product").all()
    if product is not None:
        queryset = queryset.filter(product=product)
    return queryset


__all__ = [
    "ReceiptLineInput",
    "approve_stock_count",
    "complete_stock_count",
    "current_stock",
    "manual_stock_adjustment",
    "movements_queryset",
    "open_stock_count",
    "receive_stock",
    "record_breakage",
]
