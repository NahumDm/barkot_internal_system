"""Bono configuration, custody and reconciliation services.

The rules that live here rather than in a view are the ones a second caller
would otherwise get wrong:

- configuration changes must freeze snapshots, not rewrite history;
- a price change under an active pairing opens an Owner review;
- token movements lock the operational day row before reading a balance, so two
  concurrent transfers cannot overdraw the same custody;
- a transfer only moves custody, it never becomes a fresh business-wide issue;
- a lost token never becomes a sale, breakage movement or payroll deduction by
  itself;
- a broken bottle uses the existing inventory breakage service exactly once;
- a submitted/approved report is locked, and an approved report is corrected by
  a new auditable revision rather than edited in place.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Q, Sum

from apps.audit.models import AuditLog
from apps.bono.models import (
    BonoDay,
    BonoDayStatus,
    BonoIncident,
    BonoIncidentKind,
    BonoIncidentResolution,
    BonoIssue,
    BonoIssueKind,
    BonoProductPairing,
    BonoReport,
    BonoReportLine,
    BonoReportProductLine,
    BonoReportStatus,
    BonoTransfer,
    BonoType,
)
from apps.core.business_time import (
    business_date,
    business_day_bounds,
    now_utc,
)
from apps.core.enums import MovementKind, PaymentMethod, PaymentStatus, SaleStatus
from apps.core.exceptions import (
    BARKOTDomainError,
    BonoActivityInProgress,
    BonoAllocationExceeded,
    BonoPriceMismatch,
    BonoReportIncomplete,
    BonoReportLocked,
    BonoReportStale,
    BonoReviewPending,
    BonoTypeConflict,
)
from apps.core.money import CURRENCY, quantize_money, quantize_quantity
from apps.inventory.models import StockMovement
from apps.inventory.services import record_breakage
from apps.payroll.models import PayrollDeduction, PayrollItem
from apps.payroll.services import add_deduction
from apps.products.models import Product
from apps.sales.models import Payment, Sale, SaleItem
from apps.users.models import EmployeeProfile

#: A Bono is one bottle. Anything else would make the token count ambiguous.
_BOTTLE_UNITS = {"bottle", "bottles", "btl"}

#: Presentation colour accepted by both the model validator and this service.
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

#: The visible labels and colour a pairing/report snapshot preserves.
_BONO_SNAPSHOT_FIELDS = (
    "bono_code_snapshot",
    "bono_name_snapshot",
    "bono_color_snapshot",
    "bono_price_snapshot",
    "currency",
)


# ── Configuration ───────────────────────────────────────────────────────────


def _business_today() -> date:
    return business_date(now_utc())


def _normalise_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise BonoTypeConflict("A Bono type needs a name.")
    return value


def _normalise_color(color: str) -> str:
    value = color.strip().upper()
    if not value.startswith("#"):
        value = f"#{value}"
    if not _HEX_COLOR.fullmatch(value):
        raise BonoTypeConflict("A Bono colour must be a six-digit hexadecimal value.")
    return value


def _normalise_currency(currency: str) -> str:
    value = currency.strip().upper()
    if value != CURRENCY:
        raise BARKOTDomainError(f"Bono is recorded in {CURRENCY} in this version.")
    return value


def _open_activity_dates() -> list[date]:
    """Dates with Bono activity but no approved report covering that activity."""
    approved = set(
        BonoReport.objects.filter(status=BonoReportStatus.APPROVED).values_list(
            "operational_date", flat=True
        )
    )
    dates: set[date] = set(BonoIssue.objects.values_list("operational_date", flat=True))
    dates.update(BonoTransfer.objects.values_list("operational_date", flat=True))
    dates.update(BonoIncident.objects.values_list("operational_date", flat=True))
    dates.update(
        BonoReport.objects.filter(
            status__in=[BonoReportStatus.DRAFT, BonoReportStatus.SUBMITTED]
        ).values_list("operational_date", flat=True)
    )
    return sorted(d for d in dates if d not in approved)


def _guard_in_progress(*, confirm_in_progress: bool, reason: str, operation: str) -> list[date]:
    """Refuse a configuration change that silently touches an open day.

    The caller may confirm explicitly with a written reason. Every transactional
    row already carries its own label/colour/price snapshot, so the confirmation
    is what makes the change auditable rather than a way to rewrite history.
    """
    dates = _open_activity_dates()
    if dates and not confirm_in_progress:
        rendered = ", ".join(f"{day:%Y-%m-%d}" for day in dates)
        raise BonoActivityInProgress(
            f"{operation} affects Bono activity on {rendered} with no approved report. "
            "Confirm the affected days and give a reason to continue."
        )
    if dates and not reason.strip():
        raise BonoActivityInProgress(
            "A written reason is required when changing Bono configuration during open "
            f"operational days ({', '.join(f'{day:%Y-%m-%d}' for day in dates)})."
        )
    return dates


def _audit_config(
    *,
    bono_type: BonoType,
    actor: Any,
    summary: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoType",
        object_id=bono_type.pk,
        actor=actor,
        summary=summary,
        before=before,
        after=after,
    )


@transaction.atomic
def create_bono_type(
    *,
    name: str,
    color: str,
    selling_price: Decimal,
    currency: str = CURRENCY,
    notes: str = "",
    actor: Any | None = None,
) -> BonoType:
    """Create one stable Bono identity. Pair products separately."""
    clean_name = _normalise_name(name)
    if BonoType.objects.filter(name__iexact=clean_name).exists():
        raise BonoTypeConflict(f"A Bono type named {clean_name!r} already exists.")
    if selling_price < 0:
        raise BonoTypeConflict("A Bono selling price cannot be negative.")
    price = quantize_money(selling_price)
    record = BonoType.objects.create(
        name=clean_name,
        color=_normalise_color(color),
        selling_price=price,
        currency=_normalise_currency(currency),
        notes=notes.strip(),
        created_by=actor,
        updated_by=actor,
    )
    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="bono.BonoType",
        object_id=record.pk,
        actor=actor,
        summary=f"Created Bono type {record.name} at {price} {record.currency}",
        after={
            "name": record.name,
            "color": record.color,
            "selling_price": str(record.selling_price),
            "currency": record.currency,
            "is_active": record.is_active,
        },
    )
    return record


@transaction.atomic
def update_bono_type(
    *,
    bono_type: BonoType,
    changes: dict[str, Any],
    actor: Any | None = None,
    confirm_in_progress: bool = False,
    change_reason: str = "",
) -> BonoType:
    """Edit presentation and active state without touching historical rows.

    Retiring a type also retires its active product pairings in the same
    transaction: an inactive type may never keep a product reserved, and the
    pairings stay on file as history rather than being deleted.
    """
    if not changes:
        return bono_type
    locked = BonoType.objects.select_for_update().get(pk=bono_type.pk)
    before = {
        "name": locked.name,
        "color": locked.color,
        "is_active": locked.is_active,
        "notes": locked.notes,
    }
    if "name" in changes:
        clean_name = _normalise_name(changes["name"])
        duplicate = BonoType.objects.filter(name__iexact=clean_name).exclude(pk=locked.pk)
        if duplicate.exists():
            raise BonoTypeConflict(f"A Bono type named {clean_name!r} already exists.")
        changes["name"] = clean_name
    if "color" in changes:
        changes["color"] = _normalise_color(changes["color"])

    _guard_in_progress(
        confirm_in_progress=confirm_in_progress,
        reason=change_reason,
        operation="Editing this Bono type",
    )
    retiring = changes.get("is_active") is False and locked.is_active
    for field, value in changes.items():
        setattr(locked, field, value)
    locked.updated_by = actor
    locked.save(update_fields=[*changes, "updated_by", "updated_at"])
    if retiring:
        retired_pairings = list(
            locked.pairings.select_for_update().filter(is_active=True).select_related("product")
        )
        for pairing in retired_pairings:
            _retire_pairing(
                pairing=pairing,
                actor=actor,
                reason=change_reason.strip() or "Bono type retired.",
                resolution="Retired with Bono type:",
            )
    after = {
        "name": locked.name,
        "color": locked.color,
        "is_active": locked.is_active,
        "notes": locked.notes,
    }
    suffix = f" Reason: {change_reason.strip()}" if change_reason.strip() else ""
    _audit_config(
        bono_type=locked,
        actor=actor,
        summary=f"Updated Bono type {locked.name}.{suffix}",
        before=before,
        after=after,
    )
    return locked


def _validate_bottle_product(product: Product) -> None:
    if not product.is_active:
        raise BonoTypeConflict(f"Product {product.sku!r} is inactive and cannot be paired.")
    if not product.is_stock_tracked:
        raise BonoTypeConflict(f"Product {product.sku!r} is not stock tracked.")
    if not product.requires_whole_quantity:
        raise BonoTypeConflict(f"Product {product.sku!r} is not sold in whole bottles.")
    if product.unit.strip().lower() not in _BOTTLE_UNITS:
        raise BonoTypeConflict(
            f"Product {product.sku!r} is sold in {product.unit!r}; a Bono is one bottle."
        )


def _current_price(product: Product) -> tuple[Decimal, str]:
    price = product.current_price()
    if price is None:
        raise BonoPriceMismatch(f"Product {product.sku!r} has no current selling price.")
    return price.unit_price, price.currency


def _same_price(*, product: Product, selling_price: Decimal, currency: str) -> tuple[Decimal, str]:
    price, price_currency = _current_price(product)
    if price != selling_price or price_currency != currency:
        raise BonoPriceMismatch(
            f"Product {product.sku!r} sells at {price} {price_currency}, not "
            f"{selling_price} {currency}."
        )
    return price, price_currency


@transaction.atomic
def add_pairings(
    *,
    bono_type: BonoType,
    products: list[Product],
    actor: Any | None = None,
    confirm_in_progress: bool = False,
    change_reason: str = "",
) -> list[BonoProductPairing]:
    """Pair one or more equally priced bottle products with an active Bono type."""
    locked_type = BonoType.objects.select_for_update().get(pk=bono_type.pk)
    if not locked_type.is_active:
        raise BonoTypeConflict("An inactive Bono type cannot receive new product pairings.")
    if not products:
        raise BonoTypeConflict("Select at least one product to pair.")
    if locked_type.pairings.filter(is_active=True, review_required=True).exists():
        raise BonoReviewPending(
            "Resolve the pending price review on this Bono type before adding products."
        )
    product_ids = sorted({product.pk for product in products})
    locked_products = list(
        Product.objects.select_for_update().select_related("category").filter(pk__in=product_ids)
    )
    if len(locked_products) != len(product_ids):
        raise BonoTypeConflict("One or more selected products no longer exist.")

    _guard_in_progress(
        confirm_in_progress=confirm_in_progress,
        reason=change_reason,
        operation="Pairing products",
    )
    for product in locked_products:
        _validate_bottle_product(product)
        _same_price(
            product=product,
            selling_price=locked_type.selling_price,
            currency=locked_type.currency,
        )
        conflict = BonoProductPairing.objects.filter(product=product, is_active=True).first()
        if conflict is not None:
            raise BonoTypeConflict(
                f"Product {product.sku!r} is already paired with {conflict.bono_type.name!r}."
            )

    pairings: list[BonoProductPairing] = []
    for product in locked_products:
        price, currency = _current_price(product)
        pairing = BonoProductPairing.objects.create(
            bono_type=locked_type,
            product=product,
            price_at_pairing=price,
            currency=currency,
            created_by=actor,
            updated_by=actor,
        )
        pairings.append(pairing)
    products_text = ", ".join(product.sku for product in locked_products)
    suffix = f" Reason: {change_reason.strip()}" if change_reason.strip() else ""
    _audit_config(
        bono_type=locked_type,
        actor=actor,
        summary=f"Paired {products_text} with {locked_type.name}.{suffix}",
        after={"paired_products": [product.sku for product in locked_products]},
    )
    return pairings


def _retire_pairing(
    *,
    pairing: BonoProductPairing,
    actor: Any | None,
    reason: str,
    resolution: str,
) -> BonoProductPairing:
    now = now_utc()
    pairing.is_active = False
    pairing.unpaired_at = now
    pairing.review_required = False
    pairing.reviewed_at = now
    pairing.reviewed_by = actor
    pairing.updated_by = actor
    pairing.save(
        update_fields=[
            "is_active",
            "unpaired_at",
            "review_required",
            "reviewed_at",
            "reviewed_by",
            "updated_by",
            "updated_at",
        ]
    )
    _audit_config(
        bono_type=pairing.bono_type,
        actor=actor,
        summary=(
            f"{resolution} pairing {pairing.product.sku} from {pairing.bono_type.name}. "
            f"Reason: {reason.strip()}"
        ),
        before={"product": pairing.product.sku, "bono_type": pairing.bono_type.name},
        after={"active": False},
    )
    return pairing


@transaction.atomic
def remove_pairing(
    *,
    pairing: BonoProductPairing,
    actor: Any | None = None,
    reason: str,
    confirm_in_progress: bool = False,
    change_reason: str = "",
) -> BonoProductPairing:
    """Retire a pairing without deleting its history."""
    locked = (
        BonoProductPairing.objects.select_for_update()
        .select_related("bono_type", "product")
        .get(pk=pairing.pk)
    )
    if not locked.is_active:
        raise BonoTypeConflict("That product pairing is already retired.")
    if not reason.strip():
        raise BonoTypeConflict("A reason is required to retire a product pairing.")
    if change_reason.strip():
        reason = f"{reason.strip()} {change_reason.strip()}"
    else:
        reason = reason.strip()
    _guard_in_progress(
        confirm_in_progress=confirm_in_progress,
        reason=reason,
        operation="Retiring a product pairing",
    )
    return _retire_pairing(
        pairing=locked,
        actor=actor,
        reason=reason,
        resolution="Retired",
    )


@transaction.atomic
def resolve_pairing_review(
    *,
    pairing: BonoProductPairing,
    resolution: str,
    actor: Any | None = None,
    target_bono_type: BonoType | None = None,
    reason: str = "",
    confirm_in_progress: bool = False,
) -> BonoProductPairing | BonoType:
    """Resolve a price-change review by retaining, reassigning or unpairing.

    ``RETAIN`` is only allowed when every currently paired product agrees on one
    current price. That common price becomes the type's price, recorded as an
    explicit change with before/after values. A scheduled price which has not
    taken effect yet cannot be signed off early.
    """
    pairing = (
        BonoProductPairing.objects.select_for_update()
        .select_related("bono_type", "product")
        .get(pk=pairing.pk)
    )
    if not pairing.is_active or not pairing.review_required:
        raise BonoReviewPending("That pairing has no open price review.")
    now = now_utc()
    if pairing.price_effective_from is not None and pairing.price_effective_from > now:
        raise BonoReviewPending(
            "The reviewed price is scheduled for a future date. Resolve the review after it "
            "takes effect."
        )
    if not reason.strip():
        raise BonoTypeConflict("A reason is required to resolve a Bono price review.")
    _guard_in_progress(
        confirm_in_progress=confirm_in_progress,
        reason=reason,
        operation="Resolving a Bono price review",
    )

    action = resolution.strip().upper()
    if action == "UNPAIR":
        return _retire_pairing(
            pairing=pairing,
            actor=actor,
            reason=reason,
            resolution="Unpaired during price review:",
        )

    if action == "REASSIGN":
        if target_bono_type is None:
            raise BonoTypeConflict("Choose a compatible Bono type to reassign this product.")
        target = BonoType.objects.select_for_update().get(pk=target_bono_type.pk)
        if target.pk == pairing.bono_type_id:
            raise BonoTypeConflict("Choose a different Bono type for reassignment.")
        if not target.is_active:
            raise BonoTypeConflict("The target Bono type is inactive.")
        if target.pairings.filter(is_active=True, review_required=True).exists():
            raise BonoReviewPending("The target Bono type already has an open price review.")
        price, currency = _same_price(
            product=pairing.product,
            selling_price=target.selling_price,
            currency=target.currency,
        )
        source_type = pairing.bono_type
        now = now_utc()
        pairing.is_active = False
        pairing.unpaired_at = now
        pairing.review_required = False
        pairing.reviewed_at = now
        pairing.reviewed_by = actor
        pairing.updated_by = actor
        pairing.save(
            update_fields=[
                "is_active",
                "unpaired_at",
                "review_required",
                "reviewed_at",
                "reviewed_by",
                "updated_by",
                "updated_at",
            ]
        )
        replacement = BonoProductPairing.objects.create(
            bono_type=target,
            product=pairing.product,
            price_at_pairing=price,
            currency=currency,
            created_by=actor,
            updated_by=actor,
        )
        _audit_config(
            bono_type=source_type,
            actor=actor,
            summary=(
                f"Reassigned {pairing.product.sku} from {source_type.name} to {target.name}. "
                f"Reason: {reason.strip()}"
            ),
            before={"bono_type": source_type.name, "product": pairing.product.sku},
            after={"bono_type": target.name, "product": pairing.product.sku},
        )
        _audit_config(
            bono_type=target,
            actor=actor,
            summary=f"Received {pairing.product.sku} by price-review reassignment.",
            after={"pairing_id": replacement.pk},
        )
        return replacement

    if action != "RETAIN":
        raise BonoTypeConflict("Resolution must be RETAIN, REASSIGN or UNPAIR.")

    source_type = BonoType.objects.select_for_update().get(pk=pairing.bono_type_id)
    active_pairings = list(
        BonoProductPairing.objects.select_for_update()
        .filter(bono_type=source_type, is_active=True)
        .select_related("product")
    )
    common_price: Decimal | None = None
    common_currency: str | None = None
    for active in active_pairings:
        price, currency = _current_price(active.product)
        if common_price is None:
            common_price, common_currency = price, currency
        elif price != common_price or currency != common_currency:
            raise BonoPriceMismatch(
                "The products paired to this Bono do not currently share one price. "
                "Unpair or reassign the product that differs."
            )
    if common_price is None or common_currency is None:
        raise BonoPriceMismatch("This Bono type has no active product pairings.")
    previous_type_price = source_type.selling_price
    source_type.selling_price = quantize_money(common_price)
    source_type.currency = common_currency
    source_type.updated_by = actor
    source_type.save(update_fields=["selling_price", "currency", "updated_by", "updated_at"])
    for active in active_pairings:
        active.price_at_pairing = common_price
        active.currency = common_currency
        active.review_required = False
        active.reviewed_at = now
        active.reviewed_by = actor
        active.updated_by = actor
        active.save(
            update_fields=[
                "price_at_pairing",
                "currency",
                "review_required",
                "reviewed_at",
                "reviewed_by",
                "updated_by",
                "updated_at",
            ]
        )
    _audit_config(
        bono_type=source_type,
        actor=actor,
        summary=(
            f"Retained pairings for {source_type.name} at {common_price} {common_currency}. "
            f"Reason: {reason.strip()}"
        ),
        before={"selling_price": str(previous_type_price)},
        after={"selling_price": str(common_price), "currency": common_currency},
    )
    return source_type


def flag_pairings_for_price_change(
    *,
    product: Product,
    previous_price: Decimal | None,
    new_price: Decimal,
    currency: str,
    effective_from: datetime,
    actor: Any | None = None,
) -> None:
    """Open an Owner review on every active pairing affected by a price change.

    Called by the product pricing service inside its transaction. It deliberately
    does not change the product or the Bono type: configuration interpretation is
    the Owner's explicit decision.
    """
    pairings = list(
        BonoProductPairing.objects.select_for_update()
        .filter(product=product, is_active=True)
        .select_related("bono_type")
    )
    if not pairings:
        return
    moment = now_utc()
    for pairing in pairings:
        if (
            previous_price is not None
            and previous_price == new_price
            and pairing.currency == currency
        ):
            continue
        pairing.review_required = True
        pairing.previous_price = previous_price
        pairing.new_price = new_price
        pairing.price_effective_from = effective_from
        pairing.flagged_at = moment
        pairing.review_reason = (
            f"Price for {product.sku} changed from "
            f"{previous_price if previous_price is not None else 'unset'} to "
            f"{new_price} {currency}, effective {effective_from:%Y-%m-%d %H:%M}."
        )
        pairing.updated_at = moment
        pairing.save(
            update_fields=[
                "review_required",
                "previous_price",
                "new_price",
                "price_effective_from",
                "flagged_at",
                "review_reason",
                "updated_at",
            ]
        )
        _audit_config(
            bono_type=pairing.bono_type,
            actor=actor,
            summary=(
                f"Owner review opened for {pairing.bono_type.name}: {product.sku} price changed."
            ),
            before={"price": str(previous_price) if previous_price is not None else None},
            after={"price": str(new_price), "currency": currency},
        )


# ── Operational custody ─────────────────────────────────────────────────────


def _lock_day(operational_date: date) -> BonoDay:
    if operational_date > _business_today():
        raise BARKOTDomainError("Bono activity cannot be recorded for a future business date.")
    day, _created = BonoDay.objects.select_for_update().get_or_create(
        operational_date=operational_date
    )
    return day


def _require_open(day: BonoDay) -> None:
    if day.status != BonoDayStatus.OPEN:
        raise BonoReportLocked


def _active_employee(employee: EmployeeProfile) -> EmployeeProfile:
    locked = EmployeeProfile.objects.select_for_update().get(pk=employee.pk)
    if locked.is_archived:
        raise BARKOTDomainError("An archived staff member cannot hold or move Bonos.")
    return locked


def _snapshot_for(bono_type: BonoType) -> dict[str, Any]:
    return BonoIssue.snapshot_from(bono_type)


def _staff_balance(*, employee: EmployeeProfile, bono_type: BonoType, day: date) -> int:
    issued = (
        BonoIssue.objects.filter(
            operational_date=day, employee=employee, bono_type=bono_type
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    transfers_in = (
        BonoTransfer.objects.filter(
            operational_date=day, to_employee=employee, bono_type=bono_type
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    transfers_out = (
        BonoTransfer.objects.filter(
            operational_date=day, from_employee=employee, bono_type=bono_type
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    lost = (
        BonoIncident.objects.filter(
            operational_date=day,
            kind=BonoIncidentKind.LOST_BONO,
            responsible_employee=employee,
            bono_type=bono_type,
        ).aggregate(total=Sum("quantity"))["total"]
        or 0
    )
    return int(issued + transfers_in - transfers_out - lost)


def _review_blocks_issuance(bono_type: BonoType, moment: datetime) -> bool:
    """Whether a price revision already in force is still waiting for the Owner."""
    return (
        bono_type.pairings.filter(is_active=True, review_required=True)
        .filter(Q(price_effective_from__isnull=True) | Q(price_effective_from__lte=moment))
        .exists()
    )


@transaction.atomic
def create_issue(
    *,
    operational_date: date,
    bono_type: BonoType,
    employee: EmployeeProfile,
    kind: str,
    quantity: int,
    note: str = "",
    actor: Any | None = None,
) -> BonoIssue:
    """Record the initial hand-out or a later additional issue to one person."""
    day = _lock_day(operational_date)
    _require_open(day)
    if kind not in BonoIssueKind.values:
        raise BARKOTDomainError("Issue kind must be INITIAL or ADDITIONAL.")
    if quantity < 1:
        raise BARKOTDomainError("Bono quantity must be at least one.")
    locked_type = BonoType.objects.select_for_update().get(pk=bono_type.pk)
    if not locked_type.is_active:
        raise BonoTypeConflict("Inactive Bono types cannot be issued.")
    if _review_blocks_issuance(locked_type, now_utc()):
        raise BonoReviewPending(
            "A product price change under this Bono type is waiting for Owner review. "
            "Resolve the pairing before issuing more tokens."
        )
    person = _active_employee(employee)
    if (
        kind == BonoIssueKind.INITIAL
        and BonoIssue.objects.filter(
            operational_date=operational_date,
            employee=person,
            bono_type=locked_type,
            kind=BonoIssueKind.INITIAL,
        ).exists()
    ):
        raise BonoTypeConflict(
            f"{person.full_name} already has an initial {locked_type.name} issue for this day. "
            "Record an additional issue instead."
        )
    issue = BonoIssue.objects.create(
        operational_date=operational_date,
        bono_type=locked_type,
        employee=person,
        kind=kind,
        quantity=quantity,
        occurred_at=now_utc(),
        note=note.strip(),
        created_by=actor,
        updated_by=actor,
        **_snapshot_for(locked_type),
    )
    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="bono.BonoIssue",
        object_id=issue.pk,
        actor=actor,
        summary=(
            f"{issue.get_kind_display()} {quantity} x {locked_type.name} to {person.full_name} "
            f"on {operational_date:%Y-%m-%d}"
        ),
    )
    return issue


@transaction.atomic
def create_transfer(
    *,
    operational_date: date,
    bono_type: BonoType,
    from_employee: EmployeeProfile,
    to_employee: EmployeeProfile,
    quantity: int,
    reason: str,
    note: str = "",
    actor: Any | None = None,
) -> BonoTransfer:
    """Move custody between staff; the business-wide issued total does not change."""
    day = _lock_day(operational_date)
    _require_open(day)
    if not reason.strip():
        raise BARKOTDomainError("A transfer needs a reason.")
    if quantity < 1:
        raise BARKOTDomainError("Bono quantity must be at least one.")
    if from_employee.pk == to_employee.pk:
        raise BARKOTDomainError("A Bono transfer needs two different staff members.")
    source = _active_employee(from_employee)
    recipient = _active_employee(to_employee)
    locked_type = BonoType.objects.select_for_update().get(pk=bono_type.pk)
    available = _staff_balance(employee=source, bono_type=locked_type, day=operational_date)
    if quantity > available:
        raise BonoAllocationExceeded(
            f"{source.full_name} holds {available} x {locked_type.name}, "
            f"so cannot transfer {quantity}."
        )
    transfer = BonoTransfer.objects.create(
        operational_date=operational_date,
        bono_type=locked_type,
        from_employee=source,
        to_employee=recipient,
        quantity=quantity,
        reason=reason.strip(),
        note=note.strip(),
        occurred_at=now_utc(),
        created_by=actor,
        updated_by=actor,
        **_snapshot_for(locked_type),
    )
    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="bono.BonoTransfer",
        object_id=transfer.pk,
        actor=actor,
        summary=(
            f"Transferred {quantity} x {locked_type.name}: "
            f"{source.full_name} → {recipient.full_name} on {operational_date:%Y-%m-%d}"
        ),
    )
    return transfer


def _operational_moment(day: date) -> datetime:
    start, _end = business_day_bounds(day)
    if day == _business_today():
        return now_utc()
    return start + timedelta(hours=12)


@transaction.atomic
def create_incident(
    *,
    operational_date: date,
    kind: str,
    quantity: int,
    reason: str,
    bono_type: BonoType | None = None,
    product: Product | None = None,
    responsible_employee: EmployeeProfile | None = None,
    notes: str = "",
    actor: Any | None = None,
) -> BonoIncident:
    """Record a lost token, or a broken bottle through the existing stock service."""
    day = _lock_day(operational_date)
    _require_open(day)
    if not reason.strip():
        raise BARKOTDomainError("An incident needs a reason.")
    if quantity < 1:
        raise BARKOTDomainError("Incident quantity must be at least one.")

    if kind == BonoIncidentKind.LOST_BONO:
        if bono_type is None or responsible_employee is None:
            raise BARKOTDomainError("A lost Bono needs its type and responsible staff member.")
        person = _active_employee(responsible_employee)
        locked_type = BonoType.objects.select_for_update().get(pk=bono_type.pk)
        available = _staff_balance(employee=person, bono_type=locked_type, day=operational_date)
        if quantity > available:
            raise BonoAllocationExceeded(
                f"{person.full_name} holds {available} x {locked_type.name}, "
                f"so cannot lose {quantity}."
            )
        incident = BonoIncident.objects.create(
            operational_date=operational_date,
            kind=kind,
            bono_type=locked_type,
            responsible_employee=person,
            quantity=quantity,
            reason=reason.strip(),
            notes=notes.strip(),
            occurred_at=_operational_moment(operational_date),
            created_by=actor,
            updated_by=actor,
            **_snapshot_for(locked_type),
        )
    elif kind == BonoIncidentKind.BROKEN_BOTTLE:
        if product is None:
            raise BARKOTDomainError("A broken bottle needs a product.")
        locked_product = Product.objects.select_for_update().get(pk=product.pk)
        _validate_bottle_product(locked_product)
        pairing = (
            BonoProductPairing.objects.select_related("bono_type")
            .filter(product=locked_product, is_active=True, bono_type__is_active=True)
            .first()
        )
        if pairing is None:
            raise BonoTypeConflict(
                f"Product {locked_product.sku!r} is not currently paired with an active Bono type."
            )
        locked_type = pairing.bono_type
        breakage = record_breakage(
            reason=reason.strip(),
            lines=[(locked_product, Decimal(quantity))],
            actor=actor,
            occurred_at=_operational_moment(operational_date),
            reference=f"BONO-{operational_date:%Y%m%d}",
            notes=notes.strip(),
        )
        incident = BonoIncident.objects.create(
            operational_date=operational_date,
            kind=kind,
            bono_type=locked_type,
            product=locked_product,
            responsible_employee=responsible_employee,
            quantity=quantity,
            reason=reason.strip(),
            notes=notes.strip(),
            occurred_at=_operational_moment(operational_date),
            breakage_record=breakage,
            created_by=actor,
            updated_by=actor,
            **_snapshot_for(locked_type),
        )
    else:
        raise BARKOTDomainError("Incident kind must be LOST_BONO or BROKEN_BOTTLE.")

    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="bono.BonoIncident",
        object_id=incident.pk,
        actor=actor,
        summary=(
            f"{incident.get_kind_display()} {quantity} on {operational_date:%Y-%m-%d}: "
            f"{reason.strip()}"
        ),
    )
    return incident


@transaction.atomic
def resolve_incident(
    *,
    incident: BonoIncident,
    resolution_status: str,
    resolution_notes: str,
    actor: Any | None = None,
) -> BonoIncident:
    """Record the operational outcome without inventing a financial consequence."""
    locked = BonoIncident.objects.select_for_update().get(pk=incident.pk)
    if resolution_status not in BonoIncidentResolution.values:
        raise BARKOTDomainError("Choose a valid Bono incident resolution.")
    if resolution_status == BonoIncidentResolution.DEDUCTED and locked.payroll_deduction_id is None:
        raise BARKOTDomainError(
            "A payroll deduction must be recorded before marking an incident deducted."
        )
    day = _lock_day(locked.operational_date)
    _require_open(day)
    before = locked.resolution_status
    locked.resolution_status = resolution_status
    locked.resolution_notes = resolution_notes.strip()
    locked.updated_by = actor
    locked.save(update_fields=["resolution_status", "resolution_notes", "updated_by", "updated_at"])
    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoIncident",
        object_id=locked.pk,
        actor=actor,
        summary=f"Bono incident resolution changed from {before} to {resolution_status}",
        before={"resolution": before},
        after={"resolution": resolution_status},
    )
    return locked


@transaction.atomic
def record_incident_deduction(
    *,
    incident: BonoIncident,
    payroll_item: PayrollItem,
    amount: Decimal,
    reason: str,
    actor: Any | None = None,
) -> PayrollDeduction:
    """Link an explicit deduction to a lost-Bono incident using the payroll service.

    This never runs automatically. The caller chooses the amount, the reason and
    the generated payroll line; the existing payroll rules (positive amount,
    generated run, no negative net pay) remain authoritative.
    """
    incident = BonoIncident.objects.select_for_update().get(pk=incident.pk)
    if incident.kind != BonoIncidentKind.LOST_BONO:
        raise BARKOTDomainError("Only a lost Bono can result in a staff deduction.")
    if incident.payroll_deduction_id is not None:
        raise BonoTypeConflict("This incident already has a payroll deduction.")
    if incident.responsible_employee_id is None:
        raise BARKOTDomainError("This incident has no responsible staff member.")
    if not reason.strip():
        raise BARKOTDomainError("A deduction needs a reason.")
    day = _lock_day(incident.operational_date)
    _require_open(day)
    item = (
        PayrollItem.objects.select_for_update()
        .select_related("employee__profile", "run")
        .get(pk=payroll_item.pk)
    )
    if item.employee.profile_id != incident.responsible_employee_id:
        raise BARKOTDomainError("The payroll line belongs to a different staff member.")
    deduction = add_deduction(
        payroll_item=item,
        deduction_type="OTHER",
        amount=amount,
        reason=reason.strip(),
        occurred_on=incident.operational_date,
        actor=actor,
    )
    incident.payroll_deduction = deduction
    incident.resolution_status = BonoIncidentResolution.DEDUCTED
    incident.resolution_notes = f"{incident.resolution_notes}\n{reason.strip()}".strip()
    incident.updated_by = actor
    incident.save(
        update_fields=[
            "payroll_deduction",
            "resolution_status",
            "resolution_notes",
            "updated_by",
            "updated_at",
        ]
    )
    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoIncident",
        object_id=incident.pk,
        actor=actor,
        summary=f"Deducted {amount} through payroll for lost Bono incident {incident.pk}",
        after={"payroll_deduction_id": deduction.pk, "amount": str(deduction.amount)},
    )
    return deduction


# ── Report collection ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BonoActivity:
    """One Bono type's activity for an operational day."""

    bono_type: BonoType
    initial_issued: int
    additional_issued: int
    transfers_in: int
    transfers_out: int
    lost: int


