"""Read-only report query services (spec §15.1, §15.2).

The reports app never owns source truth; these functions answer the four
questions the spec asks (§15.1) by reading the authoritative records of the
domains that actually change:

- **Financial balance** delegates to ``finance.services.finance_balance``, the
  same service the C1 balance endpoint calls. Two implementations of "what is
  net pay" would disagree eventually, and a report page showing a different
  number than the finance screen is the exact failure the spec's "never owns
  source truth" rule exists to prevent.
- **Inventory stock balance** sums the append-only movement ledger *
  up to a business date* (what should exist) and compares it to the latest
  approved physical count (what was counted).
- **Inventory variance** lists the approved count lines where expected and
  counted disagreed, which is what "where do they differ" means.
- **Payroll** sums each run's lines for the months in the period, alongside the
  deduction breakdown, so "what is owed/paid for the month" is answered from
  the run rows rather than from numbers typed elsewhere.

Filters are pushed to PostgreSQL (aggregations, not per-row loads into Python)
per §15.2, and all money and quantities are quantised to the project's fixed
precisions so the CSV and JSON agree character for character.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Case, Count, F, Q, Sum, When

from apps.core.business_time import business_date, business_period_bounds
from apps.core.enums import MovementDirection, PayrollDeductionType, PayrollRunStatus
from apps.core.fields import QuantityField
from apps.core.money import ZERO_MONEY, ZERO_QUANTITY, quantize_money, quantize_quantity
from apps.inventory.models import StockCountItem, StockMovement
from apps.payroll.models import PayrollDeduction, PayrollRun
from apps.products.models import Product


@dataclass(frozen=True, slots=True)
class StockBalanceRow:
    """One product on the stock balance report (spec §15.1)."""

    product_id: int
    sku: str
    name: str
    ledger_balance: Decimal
    last_counted: Decimal | None
    last_counted_on: date | None
    delta: Decimal | None

    def as_dict(self) -> dict[str, object]:
        return {
            "product_id": self.product_id,
            "sku": self.sku,
            "name": self.name,
            "ledger_balance": str(self.ledger_balance),
            "last_counted": str(self.last_counted) if self.last_counted is not None else None,
            "last_counted_on": self.last_counted_on.isoformat() if self.last_counted_on else None,
            "delta": str(self.delta) if self.delta is not None else None,
        }


@dataclass(frozen=True, slots=True)
class StockBalanceReport:
    """Ledger balance vs latest approved count, for the products that moved."""

    as_of: date
    rows: tuple[StockBalanceRow, ...]

    @property
    def in_stock_total(self) -> Decimal:
        return quantize_quantity(sum((row.ledger_balance for row in self.rows), ZERO_QUANTITY))

    def as_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of.isoformat(),
            "in_stock_total": str(self.in_stock_total),
            "products": len(self.rows),
            "rows": [row.as_dict() for row in self.rows],
        }


@dataclass(frozen=True, slots=True)
class StockVarianceRow:
    """One approved count line whose counted quantity differed from expected."""

    stock_count_id: int
    reference: str
    status: str
    product_id: int
    sku: str
    name: str
    counted_on: date
    expected_quantity: Decimal
    counted_quantity: Decimal
    variance: Decimal
    note: str

    def as_dict(self) -> dict[str, object]:
        return {
            "stock_count_id": self.stock_count_id,
            "reference": self.reference,
            "status": self.status,
            "product_id": self.product_id,
            "sku": self.sku,
            "name": self.name,
            "counted_on": self.counted_on.isoformat(),
            "expected_quantity": str(self.expected_quantity),
            "counted_quantity": str(self.counted_quantity),
            "variance": str(self.variance),
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class StockVarianceReport:
    """Approved count variances in a period (spec §15.1)."""

    start: date
    end: date
    rows: tuple[StockVarianceRow, ...]

    @property
    def expected_total(self) -> Decimal:
        return quantize_quantity(sum((row.expected_quantity for row in self.rows), ZERO_QUANTITY))

    @property
    def counted_total(self) -> Decimal:
        return quantize_quantity(sum((row.counted_quantity for row in self.rows), ZERO_QUANTITY))

    @property
    def variance_total(self) -> Decimal:
        return quantize_quantity(sum((row.variance for row in self.rows), ZERO_QUANTITY))

    def as_dict(self) -> dict[str, object]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "lines": len(self.rows),
            "expected_total": str(self.expected_total),
            "counted_total": str(self.counted_total),
            "variance_total": str(self.variance_total),
            "rows": [row.as_dict() for row in self.rows],
        }


@dataclass(frozen=True, slots=True)
class PayrollRunRow:
    """One payroll run on the payroll report (spec §15.1)."""

    run_id: int
    period_month: date
    status: str
    status_display: str
    currency: str
    employees: int
    gross_total: Decimal
    deduction_total: Decimal
    net_total: Decimal

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "period_month": self.period_month.isoformat(),
            "status": self.status,
            "status_display": self.status_display,
            "currency": self.currency,
            "employees": self.employees,
            "gross_total": str(self.gross_total),
            "deduction_total": str(self.deduction_total),
            "net_total": str(self.net_total),
        }


@dataclass(frozen=True, slots=True)
class PayrollStatusBucket:
    """One run status's share of the period's net pay."""

    status: str
    status_display: str
    runs: int
    gross_total: Decimal
    deduction_total: Decimal
    net_total: Decimal

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "status_display": self.status_display,
            "runs": self.runs,
            "gross_total": str(self.gross_total),
            "deduction_total": str(self.deduction_total),
            "net_total": str(self.net_total),
        }


@dataclass(frozen=True, slots=True)
class PayrollReport:
    """How much is owed and paid for the months in the period (spec §15.1).

    Only a comment, not a judgement: a ``GENERATED`` run is a proposal awaiting
    the Owner, an ``APPROVED`` run is money the Owner has signed off, and only a
    ``PAID`` run has left the account. The buckets keep that separation instead
    of folding every run into one net total.
    """

    start: date
    end: date
    currency: str
    rows: tuple[PayrollRunRow, ...]
    buckets: tuple[PayrollStatusBucket, ...]
    deductions: dict[str, str]

    @property
    def runs(self) -> int:
        return len(self.rows)

    @property
    def gross_total(self) -> Decimal:
        return quantize_money(sum((row.gross_total for row in self.rows), ZERO_MONEY))

    @property
    def deduction_total(self) -> Decimal:
        return quantize_money(sum((row.deduction_total for row in self.rows), ZERO_MONEY))

    @property
    def net_total(self) -> Decimal:
        return quantize_money(sum((row.net_total for row in self.rows), ZERO_MONEY))

    def as_dict(self) -> dict[str, object]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "currency": self.currency,
            "rows": [row.as_dict() for row in self.rows],
            "summary": {
                "runs": self.runs,
                "gross_total": str(self.gross_total),
                "deduction_total": str(self.deduction_total),
                "net_total": str(self.net_total),
                "by_status": [bucket.as_dict() for bucket in self.buckets],
            },
            "deductions": self.deductions,
        }


def inventory_stock_balance(*, as_of: date) -> StockBalanceReport:
    """Return ledger stock vs latest approved count, as of one business day.

    The ledger side is a single signed ``SUM`` up to the end of ``as_of``'s
    business day; the sign lives in :data:`MovementDirection`, which no report
    reimplements (spec §12). Only ``COUNT_VARIANCE``/``SALE_VOID`` kind rows
    would disagree with a forward-sum today, and the direction column already
    handles them.

    Products that have never moved by the as-of date are omitted: a product
    with no history is not a stock discrepancy worth reporting. Products that
    exist but have never been counted carry a ``None`` "last counted" rather
    than a fake zero, so the screen can say "not counted yet" as a real state.
    """
    _, end_utc = business_period_bounds(as_of, as_of)
    products = (
        Product.objects.filter(is_stock_tracked=True)
        .filter(stock_movements__occurred_at__lt=end_utc)
        .distinct()
        .order_by("name")
    )

    balances = dict(
        StockMovement.objects.filter(occurred_at__lt=end_utc)
        .values("product_id")
        .annotate(
            balance=Sum(
                Case(
                    When(direction=MovementDirection.OUT, then=F("quantity") * Decimal("-1")),
                    default=F("quantity"),
                    output_field=QuantityField(),
                ),
                output_field=QuantityField(),
            )
        )
        .values_list("product_id", "balance")
    )

    count_rows = (
        StockCountItem.objects.filter(
            stock_count__approved_at__isnull=False,
            stock_count__counted_at__lt=end_utc,
            product_id__in=[product.pk for product in products],
        )
        .order_by("-stock_count__counted_at", "-id")
        .select_related("stock_count")
    )
    latest: dict[int, StockCountItem] = {}
    for item in count_rows:
        latest.setdefault(item.product_id, item)

    rows: list[StockBalanceRow] = []
    for product in products:
        ledger = quantize_quantity(balances.get(product.pk, ZERO_QUANTITY))
        latest_count = latest.get(product.pk)
        counted = quantize_quantity(latest_count.counted_quantity) if latest_count else None
        counted_on = business_date(latest_count.stock_count.counted_at) if latest_count else None
        rows.append(
            StockBalanceRow(
                product_id=product.pk,
                sku=product.sku,
                name=product.name,
                ledger_balance=ledger,
                last_counted=counted,
                last_counted_on=counted_on,
                delta=quantize_quantity(counted - ledger) if counted is not None else None,
            )
        )
    return StockBalanceReport(as_of=as_of, rows=tuple(rows))


def inventory_variance(*, start: date, end: date) -> StockVarianceReport:
    """Return approved count variances in an inclusive business date range.

    Only approved counts count: a ``COMPLETED`` count is a submission awaiting
    the Manager, and reporting its lines would surface discrepancies nobody has
    agreed to yet. Lines whose variance is exactly zero are omitted — a report
    about "where expected and actual differ" does not list the rows where they
    agree.
    """
    start_utc, end_utc = business_period_bounds(start, end)
    rows = []
    for item in (
        StockCountItem.objects.filter(
            variance__isnull=False,
            stock_count__approved_at__isnull=False,
            stock_count__counted_at__gte=start_utc,
            stock_count__counted_at__lt=end_utc,
        )
        .exclude(variance=ZERO_QUANTITY)
        .select_related("product", "stock_count")
        .order_by("-stock_count__counted_at", "product__name", "id")
    ):
        rows.append(
            StockVarianceRow(
                stock_count_id=item.stock_count_id,
                reference=item.stock_count.reference,
                status=item.stock_count.get_status_display(),
                product_id=item.product_id,
                sku=item.product.sku,
                name=item.product.name,
                counted_on=business_date(item.stock_count.counted_at),
                expected_quantity=quantize_quantity(item.expected_quantity, field="expected"),
                counted_quantity=quantize_quantity(item.counted_quantity, field="counted"),
                variance=quantize_quantity(item.variance, field="variance"),
                note=item.note,
            )
        )
    return StockVarianceReport(start=start, end=end, rows=tuple(rows))


def payroll_report(*, start: date, end: date) -> PayrollReport:
    """Return payroll runs and totals for the months in ``[start, end]``.

    A run's ``period_month`` is the first of the month being paid, so the same
    inclusive date comparison used everywhere else places a September run in a
    September report (see ``finance.services.approved_payroll_total``).

    Totals are the same ``SUM`` over ``items`` the models already expose, taken
    here in one aggregation per report rather than one query per property so a
    ten-year report is still constant-round-trips. ``GENERATED`` runs are owed
    but not yet approved; only ``APPROVED`` and ``PAID`` would move the finance
    balance, and the buckets keep that readable.
    """
    period = Q(period_month__gte=start) & Q(period_month__lte=end)
    runs = (
        PayrollRun.objects.filter(period)
        .annotate(
            employees=Count("items", distinct=True),
            gross=Sum("items__gross_amount"),
            deductions=Sum("items__total_deductions"),
            net=Sum("items__net_amount"),
        )
        .order_by("-period_month", "-id")
    )

    rows: list[PayrollRunRow] = []
    buckets_raw: dict[str, dict[str, Any]] = {}
    currency = "ETB"
    for run in runs:
        currency = run.currency or currency
        gross = quantize_money(run.gross or ZERO_MONEY)
        deduction_sum = quantize_money(run.deductions or ZERO_MONEY)
        net = quantize_money(run.net or ZERO_MONEY)
        rows.append(
            PayrollRunRow(
                run_id=run.pk,
                period_month=run.period_month,
                status=run.status,
                status_display=run.get_status_display(),
                currency=run.currency,
                employees=run.employees,
                gross_total=gross,
                deduction_total=deduction_sum,
                net_total=net,
            )
        )
        bucket = buckets_raw.setdefault(
            run.status,
            {
                "status": run.status,
                "status_display": run.get_status_display(),
                "runs": 0,
                "gross_total": ZERO_MONEY,
                "deduction_total": ZERO_MONEY,
                "net_total": ZERO_MONEY,
            },
        )
        bucket["runs"] = int(bucket["runs"]) + 1
        bucket["gross_total"] = Decimal(bucket["gross_total"]) + gross
        bucket["deduction_total"] = Decimal(bucket["deduction_total"]) + deduction_sum
        bucket["net_total"] = Decimal(bucket["net_total"]) + net

    preferred = (
        PayrollRunStatus.GENERATED,
        PayrollRunStatus.APPROVED,
        PayrollRunStatus.PAID,
    )
    bucket_order = [str(s) for s in preferred if s in buckets_raw]
    bucket_order.extend(s for s in buckets_raw if s not in bucket_order)
    buckets = tuple(
        PayrollStatusBucket(
            status=str(b["status"]),
            status_display=str(b["status_display"]),
            runs=int(b["runs"]),
            gross_total=quantize_money(b["gross_total"]),
            deduction_total=quantize_money(b["deduction_total"]),
            net_total=quantize_money(b["net_total"]),
        )
        for b in (buckets_raw[s] for s in bucket_order)
    )

    deduction_rows = (
        PayrollDeduction.objects.filter(
            payroll_item__run__period_month__gte=start,
            payroll_item__run__period_month__lte=end,
            voided_at__isnull=True,
        )
        .values("deduction_type")
        .annotate(total=Sum("amount"))
        .order_by("deduction_type")
    )
    deductions = {
        str(PayrollDeductionType(row["deduction_type"]).label): str(
            quantize_money(row["total"] or ZERO_MONEY)
        )
        for row in deduction_rows
    }

    return PayrollReport(
        start=start,
        end=end,
        currency=currency,
        rows=tuple(rows),
        buckets=buckets,
        deductions=deductions,
    )


__all__ = [
    "PayrollReport",
    "PayrollRunRow",
    "PayrollStatusBucket",
    "StockBalanceReport",
    "StockBalanceRow",
    "StockVarianceReport",
    "StockVarianceRow",
    "inventory_stock_balance",
    "inventory_variance",
    "payroll_report",
]
