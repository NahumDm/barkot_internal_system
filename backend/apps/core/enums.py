"""Closed enums shared across the Barkot domain (spec §11.2).

Two kinds of enum live here and they are deliberately kept apart:

- **Business state enums** — the vocabulary a cashier and a manager use. These
  are Django model enums persisted in the database, so changing one is a
  migration and a spec change, not a deploy.
- **Permission codes** — the authorization vocabulary from spec §9.2, with a
  Django permission attached to each so ``user.has_perm`` is server-authoritative
  (principle P06) rather than an ad-hoc role check.

Every enum is a :class:`~django.db.models.TextChoices` subclass rather than a bare
``str`` constant so Django renders the same label everywhere and a typo in a
migration is caught at import time instead of producing a blank row.
"""

from __future__ import annotations

from typing import Final

from django.db import models
from django.utils.translation import gettext_lazy as _

# ── Inventory ───────────────────────────────────────────────────────────────


class MovementKind(models.TextChoices):
    """Inventory movement kinds (spec §11.2, §12).

    ``RECEIPT`` is the only increase a normal user may record. Everything else
    that decreases stock is a consequence of a documented event (a sale, a
    breakage entry, a count variance) or an explicit manager decision
    (``STOCK_OUT``). Keeping the set closed is what makes "sum of movements
    equals current stock" auditable.
    """

    RECEIPT = "RECEIPT", _("Stock receipt")
    SALE = "SALE", _("Sold")
    # A void is not an inbound purchase, so it gets its own kind rather than
    # reusing SALE. The ledger direction is derived from the kind alone, and
    # SALE is pinned to OUT, so a reversal recorded as SALE would subtract the
    # stock a second time instead of returning it.
    SALE_VOID = "SALE_VOID", _("Sale voided (stock returned)")
    BREAKAGE = "BREAKAGE", _("Breakage / waste")
    COUNT_VARIANCE = "COUNT_VARIANCE", _("Stock count variance")
    STOCK_IN = "STOCK_IN", _("Manual stock in")
    STOCK_OUT = "STOCK_OUT", _("Manual stock out")


class MovementSource(models.TextChoices):
    """Where a movement came from, so the ledger can be re-derived (spec §12)."""

    STOCK_RECEIPT = "STOCK_RECEIPT", _("Stock receipt")
    SALE = "SALE", _("Sale")
    BREAKAGE = "BREAKAGE", _("Breakage record")
    STOCK_COUNT = "STOCK_COUNT", _("Stock count")
    MANUAL = "MANUAL", _("Manual adjustment")


class MovementDirection(models.TextChoices):
    """Whether a movement adds to or removes from stock.

    Derived from :class:`MovementKind` and stored alongside it. Storing the
    direction is what lets current stock be a single ``SUM`` in the database
    rather than a ``CASE`` expression in every report that must agree with every
    other report. It is never set by hand; :func:`direction_for_kind` is the
    only writer.
    """

    IN = "IN", _("Stock in")
    OUT = "OUT", _("Stock out")


class StockCountStatus(models.TextChoices):
    """Stock count lifecycle (spec §12.3)."""

    DRAFT = "DRAFT", _("Draft")
    COMPLETED = "COMPLETED", _("Completed")
    APPROVED = "APPROVED", _("Approved")


class ReceiptStatus(models.TextChoices):
    """Stock receipt lifecycle."""

    DRAFT = "DRAFT", _("Draft")
    COMPLETED = "COMPLETED", _("Completed")
    APPROVED = "APPROVED", _("Approved")


# ── Sales and finance ───────────────────────────────────────────────────────


class PaymentMethod(models.TextChoices):
    """Payment methods, exactly as the client operates today (CD-02).

    ``MOBILE_BANKING`` is a *business category* — money received into the
    restaurant's bank account — not a payment gateway. No provider integration
    exists in this version; see ADR-0003 deviation D1.
    """

    CASH = "CASH", _("Cash")
    MOBILE_BANKING = "MOBILE_BANKING", _("Mobile banking")


class SaleStatus(models.TextChoices):
    """Sale lifecycle.

    ``COMPLETED`` is the only status that moves stock or income. ``VOIDED`` is a
    reversal: it is never a delete, and it leaves an auditable trail (spec §13.1).
    """

    COMPLETED = "COMPLETED", _("Completed")
    VOIDED = "VOIDED", _("Voided")