@dataclass(frozen=True, slots=True)
class ProductActivity:
    """One product's independent stock movement for an operational day."""

    product: Product
    bono_type: BonoType | None
    opening: Decimal
    received: Decimal
    other_additions: Decimal
    sold: Decimal
    breakage: Decimal
    other_losses: Decimal

    @property
    def expected(self) -> Decimal:
        """Ledger-consistent closing quantity."""
        return quantize_quantity(
            self.opening
            + self.received
            + self.other_additions
            - self.sold
            - self.breakage
            - self.other_losses
        )


@dataclass(frozen=True, slots=True)
class DayActivity:
    """Everything a daily report needs to know, read from existing domains."""

    bono: tuple[BonoActivity, ...]
    products: tuple[ProductActivity, ...]
    sales_total: Decimal
    cash_total: Decimal
    mobile_total: Decimal
    payments_total: Decimal


def _sum_quantity(rows: Any) -> Decimal:
    value = rows.aggregate(total=Sum("quantity"))["total"]
    return quantize_quantity(value or Decimal("0"))


def _pairings_during(day: date) -> list[BonoProductPairing]:
    start, end = business_day_bounds(day)
    return list(
        BonoProductPairing.objects.select_related("product", "bono_type")
        .filter(paired_at__lt=end)
        .filter(Q(unpaired_at__isnull=True) | Q(unpaired_at__gt=start))
        .order_by("product__name", "paired_at", "id")
    )


