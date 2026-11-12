"""Validation helpers for query-string filters.

Django raises ``ValueError`` for a non-numeric PK lookup and ``ValidationError``
for a malformed datetime. Neither is a DRF exception, so without translation
they reach the client as a 500. These helpers turn the same mistakes into the
standard 400 validation envelope, naming the parameter that was wrong.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError


def positive_int(value: str, name: str) -> int:
    """Return ``value`` as a positive integer, or raise a field error."""
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: ["Enter a whole number."]}) from exc
    if number < 1:
        raise ValidationError({name: ["Enter a positive whole number."]})
    return number


def datetime_value(value: str, name: str) -> datetime:
    """Return ``value`` as an aware datetime, or raise a field error.

    ``parse_datetime`` returns ``None`` for both a malformed value and a
    date-only string. Filters on this API are timestamps, so both are refused
    rather than silently interpreted as midnight.
    """
    moment = parse_datetime(value)
    if moment is None:
        raise ValidationError({name: ["Enter a valid date and time."]})
    return moment


def boolean_value(value: str, name: str) -> bool:
    """Accept only the literal true/false spellings the API documents."""
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValidationError({name: ["Use true or false."]})
    return normalized == "true"


def choice_value(value: str, name: str, choices: Iterable[str]) -> str:
    """Return a value present in ``choices`` or raise a field error."""
    allowed = set(choices)
    if value not in allowed:
        raise ValidationError({name: [f"Choose one of: {', '.join(sorted(allowed))}."]})
    return value


__all__ = ["boolean_value", "choice_value", "datetime_value", "positive_int"]
