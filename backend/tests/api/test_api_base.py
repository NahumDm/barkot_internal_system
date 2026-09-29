r"""The API base: routing, versioning, and the generated schema (roadmap A2).

The gate for A2 is that the OpenAPI schema's ``paths`` is no longer empty, and
``test_the_schema_documents_at_least_one_endpoint`` is that gate. It is a test
rather than only a CI grep because an empty schema is precisely the state this
task exists to end: a frontend generates a client with no endpoints in it,
every screen 404s, and nothing else in the codebase notices.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
import yaml
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import Resolver404, resolve, reverse

from apps.accounts.models import Role
from config.api_root import API_VERSION

pytestmark = pytest.mark.django_db

TEST_URLS = "tests.api.urls_for_tests"

#: Only the Owner holds payroll.approve_run. The refusal test uses the Cashier
#: and the acceptance test the Owner, so the pair proves the check reads the
#: role matrix rather than testing a role boundary that does not exist.
APPROVER = Role.Code.OWNER
REFUSED = Role.Code.CASHIER


def generate_schema() -> dict[str, Any]:
    """Run the same management command the CI gate runs, and parse its output.

    Calling the command rather than the generator directly means this test
    exercises the document CI actually validates, including the settings that
    decide which endpoints are visible to whom.

    Returns:
        The parsed OpenAPI document.
    """
    out = io.StringIO()
    call_command("spectacular", stdout=out)
    return yaml.safe_load(out.getvalue())


# ── Versioning ──────────────────────────────────────────────────────────────


def test_the_api_lives_under_the_version_prefix() -> None:
    """Spec §8.1: the browser talks to /api/v1/..., not to a bare /api/."""
    assert reverse("v1:root") == "/api/v1/"


def test_the_version_is_readable_from_the_resolved_route() -> None:
    """DRF reports which version served a request, from the URL namespace."""
    assert resolve("/api/v1/").namespace == "v1"


def test_only_v1_is_allowed() -> None:
    """A version bump is a code change, not an accident of deployment.

    The versioning class refuses anything outside this list, so a copied
    URLconf cannot end up serving v1 views under an /api/v2/ prefix.
    """
    from django.conf import settings

    assert tuple(settings.REST_FRAMEWORK["ALLOWED_VERSIONS"]) == ("v1",)


def test_an_unimplemented_version_does_not_resolve() -> None:
    """/api/v2/ is a 404 today, not a silent alias for v1.

    Asserted with ``pytest.raises`` because ``resolve()`` raises rather than
    returning None, and an ``assert x is None`` would fail for the wrong reason
    if that ever changed.
    """
    with pytest.raises(Resolver404):
        resolve("/api/v2/")


# ── The API root ────────────────────────────────────────────────────────────


def test_the_api_root_identifies_the_service() -> None:
    """The frontend calls this at start-up to catch a stale bundle after deploy."""
    response = Client().get("/api/v1/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "Barkot Bar & Restaurant API",
        "version": API_VERSION,
        "documentation": "/api/schema/",
    }


def test_the_api_root_needs_no_session() -> None:
    """A version check that demands a session cannot report an expired one.

    Requiring authentication here would turn "your session expired" into a
    login redirect with nothing telling the user why the screen is empty.
    """
    assert Client().get("/api/v1/").status_code == 200


# ── 401 versus 403 ──────────────────────────────────────────────────────────


@override_settings(ROOT_URLCONF=TEST_URLS)
def test_a_signed_out_request_to_a_protected_route_is_401() -> None:
    """Not signed in is 401, so the client can redirect to login.

    DRF defaults to 403 here, because stock SessionAuthentication cannot
    challenge and DRF reads that as "no credential scheme applies". The
    frontend then cannot tell an expired session from a permission refusal, and
    those two need opposite handling.
    """
    response = Client().get("/api/v1/anything/")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


@override_settings(ROOT_URLCONF=TEST_URLS)
def test_the_401_carries_a_challenge_header() -> None:
    """That header is what makes the status a 401 rather than a 403."""
    response = Client().get("/api/v1/anything/")

    assert response["WWW-Authenticate"] == 'Session realm="barkot"'


@override_settings(ROOT_URLCONF=TEST_URLS)
def test_a_signed_in_user_without_the_permission_gets_403(client, staff_login) -> None:
    """Signed in but not allowed is 403, and must not read as a sign-in problem.

    A Cashier is refused. Were this a 401, the frontend would log them out for
    asking a question, and they would have no way to explain what they did.
    """
    staff_login(client, REFUSED)

    response = client.get("/api/v1/payroll/approve/")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


@override_settings(ROOT_URLCONF=TEST_URLS)
def test_a_role_holding_the_permission_is_allowed(client, staff_login) -> None:
    """The same route the other way round, so the 403 is not unconditional."""
    staff_login(client, APPROVER)

    assert client.get("/api/v1/payroll/approve/").status_code == 200


# ── One error shape, everywhere ─────────────────────────────────────────────


def test_an_unmatched_api_url_returns_the_envelope_not_an_html_page() -> None:
    """A 404 from the API is still JSON, so no client has to branch on type.

    Django's default 404 is HTML. A client that must check the content type
    before reading a code has two error paths, and the second is always the
    buggy one.
    """
    response = Client().get("/api/v1/nothing-here/")

    assert response.status_code == 404
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["error"]["code"] == "not_found"


def test_a_non_api_404_stays_an_html_page() -> None:
    """A person reading a 404 in a browser should not be handed JSON."""
    response = Client().get("/not-an-api-path/")

    assert response.status_code == 404
    assert "text/html" in response["Content-Type"]


def test_health_probes_are_unaffected() -> None:
    """Docker and Nginx depend on these; A2 must not have moved them."""
    assert Client().get("/health/live").status_code == 200


# ── The generated schema (the A2 gate) ──────────────────────────────────────


def test_the_schema_documents_at_least_one_endpoint() -> None:
    """The A2 gate: an empty ``paths`` yields a generated client with no API."""
    paths = generate_schema()["paths"]

    assert paths, "OpenAPI paths is empty: the API documents no endpoints"
    assert "/api/v1/" in paths


def test_schema_paths_keep_their_version_prefix() -> None:
    """A generated client must not have to reconstruct the prefix itself.

    Trimming ``/api/v1/`` is cosmetically tidier, but it is only correct if the
    schema also advertises a server URL. There is none here, so trimming would
    produce a client that calls ``/`` and stops working the day the API is
    served from another path.
    """
    paths = generate_schema()["paths"]

    assert all(path.startswith("/api/v1/") for path in paths), paths


def test_the_schema_is_valid_openapi() -> None:
    """The CI gate runs ``spectacular --validate``; this keeps it meaningful.

    ``--validate`` checks the document against the OpenAPI meta-schema. A
    document that is empty passes it trivially, which is why the two assertions
    above exist alongside this one.
    """
    schema = generate_schema()

    assert schema["openapi"].startswith("3.")
    assert schema["info"]["title"] == "Barkot Bar & Restaurant API"
    assert schema["components"]["schemas"], "the schema declares no reusable schemas"


def test_the_schema_requires_a_session() -> None:
    """The schema enumerates the whole internal surface, so it is not public.

    Docker's and Nginx's probes stay unauthenticated; the API contract does not.
    """
    assert Client().get("/api/schema/").status_code == 401


def test_a_signed_in_staff_member_can_read_the_schema(client, staff_login) -> None:
    """Otherwise nobody could generate the client the frontend depends on."""
    staff_login(client, Role.Code.MANAGER)

    assert client.get("/api/schema/").status_code == 200