def _product_activity(product: Product, bono_type: BonoType | None, day: date) -> ProductActivity:
    start, end = business_day_bounds(day)
    opening = StockMovement.objects.balance_for(product, before=start)
    movements = StockMovement.objects.filter(
        product=product, occurred_at__gte=start, occurred_at__lt=end
    )
    by_kind = {
        row["kind"]: quantize_quantity(row["total"] or Decimal("0"))
        for row in movements.values("kind").annotate(total=Sum("quantity"))
    }
    sale_void = movements.filter(
        kind=MovementKind.SALE_VOID,
        sale_item__sale__sold_at__lt=start,
    )
    other_add = (
        _sum_quantity(movements.filter(kind=MovementKind.STOCK_IN))
        + _sum_quantity(movements.filter(kind=MovementKind.COUNT_VARIANCE, direction="IN"))
        + _sum_quantity(sale_void)
    )
    other_loss = _sum_quantity(movements.filter(kind=MovementKind.STOCK_OUT)) + _sum_quantity(
        movements.filter(kind=MovementKind.COUNT_VARIANCE, direction="OUT")
    )
    sold_rows = SaleItem.objects.filter(
        product=product,
        sale__status=SaleStatus.COMPLETED,
        sale__sold_at__gte=start,
        sale__sold_at__lt=end,
    )
    return ProductActivity(
        product=product,
        bono_type=bono_type,
        opening=quantize_quantity(opening),
        received=by_kind.get(MovementKind.RECEIPT, Decimal("0.000")),
        other_additions=other_add,
        sold=_sum_quantity(sold_rows),
        breakage=by_kind.get(MovementKind.BREAKAGE, Decimal("0.000")),
        other_losses=other_loss,
    )


