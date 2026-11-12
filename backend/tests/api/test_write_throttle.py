"""Tests for the state-changing request limit (roadmap D0, spec §9.3).

The D0 gate reads "load test exceeds the configured limit and receives 429".
That sentence hides several separate failure modes, so each is tested on its
own, in the shape A5's login tests established.

**The limit has to bite at the configured number.** The load test drives real
requests through a real view until the sixty-first is refused. A throttle that
counts nothing answers 200 forever and still looks plausible in any test that
only exercises the happy path.

**Reads must not spend the budget.** Rendering one screen fires a burst of
GETs; if those were charged, a busy dashboard would lock a cashier out of her
own till. The early return in ``WriteRateThrottle.allow_request`` is asserted
directly against the cache, because "the read was allowed" would also pass
for a read that recorded itself.

**The default wiring is the mechanism.** The limit arrives from
``DEFAULT_THROTTLE_CLASSES``, not from each view remembering it. A view that
forgets is the likeliest regression, and the whole point of D0 is that
forgetting is impossible - so the tests pin the setting and the inherited
class attribute, not just the throttle class in isolation.

**Successes and failures count alike.** DRF checks throttles before dispatch,
so the outcome cannot influence the charge; the load test spends its budget
with deliberately invalid bodies and a successful write is shown to spend
the last slot.

**Login and writes are separate budgets**, at the key level and behaviourally
in both directions: sign-in has its own 5/m scope and must not be blockable -
or be blockable *by* - the write budget.

The window test advances the throttle's own clock instead of sleeping, so the
suite does not spend a minute proving the window rolls over.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from django.conf import settings
from django.core.cache import cache
from django.test import Client

if TYPE_CHECKING:
    # Present in django-stubs, absent at runtime: Django's test client has no such
    # public name. Importing it for real would break collection.
    from django.test.client import _MonkeyPatchedWSGIResponse
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.accounts.admin_views import RoleViewSet, SiteSettingsView
from apps.accounts.models import Role
from apps.accounts.views import LoginView
from apps.core.throttling import LOGIN_SCOPE, WRITE_SCOPE, LoginRateThrottle, WriteRateThrottle
from conftest import TEST_PASSWORD

pytestmark = pytest.mark.django_db

CSRF_URL = "/api/v1/auth/csrf/"
LOGIN_URL = "/api/v1/auth/login/"
USERS_URL = "/api/v1/users/"
SETTINGS_URL = "/api/v1/settings/"

#: Matches ``DEFAULT_THROTTLE_RATES`` in :mod:`config.settings.base`. Written out
#: rather than parsed from settings so a change to the rate has to be a deliberate
#: edit here, not a silent pass; ``test_the_rate_is_sixty_a_minute`` pins the
#: configured value against it.
ALLOWED_WRITES = 60

#: Login's own budget (A5), restated rather than imported so this file stands
#: alone; ``test_login_throttle`` pins the configured ``login`` rate.
ALLOWED_SIGN_INS = 5

#: Distinct from the addresses A5's login tests use, so a shared cache - or a
#: suite that forgot to isolate - shows up as a failure here rather than there.
CLIENT_IP = "203.0.113.50"
OTHER_IP = "203.0.113.77"

#: DRF passes the view being throttled to ``allow_request``; neither throttle
#: uses it, so one shared instance stands in for whatever view is dispatched.
VIEW = SiteSettingsView()


def make_throttle() -> WriteRateThrottle:
    """Return a fresh throttle, standing in for a freshly started worker.

    DRF builds a new throttle instance per request, so this is the same starting
    state the view gets every time.

    Returns:
        An unprimed :class:`WriteRateThrottle`.
    """
    return WriteRateThrottle()


def write_request(method: str = "POST", ip: str = CLIENT_IP) -> Request:
    """Build a state-changing request carrying a chosen client address.

    Args:
        method: The HTTP method to charge. ``GET`` builds the read whose early
            return is under test; the other four are DRF's unsafe methods.
        ip: Value for ``REMOTE_ADDR``, the address the socket saw.

    Returns:
        A DRF ``Request`` usable with ``get_cache_key`` and ``allow_request``.
    """
    extra: dict[str, str] = {"REMOTE_ADDR": ip}
    factory = APIRequestFactory()
    if method == "GET":
        request = factory.get(USERS_URL, REMOTE_ADDR=ip)
    elif method == "POST":
        request = factory.post(USERS_URL, {}, format="json", **extra)
    elif method == "PUT":
        request = factory.put(USERS_URL, {}, format="json", **extra)
    elif method == "PATCH":
        request = factory.patch(USERS_URL, {}, format="json", **extra)
    elif method == "DELETE":
        request = factory.delete(USERS_URL, {}, format="json", **extra)
    else:
        raise ValueError(f"unsupported method: {method}")
    return Request(request)


def login_request(ip: str = CLIENT_IP) -> Request:
    """Build a request carrying a chosen address, for the login scope.

    The path and method are irrelevant to both throttles - the budget belongs
    to the address - but a POST keeps the shape recognisable.

    Args:
        ip: Value for ``REMOTE_ADDR``.

    Returns:
        A DRF ``Request`` for the login throttle.
    """
    return Request(APIRequestFactory().post(LOGIN_URL, {}, format="json", REMOTE_ADDR=ip))


def exhaust(throttle: WriteRateThrottle, ip: str = CLIENT_IP) -> None:
    """Spend an address's whole write budget, asserting each request was allowed.

    Args:
        throttle: The throttle to spend.
        ip: The address whose budget is being spent.
    """
    for attempt in range(ALLOWED_WRITES):
        assert throttle.allow_request(write_request(ip=ip), VIEW), (
            f"request {attempt + 1} was refused on an empty budget"
        )


def post_users(client: Client, ip: str = CLIENT_IP) -> _MonkeyPatchedWSGIResponse:
    """Send the cheapest state-changing request the API has: an empty POST.

    The empty body fails validation, and that is deliberate: the throttle runs
    before the handler, so a 400 is a request the server processed and must
    charge. An attacker does not get to keep a budget alive with invalid JSON.

    Args:
        client: A signed-in Django test client.
        ip: Value for ``REMOTE_ADDR``.

    Returns:
        The response, whatever its status.
    """
    return client.post(USERS_URL, {}, content_type="application/json", REMOTE_ADDR=ip)


def spend_over_http(client: Client, ip: str = CLIENT_IP) -> None:
    """Drive a full budget of real requests, asserting none is refused early.

    Args:
        client: A signed-in Django test client.
        ip: The address whose budget is being spent.
    """
    for attempt in range(ALLOWED_WRITES):
        response = post_users(client, ip)
        assert response.status_code == status.HTTP_400_BAD_REQUEST, (
            f"request {attempt + 1} was {response.status_code}: {response.content[:200]!r}"
        )


class TestTheConfiguredLimit:
    """The rate, and the wiring that gives every endpoint the limit."""

    def test_the_rate_is_sixty_a_minute(self) -> None:
        """Sixty writes a minute, per the D0 policy in ``throttling``.

        Sixty matches the edge's ``api`` zone in
        ``infrastructure/nginx/nginx.conf``, so the application's 429 arrives
        inside the proxy's burst headroom instead of a proxy 503 arriving
        first.
        """
        rates = cast(dict[str, str], settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"])
        assert rates["write"] == "60/m"

        throttle = make_throttle()
        assert throttle.parse_rate(throttle.rate) == (ALLOWED_WRITES, 60)

    def test_views_inherit_the_limit_without_declaring_it(self) -> None:
        """The limit arrives from settings, so a new endpoint cannot forget it.

        Asserted on views that declare nothing: their class attribute is
        DRF's, bound from ``DEFAULT_THROTTLE_CLASSES`` at import. A test that
        only exercised the throttle class would pass on an API where every
        view opted out.
        """
        declared = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"]
        assert declared == ("apps.core.throttling.WriteRateThrottle",)
        assert SiteSettingsView.throttle_classes == [WriteRateThrottle]
        assert RoleViewSet.throttle_classes == [WriteRateThrottle]

    def test_login_keeps_its_own_stricter_scope(self) -> None:
        """Login replaces the default rather than stacking a second budget.

        A login POST charged against both scopes would spend write budget for
        traffic that never touches the business API, and its documented 5/m
        would be the only number that ever bit.
        """
        assert LoginView.throttle_classes == [LoginRateThrottle]


class TestReadsDoNotSpendTheBudget:
    """A screen's normal traffic must never exhaust what bounds its writes."""

    def test_a_read_leaves_no_record_in_the_cache(self) -> None:
        """A GET is allowed *and* writes nothing.

        Asserting only that the read was allowed would pass for a read that
        recorded itself; the cache is where the budget lives, so the cache is
        what has to be empty.
        """
        throttle = make_throttle()
        read = write_request(method="GET")
        key = throttle.get_cache_key(read, VIEW)
        assert key is not None

        for _ in range(3):
            assert throttle.allow_request(read, VIEW)

        assert cache.get(key) is None, "a read wrote to the throttle cache"

    def test_the_budget_survives_a_screen_full_of_reads(self) -> None:
        """A hundred and twenty GETs later, the first write is still allowed."""
        throttle = make_throttle()
        read = write_request(method="GET")

        for _ in range(ALLOWED_WRITES * 2):
            assert throttle.allow_request(read, VIEW)

        assert throttle.allow_request(write_request(), VIEW), "reads spent the write budget"

    @pytest.mark.parametrize(
        ("method", "ip"),
        [
            ("POST", "203.0.113.61"),
            ("PUT", "203.0.113.62"),
            ("PATCH", "203.0.113.63"),
            ("DELETE", "203.0.113.64"),
        ],
    )
    def test_every_unsafe_method_is_charged(self, method: str, ip: str) -> None:
        """POST, PUT, PATCH and DELETE each leave a record behind.

        A whitelist of "dangerous" methods would be a list to maintain; the
        rule is the complement of DRF's ``SAFE_METHODS``, so a method DRF
        learns about tomorrow is charged without anyone editing here.
        """
        throttle = make_throttle()
        request = write_request(method=method, ip=ip)
        key = throttle.get_cache_key(request, VIEW)
        assert key is not None

        assert throttle.allow_request(request, VIEW), f"{method} was refused on an empty budget"
        assert cache.get(key), f"{method} left no record; it did not spend the budget"


