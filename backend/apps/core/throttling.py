"""Rate limiting for login and for every state-changing request (spec §9.3).

§9.3 asks for "rate limiting/throttling on login and sensitive endpoints" and
does not say what "sensitive" means. A5 answered the login half: five attempts
a minute per address, in an error envelope the frontend can act on. D0 answers
the rest with one rule - **a state-changing request is a sensitive request** -
because POST, PUT, PATCH and DELETE are the methods that create, mutate and
destroy business records, while reads are gated by the same permission classes
every write is and make up the normal traffic of every screen.

:class:`WriteRateThrottle` therefore charges every unsafe method 60 a minute
per client address, and :mod:`config.settings` installs it as DRF's
``DEFAULT_THROTTLE_CLASSES``. That placement is the whole design: a view
cannot be added to this API without inheriting the limit, exactly as
``DEFAULT_PERMISSION_CLASSES`` already makes a new endpoint private by
default, and for the same reason. The likeliest regression is not a wrong
rate, it is an endpoint that quietly has none, and a default is the only
mechanism that closes the hole for endpoints nobody has written yet. The one
view that overrides ``throttle_classes`` is login, whose own 5/m scope is
stricter than - and replaces, rather than stacks with - the generic default.

**Why 60 a minute.** ``infrastructure/nginx`` already allows 60 requests a
minute per address at the edge (``zone=api``, plus a burst of 20 on top).
Setting the write budget to the same 60/m puts Django's answer - a 429 in the
project's error envelope, with a ``Retry-After`` header - inside that burst
headroom, so a write flood is answered by the application with a body the
frontend can read instead of by a proxy 503. Sixty a minute is also far above
what a person at a till can sustain by hand, which is the point: the limit is
for runaway clients and abused sessions, not for staff.

**What does not spend the budget.** DRF consults throttles *after*
permissions (``APIView.initial`` in ``rest_framework/views.py``), so a request
answered 401 or 403 never reaches the counter: an unauthenticated flood is
refused before the throttle runs, and the edge's zones bound raw request
volume regardless. Reads return early in
:meth:`WriteRateThrottle.allow_request` without touching the cache at all - a
screen firing twenty GETs to render one page must not be charged against the
budget that bounds its writes.

**Why the counter lives in the database.** Production runs Gunicorn with
``--workers=2``, so two worker processes serve one deployment. DRF's throttles
count in ``django.core.cache``, and Django's default backend is
``LocMemCache``: a plain dict inside a single process. Two workers would
therefore allow twice the documented limit, and no test would catch it,
because the suite runs in one process. ``CACHES`` in
:mod:`config.settings.base` points at ``DatabaseCache`` and
:mod:`apps.core.migrations` creates the table, so every worker counts against
the same budget. Redis is the better store once there is real asynchronous
workload and it is not in this stack yet; the database is already there,
already backed up, and already the system of record.

**A throttle that any caller can reset with a header is not a throttle.** Behind
Nginx the address that reaches Django is the proxy's, so the real client is only
available from ``X-Forwarded-For`` - but that header is written by whoever sent
the request, so trusting it unconditionally lets an attacker pick a fresh counter
per attempt and brute force a password indefinitely. ``TRUSTED_PROXY`` therefore
defaults to off and :func:`client_ip` reads only ``REMOTE_ADDR`` unless an
operator has declared that a proxy they control sets the header. Production
deployments behind Nginx must set ``DJANGO_TRUSTED_PROXY=true``; without it
every caller shares the proxy's budget - at login that is five sign-ins a
minute for the whole office, and with D0 it is sixty writes a minute for the
whole venue, so the busiest night would throttle itself out of its own sales
API. That trade-off is explicit rather than silent.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework.permissions import SAFE_METHODS
from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle

#: Matches the keys looked up in ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``.
LOGIN_SCOPE = "login"
WRITE_SCOPE = "write"

#: Bucket for a request that carries no address at all. Such a request still needs
#: a limit, and one shared bucket beats no limit. This is applied at the cache key
#: rather than inside :func:`client_ip` because the audit fields the helper also
#: feeds are ``GenericIPAddressField``, and Postgres would reject this string.
UNKNOWN_CLIENT = "unknown"


def client_ip(request: Request) -> str | None:
    """Return the address a request came from, if it can be determined.

    Shared with the sign-in audit trail so the address a throttle counts and the
    address a login is recorded under cannot drift apart.

    ``X-Forwarded-For`` is read only when the deployment has declared a trusted
    proxy, because its leftmost entry is attacker-controlled otherwise. Everything
    else keys on ``REMOTE_ADDR``, which is the peer address as the socket sees it
    and which a caller cannot set.

    Args:
        request: The incoming request.

    Returns:
        The client address, or None when the request carries neither header. None
        rather than a placeholder, because callers pass this to
        ``GenericIPAddressField`` columns.
    """
    if getattr(settings, "TRUSTED_PROXY", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            # The leftmost entry is the originating client; proxies in the chain
            # append to the right. A caller reaching Django directly can still
            # prepend a fake address, which is exactly why this only runs when
            # TRUSTED_PROXY says a proxy is in front.
            first = forwarded.split(",")[0].strip()
            if first:
                return first

    return request.META.get("REMOTE_ADDR") or None


class AddressRateThrottle(SimpleRateThrottle):
    """A budget per client address, counted in the shared cache.

    Base for every throttle this project deploys: :class:`LoginRateThrottle`
    and :class:`WriteRateThrottle` differ only in scope and in which requests
    are charged, not in where the counter lives or which address it belongs to.
    Those two decisions are the ones that have failure modes (per-process
    counters, a spoofable header), so they exist once, here, and cannot drift
    between scopes.
    """

    def get_cache_key(self, request: Request, view: Any) -> str | None:
        """Key the counter on the client address rather than the session.

        DRF's stock anonymous throttle keys on ``get_ident``, which reads
        ``REMOTE_ADDR`` and consults ``X-Forwarded-For`` only when a separate
        ``NUM_PROXIES`` setting is present. That spreads one decision across two
        switches and trusts the header whenever ``NUM_PROXIES`` is set. Keying
        this throttle directly keeps the whole trusted-proxy decision in
        :func:`client_ip`, where it cannot drift away from what the audit log
        records.

        Args:
            request: The incoming request.
            view: The view being throttled. Unused: the rate is per address, so
                one client spreading requests over several URLs still has one
                budget.

        Returns:
            The cache key for this client's window.
        """
        ident = client_ip(request) or UNKNOWN_CLIENT
        return self.cache_format % {"scope": self.scope, "ident": ident}


class LoginRateThrottle(AddressRateThrottle):
    """Limit sign-in attempts per client address.

    Every attempt counts, successful ones included. Counting only failures would
    leave an attacker unthrottled for as long as one attempt in five succeeded,
    and would let a legitimate user lock themselves out of their own account by
    mistyping a password five times.

    A missing rate is not survivable here: DRF raises ``ImproperlyConfigured``
    while constructing this class, so a typo in ``DEFAULT_THROTTLE_RATES`` fails
    loudly on the first login request instead of quietly leaving the endpoint
    unthrottled.
    """

    scope = LOGIN_SCOPE


class WriteRateThrottle(AddressRateThrottle):
    """Limit state-changing requests per client address (D0).

    Reads return True before anything is counted, so rendering a screen can
    never exhaust the budget that bounds its writes. Everything else is
    charged, and it is charged before the view runs: DRF checks throttles
    ahead of dispatching to the handler, so the outcome of a request cannot
    influence whether it was counted - a 400 validation failure, a 409
    conflict and a 201 have all been processed and all spend. An attacker
    cannot keep a budget alive by sending bodies the serializer rejects,
    which is the same property login's throttle has and for the same reason.

    The missing-rate failure mode is login's: ``ImproperlyConfigured`` on the
    first state-changing request rather than a silent unlimited endpoint.
    """

    scope = WRITE_SCOPE

    def allow_request(self, request: Request, view: Any) -> bool:
        """Charge unsafe methods; pass reads through untouched.

        Args:
            request: The incoming request.
            view: The view being throttled. Passed to the base implementation,
                which ignores it: the budget belongs to the address.

        Returns:
            True when the request is a read or the address still has room in
            its window; False when the budget is spent, which DRF turns into a
            429 with ``Retry-After``.
        """
        if request.method in SAFE_METHODS:
            return True
        return super().allow_request(request, view)