def _sales_and_payments(day: date) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    start, end = business_day_bounds(day)
    sales_total = Sale.objects.filter(
        status=SaleStatus.COMPLETED, sold_at__gte=start, sold_at__lt=end
    ).aggregate(total=Sum("total"))["total"] or Decimal("0")
    payment_rows = (
        Payment.objects.filter(
            status=PaymentStatus.PAID,
            received_at__gte=start,
            received_at__lt=end,
            sale__status=SaleStatus.COMPLETED,
        )
        .values("method")
        .annotate(total=Sum("amount"))
    )
    by_method = {
        row["method"]: quantize_money(row["total"] or Decimal("0")) for row in payment_rows
    }
    cash = by_method.get(PaymentMethod.CASH, quantize_money(Decimal("0")))
    mobile = by_method.get(PaymentMethod.MOBILE_BANKING, quantize_money(Decimal("0")))
    return (
        quantize_money(sales_total),
        cash,
        mobile,
        quantize_money(cash + mobile),
    )


def collect_day_activity(day: date) -> DayActivity:
    """Read one day's Bono custody and independent product stock facts."""
    issues: dict[int, dict[str, int]] = defaultdict(lambda: {"INITIAL": 0, "ADDITIONAL": 0})
    for issue_row in (
        BonoIssue.objects.filter(operational_date=day)
        .values("bono_type_id", "kind")
        .annotate(total=Sum("quantity"))
    ):
        issues[issue_row["bono_type_id"]][issue_row["kind"]] = int(issue_row["total"] or 0)
    transfers: dict[int, dict[str, int]] = defaultdict(lambda: {"IN": 0, "OUT": 0})
    for out_row in (
        BonoTransfer.objects.filter(operational_date=day)
        .values("bono_type_id")
        .annotate(transferred_out=Sum("quantity"))
    ):
        transfers[out_row["bono_type_id"]]["OUT"] = int(out_row["transferred_out"] or 0)
    for in_row in (
        BonoTransfer.objects.filter(operational_date=day)
        .values("bono_type_id")
        .annotate(transferred_in=Sum("quantity"))
    ):
        transfers[in_row["bono_type_id"]]["IN"] = int(in_row["transferred_in"] or 0)
    lost: dict[int, int] = defaultdict(int)
    for lost_row in (
        BonoIncident.objects.filter(operational_date=day, kind=BonoIncidentKind.LOST_BONO)
        .values("bono_type_id")
        .annotate(total=Sum("quantity"))
    ):
        if lost_row["bono_type_id"] is not None:
            lost[lost_row["bono_type_id"]] = int(lost_row["total"] or 0)

    pairings = _pairings_during(day)
    pairing_by_product: dict[int, BonoProductPairing] = {}
    for pairing in pairings:
        pairing_by_product[pairing.product_id] = pairing

    type_ids = set(issues) | set(transfers) | set(lost)
    type_ids.update(pairing.bono_type_id for pairing in pairing_by_product.values())
    types = {
        bono_type.pk: bono_type
        for bono_type in BonoType.objects.filter(pk__in=type_ids).order_by("name", "id")
    }
    bono_rows = tuple(
        BonoActivity(
            bono_type=bono_type,
            initial_issued=issues[type_id]["INITIAL"],
            additional_issued=issues[type_id]["ADDITIONAL"],
            transfers_in=transfers[type_id]["IN"],
            transfers_out=transfers[type_id]["OUT"],
            lost=lost[type_id],
        )
        for type_id, bono_type in types.items()
    )
    product_rows = tuple(
        _product_activity(pairing.product, pairing.bono_type, day)
        for pairing in pairing_by_product.values()
    )
    sales_total, cash, mobile, payments_total = _sales_and_payments(day)
    return DayActivity(
        bono=bono_rows,
        products=product_rows,
        sales_total=sales_total,
        cash_total=cash,
        mobile_total=mobile,
        payments_total=payments_total,
    )


