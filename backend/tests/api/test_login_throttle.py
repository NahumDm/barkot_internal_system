"""Tests for login rate limiting (roadmap A5, spec §9.3).

The gate is "6th attempt from one IP returns 429". That sentence is short and hides
three separate failure modes, so each is tested on its own.

**The limit has to actually bite.** Five attempts pass and the sixth is refused. A
throttle that counts nothing answers 200 forever and still looks plausible in any
test that only exercises the happy path.

**The counter has to be shared.** Production runs Gunicorn with ``--workers=2``.
DRF keeps the timestamps in ``history`` on the throttle instance and only mirrors
them into the cache, so two throttle objects are the closest in-process stand-in
for two workers. If the history were the only copy, each worker would grant five
attempts, the deployment behind one Nginx would allow ten, and no single-process
test would notice.

**The address has to be the real one.** The counter is keyed on an IP and
``X-Forwarded-For`` is written by whoever sent the request. Believing it by default
means an attacker picks a fresh bucket per attempt and the limit never applies. So
the header is ignored unless a trusted proxy is declared - tested in both
directions, because a fix that only works while the setting happens to be off is
not a fix.

The reset test advances the throttle's own clock instead of sleeping, so the suite
does not spend a minute proving the window rolls over.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import Client, override_settings

if TYPE_CHECKING:
    # Present in django-stubs, absent at runtime: Django's test client has no such
    # public name. Importing it for real would break collection.
    from django.test.client import _MonkeyPatchedWSGIResponse
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.accounts.models import Role
from apps.accounts.views import LoginView
from apps.core.throttling import UNKNOWN_CLIENT, LoginRateThrottle, client_ip
from conftest import TEST_PASSWORD

pytestmark = pytest.mark.django_db

CSRF_URL = "/api/v1/auth/csrf/"
LOGIN_URL = "/api/v1/auth/login/"

#: DRF passes the view being throttled to ``allow_request``; this throttle
#: ignores it, so one shared instance stands in for it.
LOGIN_VIEW = LoginView()

#: Matches ``DEFAULT_THROTTLE_RATES`` in :mod:`config.settings.base`. Written out
#: rather than parsed from settings so a change to the rate has to be a deliberate
#: edit here, not a silent pass.
ALLOWED_ATTEMPTS = 5

#: The tests are about *which* address is chosen, not the value. Kept distinct per
#: test so one test's counter cannot be spent by another's.
CLIENT_IP = "203.0.113.10"
OTHER_IP = "203.0.113.99"


def make_throttle() -> LoginRateThrottle:
    """Return a fresh throttle, standing in for a freshly started worker.

    DRF builds a new throttle instance per request, so this is the same starting
    state the view gets every time.

    Returns:
        An unprimed :class:`LoginRateThrottle`.
    """
    return LoginRateThrottle()


def throttle_request(ip: str = CLIENT_IP, forwarded: str | None = None) -> Request:
    """Build a request carrying a chosen client address.

    Args:
        ip: Value for ``REMOTE_ADDR``, the address the socket saw.
        forwarded: Value for ``X-Forwarded-For``, when the test needs one.

    Returns:
        A DRF ``Request`` usable with ``get_cache_key`` and ``allow_request``.
    """
    extra: dict[str, str] = {"REMOTE_ADDR": ip}
    if forwarded is not None:
        extra["HTTP_X_FORWARDED_FOR"] = forwarded
    return Request(APIRequestFactory().post(LOGIN_URL, {}, format="json", **extra))


def login_response(
    client: Client, username: str, password: str = TEST_PASSWORD
) -> _MonkeyPatchedWSGIResponse:
    """Post credentials the way the frontend does, CSRF token included.

    Args:
        client: A CSRF-enforcing client.
        username: Login name to present.
        password: Password to present.

    Returns:
        The login response, whatever its status.
    """
    token = client.get(CSRF_URL).json()["token"]
    return client.post(
        LOGIN_URL,
        {"username": username, "password": password},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
        REMOTE_ADDR=CLIENT_IP,
    )


class TestRateAndStore:
    """The rate, and the store the counter lives in."""

    def test_the_rate_is_five_a_minute(self) -> None:
        """Five allowed attempts per sixty seconds, per the A5 gate."""
        rates = cast(dict[str, str], settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])
        assert rates["login"] == "5/m"

        throttle = make_throttle()
        assert throttle.parse_rate(throttle.rate) == (ALLOWED_ATTEMPTS, 60)

    def test_the_counter_is_shared_between_processes(self) -> None:
        """The cache cannot be per-process while Gunicorn runs two workers.

        ``LocMemCache`` is a dict inside one process, which would make the real
        limit ten attempts. Asserted on the setting because the behaviour is
        indistinguishable in a single-process suite - which is precisely why it
        needs asserting at all.
        """
        backend = settings.CACHES["default"]["BACKEND"]
        assert backend == "django.core.cache.backends.db.DatabaseCache"


class TestSixthAttemptIsRefused:
    """The gate itself: one to five pass, the sixth does not."""

    def test_sixth_attempt_from_one_address_is_throttled(self) -> None:
        """The sixth request from one address is the one that is refused."""
        throttle = make_throttle()
        request = throttle_request()

        for attempt in range(1, ALLOWED_ATTEMPTS + 1):
            assert throttle.allow_request(request, LOGIN_VIEW), f"attempt {attempt} was refused"

        assert not throttle.allow_request(request, LOGIN_VIEW), "the sixth attempt was allowed"

    def test_the_refusal_reports_how_long_to_wait(self) -> None:
        """A 429 without a retry time leaves the client guessing.

        DRF reads the wait off the throttle, so overriding ``get_cache_key`` must
        leave ``history`` and ``duration`` alone.
        """
        throttle = make_throttle()
        request = throttle_request()
        for _ in range(ALLOWED_ATTEMPTS):
            throttle.allow_request(request, LOGIN_VIEW)
        throttle.allow_request(request, LOGIN_VIEW)

        wait = throttle.wait()
        assert wait is not None
        assert wait > 0

    def test_a_different_address_has_its_own_budget(self) -> None:
        """The limit is per address, so one user cannot lock out everyone."""
        throttle = make_throttle()
        for _ in range(ALLOWED_ATTEMPTS + 1):
            throttle.allow_request(throttle_request(ip=CLIENT_IP), LOGIN_VIEW)

        assert throttle.allow_request(throttle_request(ip=OTHER_IP), LOGIN_VIEW)


class TestCounterIsSharedBetweenWorkers:
    """Two worker processes must not each grant a fresh budget."""

    def test_a_second_worker_sees_the_first_workers_count(self) -> None:
        """A throttle built after the budget is spent is already throttled.

        Each instance has its own ``history`` list, so if that were the only copy
        this would pass five more attempts - exactly what two Gunicorn workers
        would really do.
        """
        first_worker = make_throttle()
        request = throttle_request()
        for _ in range(ALLOWED_ATTEMPTS):
            first_worker.allow_request(request, LOGIN_VIEW)

        second_worker = make_throttle()
        assert not second_worker.allow_request(request, LOGIN_VIEW)

    def test_the_count_is_written_to_the_shared_store(self) -> None:
        """The attempt history reaches the cache, not just the instance."""
        request = throttle_request()
        primer = make_throttle()
        for _ in range(ALLOWED_ATTEMPTS):
            primer.allow_request(request, LOGIN_VIEW)

        cache_key = primer.get_cache_key(request, LOGIN_VIEW)
        assert cache_key is not None
        assert cache.get(cache_key), "the attempt history was not written to the cache"


class TestProxyHeaderIsNotTrustedByDefault:
    """The address must be the one the socket saw, not one the caller chose."""

    def test_the_default_does_not_trust_the_forwarded_header(self) -> None:
        """``TRUSTED_PROXY`` ships off, so the header cannot pick the bucket."""
        assert settings.TRUSTED_PROXY is False
        spoofed = throttle_request(ip=CLIENT_IP, forwarded="198.51.100.1")
        assert client_ip(spoofed) == CLIENT_IP

    def test_a_spoofed_header_cannot_reset_the_budget(self) -> None:
        """Rotating the header buys no extra attempts.

        This is the brute-force case: a new fake address per request would
        otherwise mean an unlimited number of password guesses.
        """
        throttle = make_throttle()
        for spoofed in range(ALLOWED_ATTEMPTS):
            request = throttle_request(ip=CLIENT_IP, forwarded=f"198.51.100.{spoofed}")
            throttle.allow_request(request, LOGIN_VIEW)

        sixth = throttle_request(ip=CLIENT_IP, forwarded="198.51.100.200")
        assert not throttle.allow_request(sixth, LOGIN_VIEW)

    @override_settings(TRUSTED_PROXY=True)
    def test_a_declared_proxy_header_is_honoured(self) -> None:
        """With a proxy in front, the leftmost forwarded entry is the client.

        Nginx appends to the right of the header, so the entry it did not write
        is the originating address.
        """
        request = throttle_request(ip="127.0.0.1", forwarded="198.51.100.1, 10.0.0.1")
        assert client_ip(request) == "198.51.100.1"

    @override_settings(TRUSTED_PROXY=True)
    def test_a_declared_proxy_still_falls_back_to_remote_addr(self) -> None:
        """A proxy that sets no header must not switch limiting off."""
        assert client_ip(throttle_request(ip="127.0.0.1")) == "127.0.0.1"

    def test_a_request_with_no_address_is_still_limited(self) -> None:
        """No address at all gets the shared sentinel bucket, not a free pass.

        A falsy cache key would mean ``allow_request`` skips the check entirely,
        which would disable the limit rather than sharing it.
        """
        throttle = make_throttle()
        request = throttle_request(ip="")
        for _ in range(ALLOWED_ATTEMPTS):
            throttle.allow_request(request, LOGIN_VIEW)

        assert not throttle.allow_request(request, LOGIN_VIEW)
        assert UNKNOWN_CLIENT in str(throttle.get_cache_key(request, LOGIN_VIEW))


class TestWindowResets:
    """The limit is a rate, not a lifetime ban."""

    def test_attempts_are_allowed_again_after_the_window(self) -> None:
        """Once the window passes, the address starts from zero.

        ``SimpleRateThrottle`` reads time through ``timer``, so advancing that is
        what the expiry branch in ``allow_request`` is tested against.
        """
        throttle = make_throttle()
        request = throttle_request()
        for _ in range(ALLOWED_ATTEMPTS):
            throttle.allow_request(request, LOGIN_VIEW)
        assert not throttle.allow_request(request, LOGIN_VIEW)

        real_timer = throttle.timer
        _, duration = throttle.parse_rate(throttle.rate)
        assert duration is not None
        throttle.timer = lambda: real_timer() + duration + 1
        assert throttle.allow_request(request, LOGIN_VIEW)


class TestLoginEndpointEnforcesTheLimit:
    """End to end over HTTP, so the wiring on the view is covered too.

    Asserting on the throttle class alone would not notice a view that simply
    forgot to declare ``throttle_classes``, which is the likeliest regression.
    """

    def test_sixth_http_login_returns_429_in_the_error_envelope(self, make_staff_user) -> None:
        """The sixth real login is refused, in the shape the frontend expects.

        Both wrong passwords and right ones are used: the sixth attempt must be
        refused either way, or a valid account is still guessable at five a
        minute forever.
        """
        client = Client(enforce_csrf_checks=True)
        user = make_staff_user(Role.Code.OWNER)

        for attempt in range(ALLOWED_ATTEMPTS):
            response = login_response(client, user.username, f"wrong-{attempt}")
            assert response.status_code == status.HTTP_400_BAD_REQUEST, (
                f"attempt {attempt + 1} was {response.status_code}: {response.content!r}"
            )

        response = login_response(client, user.username)
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert response.json()["error"]["code"] == "throttled"
        assert response.headers["Retry-After"]

    def test_a_correct_password_is_throttled_too(self, make_staff_user) -> None:
        """Successful attempts count, so valid accounts are protected too.

        Counting only failures would let an attacker keep guessing without ever
        being throttled as long as one attempt in five succeeded.
        """
        client = Client(enforce_csrf_checks=True)
        user = make_staff_user(Role.Code.OWNER)

        for _ in range(ALLOWED_ATTEMPTS):
            assert login_response(client, user.username).status_code == status.HTTP_200_OK

        response = login_response(client, user.username)
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_the_limit_is_per_address_over_http(self, make_staff_user) -> None:
        """One address exhausting its budget does not throttle another."""
        noisy = Client(enforce_csrf_checks=True)
        user = make_staff_user(Role.Code.OWNER)
        for _ in range(ALLOWED_ATTEMPTS + 1):
            login_response(noisy, user.username, "wrong")

        token = Client().get(CSRF_URL).json()["token"]
        other = Client(enforce_csrf_checks=True)
        response = other.post(
            LOGIN_URL,
            {"username": user.username, "password": TEST_PASSWORD},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=other.get(CSRF_URL).json()["token"],
            REMOTE_ADDR=OTHER_IP,
        )
        assert response.status_code == status.HTTP_200_OK
        assert token
