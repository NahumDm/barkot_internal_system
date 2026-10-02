"""What makes two attempts "the same request" (spec §10.2).

An idempotency key is only useful if the mechanism can tell a retry apart from a
different request that happens to reuse the key. That judgement is one SHA-256
digest over a normalised body, so everything that decides a request's identity is
decided here: :func:`~apps.core.idempotency.canonical` decides which differences
between two payloads are noise, and everything else is treated as a different sale.

No database is involved, so this module is marked neither ``django_db`` nor
anything else. The integration half of A10 - the claim row, the replay, the
double-click - is in ``test_idempotency.py``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from apps.core.idempotency import MAX_KEY_LENGTH, canonical, fingerprint, validate_key

# ── Noise: differences the client did not mean ──────────────────────────────


def test_key_order_is_not_part_of_the_request() -> None:
    """A rebuilt payload must still be recognised.

    Any client that re-serialises a request on the way out - a different language,
    a dict comprehension, a JSON round-trip through a proxy - can emit the same
    fields in a different order. Refusing the retry over that would make the key
    worse than useless: it would turn a network retry into a user-visible error.
    """
    assert fingerprint({"sku": "BEKO-330", "qty": 2}) == fingerprint({"qty": 2, "sku": "BEKO-330"})


def test_one_and_one_point_zero_are_the_same_number() -> None:
    """``1`` and ``1.0`` are the same quantity, and the client chose which to send."""
    assert fingerprint({"quantity": 1}) == fingerprint({"quantity": 1.0})


def test_an_int_and_the_equivalent_decimal_hash_alike() -> None:
    """A JSON number and the ``Decimal`` it becomes are one value.

    This is the seam a JSON client actually crosses: it sends ``2``, the service
    turns it into ``Decimal("2")``, and the retry has to hash as the same thing.
    """
    assert fingerprint({"quantity": 2}) == fingerprint({"quantity": Decimal("2")})


def test_whole_and_fractional_money_spellings_are_one_amount() -> None:
    """``Decimal("10.00")`` and ``Decimal("10")`` are the same amount of money.

    A POS that formats currency on the way out sends ``"120.00"``; one that does not
    sends ``"120"``. Neither is a different sale.
    """
    assert fingerprint({"amount": Decimal("120.00")}) == fingerprint({"amount": Decimal("120")})


def test_set_order_is_not_part_of_the_request() -> None:
    """A set is unordered by definition, so its hash must be too."""
    assert fingerprint({"skus": {"A", "B", "C"}}) == fingerprint({"skus": {"C", "A", "B"}})


# ── Signal: differences that really are a different request ─────────────────


def test_list_order_is_part_of_the_request() -> None:
    """Two sales with the same lines in a different order are different receipts.

    Lines are positional in a receipt, so unlike a set their order carries meaning
    and must not be normalised away.
    """
    assert fingerprint({"lines": ["beer", "wine"]}) != fingerprint({"lines": ["wine", "beer"]})


def test_amounts_differing_below_float_precision_stay_distinct() -> None:
    """Two amounts that differ at all are two amounts.

    This is the reason money is never hashed as a float. Rounding either value to a
    float would make them collide, and the two requests would be treated as one
    sale.
    """
    assert fingerprint({"amount": Decimal("0.1")}) != fingerprint({
        "amount": Decimal("0.100000001")
    })


def test_a_binary_float_artefact_is_not_silently_rounded_away() -> None:
    """``0.1 + 0.2`` stays visibly distinct from ``0.3``.

    Float arithmetic produces a value a human never typed. Silently normalising it
    onto the "intended" ``0.3`` would be a guess about money, and a guess that
    decides whether two requests are the same one.
    """
    assert fingerprint({"total": 0.1 + 0.2}) != fingerprint({"total": 0.3})


def test_true_is_not_one() -> None:
    """``bool`` is a subclass of ``int``, and the two must not collide.

    Without the explicit check, ``{"paid": True}`` and ``{"paid": 1}`` would hash
    alike - and one of them is a different request.
    """
    assert fingerprint({"paid": True}) != fingerprint({"paid": 1})


def test_a_different_product_is_a_different_request() -> None:
    """The SKU is what identifies a line, so it has to be in the digest."""
    assert fingerprint({"sku": "BEKO-330"}) != fingerprint({"sku": "BEKO-500"})


# ── The canonical form itself ───────────────────────────────────────────────


def test_a_datetime_is_tagged_so_it_cannot_collide_with_a_string() -> None:
    """Instants are tagged rather than rendered bare.

    The tag keeps an instant from hashing the same as the ISO text a client might
    send for it. The two are different inputs; an HTTP adapter is responsible for
    parsing the header body into the same types the service uses, rather than the
    digest guessing which was meant.
    """
    moment = datetime(2026, 9, 29, 10, 30, tzinfo=UTC)

    assert canonical(moment) == {"__datetime__": "2026-09-29T10:30:00+00:00"}


def test_a_date_is_not_confused_with_a_datetime() -> None:
    """``date`` is a superclass of ``datetime``, so the narrower check must come first."""
    assert canonical(date(2026, 9, 29)) == {"__date__": "2026-09-29"}
    assert canonical(date(2026, 9, 29)) != canonical(datetime(2026, 9, 29, tzinfo=UTC))


def test_nested_structures_are_canonicalised_all_the_way_down() -> None:
    """A body is rarely flat, and the noise rules must apply at every depth."""
    first = {
        "lines": [{"sku": "BEKO-330", "qty": Decimal("2.00")}],
        "payments": [[1, Decimal("120")]],
    }
    second = {"payments": [[1, Decimal("120.0")]], "lines": [{"qty": 2, "sku": "BEKO-330"}]}

    assert fingerprint(first) == fingerprint(second)


def test_canonical_refuses_what_it_cannot_hash() -> None:
    """An unhashable body fails loudly rather than hashing a ``repr``.

    Hashing ``repr()`` would make two genuinely different objects look like one
    request, which is the exact failure the fingerprint exists to prevent - and it
    would fail silently, which is worse.
    """
    with pytest.raises(TypeError, match="Cannot build a canonical form of object"):
        canonical(object())


# ── Key validation ──────────────────────────────────────────────────────────


def test_a_key_is_trimmed() -> None:
    """Leading whitespace is a transport artefact, not a different key.

    If it counted, a proxy that trimmed on one request and not the next would let a
    retry through as a brand-new sale.
    """
    assert validate_key("  pos-1-0001  ") == "pos-1-0001"


@pytest.mark.parametrize("key", ["", "   ", "\t", "\n", " \t\n "])
def test_a_blank_key_is_refused_rather_than_treated_as_absent(key: str) -> None:
    """A client sending an empty key believes it is protected.

    Proceeding without a claim is the one outcome worse than an error, because the
    duplicate it fails to prevent is invisible to everyone involved.
    """
    with pytest.raises(ValueError, match="cannot be blank"):
        validate_key(key)


def test_a_key_of_the_maximum_length_is_accepted() -> None:
    """A UUID or a ULID fits, and the boundary is not off by one."""
    assert validate_key("x" * MAX_KEY_LENGTH) == "x" * MAX_KEY_LENGTH


def test_a_key_longer_than_the_column_is_refused() -> None:
    """An over-long key is a payload in a token column, not a key."""
    with pytest.raises(ValueError, match="at most"):
        validate_key("x" * (MAX_KEY_LENGTH + 1))