class TestTheLimitBites:
    """The refusal itself, at unit level."""

    def test_the_sixty_first_write_is_refused(self) -> None:
        """Sixty pass, the sixty-first does not - the configured number bites."""
        throttle = make_throttle()
        exhaust(throttle)

        assert not throttle.allow_request(write_request(), VIEW), (
            "the sixty-first write was allowed"
        )

    def test_the_refusal_reports_how_long_to_wait(self) -> None:
        """A 429 without a retry time leaves the client guessing.

        DRF reads the wait off the throttle, so returning early for reads and
        otherwise deferring to the base class must leave ``history`` and
        ``duration`` alone.
        """
        throttle = make_throttle()
        exhaust(throttle)
        throttle.allow_request(write_request(), VIEW)

        wait = throttle.wait()
        assert wait is not None
        assert wait > 0

    def test_a_different_address_has_its_own_budget(self) -> None:
        """The limit is per address, so one runaway client cannot lock out the till."""
        throttle = make_throttle()
        exhaust(throttle, ip=CLIENT_IP)

        assert throttle.allow_request(write_request(ip=OTHER_IP), VIEW)

    def test_a_second_worker_sees_the_first_workers_count(self) -> None:
        """Two Gunicorn workers must not each grant a fresh sixty.

        Each instance has its own ``history`` list, so if that were the only
        copy this would allow sixty more writes - exactly what two workers
        would really do. The counter being in the database is what stops that.
        """
        first_worker = make_throttle()
        exhaust(first_worker)

        second_worker = make_throttle()
        assert not second_worker.allow_request(write_request(), VIEW), (
            "a fresh worker got a fresh budget"
        )