def _activity_signature(activity: DayActivity) -> dict[str, Any]:
    bono = {
        str(row.bono_type.pk): (
            row.initial_issued,
            row.additional_issued,
            row.transfers_in,
            row.transfers_out,
            row.lost,
        )
        for row in activity.bono
    }
    products = {
        str(row.product.pk): (
            str(row.opening),
            str(row.received),
            str(row.other_additions),
            str(row.sold),
            str(row.breakage),
            str(row.other_losses),
            str(row.expected),
        )
        for row in activity.products
    }
    return {
        "bono": bono,
        "products": products,
        "money": (
            str(activity.sales_total),
            str(activity.cash_total),
            str(activity.mobile_total),
            str(activity.payments_total),
        ),
    }


def _report_signature(report: BonoReport) -> dict[str, Any]:
    bono = {
        str(line.bono_type_id): (
            line.initial_issued_quantity,
            line.additional_issued_quantity,
            line.transfers_in_quantity,
            line.transfers_out_quantity,
            line.lost_quantity,
        )
        for line in report.bono_lines.all()
    }
    products = {
        str(line.product_id): (
            str(line.opening_quantity),
            str(line.received_quantity),
            str(line.other_addition_quantity),
            str(line.sold_quantity),
            str(line.breakage_quantity),
            str(line.other_loss_quantity),
            str(line.expected_closing_quantity),
        )
        for line in report.product_lines.all()
    }
    return {
        "bono": bono,
        "products": products,
        "money": (
            str(report.sales_total),
            str(report.cash_paid_total),
            str(report.mobile_paid_total),
            str(report.payments_total),
        ),
    }


