"""Rate limiting for the login endpoint (spec §9.3, P09).

§9.3 asks for "rate limiting/throttling on login and sensitive endpoints" and
nothing more - no limit, no window, no scope. The numbers come from the A5
roadmap gate, "6th attempt from one IP returns 429", which fixes five attempts
per minute; ``5/m`` also matches the ``r/m`` convention already used by
``limit_req_zone`` in ``infrastructure/nginx/nginx.conf``.

**Why the counter lives in the database.** Production runs Gunicorn with
``--workers=2``, so two worker processes serve one deployment. DRF's throttles
count in ``django.core.cache``, and Django's default backend is ``LocMemCache``:
a plain dict inside a single process. Two workers would therefore allow ten
attempts while the documentation says five, and no test would catch it, because
the suite runs in one process. ``CACHES`` in :mod:`config.settings.base` points
at ``DatabaseCache`` and :mod:`apps.core.migrations` creates the table, so every
worker counts against the same budget. Redis is the better store once there is
real asynchronous workload and it is not in this stack yet; the database is
already there, already backed up, and already the system of record.

**Only login is throttled now.** Login is the only endpoint an unauthenticated
caller can attack, because no business endpoint exists yet. Each endpoint that
later lands on a "sensitive" path needs the same treatment, so
:class:`LoginRateThrottle` is written to be reused rather than copied - the
failure modes below are not specific to signing in.

**A throttle that any caller can reset with a header is not a throttle.** Behind
Nginx the address that reaches Django is the proxy's, so the real client is only
available from ``X-Forwarded-For`` - but that header is written by whoever sent
the request, so trusting it unconditionally lets an attacker pick a fresh counter
per attempt and brute force a password indefinitely. ``TRUSTED_PROXY`` therefore
defaults to off and :func:`client_ip` reads only ``REMOTE_ADDR`` unless an
operator has declared that a proxy they control sets the header. Production
deployments behind Nginx must set ``DJANGO_TRUSTED_PROXY=true``; without it every
caller shares the proxy's budget and throttles each other, which is a denial of
service on itself. That trade-off is explicit rather than silent.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle

#: Matches the key looked up in ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]``.
LOGIN_SCOPE = "login"

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


class LoginRateThrottle(SimpleRateThrottle):
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