class TestLoginAndWriteAreSeparateBudgets:
    """Two scopes, one address, two independent counters."""

    def test_the_two_scopes_produce_different_cache_keys(self) -> None:
        """The independence is pinned at the key level, not just behaviourally.

        Two throttles that accidentally shared a key would still pass the
        behavioural tests below by ordering luck; the key is where the
        separation actually lives.
        """
        request = write_request()
        login_key = LoginRateThrottle().get_cache_key(request, VIEW)
        write_key = WriteRateThrottle().get_cache_key(request, VIEW)

        assert login_key is not None and write_key is not None
        assert LOGIN_SCOPE in login_key
        assert WRITE_SCOPE in write_key
        assert login_key != write_key

    def test_an_exhausted_write_budget_does_not_block_sign_in(self) -> None:
        """Spamming the API must not lock staff out of their own accounts.

        The attack matters in reverse too: a runaway write client that
        exhausts the budget would otherwise take authentication down with it.
        """
        exhaust(make_throttle())

        login = LoginRateThrottle()
        for attempt in range(ALLOWED_SIGN_INS):
            assert login.allow_request(login_request(), VIEW), (
                f"sign-in attempt {attempt + 1} was blocked by the write budget"
            )
        assert not login.allow_request(login_request(), VIEW)

    def test_an_exhausted_login_budget_does_not_block_writes(self) -> None:
        """A password-guessing burst must not freeze the business API.

        Five wrong passwords from one address is a brute force in progress;
        it is also, on a shared kiosk, a colleague who cannot remember theirs.
        Neither should stop sales from being recorded.
        """
        login = LoginRateThrottle()
        for _ in range(ALLOWED_SIGN_INS):
            assert login.allow_request(login_request(), VIEW)
        assert not login.allow_request(login_request(), VIEW)

        assert make_throttle().allow_request(write_request(), VIEW), (
            "an exhausted login budget blocked a write"
        )