def _snapshot_for_day(bono_type: BonoType, day: date) -> dict[str, Any]:
    """Return the appearance frozen by that day's earliest custody event.

    A report prepared after a label or colour edit must still describe the day
    the tokens were issued, not today's configuration. An event on the day is
    the authoritative source because it already carries the historical snapshot;
    current configuration is only the fallback for a type with no movement yet.
    """
    issue = (
        BonoIssue.objects.filter(operational_date=day, bono_type=bono_type)
        .order_by("occurred_at", "id")
        .first()
    )
    event: Any = issue
    if event is None:
        event = (
            BonoIncident.objects.filter(operational_date=day, bono_type=bono_type)
            .order_by("occurred_at", "id")
            .first()
        )
    if event is None:
        event = (
            BonoTransfer.objects.filter(operational_date=day, bono_type=bono_type)
            .order_by("occurred_at", "id")
            .first()
        )
    if event is None:
        return BonoIssue.snapshot_from(bono_type)
    return {field: getattr(event, field) for field in _BONO_SNAPSHOT_FIELDS}


def _sync_report(report: BonoReport, activity: DayActivity) -> BonoReport:
    existing_bono = {line.bono_type_id: line for line in report.bono_lines.all()}
    for row in activity.bono:
        line = existing_bono.get(row.bono_type.pk)
        if line is None:
            line = BonoReportLine(
                report=report,
                bono_type=row.bono_type,
                **_snapshot_for_day(row.bono_type, report.operational_date),
            )
        line.initial_issued_quantity = row.initial_issued
        line.additional_issued_quantity = row.additional_issued
        line.transfers_in_quantity = row.transfers_in
        line.transfers_out_quantity = row.transfers_out
        line.lost_quantity = row.lost
        line.save()
    existing_products = {line.product_id: line for line in report.product_lines.all()}
    for product_row in activity.products:
        product_line = existing_products.get(product_row.product.pk)
        if product_line is None:
            snapshot = (
                _snapshot_for_day(product_row.bono_type, report.operational_date)
                if product_row.bono_type is not None
                else None
            )
            product_line = BonoReportProductLine(
                report=report,
                product=product_row.product,
                bono_type=product_row.bono_type,
                product_name_snapshot=product_row.product.name,
                product_sku_snapshot=product_row.product.sku,
                bono_name_snapshot=snapshot["bono_name_snapshot"] if snapshot else "",
                bono_color_snapshot=snapshot["bono_color_snapshot"] if snapshot else "",
            )
        product_line.opening_quantity = product_row.opening
        product_line.received_quantity = product_row.received
        product_line.other_addition_quantity = product_row.other_additions
        product_line.sold_quantity = product_row.sold
        product_line.breakage_quantity = product_row.breakage
        product_line.other_loss_quantity = product_row.other_losses
        product_line.save()
    report.sales_total = activity.sales_total
    report.cash_paid_total = activity.cash_total
    report.mobile_paid_total = activity.mobile_total
    report.payments_total = activity.payments_total
    report.activity_generated_at = now_utc()
    report.save(
        update_fields=[
            "sales_total",
            "cash_paid_total",
            "mobile_paid_total",
            "payments_total",
            "activity_generated_at",
            "updated_at",
        ]
    )
    return report


@transaction.atomic
def create_report(
    *, operational_date: date, notes: str = "", actor: Any | None = None
) -> BonoReport:
    """Open the one draft daily report for a date and snapshot its activity."""
    if operational_date > _business_today():
        raise BARKOTDomainError("A Bono report cannot be opened for a future business date.")
    day = _lock_day(operational_date)
    _require_open(day)
    existing = BonoReport.objects.filter(operational_date=operational_date)
    if existing.filter(status=BonoReportStatus.APPROVED).exists():
        raise BonoTypeConflict(
            "This day already has an approved Bono report. Use the correction process."
        )
    if existing.filter(status__in=[BonoReportStatus.DRAFT, BonoReportStatus.SUBMITTED]).exists():
        raise BonoTypeConflict("This day already has an open Bono report.")
    if existing.exists():
        raise BonoTypeConflict(
            "This day has a rejected report. Reopen that report to correct and resubmit it."
        )
    report = BonoReport.objects.create(
        operational_date=operational_date,
        notes=notes.strip(),
        currency=CURRENCY,
        created_by=actor,
        updated_by=actor,
    )
    _sync_report(report, collect_day_activity(operational_date))
    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="bono.BonoReport",
        object_id=report.pk,
        actor=actor,
        summary=f"Opened Bono report for {operational_date:%Y-%m-%d}",
    )
    return report


@transaction.atomic
def refresh_report(*, report: BonoReport, actor: Any | None = None) -> BonoReport:
    """Re-read activity into a draft/rejected report without losing manual counts."""
    locked = BonoReport.objects.select_for_update().get(pk=report.pk)
    if locked.status not in {BonoReportStatus.DRAFT, BonoReportStatus.REJECTED}:
        raise BonoReportLocked("Only a draft or rejected report can be refreshed.")
    day = _lock_day(locked.operational_date)
    if day.status != BonoDayStatus.OPEN and locked.corrects_id is None:
        raise BonoReportLocked
    _sync_report(locked, collect_day_activity(locked.operational_date))
    locked.updated_by = actor
    locked.save(update_fields=["updated_by", "updated_at"])
    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoReport",
        object_id=locked.pk,
        actor=actor,
        summary=f"Refreshed Bono report {locked.operational_date:%Y-%m-%d} r{locked.revision}",
    )
    return locked


def _apply_bono_line_changes(report: BonoReport, changes: list[dict[str, Any]]) -> None:
    if not changes:
        return
    lines = {line.pk: line for line in report.bono_lines.all()}
    for change in changes:
        line = lines.get(change["id"])
        if line is None:
            raise BonoReportIncomplete("A Bono line does not belong to this report.")
        for field in ("used_quantity", "returned_quantity"):
            if field in change:
                value = change[field]
                if value < 0:
                    raise BonoReportIncomplete("Bono quantities cannot be negative.")
                setattr(line, field, value)
        if "explanation" in change:
            line.explanation = str(change["explanation"]).strip()
        line.save(update_fields=["used_quantity", "returned_quantity", "explanation"])


