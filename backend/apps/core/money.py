"""Money primitives for the Barkot backend (spec §10.3).

Rules enforced here, once, for every domain:

- Money is :class:`~decimal.Decimal` end to end. A float is never accepted and
  never returned.
- The MVP currency is ETB and is stored explicitly on every monetary row, so a
  future multi-currency version is a data change rather than a guess.
- Every amount crossing this layer is quantised to the stored scale before it
  reaches the database, so ``0.1 + 0.2`` style drift cannot be persisted.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, DecimalException

#: MVP currency code (spec §10.3: "Store currency explicitly as ETB for the MVP").
CURRENCY = "ETB"

#: Matches :class:`apps.core.fields.MoneyField`. NUMERIC(14, 2) comfortably holds
#: any realistic restaurant figure while still refusing absurd input at the
#: database boundary.
MONEY_MAX_DIGITS = 14
MONEY_DECIMAL_PLACES = 2

#: Quantisation unit for every monetary amount: Decimal("0.01").
CENT = Decimal(1).scaleb(-MONEY_DECIMAL_PLACES)

#: Matches :class:`apps.core.fields.QuantityField`. Spec §10.3 allows non-integer
#: units ("where products may have non-integer units") while bottle-based stock
#: stays whole, so quantities are numeric with a small fractional allowance.
QUANTITY_MAX_DIGITS = 12
QUANTITY_DECIMAL_PLACES = 3
QUANTITY_UNIT = Decimal(1).scaleb(-QUANTITY_DECIMAL_PLACES)

ZERO_MONEY = Decimal("0.00")
ZERO_QUANTITY = Decimal("0.000")


class MoneyError(DecimalException):
    """Raised when a value cannot be treated as an exact monetary amount."""


def to_decimal(value: Decimal | int | str, *, field: str = "amount") -> Decimal:
    """Coerce ``value`` to :class:`~decimal.Decimal`, refusing floats.

    A float is rejected outright rather than converted. ``Decimal(0.1)`` is
    already the wrong number, and silently accepting one would let binary
    rounding error reach a NUMERIC column.

    Args:
        value: A ``Decimal``, ``int`` or numeric ``str``.
        field: Field name used in the error message.

    Returns:
        The value as an exact ``Decimal``.

    Raises:
        MoneyError: If ``value`` is a float or cannot be parsed exactly.
    """
    if isinstance(value, bool):
        raise MoneyError(f"{field} must be Decimal, int or str. Received bool.")
    if isinstance(value, float):
        raise MoneyError(
            f"{field} must be Decimal, int or str, never float. Received {value!r}. "
            "Convert the value at the boundary that produced it."
        )
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if not isinstance(value, str):
        raise MoneyError(f"{field} must be Decimal, int or str. Received {type(value).__name__}.")
    try:
        return Decimal(value)
    except (ArithmeticError, ValueError) as exc:
        raise MoneyError(f"{field} is not a valid decimal value: {value!r}") from exc


def quantize_money(value: Decimal | int | str, *, field: str = "amount") -> Decimal:
    """Return ``value`` as money quantised to :data:`MONEY_DECIMAL_PLACES`.

    Rounding is ``ROUND_HALF_UP``, the convention a cashier expects when a line
    total lands on a half-cent.
    """
    return to_decimal(value, field=field).quantize(CENT, rounding=ROUND_HALF_UP)


def quantize_quantity(value: Decimal | int | str, *, field: str = "quantity") -> Decimal:
    """Return ``value`` as a stock quantity quantised to
    :data:`QUANTITY_DECIMAL_PLACES`.
    """
    return to_decimal(value, field=field).quantize(QUANTITY_UNIT, rounding=ROUND_HALF_UP)


def validate_whole_quantity(
    value: Decimal | int | str, *, product: object, field: str = "quantity"
) -> Decimal:
    """Coerce ``value`` to a quantity and refuse a fraction for a whole-unit product.

    A product whose ``quantity_mode`` is ``WHOLE`` (crates, bottles) is counted
    in whole numbers; a ``FRACTIONAL`` product (kg, litre) keeps decimals.

    Args:
        value: The submitted quantity.
        product: The product it belongs to. Anything exposing
            ``requires_whole_quantity`` and ``sku`` works.
        field: Field name used in the error message.

    Returns:
        The value as an exact ``Decimal`` (not quantised).

    Raises:
        MoneyError: If ``value`` is a float or cannot be parsed.
        FractionalQuantityNotAllowed: If the product is whole-unit and the value
            has a fractional part.
    """
    from apps.core.exceptions import FractionalQuantityNotAllowed

    quantity = to_decimal(value, field=field)
    sku = getattr(product, "sku", "product")
    if (
        getattr(product, "requires_whole_quantity", False)
        and quantity != quantity.to_integral_value()
    ):
        raise FractionalQuantityNotAllowed(
            f"Product {sku!r} is counted in whole units; enter a whole number, not {quantity}."
        )
    return quantity


def multiply_money(unit_price: Decimal | int | str, quantity: Decimal | int | str) -> Decimal:
    """Return ``unit_price * quantity`` as quantised money.

    Quantising the product rather than the operands is deliberate: a unit price
    of ``0.335`` times ``3`` is ``1.005``, which must persist as ``1.01``, not as
    a line total that silently differs from the product of the stored columns by
    half a cent.
    """
    price = to_decimal(unit_price, field="unit_price")
    qty = to_decimal(quantity, field="quantity")
    return quantize_money(price * qty)


def sum_money(values: Iterable[Decimal | int | str]) -> Decimal:
    """Sum monetary values, returning exactly ``0.00`` when empty.

    ``Decimal`` addition is exact, so ``0.1 + 0.2`` is exactly ``0.3``; quantising
    once at the end is safe and order-independent.
    """
    total = Decimal("0")
    for index, value in enumerate(values):
        total += to_decimal(value, field=f"amount[{index}]")
    return quantize_money(total)
