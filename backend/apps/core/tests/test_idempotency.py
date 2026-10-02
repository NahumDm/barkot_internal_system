"""Idempotency for sale writes, and receipt numbers under contention (roadmap A10).

A10 has two halves, and this module covers both against
:func:`apps.sales.services.complete_sale`:

* **A key makes a retry safe.** §10.2 asks that financial and stock-creating writes
  accept an ``Idempotency-Key``, because a weak network or an accidental
  double-click must not create duplicate sales. The gate is "the same key twice
  creates one sale, not two".
* **A receipt number is allocated once.** ``next_sale_reference`` derives the day's
  number from a ``COUNT()``, which is what makes the no-skipped-numbers promise
  possible and is also what made it racy: two concurrent sales both read "3 used".

Neither half is proved through HTTP. A10 is Phase A's last task and no business
endpoint exists yet, so the guarantee is asserted where it actually lives - the
service layer. Inventing a route to carry a header would be a business endpoint by
another name, and the roadmap forbids exactly that.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest
from django.db import connections, transaction

from apps.accounts.models import Role, User
from apps.core.business_time import business_date, now_utc
from apps.core.enums import PaymentMethod
from apps.core.exceptions import IdempotencyInFlight, IdempotencyKeyReuse, InsufficientStock
from apps.core.idempotency import (
    SALE_SCOPE,
    IdempotencyRecord,
    claim_key,
    fingerprint,
    replayed_object,
)
from apps.inventory.models import StockMovement
from apps.inventory.services import ReceiptLineInput, current_stock, receive_stock
from apps.products.models import Category, Product, ProductPrice
from apps.sales.models import Sale
from apps.sales.services import SaleLineInput, complete_sale

pytestmark = pytest.mark.django_db

#: The catalogue price every product fixture is given.
UNIT_PRICE = Decimal("60.00")

#: Enough stock that no test accidentally fails on quantity rather than on the
#: thing it is actually testing.
STOCKED = Decimal("100")


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def category() -> Category:
    return Category.objects.create(name="Beer")


@pytest.fixture
def product(category: Category) -> Product:
    return Product.objects.create(
        category=category,
        name="Beko 330ml",
        sku="BEKO-330",
        is_stock_tracked=True,
    )


@pytest.fixture
def price(product: Product) -> ProductPrice:
    return ProductPrice.objects.create(
        product=product,
        unit_price=UNIT_PRICE,
        effective_from=now_utc(),
    )


@pytest.fixture
def stocked(product: Product, price: ProductPrice) -> Product:
    receive_stock(
        supplier_name="Test Supplier",
        lines=[ReceiptLineInput(product=product, quantity=STOCKED, unit_cost=Decimal("40.00"))],
    )
    return product


@pytest.fixture
def owner(make_staff_user: Callable[..., Any]) -> User:
    return make_staff_user(Role.Code.OWNER)


@pytest.fixture
def one_beer(stocked: Product) -> SaleLineInput:
    return SaleLineInput(product=stocked, quantity=Decimal("1"))


@pytest.fixture
def one_beer_cash() -> list[tuple[PaymentMethod, Decimal]]:
    return [(PaymentMethod.CASH, UNIT_PRICE)]


# ── 1. The gate: the same key twice creates one sale, not two ────────────────


def test_the_same_key_twice_creates_one_sale_not_two(
    one_beer: SaleLineInput, one_beer_cash: list[tuple[PaymentMethod, Decimal]]
) -> None:
    """The A10 gate, stated the way the roadmap states it.

    A retry must return the first sale. A second sale, a fresh reference, or a
    second draw-down of stock is the duplicate §10.2 exists to prevent.
    """
    first = complete_sale(lines=[one_beer], payments=one_beer_cash, idempotency_key="pos-1-0001")
    second = complete_sale(lines=[one_beer], payments=one_beer_cash, idempotency_key="pos-1-0001")

    assert second.pk == first.pk
    assert Sale.all_rows.count() == 1
    # The retry must not touch stock twice either: 100 received, 1 sold, once.
    assert current_stock(one_beer.product) == STOCKED - 1


def test_a_retry_returns_the_original_reference_and_nothing_is_burned(
    one_beer: SaleLineInput, one_beer_cash: list[tuple[PaymentMethod, Decimal]]
) -> None:
    """The replayed object is the same row, reference included.

    Comparing the primary key is the weak check. Comparing the reference is the one
    a cashier notices: a fresh sale would have consumed the next number on the day's
    roll and left a gap in it.
    """
    first = complete_sale(lines=[one_beer], payments=one_beer_cash, idempotency_key="pos-2-0001")
    second = complete_sale(lines=[one_beer], payments=one_beer_cash, idempotency_key="pos-2-0001")

    assert second.reference == first.reference
    assert second.total == first.total
    assert list(Sale.all_rows.values_list("reference", flat=True)) == [first.reference]


def test_a_retry_that_omitted_sold_at_both_times_still_replays(
    one_beer: SaleLineInput, one_beer_cash: list[tuple[PaymentMethod, Decimal]]
) -> None:
    """Omitting ``sold_at`` must not make every attempt a different request.

    This is the case that a fingerprint built from the service's *resolved*
    timestamp gets wrong: ``now_utc()`` returns a new instant every call, so the
    retry hashes differently and the double-click comes back as a key-reuse error
    instead of the first sale. Neither call passes ``sold_at`` here, which is what
    an ordinary POS does.
    """
    first = complete_sale(lines=[one_beer], payments=one_beer_cash, idempotency_key="pos-2-0002")
    second = complete_sale(lines=[one_beer], payments=one_beer_cash, idempotency_key="pos-2-0002")

    assert second.pk == first.pk
    assert Sale.all_rows.count() == 1


def test_a_retry_with_equivalent_money_spellings_still_replays(
    stocked: Product, one_beer_cash: list[tuple[PaymentMethod, Decimal]]
) -> None:
    """``2.00`` then ``2`` is the same basket, not a reused key.

    A client that formats currency on one attempt and not the next would otherwise
    be told its own retry was a different sale - a 409 shown to a cashier who did
    nothing but press the button twice.
    """
    first = complete_sale(
        lines=[SaleLineInput(product=stocked, quantity=Decimal("2.00"))],
        payments=[(PaymentMethod.CASH, Decimal("120.00"))],
        idempotency_key="pos-2-0003",
    )
    second = complete_sale(
        lines=[SaleLineInput(product=stocked, quantity=Decimal("2"))],
        payments=[(PaymentMethod.CASH, Decimal("120"))],
        idempotency_key="pos-2-0003",
    )

    assert second.pk == first.pk
    assert current_stock(stocked) == STOCKED - 2


# ── 2. A key is a claim about content, not just a token ─────────────────────


def test_the_same_key_with_a_different_basket_is_refused(
    one_beer: SaleLineInput, one_beer_cash: list[tuple[PaymentMethod, Decimal]]
) -> None:
    """A key reused for a different sale must fail, not return the first result.

    Returning the first sale would be the worst available answer: the caller would
    believe its second, different request had been recorded. Both baskets here are
    internally consistent, so the key is the only possible reason for the second to
    fail - a basket that did not add up would be refused for the wrong reason and
    would keep being "refused" even if the fingerprint stopped distinguishing them.
    """
    two_beers = SaleLineInput(product=one_beer.product, quantity=Decimal("2"))
    complete_sale(
        lines=[two_beers],
        payments=[(PaymentMethod.CASH, Decimal("120.00"))],
        idempotency_key="pos-3-0001",
    )

    with pytest.raises(IdempotencyKeyReuse) as raised:
        complete_sale(
            lines=[one_beer],
            payments=one_beer_cash,
            idempotency_key="pos-3-0001",
        )

    assert raised.value.status_code == 409
    assert Sale.all_rows.count() == 1
    # The refused attempt must not have moved stock either.
    assert current_stock(one_beer.product) == STOCKED - 2


def test_the_same_key_for_a_different_product_is_refused(stocked: Product) -> None:
    """Changing the line, not just the total, is a different request.

    Both products are stocked and priced, so the key is the only possible reason for
    the refusal. A test that relied on the second sale failing for lack of stock
    would pass for the wrong reason, and would keep passing if the fingerprint
    stopped distinguishing products.
    """
    cellar = Category.objects.create(name="Cellar")
    wine = Product.objects.create(
        category=cellar, name="Merlot 750ml", sku="MERLOT-750", is_stock_tracked=True
    )
    ProductPrice.objects.create(product=wine, unit_price=Decimal("80.00"), effective_from=now_utc())
    receive_stock(
        supplier_name="Wine Supplier",
        lines=[ReceiptLineInput(product=wine, quantity=Decimal("10"), unit_cost=Decimal("50.00"))],
    )

    complete_sale(
        lines=[SaleLineInput(product=stocked, quantity=Decimal("1"))],
        payments=[(PaymentMethod.CASH, UNIT_PRICE)],
        idempotency_key="pos-3-0002",
    )

    with pytest.raises(IdempotencyKeyReuse):
        complete_sale(
            lines=[SaleLineInput(product=wine, quantity=Decimal("1"))],
            payments=[(PaymentMethod.CASH, Decimal("80.00"))],
            idempotency_key="pos-3-0002",
        )

    assert Sale.all_rows.count() == 1
    assert current_stock(wine) == Decimal("10")


def test_keys_are_scoped_so_two_operations_may_share_one(
    one_beer: SaleLineInput, one_beer_cash: list[tuple[PaymentMethod, Decimal]]
) -> None:
    """The same key value on a different scope is a different claim.

    Scoping is what lets a client use one key per request without a global namespace
    it has to coordinate. Without it, a stock receipt reusing a sale's key would be
    refused for no reason a user could put into words.
    """
    complete_sale(lines=[one_beer], payments=one_beer_cash, idempotency_key="shared-key")

    other = claim_key(scope="inventory.receive_stock", key="shared-key", body={"supplier": "X"})

    assert other.replayed is False
    assert other.guarded is True


# ── 3. The claim row is the mechanism, so it is worth reading ───────────────


def test_the_claim_names_the_sale_the_first_attempt_created(
    one_beer: SaleLineInput, one_beer_cash: list[tuple[PaymentMethod, Decimal]]
) -> None:
    """A claim has to be evidence, and it has to point at something.

    A claim that existed but named nothing could not answer a retry, and a replay
    that quietly created a replacement sale would be the very defect this is for.
    """
    sale = complete_sale(lines=[one_beer], payments=one_beer_cash, idempotency_key="pos-4-0001")

    record = IdempotencyRecord.objects.get(scope=SALE_SCOPE, key="pos-4-0001")
    assert record.object_id == str(sale.pk)
    assert record.object_type == f"{Sale.__module__}.{Sale.__qualname__}"
    # The fingerprint is over the request, not over the row it produced, so it is
    # recorded before the sale exists and does not change afterwards.
    assert len(record.request_fingerprint) == 64


def test_a_replayed_claim_hands_back_the_stored_object(
    one_beer: SaleLineInput, one_beer_cash: list[tuple[PaymentMethod, Decimal]]
) -> None:
    """``replayed_object`` resolves the recorded reference to the real row.

    Worth a direct test because it is the one place a label stored in the database
    is turned back into a query, and a label that stopped matching its model would
    otherwise surface as a confusing "in flight" on every retry.
    """
    from apps.sales.services import _sale_fingerprint_body

    moment = now_utc()
    body = _sale_fingerprint_body(lines=[one_beer], payments=one_beer_cash, sold_at=moment, note="")
    claim = claim_key(scope=SALE_SCOPE, key="pos-4-0002", body=body)
    sale = Sale.objects.create(
        reference="S-20260101-0001",
        sold_at=moment,
        subtotal=UNIT_PRICE,
        total=UNIT_PRICE,
        amount_paid=UNIT_PRICE,
        note="",
    )
    claim.produced(sale)

    replay = claim_key(scope=SALE_SCOPE, key="pos-4-0002", body=body)

    assert replay.replayed is True
    assert replayed_object(replay, Sale) == sale


def test_a_claim_without_a_result_is_reported_as_in_flight() -> None:
    """The half-finished case: the first attempt claimed the key and is still working.

    "In flight" asks the client to retry *the same key*, which is the remedy.
    Reporting success would be a lie, and minting a new key would let the duplicate
    through.
    """
    IdempotencyRecord.objects.create(
        scope=SALE_SCOPE, key="in-flight", request_fingerprint=fingerprint({"x": 1})
    )

    with pytest.raises(IdempotencyInFlight) as raised:
        claim_key(scope=SALE_SCOPE, key="in-flight", body={"x": 1})

    assert raised.value.status_code == 409


def test_a_replay_whose_sale_is_gone_is_refused_not_recreated(
    stocked: Product, one_beer_cash: list[tuple[PaymentMethod, Decimal]]
) -> None:
    """A claim whose result has vanished must not be quietly replaced.

    "The object is gone, so let me write a new one" is precisely the reasoning that
    turns a retry into a duplicate. The key stays spent and the caller is told to
    record the sale under a new one.
    """
    from apps.sales.services import _sale_fingerprint_body

    line = SaleLineInput(product=stocked, quantity=Decimal("1"))
    moment = now_utc()
    body = _sale_fingerprint_body(lines=[line], payments=one_beer_cash, sold_at=moment, note="")
    IdempotencyRecord.objects.create(
        scope=SALE_SCOPE,
        key="orphan",
        request_fingerprint=fingerprint(body),
        object_type=f"{Sale.__module__}.{Sale.__qualname__}",
        object_id="999999999",
    )

    with pytest.raises(IdempotencyInFlight, match="no longer exists"):
        complete_sale(
            lines=[line],
            payments=one_beer_cash,
            sold_at=moment,
            idempotency_key="orphan",
        )

    assert not Sale.all_rows.exists()


def test_a_failed_sale_leaves_no_claim_behind(stocked: Product) -> None:
    """The claim and the work it guards commit or roll back together.

    If the claim survived a failed sale, the key would be spent on a sale that never
    happened and every retry would be refused forever - the customer could not
    complete the transaction at all. The restock here proves the same key is still
    usable afterwards.
    """
    too_many = SaleLineInput(product=stocked, quantity=Decimal("500"))

    with pytest.raises(InsufficientStock):
        complete_sale(
            lines=[too_many],
            payments=[(PaymentMethod.CASH, Decimal("30000.00"))],
            idempotency_key="rolled-back",
        )

    assert not IdempotencyRecord.objects.filter(key="rolled-back").exists()

    receive_stock(
        supplier_name="Restock",
        lines=[
            ReceiptLineInput(product=stocked, quantity=Decimal("500"), unit_cost=Decimal("40.00"))
        ],
    )
    sale = complete_sale(
        lines=[too_many],
        payments=[(PaymentMethod.CASH, Decimal("30000.00"))],
        idempotency_key="rolled-back",
    )

    assert sale.pk is not None
    assert IdempotencyRecord.objects.filter(key="rolled-back").count() == 1


# ── 4. No key means no promise to keep ──────────────────────────────────────


def test_omitting_the_key_records_two_sales(
    one_beer: SaleLineInput, one_beer_cash: list[tuple[PaymentMethod, Decimal]]
) -> None:
    """Two keyless calls are two sales, and that is correct.

    Refusing to sell because a caller did not send a key would be worse than the
    duplicate it prevents: a management command that runs once, or a deliberate
    second sale at the till, must still work.
    """
    first = complete_sale(lines=[one_beer], payments=one_beer_cash)
    second = complete_sale(lines=[one_beer], payments=one_beer_cash)

    assert first.pk != second.pk
    assert Sale.all_rows.count() == 2
    assert not IdempotencyRecord.objects.exists()


def test_an_unguarded_call_writes_no_claim_row() -> None:
    """The synthetic claim for a keyless call is never persisted.

    It exists so a caller needs no branch on whether the request was guarded.
    Persisting it would put empty keys in the table and make the unique constraint
    mean something other than what its name says.
    """
    claim = claim_key(scope=SALE_SCOPE, key=None, body={"x": 1})

    assert claim.guarded is False
    assert claim.replayed is False

    # Safe to call: an unguarded claim returns before it looks at the object.
    claim.produced(Sale(reference="S-20260101-0001"))

    assert not IdempotencyRecord.objects.exists()


def test_a_key_is_trimmed_before_it_is_stored(
    one_beer: SaleLineInput, one_beer_cash: list[tuple[PaymentMethod, Decimal]]
) -> None:
    """A padded key is the same key.

    Otherwise a proxy that trims on one request and not the next would let a retry
    through as a new sale.
    """
    complete_sale(lines=[one_beer], payments=one_beer_cash, idempotency_key="  padded-key  ")

    assert IdempotencyRecord.objects.filter(scope=SALE_SCOPE, key="padded-key").exists()


# ── Concurrency ─────────────────────────────────────────────────────────────
#
# These are marked ``transaction=True``. Under the default ``django_db`` the test
# runs inside a transaction that is rolled back, and a worker thread on its own
# connection would not see the fixture data at all - the threads would race over an
# empty database and the assertions would pass without anything having been
# allocated. ``transaction=True`` commits the setup, so the workers contend for the
# same rows the test just wrote.


@dataclass(slots=True)
class _Outcome:
    """What one worker thread did, captured for the assertion to explain."""

    index: int
    value: Any = None
    error: BaseException | None = None

    def __str__(self) -> str:
        if self.error is not None:
            return f"worker {self.index} raised {type(self.error).__name__}: {self.error}"
        return f"worker {self.index} returned {self.value!r}"


def _race(workers: int, job: Callable[[int], Any]) -> list[_Outcome]:
    """Run ``job`` in ``workers`` threads released from a barrier together.

    Every worker opens its own connection and its own transaction, which is the
    point: a worker that shared the test's transaction would serialise behind it
    and the test would report a race that never happened.

    Args:
        workers: How many threads to start.
        job: Called with the worker's index. Exceptions are captured, not raised, so
            the assertion can report which worker lost and how.

    Returns:
        One :class:`_Outcome` per worker, in index order.
    """
    barrier = threading.Barrier(workers, timeout=30)
    outcomes: list[_Outcome] = []
    collected = threading.Lock()

    def run(index: int) -> None:
        outcome = _Outcome(index=index)
        try:
            with transaction.atomic():
                barrier.wait()
                try:
                    outcome.value = job(index)
                except Exception as exc:
                    outcome.error = exc
        except BaseException as exc:
            outcome.error = exc
        finally:
            # The worker's connection has to go, or the suite cannot flush.
            connections.close_all()
            with collected:
                outcomes.append(outcome)

    threads = [
        threading.Thread(target=run, args=(index,), name=f"a10-{index}") for index in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    hung = [thread.name for thread in threads if thread.is_alive()]
    assert not hung, f"workers hung: {hung}"
    assert len(outcomes) == workers, f"only {len(outcomes)} of {workers} finished"
    return sorted(outcomes, key=lambda outcome: outcome.index)


@pytest.mark.django_db(transaction=True)
def test_the_double_click_produces_one_sale_and_one_draw_down(
    stocked: Product, one_beer_cash: list[tuple[PaymentMethod, Decimal]]
) -> None:
    """Two connections, one key, released together: the real A10 race.

    Sequence-based coverage cannot reach this. Both workers genuinely contend for
    the ``(scope, key)`` unique constraint at the database rather than one of them
    observing the other's uncommitted work. The loser's insert blocks until the
    winner commits, so it should come back as a replay of the same sale - the key
    property being that the loser does not write a second one.
    """
    moment = now_utc()

    def sell(_index: int) -> int:
        return complete_sale(
            lines=[SaleLineInput(product=stocked, quantity=Decimal("1"))],
            payments=one_beer_cash,
            sold_at=moment,
            idempotency_key="double-click",
        ).pk

    outcomes = _race(2, sell)

    assert not [outcome for outcome in outcomes if outcome.error], outcomes
    assert len({outcome.value for outcome in outcomes}) == 1, outcomes
    assert Sale.all_rows.count() == 1
    # One claim, one sale, one line, one payment, and stock drawn down exactly once.
    assert IdempotencyRecord.objects.filter(scope=SALE_SCOPE, key="double-click").count() == 1
    assert Sale.all_rows.get().items.count() == 1
    assert current_stock(stocked) == STOCKED - 1
    assert StockMovement.objects.filter(product=stocked, sale_item__isnull=False).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_receipt_numbers_are_distinct_and_leave_no_gap(
    stocked: Product, one_beer_cash: list[tuple[PaymentMethod, Decimal]]
) -> None:
    """Four sales at once must take four different numbers off one day's roll.

    This is the race ``next_sale_reference`` had. Each worker counts the day's
    sales, so without the advisory lock all four read the same count and return the
    same reference; the ``unique`` constraint on ``Sale.reference`` then turns three
    of them into an ``IntegrityError`` - a 500 for a cashier who did nothing wrong,
    on numbers burned by sales that never landed. With the lock the count is taken
    one worker at a time and the numbers come out contiguous.
    """
    moment = now_utc()
    day = business_date(moment)

    def sell(index: int) -> str:
        return complete_sale(
            lines=[SaleLineInput(product=stocked, quantity=Decimal("1"))],
            payments=one_beer_cash,
            sold_at=moment,
            # Distinct keys: these are four deliberate sales, not one retried four
            # times. This isolates reference allocation from idempotency.
            idempotency_key=f"concurrent-{index}",
        ).reference

    outcomes = _race(4, sell)

    assert not [outcome for outcome in outcomes if outcome.error], outcomes
    assert len(set(Sale.all_rows.values_list("reference", flat=True))) == 4
    assert sorted(outcome.value for outcome in outcomes) == [
        f"S-{day:%Y%m%d}-000{index}" for index in range(1, 5)
    ]
    assert current_stock(stocked) == STOCKED - 4


@pytest.mark.django_db(transaction=True)
def test_one_key_with_two_different_baskets_yields_one_sale_and_one_refusal(
    stocked: Product,
) -> None:
    """Under contention, a reused key loses loudly rather than quietly.

    The winner's basket is recorded. The loser asked for a different basket with
    the same key, so it is refused with :class:`IdempotencyKeyReuse` - not given the
    winner's sale, which the caller would read as its own request having succeeded.
    """
    moment = now_utc()

    def sell(index: int) -> str:
        quantity = Decimal("1") if index == 0 else Decimal("2")
        return complete_sale(
            lines=[SaleLineInput(product=stocked, quantity=quantity)],
            payments=[(PaymentMethod.CASH, UNIT_PRICE * quantity)],
            sold_at=moment,
            idempotency_key="contested",
        ).reference

    outcomes = _race(2, sell)

    refused = [outcome for outcome in outcomes if isinstance(outcome.error, IdempotencyKeyReuse)]
    assert len(refused) == 1, outcomes
    assert not [
        outcome
        for outcome in outcomes
        if outcome.error is not None and not isinstance(outcome.error, IdempotencyKeyReuse)
    ], outcomes
    assert Sale.all_rows.count() == 1
    # Whoever won, exactly one basket's worth of stock left the shelf.
    assert current_stock(stocked) in (STOCKED - 1, STOCKED - 2)