def _apply_product_line_changes(report: BonoReport, changes: list[dict[str, Any]]) -> None:
    if not changes:
        return
    lines = {line.pk: line for line in report.product_lines.all()}
    for change in changes:
        line = lines.get(change["id"])
        if line is None:
            raise BonoReportIncomplete("A product line does not belong to this report.")
        if "physical_closing_quantity" in change:
            value = change["physical_closing_quantity"]
            if value is None:
                line.physical_closing_quantity = None
            else:
                quantity = quantize_quantity(value)
                if quantity < 0:
                    raise BonoReportIncomplete("Physical stock cannot be negative.")
                if quantity != quantity.to_integral_value():
                    raise BonoReportIncomplete("Bono products are counted in whole bottles.")
                line.physical_closing_quantity = quantity
        if "explanation" in change:
            line.explanation = str(change["explanation"]).strip()
        line.save(update_fields=["physical_closing_quantity", "explanation"])


@transaction.atomic
def update_report(
    *,
    report: BonoReport,
    notes: str | None = None,
    bono_lines: list[dict[str, Any]] | None = None,
    product_lines: list[dict[str, Any]] | None = None,
    actor: Any | None = None,
) -> BonoReport:
    """Edit the manual counts/explanations of a draft or rejected report."""
    locked = BonoReport.objects.select_for_update().get(pk=report.pk)
    if locked.status not in {BonoReportStatus.DRAFT, BonoReportStatus.REJECTED}:
        raise BonoReportLocked("A submitted or approved Bono report cannot be edited.")
    _apply_bono_line_changes(locked, bono_lines or [])
    _apply_product_line_changes(locked, product_lines or [])
    if notes is not None:
        locked.notes = notes.strip()
    locked.updated_by = actor
    locked.save(update_fields=["notes", "updated_by", "updated_at"])
    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoReport",
        object_id=locked.pk,
        actor=actor,
        summary=(f"Edited Bono report {locked.operational_date:%Y-%m-%d} r{locked.revision}"),
    )
    return locked


def _validate_report_ready(report: BonoReport) -> None:
    bono_lines = list(report.bono_lines.all())
    product_lines = list(report.product_lines.all())
    for line in bono_lines:
        if line.accounted_quantity > line.total_issued_quantity:
            raise BonoReportIncomplete(
                f"{line.bono_name_snapshot}: used, returned and lost tokens exceed "
                "the issued total."
            )
        if line.discrepancy_quantity != 0 and not line.explanation.strip():
            raise BonoReportIncomplete(
                f"{line.bono_name_snapshot}: explain the "
                f"{line.discrepancy_quantity} token discrepancy."
            )
    for product_line in product_lines:
        if product_line.physical_closing_quantity is None:
            raise BonoReportIncomplete(
                f"{product_line.product_name_snapshot}: enter the physical closing stock."
            )
        if product_line.variance_quantity not in (None, Decimal("0.000")) and (
            not product_line.explanation.strip()
        ):
            raise BonoReportIncomplete(
                f"{product_line.product_name_snapshot}: explain the stock variance."
            )
    if not bono_lines and not product_lines:
        raise BonoReportIncomplete("A daily Bono report needs at least one Bono or product line.")


@transaction.atomic
def submit_report(*, report: BonoReport, actor: Any | None = None) -> BonoReport:
    """Validate, freeze and submit a report; this also closes operational writes."""
    locked = BonoReport.objects.select_for_update().get(pk=report.pk)
    if locked.status not in {BonoReportStatus.DRAFT, BonoReportStatus.REJECTED}:
        raise BonoReportLocked("Only a draft or rejected report can be submitted.")
    day = _lock_day(locked.operational_date)
    if locked.corrects_id is None:
        _require_open(day)
    current = collect_day_activity(locked.operational_date)
    if _activity_signature(current) != _report_signature(locked):
        raise BonoReportStale
    _validate_report_ready(locked)
    now = now_utc()
    locked.status = BonoReportStatus.SUBMITTED
    locked.submitted_by = actor
    locked.submitted_at = now
    locked.rejected_by = None
    locked.rejected_at = None
    locked.rejection_reason = ""
    locked.updated_by = actor
    locked.save(
        update_fields=[
            "status",
            "submitted_by",
            "submitted_at",
            "rejected_by",
            "rejected_at",
            "rejection_reason",
            "updated_by",
            "updated_at",
        ]
    )
    day.status = BonoDayStatus.SUBMITTED
    day.save(update_fields=["status", "updated_at"])
    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoReport",
        object_id=locked.pk,
        actor=actor,
        summary=f"Submitted Bono report for {locked.operational_date:%Y-%m-%d}",
    )
    return locked


@transaction.atomic
def approve_report(*, report: BonoReport, actor: Any | None = None) -> BonoReport:
    """Owner sign-off. The report and its lines become immutable."""
    locked = BonoReport.objects.select_for_update().get(pk=report.pk)
    if locked.status != BonoReportStatus.SUBMITTED:
        raise BonoReportLocked("Only a submitted Bono report can be approved.")
    day = BonoDay.objects.select_for_update().get(operational_date=locked.operational_date)
    if _activity_signature(collect_day_activity(locked.operational_date)) != _report_signature(
        locked
    ):
        raise BonoReportStale
    now = now_utc()
    locked.status = BonoReportStatus.APPROVED
    locked.approved_by = actor
    locked.approved_at = now
    locked.updated_by = actor
    locked.save(
        update_fields=[
            "status",
            "approved_by",
            "approved_at",
            "updated_by",
            "updated_at",
        ]
    )
    day.status = BonoDayStatus.APPROVED
    day.save(update_fields=["status", "updated_at"])
    AuditLog.record(
        action=AuditLog.Action.APPROVE,
        object_type="bono.BonoReport",
        object_id=locked.pk,
        actor=actor,
        summary=(f"Approved Bono report {locked.operational_date:%Y-%m-%d} r{locked.revision}"),
    )
    return locked


@transaction.atomic
def reject_report(*, report: BonoReport, reason: str, actor: Any | None = None) -> BonoReport:
    """Owner rejection reopens operational writes for the day."""
    if not reason.strip():
        raise BARKOTDomainError("A rejection reason is required.")
    locked = BonoReport.objects.select_for_update().get(pk=report.pk)
    if locked.status != BonoReportStatus.SUBMITTED:
        raise BonoReportLocked("Only a submitted Bono report can be rejected.")
    day = BonoDay.objects.select_for_update().get(operational_date=locked.operational_date)
    now = now_utc()
    locked.status = BonoReportStatus.REJECTED
    locked.rejected_by = actor
    locked.rejected_at = now
    locked.rejection_reason = reason.strip()
    locked.updated_by = actor
    locked.save(
        update_fields=[
            "status",
            "rejected_by",
            "rejected_at",
            "rejection_reason",
            "updated_by",
            "updated_at",
        ]
    )
    day.status = BonoDayStatus.APPROVED if locked.corrects_id is not None else BonoDayStatus.OPEN
    day.save(update_fields=["status", "updated_at"])
    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoReport",
        object_id=locked.pk,
        actor=actor,
        summary=(
            f"Rejected Bono report {locked.operational_date:%Y-%m-%d} r{locked.revision}: "
            f"{reason.strip()}"
        ),
    )
    return locked