class TestWindowResets:
    """The limit is a rate, not a lifetime ban."""

    def test_the_budget_refills_after_the_window(self) -> None:
        """Once the window passes, the address starts from zero.

        ``SimpleRateThrottle`` reads time through ``timer``, so advancing that
        is what the expiry branch in ``allow_request`` is tested against.
        """
        throttle = make_throttle()
        exhaust(throttle)
        assert not throttle.allow_request(write_request(), VIEW)

        real_timer = throttle.timer
        _, duration = throttle.parse_rate(throttle.rate)
        assert duration is not None
        throttle.timer = lambda: real_timer() + duration + 1
        assert throttle.allow_request(write_request(), VIEW)


class TestTheLoadTest:
    """The D0 gate itself, over HTTP: "load test exceeds the configured limit
    and receives 429".

    Driving a real viewset through a real session covers everything the unit
    tests above cannot: ``throttle_classes`` inheritance on the dispatched
    view, the address as the WSGI layer reports it, and the error envelope the
    frontend actually branches on.
    """

    def test_the_load_test_exceeds_the_configured_limit_and_gets_429(self, staff_login) -> None:
        """Sixty state-changing requests pass; the sixty-first is a 429.

        Every one of the sixty is an invalid body, deliberately: they are
        requests the server processed and refused, which is exactly what an
        attacker spraying garbage would generate. The refusal has to arrive
        in the project's envelope with a retry time, because the frontend
        branches on ``error.code`` and cannot act on a bare status.
        """
        client = Client()
        staff_login(client, Role.Code.OWNER)

        spend_over_http(client)

        refused = post_users(client)
        assert refused.status_code == status.HTTP_429_TOO_MANY_REQUESTS, (
            f"the sixty-first write was {refused.status_code}: {refused.content[:200]!r}"
        )
        assert refused.json()["error"]["code"] == "throttled"
        assert refused.headers["Retry-After"]

    def test_a_successful_write_is_charged_too(self, staff_login) -> None:
        """A write that *succeeds* spends the last slot.

        If only failures counted, a valid client could loop forever while a
        mistyped form locked the budget. Fifty-nine failures are spent, one
        successful no-op patch takes the sixtieth, and the next request is
        refused - which it would not be had the success gone uncharged.
        """
        client = Client()
        staff_login(client, Role.Code.OWNER)

        for attempt in range(ALLOWED_WRITES - 1):
            response = post_users(client)
            assert response.status_code == status.HTTP_400_BAD_REQUEST, (
                f"request {attempt + 1} was {response.status_code}"
            )

        accepted = client.patch(
            SETTINGS_URL, {}, content_type="application/json", REMOTE_ADDR=CLIENT_IP
        )
        assert accepted.status_code == status.HTTP_200_OK, (
            f"the no-op write was {accepted.status_code}: {accepted.content[:200]!r}"
        )

        assert post_users(client).status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_the_budget_is_shared_across_endpoints(self, staff_login) -> None:
        """One address, one budget - spending it on /users/ spends it everywhere.

        The cache key carries the scope and the address but no path, on
        purpose: a client spreading requests over several URLs is still one
        client, and a per-path budget would be a budget per endpoint an
        attacker gets to choose.
        """
        client = Client()
        staff_login(client, Role.Code.OWNER)

        spend_over_http(client)

        patched = client.patch(
            SETTINGS_URL, {}, content_type="application/json", REMOTE_ADDR=CLIENT_IP
        )
        assert patched.status_code == status.HTTP_429_TOO_MANY_REQUESTS, (
            f"a second endpoint answered {patched.status_code} on a spent budget"
        )

    def test_reads_keep_working_once_the_budget_is_spent(self, staff_login) -> None:
        """An exhausted write budget must not turn the till read-only.

        The screens keep rendering; only the next mutation waits. Without
        this, a runaway save button would take down navigation too.
        """
        client = Client()
        staff_login(client, Role.Code.OWNER)

        spend_over_http(client)

        listed = client.get(USERS_URL, REMOTE_ADDR=CLIENT_IP)
        assert listed.status_code == status.HTTP_200_OK, (
            f"a read was {listed.status_code} on a spent write budget"
        )

    def test_signing_in_is_not_blocked_by_an_exhausted_write_budget(self, staff_login) -> None:
        """Sign-in has its own scope, so it survives a spent write budget.

        Runs over HTTP with a CSRF-enforcing client - the unit test proves
        the two counters are separate; this proves the login *view* is only
        wired to its own.
        """
        client = Client()
        user = staff_login(client, Role.Code.OWNER)
        spend_over_http(client)

        fresh = Client(enforce_csrf_checks=True)
        token = fresh.get(CSRF_URL).json()["token"]
        response = fresh.post(
            LOGIN_URL,
            {"username": user.username, "password": TEST_PASSWORD},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
            REMOTE_ADDR=CLIENT_IP,
        )
        assert response.status_code == status.HTTP_200_OK, (
            f"sign-in was {response.status_code} on a spent write budget"
        )

    def test_only_the_spending_address_is_refused(self, staff_login) -> None:
        """One address's flood must not refuse the next customer's order.

        Two real clients on two addresses, both signed in as the same account
        (Barkot has one Owner): the noisy one is at its limit, the quiet one is
        untouched. ``quiet.login`` is Django's session helper, not the login
        endpoint, so this second sign-in does not touch the login budget either.
        """
        noisy = Client()
        owner = staff_login(noisy, Role.Code.OWNER)
        spend_over_http(noisy)
        assert post_users(noisy).status_code == status.HTTP_429_TOO_MANY_REQUESTS

        # The same account from a second address, because Barkot permits exactly
        # one Owner: the point is that the throttle is keyed by address, not by
        # account, so one client's flood cannot spend another client's budget.
        quiet = Client()
        assert quiet.login(username=owner.username, password=TEST_PASSWORD)

        allowed = post_users(quiet, ip=OTHER_IP)
        assert allowed.status_code == status.HTTP_400_BAD_REQUEST, (
            f"an uninvolved address was refused with {allowed.status_code}"
        )
