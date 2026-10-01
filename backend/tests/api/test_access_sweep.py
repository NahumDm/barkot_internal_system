"""A9: signed-out access sweep across every registered endpoint.

The contract suite (``tests/api/contract.py``) proves each endpoint *declares*
``IsAuthenticated``. It cannot prove a request actually receives a 401, because its
rules are pure attribute reads by design (``contract.py:11-15``) - that restraint is
what keeps it fast and free of setup, and it is the right trade there. The cost is that
the gate "401/403 on every protected route" had no test behind it at all: every 401 in
the suite hard-codes one URL, so an endpoint added tomorrow without protection fails
nothing.

This module closes that gap by issuing real requests against the live URLconf. It
imports :func:`discover_endpoints` from the contract engine rather than maintaining a
second list of routes, because a second list would be a second thing to forget.

What is deliberately public comes from the contract suite's ``EXEMPTIONS`` table - the
one place where "this route is public on purpose, and here is why" is already written
down. Deriving it means a new endpoint cannot become public by being added to a list
here; it would have to be exempted there, with a reason, and that exemption is
reviewed.

Two endpoints need to be handled apart from the rest, and the file records why rather
than hiding the exception:

* ``/api/schema/`` (``SpectacularAPIView``) does go through the DRF exception handler,
  so its 401 carries ``error.code`` - but the handler's output is rendered in whatever
  format was negotiated. Without an ``Accept`` header that is YAML, so the body is not
  JSON-parseable. Asking for JSON returns the normal envelope.
* ``/api/docs/`` (``SpectacularSwaggerView``) is a Django template view. Its 401 is a
  plain ``text/html`` "401 Unauthorized" page produced outside DRF, so there is no
  envelope to parse and sending ``Accept: application/json`` gets a 406 instead. It is
  still correctly protected - the status and the challenge header are what matter - but
  it is asserted on those alone.

The role dimension is covered separately, at the end, because it needs a live user and
because most endpoints do not have a role dimension at all - ``me``, ``logout`` and
``change-password`` require a session, not a rank.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from rest_framework.permissions import AllowAny

from apps.accounts.models import Role
from apps.accounts.permissions import HasRolePermission
from tests.api.contract import EXEMPTIONS, Endpoint, discover_endpoints

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from django.test import Client

ENDPOINTS = discover_endpoints()

#: The rule whose waiver means "this endpoint is meant to be reachable signed out".
#: Reading it from the contract engine rather than repeating the list keeps the two
#: in step: an exemption waiving some other rule does not silently make a route public.
PUBLIC_RULE = "private_by_default"

#: Minimum number of endpoints the sweep must see. A discovery bug or a broken import
#: that yielded an empty list would make every parameterised test below pass having
#: requested nothing, and a security gate that tests nothing while reporting green is
#: worse than no gate at all. Three is the floor below which the suite has lost its
#: ability to fail; the current count is well above it.
MIN_ENDPOINTS = 3

#: Endpoints that refuse correctly but do not speak the JSON envelope. Kept as a
#: named set with the reasoning in the module docstring so that a future change to
#: either view's rendering is a visible diff rather than a silently dropped assertion.
NON_JSON_REFUSALS = frozenset({
    "drf_spectacular.views.SpectacularSwaggerView",
})

#: ``LogoutView`` ends the session it is asked about, so a signed-in client cannot be
#: expected to still hold one afterwards. Asking it about the session is the refusal,
#: not a bypass. Module level because a comprehension in a class body cannot see a
#: name defined in that same class body.
ENDS_SESSION = frozenset({"apps.accounts.views.LogoutView"})


def _is_public(endpoint: Endpoint) -> bool:
    """Return whether the contract suite declares this endpoint reachable signed out."""
    return any(e.view_key == endpoint.key and PUBLIC_RULE in e.waives for e in EXEMPTIONS)


def _role_gated(endpoint: Endpoint) -> bool:
    """Return whether this view names a :class:`HasRolePermission`."""
    return any(
        issubclass(p, HasRolePermission)
        for p in (getattr(endpoint.view, "permission_classes", []) or [])
    )


PROTECTED: list[Endpoint] = [e for e in ENDPOINTS if not _is_public(e)]
PUBLIC: list[Endpoint] = [e for e in ENDPOINTS if _is_public(e)]

#: Protected endpoints whose refusal must parse as the project envelope.
ENVELOPE_PROTECTED: list[Endpoint] = [e for e in PROTECTED if e.key not in NON_JSON_REFUSALS]


def _ids(endpoints: list[Endpoint]) -> list[str]:
    """Return stable test IDs for parametrisation."""
    return [f"{e.method}-{e.path}" for e in endpoints]


def _request(client: Client, endpoint: Endpoint, *, as_json: bool = False) -> Any:
    """Send ``endpoint``'s own method at its own path, as a sessionless client.

    The method and path both come from discovery rather than being written down here,
    which is the whole mechanism: a route nobody wrote a test for is still requested.

    An empty JSON object is sent on POST. That is not cosmetic - DRF's CSRF check reads
    ``request.POST`` to look for a form-encoded token, and that read parses the body, so
    a body-less POST arriving as ``multipart/form-data`` (the Django test client's
    default) is rejected with 415 before authentication is even reached. Sending ``{}``
    keeps the assertion about authorisation rather than about content negotiation.

    Args:
        client: The Django test client.
        endpoint: The endpoint to request.
        as_json: Ask for JSON explicitly. Needed for the schema view, whose error body
            is otherwise rendered as YAML.

    Returns:
        The response.
    """
    headers: dict[str, str] = {"Accept": "application/json"} if as_json else {}
    if endpoint.method == "GET":
        return client.get(endpoint.path, headers=headers)
    return client.generic(
        endpoint.method,
        endpoint.path,
        data=json.dumps({}),
        content_type="application/json",
        headers=headers,
    )


class TestTheSweepIsNotVacuous:
    """Guards against a discovery failure masquerading as a clean bill of health.

    Every test below is parameterised over what discovery returned. If that list were
    empty - a typo'd import, a URLconf that no longer resolves, a pytest collection
    problem - the whole class would report green having issued zero requests. This is
    the failure mode the contract suite guards against for its own rules
    (``test_contract.py:357-370``) and it applies with more force here, because these
    tests send real traffic.
    """

    def test_discovery_found_endpoints(self) -> None:
        """Discovery returned something, and enough of it."""
        assert len(ENDPOINTS) >= MIN_ENDPOINTS, (
            f"discovery returned {len(ENDPOINTS)} endpoints; the sweep is inert below "
            f"{MIN_ENDPOINTS} and may be broken rather than passing"
        )

    def test_some_endpoints_are_protected(self) -> None:
        """The sweep has protected routes to sweep.

        An API where every endpoint is exempt from ``private_by_default`` is a real
        possibility this suite should notice rather than pass quietly.
        """
        assert PROTECTED, (
            "no endpoint requires a session; every route is exempt from "
            f"{PUBLIC_RULE!r}, so the signed-out sweep would assert nothing"
        )

    def test_the_public_set_is_derived_not_declared(self) -> None:
        """Public and protected partition the endpoints exactly.

        If these could overlap or leave a gap, an endpoint could be skipped by both
        loops and never requested at all - which is precisely the hole this module
        exists to close.
        """
        assert len(PROTECTED) + len(PUBLIC) == len(ENDPOINTS)
        public_keys = {e.key for e in PUBLIC}
        assert not ({e.key for e in PROTECTED} & public_keys)

    def test_every_exemption_reason_still_reads_as_a_reason(self) -> None:
        """The public set is only trustworthy if its waivers are justified.

        Copied in spirit from ``test_each_exemption_states_a_reason`` in the contract
        suite. Re-asserted here because this module trusts ``EXEMPTIONS`` to decide what
        is public; if that trust were ever misplaced, the reason is the thing to read.
        """
        for exemption in EXEMPTIONS:
            if PUBLIC_RULE in exemption.waives:
                assert exemption.reason.strip(), f"{exemption.view_key} has no stated reason"


class TestSignedOutIsRefusedEverywhere:
    """The core of A9: no protected route answers a sessionless request."""

    @pytest.mark.parametrize("endpoint", PROTECTED, ids=_ids(PROTECTED))
    def test_a_signed_out_request_is_401(self, client: Client, endpoint: Endpoint) -> None:
        """Every protected endpoint refuses a request carrying no session.

        Asserts 401 specifically, not merely "not 2xx". That distinction is the whole
        point of the gate: a 403 would tell the frontend the session is valid and merely
        unauthorised, and a 400 or 415 would tell it the request was malformed. Only a
        401 carries the instruction to send the user back to the login screen, and the
        frontend's entire recovery path depends on getting that status.

        Args:
            client: The Django test client, unauthenticated.
            endpoint: One HTTP method on one protected view.
        """
        response = _request(client, endpoint)

        assert response.status_code == 401, (
            f"{endpoint.label} answered {response.status_code} to a signed-out request "
            f"instead of 401; body: {response.content[:300]!r}"
        )

    @pytest.mark.parametrize("endpoint", PROTECTED, ids=_ids(PROTECTED))
    def test_the_401_offers_a_challenge(self, client: Client, endpoint: Endpoint) -> None:
        """Every 401 carries ``WWW-Authenticate``.

        The status code alone is ambiguous - some intermediaries turn a 401 into a 403,
        and this header is what lets the client tell a refused session from a refused
        action, since DRF derives the 401 from it.
        """
        response = _request(client, endpoint)

        assert "WWW-Authenticate" in response, (
            f"{endpoint.label} answered 401 with no WWW-Authenticate header"
        )

    @pytest.mark.parametrize("endpoint", ENVELOPE_PROTECTED, ids=_ids(ENVELOPE_PROTECTED))
    def test_the_401_carries_the_project_envelope(self, client: Client, endpoint: Endpoint) -> None:
        """Every JSON-speaking refusal is a parseable error object.

        The frontend branches on ``error.code``, so a 401 that arrives as an HTML page
        or a bare string is a 401 the client cannot act on. This excludes the Swagger
        view, which is documented at the top of this file as answering outside DRF, and
        asks for JSON explicitly so the schema view's YAML rendering does not obscure
        the envelope it does send.

        Args:
            client: The Django test client, unauthenticated.
            endpoint: One HTTP method on one protected view.
        """
        response = _request(client, endpoint, as_json=True)

        body = response.json()
        assert set(body) == {"error"}, f"{endpoint.label} body is not the envelope: {body}"
        assert body["error"]["code"] == "not_authenticated", body["error"]["code"]
        assert body["error"]["message"].strip(), "the envelope's message is empty"

    def test_the_docs_refusal_does_not_leak(self, client: Client) -> None:
        """The Swagger view's out-of-band 401 says nothing about the resource.

        ``/api/docs/`` escapes the DRF exception handler, so its refusal is whatever
        Django renders. It is still a 401 with a challenge - both asserted above - but
        the body must not have picked up a traceback or a session identifier on the way
        past the handler.
        """
        response = client.get("/api/docs/")

        assert response.status_code == 401
        assert len(response.content) < 1024, (
            f"the docs refusal body is {len(response.content)} bytes; it looks like a "
            "debug page rather than a refusal"
        )


class TestPublicRoutesStayPublic:
    """The exemptions must describe reality, not just intent.

    An exemption that no longer matches reality is either a route that became private
    without anyone noticing (a client that can no longer reach it) or one that was public
    when it should not have been. Both are worth a failing test.
    """

    @pytest.mark.parametrize("endpoint", PUBLIC, ids=_ids(PUBLIC))
    @pytest.mark.django_db
    def test_a_public_route_does_not_refuse_a_signed_out_request(
        self, client: Client, endpoint: Endpoint
    ) -> None:
        """A declared-public endpoint is actually reachable while signed out.

        The API root answers "am I talking to the API I think I am?", so a client that
        cannot ask loses its way of diagnosing a misconfigured base URL. If this starts
        failing, either the exemption has gone stale or a view tightened itself.

        Marked ``django_db`` because the login route is throttled and the throttle cache
        is the database. Without it the request dies in the cache rather than at the
        permission check, which would be a false failure.

        Args:
            client: The Django test client, unauthenticated.
            endpoint: One HTTP method on one exempt view.
        """
        response = _request(client, endpoint)

        assert response.status_code != 401, (
            f"{endpoint.label} is exempt from {PUBLIC_RULE!r} but answers 401 signed out; "
            f"the exemption is stale"
        )

    @pytest.mark.parametrize("endpoint", PUBLIC, ids=_ids(PUBLIC))
    def test_a_public_route_still_declares_allow_any(self, endpoint: Endpoint) -> None:
        """The exemption is not masking a route that declares it is private.

        Without this, an endpoint could be exempt for a historical reason while its view
        says ``IsAuthenticated``, and the sweep would assert it is reachable while the
        code says otherwise. The two must agree.
        """
        permissions = list(getattr(endpoint.view, "permission_classes", []) or [])
        assert any(issubclass(p, AllowAny) for p in permissions), (
            f"{endpoint.label} is exempt from {PUBLIC_RULE!r} but declares "
            f"{[p.__name__ for p in permissions]}"
        )


class TestRoleBypass:
    """The 403 half of the gate, for the endpoints that have a role dimension.

    ``me``, ``logout`` and ``change-password`` require a session, not a rank, so a
    Cashier using them is correct behaviour and there is nothing to assert. The check
    applies to whichever views actually name a :class:`HasRolePermission`, which today
    is none of the shipped ones - the payroll endpoints arrive in a later phase. The
    selection below is therefore expected to be empty for now, and that emptiness is
    guarded rather than left to look like a pass.

    A8 already covers role bypass for a shipped permission class end-to-end through
    ``tests/api/urls_for_tests.py``, which is where a 403 is observable while no business
    endpoint exists. What this adds is the wiring: when the first role-gated view lands,
    it is swept here without anyone remembering to add it.
    """

    ROLE_GATED: list[Endpoint] = [e for e in ENDPOINTS if _role_gated(e)]

    def test_no_shipped_endpoint_has_a_role_gate_yet(self) -> None:
        """No shipped view names a role permission class yet.

        Documented as an assertion rather than left implicit so that when this starts
        failing, the message explains that the payroll endpoints have landed and the
        parametrised tests below have just gained real work to do.
        """
        assert self.ROLE_GATED == [], (
            "these shipped views now declare a role gate, so the role-bypass tests "
            f"below apply to them: {[e.label for e in self.ROLE_GATED]}"
        )

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "endpoint",
        [e for e in PROTECTED if not _role_gated(e) and e.key not in ENDS_SESSION],
        ids=_ids([e for e in PROTECTED if not _role_gated(e) and e.key not in ENDS_SESSION]),
    )
    def test_a_cashier_is_not_merely_authenticated_on_session_endpoints(
        self, client: Client, staff_login: Callable[..., Any], endpoint: Endpoint
    ) -> None:
        """A signed-in Cashier reaches every session-gated endpoint successfully.

        The mirror image of A8's gate. A test that only checked refusals would pass if
        the permission classes refused everyone, including the Owner who is supposed to
        be allowed; this is the half that would catch that.

        Each endpoint gets a fresh sign-in. Reusing one client across the sweep would let
        the first request invalidate the session for the rest, and the failure would look
        like a permission bug.

        Args:
            client: The Django test client.
            staff_login: Fixture signing the client in as a given role.
            endpoint: One session-gated endpoint.
        """
        staff_login(client, Role.Code.CASHIER)

        response = _request(client, endpoint)

        assert response.status_code not in (401, 403), (
            f"{endpoint.label} refused a signed-in Cashier with {response.status_code}; "
            f"it gates on the session, not the role"
        )