class PaymentStatus(models.TextChoices):
    """Payment lifecycle (spec §13.1)."""

    PENDING = "PENDING", _("Pending")
    PAID = "PAID", _("Paid")
    VOIDED = "VOIDED", _("Voided")


class ExpenseStatus(models.TextChoices):
    """Expense lifecycle (spec §13.2)."""

    RECORDED = "RECORDED", _("Recorded")
    APPROVED = "APPROVED", _("Approved")
    VOIDED = "VOIDED", _("Voided")


# ── Payroll ─────────────────────────────────────────────────────────────────


class EmployeeStatus(models.TextChoices):
    """Payroll employment status (spec §14.2)."""

    ACTIVE = "ACTIVE", _("Active")
    INACTIVE = "INACTIVE", _("Inactive")
    TERMINATED = "TERMINATED", _("Terminated")


class ContractType(models.TextChoices):
    """Employment contract kinds on an employee register record.

    The register (spec §5) is deliberately separate from ``EmployeeStatus``:
    status says whether the person is currently paid, contract says what they
    are employed *on*. An employee can be ``ACTIVE`` on a fixed-term contract
    that ends next month, which is exactly the case ``contract_end_date``
    exists to surface before it lapses.
    """

    FULL_TIME = "FULL_TIME", _("Full-time")
    PART_TIME = "PART_TIME", _("Part-time")
    CONTRACT = "CONTRACT", _("Contract")
    TEMPORARY = "TEMPORARY", _("Temporary")
    INTERN = "INTERN", _("Intern")


class PayrollRunStatus(models.TextChoices):
    """Payroll run lifecycle: generate → review → approve → mark paid (spec §14.1)."""

    GENERATED = "GENERATED", _("Generated")
    APPROVED = "APPROVED", _("Approved")
    PAID = "PAID", _("Paid")
    CANCELLED = "CANCELLED", _("Cancelled")


class PayrollItemStatus(models.TextChoices):
    """Per-employee run outcome (spec §14.2)."""

    PENDING = "PENDING", _("Pending")
    APPROVED = "APPROVED", _("Approved")
    PAID = "PAID", _("Paid")


class PayrollDeductionType(models.TextChoices):
    """Deduction kinds (spec §14.2).

    ``OTHER`` exists because the client has not yet confirmed the statutory
    calculation rules (spec §30 items 5-6). Statutory categories are deliberately
    absent until the accountant confirms them, rather than being guessed.
    """

    ADVANCE = "ADVANCE", _("Salary advance")
    ABSENCE = "ABSENCE", _("Absence")
    LATE = "LATE", _("Tardiness")
    OTHER = "OTHER", _("Other")


#: Which :class:`MovementDirection` each :class:`MovementKind` implies. This
#: mapping is the single source of truth for ledger signs; nothing else in the
#: codebase is allowed to decide that a sale is an ``OUT``.
KIND_DIRECTIONS: Final[dict[str, str]] = {
    MovementKind.RECEIPT: MovementDirection.IN,
    MovementKind.STOCK_IN: MovementDirection.IN,
    MovementKind.SALE: MovementDirection.OUT,
    MovementKind.SALE_VOID: MovementDirection.IN,
    MovementKind.BREAKAGE: MovementDirection.OUT,
    MovementKind.STOCK_OUT: MovementDirection.OUT,
    # A count variance is a correction, so its direction depends on the sign of
    # the variance and is resolved at write time rather than declared here.
}


def direction_for_kind(kind: str, *, variance: str | None = None) -> str:
    """Return the ledger direction for a movement.

    Args:
        kind: A :class:`MovementKind` value.
        variance: For ``COUNT_VARIANCE`` only, the sign of the variance —
            ``"IN"`` when the count was higher than expected, ``"OUT"`` when
            lower. Ignored for every other kind.

    Returns:
        A :class:`MovementDirection` value.

    Raises:
        ValueError: If ``kind`` is unknown, or a count variance is requested
            without a direction.
    """
    try:
        return KIND_DIRECTIONS[kind]
    except KeyError:
        if kind == MovementKind.COUNT_VARIANCE:
            if variance in {MovementDirection.IN, MovementDirection.OUT}:
                return variance
            raise ValueError(
                "A COUNT_VARIANCE movement requires variance='IN' or variance='OUT'."
            ) from None
        raise ValueError(f"Unknown movement kind {kind!r}.") from None