@transaction.atomic
def create_correction(*, report: BonoReport, reason: str, actor: Any | None = None) -> BonoReport:
    """Clone an approved report into a new draft revision, leaving the original intact."""
    if not reason.strip():
        raise BARKOTDomainError("A correction reason is required.")
    original = BonoReport.objects.select_for_update().get(pk=report.pk)
    if original.status != BonoReportStatus.APPROVED:
        raise BonoReportLocked("Only an approved Bono report can be corrected.")
    if BonoReport.objects.filter(
        corrects=original,
        status__in=[BonoReportStatus.DRAFT, BonoReportStatus.SUBMITTED],
    ).exists():
        raise BonoTypeConflict("A correction for this report is already in progress.")
    latest_revision = (
        BonoReport.objects.filter(operational_date=original.operational_date)
        .order_by("-revision")
        .values_list("revision", flat=True)
        .first()
        or 0
    )
    correction = BonoReport.objects.create(
        operational_date=original.operational_date,
        revision=latest_revision + 1,
        corrects=original,
        status=BonoReportStatus.DRAFT,
        correction_reason=reason.strip(),
        notes=original.notes,
        sales_total=original.sales_total,
        cash_paid_total=original.cash_paid_total,
        mobile_paid_total=original.mobile_paid_total,
        payments_total=original.payments_total,
        currency=original.currency,
        activity_generated_at=original.activity_generated_at,
        created_by=actor,
        updated_by=actor,
    )
    for line in original.bono_lines.all():
        BonoReportLine.objects.create(
            report=correction,
            bono_type=line.bono_type,
            bono_code_snapshot=line.bono_code_snapshot,
            bono_name_snapshot=line.bono_name_snapshot,
            bono_color_snapshot=line.bono_color_snapshot,
            bono_price_snapshot=line.bono_price_snapshot,
            currency=line.currency,
            initial_issued_quantity=line.initial_issued_quantity,
            additional_issued_quantity=line.additional_issued_quantity,
            transfers_in_quantity=line.transfers_in_quantity,
            transfers_out_quantity=line.transfers_out_quantity,
            lost_quantity=line.lost_quantity,
            used_quantity=line.used_quantity,
            returned_quantity=line.returned_quantity,
            explanation=line.explanation,
        )
    for product_line in original.product_lines.all():
        BonoReportProductLine.objects.create(
            report=correction,
            product=product_line.product,
            bono_type=product_line.bono_type,
            product_name_snapshot=product_line.product_name_snapshot,
            product_sku_snapshot=product_line.product_sku_snapshot,
            bono_name_snapshot=product_line.bono_name_snapshot,
            bono_color_snapshot=product_line.bono_color_snapshot,
            opening_quantity=product_line.opening_quantity,
            received_quantity=product_line.received_quantity,
            other_addition_quantity=product_line.other_addition_quantity,
            sold_quantity=product_line.sold_quantity,
            breakage_quantity=product_line.breakage_quantity,
            other_loss_quantity=product_line.other_loss_quantity,
            physical_closing_quantity=product_line.physical_closing_quantity,
            explanation=product_line.explanation,
        )
    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type="bono.BonoReport",
        object_id=correction.pk,
        actor=actor,
        summary=(
            f"Opened correction r{correction.revision} for approved Bono report "
            f"{original.operational_date:%Y-%m-%d}: {reason.strip()}"
        ),
    )
    return correction


# ── Summary reads ───────────────────────────────────────────────────────────


def staff_balances_for_day(day: date) -> list[dict[str, Any]]:
    """Return every staff/type custody balance for one operational day."""
    rows: dict[tuple[int, int], dict[str, Any]] = {}
    for issue in BonoIssue.objects.filter(operational_date=day).select_related(
        "employee", "bono_type"
    ):
        key = (issue.employee_id, issue.bono_type_id)
        entry = rows.setdefault(
            key,
            {
                "employee_id": issue.employee_id,
                "employee_name": issue.employee.full_name,
                "employee_position": issue.employee.position,
                "bono_type_id": issue.bono_type_id,
                "bono_name": issue.bono_type.name,
                "bono_color": issue.bono_type.color,
                "issued": 0,
                "transfers_in": 0,
                "transfers_out": 0,
                "lost": 0,
                "balance": 0,
            },
        )
        entry["issued"] += issue.quantity
    for transfer in BonoTransfer.objects.filter(operational_date=day).select_related(
        "from_employee", "to_employee", "bono_type"
    ):
        source_key = (transfer.from_employee_id, transfer.bono_type_id)
        source = rows.setdefault(
            source_key,
            {
                "employee_id": transfer.from_employee_id,
                "employee_name": transfer.from_employee.full_name,
                "employee_position": transfer.from_employee.position,
                "bono_type_id": transfer.bono_type_id,
                "bono_name": transfer.bono_type.name,
                "bono_color": transfer.bono_type.color,
                "issued": 0,
                "transfers_in": 0,
                "transfers_out": 0,
                "lost": 0,
                "balance": 0,
            },
        )
        source["transfers_out"] += transfer.quantity
        target_key = (transfer.to_employee_id, transfer.bono_type_id)
        target = rows.setdefault(
            target_key,
            {
                "employee_id": transfer.to_employee_id,
                "employee_name": transfer.to_employee.full_name,
                "employee_position": transfer.to_employee.position,
                "bono_type_id": transfer.bono_type_id,
                "bono_name": transfer.bono_type.name,
                "bono_color": transfer.bono_type.color,
                "issued": 0,
                "transfers_in": 0,
                "transfers_out": 0,
                "lost": 0,
                "balance": 0,
            },
        )
        target["transfers_in"] += transfer.quantity
    for incident in BonoIncident.objects.filter(
        operational_date=day, kind=BonoIncidentKind.LOST_BONO
    ).select_related("responsible_employee", "bono_type"):
        responsible = incident.responsible_employee
        incident_type = incident.bono_type
        if responsible is None or incident_type is None:
            continue
        key = (responsible.pk, incident_type.pk)
        entry = rows.setdefault(
            key,
            {
                "employee_id": responsible.pk,
                "employee_name": responsible.full_name,
                "employee_position": responsible.position,
                "bono_type_id": incident_type.pk,
                "bono_name": incident_type.name,
                "bono_color": incident_type.color,
                "issued": 0,
                "transfers_in": 0,
                "transfers_out": 0,
                "lost": 0,
                "balance": 0,
            },
        )
        entry["lost"] += incident.quantity
    result = []
    for entry in rows.values():
        entry["balance"] = (
            entry["issued"] + entry["transfers_in"] - entry["transfers_out"] - entry["lost"]
        )
        result.append(entry)
    result.sort(key=lambda row: (row["employee_name"], row["bono_name"]))
    return result


def day_summary(day: date) -> dict[str, Any]:
    """Read-only Bono state for the manager's hand-over and the barman's view."""
    reports = BonoReport.objects.filter(operational_date=day).order_by("-revision")
    latest = reports.first()
    day_row = BonoDay.objects.filter(operational_date=day).first()
    activity = collect_day_activity(day)
    return {
        "operational_date": day.isoformat(),
        "day_status": day_row.status if day_row else BonoDayStatus.OPEN,
        "operations_locked": bool(day_row and day_row.status != BonoDayStatus.OPEN),
        "bono_totals": [
            {
                "bono_type_id": row.bono_type.pk,
                "bono_code": str(row.bono_type.code),
                "bono_name": row.bono_type.name,
                "bono_color": row.bono_type.color,
                "initial_issued": row.initial_issued,
                "additional_issued": row.additional_issued,
                "total_issued": row.initial_issued + row.additional_issued,
                "transfers_in": row.transfers_in,
                "transfers_out": row.transfers_out,
                "lost": row.lost,
            }
            for row in activity.bono
        ],
        "staff_balances": staff_balances_for_day(day),
        "latest_report": (
            {
                "id": latest.pk,
                "revision": latest.revision,
                "status": latest.status,
                "submitted_at": latest.submitted_at,
                "approved_at": latest.approved_at,
            }
            if latest
            else None
        ),
        "in_progress_dates": [
            value.isoformat() for value in _open_activity_dates() if value <= day
        ],
    }


def config_history(bono_type: BonoType) -> list[AuditLog]:
    """Configuration audit rows for the type, newest first."""
    return list(
        AuditLog.objects.filter(object_type="bono.BonoType", object_id=str(bono_type.pk)).order_by(
            "-created_at", "-id"
        )
    )


def today_business_date() -> date:
    """Expose the business date to the API layer without duplicating timezone logic."""
    return _business_today()


def local_day_label(day: date) -> str:
    """Human label used in audit summaries and error messages."""
    return day.strftime("%Y-%m-%d")


__all__ = [
    "add_pairings",
    "approve_report",
    "collect_day_activity",
    "config_history",
    "create_bono_type",
    "create_correction",
    "create_incident",
    "create_issue",
    "create_report",
    "create_transfer",
    "day_summary",
    "flag_pairings_for_price_change",
    "local_day_label",
    "record_incident_deduction",
    "refresh_report",
    "reject_report",
    "remove_pairing",
    "resolve_incident",
    "resolve_pairing_review",
    "staff_balances_for_day",
    "submit_report",
    "today_business_date",
    "update_bono_type",
    "update_report",
]
