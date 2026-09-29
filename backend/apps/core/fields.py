"""Shared model fields for money and stock quantity (spec §10.3).

Every monetary and quantity column in Barkot is declared through these fields so
the NUMERIC scale, the currency default and the float rejection cannot drift
between domains. Declaring ``models.DecimalField(max_digits=14, decimal_places=2)``
by hand in ten places is how one of them eventually ends up at four decimal
places and quietly breaks a report.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.money import (
    CURRENCY,
    MONEY_DECIMAL_PLACES,
    MONEY_MAX_DIGITS,
    QUANTITY_DECIMAL_PLACES,
    QUANTITY_MAX_DIGITS,
    MoneyError,
    to_decimal,
)


class _ExactDecimalField(models.DecimalField):
    """Shared behaviour: coerce to ``Decimal``, reject ``float`` on assignment."""

    def to_python(self, value: Any) -> Any:
        if value is None or isinstance(value, Decimal):
            return value
        try:
            return to_decimal(value, field=self.name or "value")
        except MoneyError as exc:
            raise ValidationError(str(exc)) from exc

    def deconstruct(self) -> tuple[str, str, list[Any], dict[str, Any]]:
        name, path, args, kwargs = super().deconstruct()
        args = list(args)
        # The scale is a Barkot constant, not a per-field choice. Emitting it
        # into migration files would let someone "change" it by accident.
        for key in ("max_digits", "decimal_places"):
            kwargs.pop(key, None)
        return name, path, args, kwargs


class MoneyField(_ExactDecimalField):
    """ETB amount stored as ``NUMERIC(14, 2)``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", MONEY_MAX_DIGITS)
        kwargs.setdefault("decimal_places", MONEY_DECIMAL_PLACES)
        super().__init__(*args, **kwargs)


class QuantityField(_ExactDecimalField):
    """Stock quantity stored as ``NUMERIC(12, 3)``.

    Numeric rather than integer because spec §10.3 allows fractional units
    (litres, kilos) while bottle-based stock simply stores whole numbers.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", QUANTITY_MAX_DIGITS)
        kwargs.setdefault("decimal_places", QUANTITY_DECIMAL_PLACES)
        super().__init__(*args, **kwargs)


class CurrencyField(models.CharField):
    """Explicit ISO currency code. MVP is ETB only (spec §10.3).

    Storing the currency on every monetary row is what makes a future
    multi-currency version a reporting change rather than a data-recovery
    project.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 3)
        kwargs.setdefault("default", CURRENCY)
        super().__init__(*args, **kwargs)
