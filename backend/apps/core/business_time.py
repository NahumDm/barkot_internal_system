"""Business-time helpers (spec §11.4, principle P10).

Timestamps are stored in UTC and every daily or period report is computed in
``Africa/Addis_Ababa``. These helpers are the only sanctioned way to cross that
boundary, so no report has to re-derive it — and no report trusts a
browser-supplied timezone, which P10 explicitly forbids.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings

#: Used only if the configured zone is unavailable, so a typo in an environment
#: variable degrades to a safe, well-known zone instead of raising inside a report.
FALLBACK_BUSINESS_TIMEZONE = "Africa/Addis_Ababa"


def business_timezone() -> ZoneInfo:
    """Return the configured business reporting timezone."""
    name = getattr(settings, "BUSINESS_TIMEZONE", FALLBACK_BUSINESS_TIMEZONE)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo(FALLBACK_BUSINESS_TIMEZONE)


def now_utc() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)


def to_business_time(moment: datetime) -> datetime:
    """Convert an aware datetime to business-local time.

    Naive datetimes are rejected: Django returns aware datetimes when ``USE_TZ``
    is on, and silently assuming UTC for a naive value is exactly the class of
    bug that shifts a day's sales into the wrong report.
    """
    if moment.tzinfo is None:
        raise ValueError("to_business_time requires an aware datetime; naive values are ambiguous.")
    return moment.astimezone(business_timezone())


def business_date(moment: datetime) -> date:
    """Return the business-local calendar date for an aware datetime.

    A sale at 23:30 UTC belongs to the *next* Ethiopian business day, so this is
    the function every daily report must group by.
    """
    return to_business_time(moment).date()


def business_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Return the ``[start, end)`` UTC instants of a business-local calendar day."""
    tz = business_timezone()
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def business_period_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Return the ``[start, end)`` UTC instants covering business days ``start``
    through ``end`` **inclusive**.

    The end bound is the start of the following day, so ``end`` itself is
    included. An end before the start is a programming error and raises.
    """
    if end < start:
        raise ValueError(f"business period end {end} precedes start {start}")
    start_utc, _ = business_day_bounds(start)
    _, exclusive_end = business_day_bounds(end + timedelta(days=1))
    return start_utc, exclusive_end
