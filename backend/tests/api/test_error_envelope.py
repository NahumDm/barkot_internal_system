r"""The shared error envelope, exercised through real DRF dispatch.

Every test here drives an actual ``APIView`` through ``APIRequestFactory``
rather than calling ``exception_handler`` directly, because what is under test
is as much about which headers DRF attaches and which exceptions it re-raises
as it is about the body shape.

Views are defined here rather than added to the real URLconf on purpose: these
are tests of the envelope, not of any endpoint, and a test-only view that
exists only to raise is clearer than a fake endpoint in the shipped API.
"""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework import status
from rest_framework.exceptions import NotFound, ParseError, PermissionDenied, Throttled
from rest_framework.exceptions import ValidationError as DrfValidationError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.core.exceptions import InsufficientStock, InvalidStateTransition, exception_handler

factory = APIRequestFactory()


class _AlwaysFails(APIView):
    """Raises whatever the test assigned, for both GET and POST."""

    exc: Exception = RuntimeError("replaced per test")
    permission_classes = [AllowAny]
    authentication_classes: list[type] = []

    def get(self, request: Request) -> Any:
        raise self.exc

    def post(self, request: Request) -> Any:
        raise self.exc


def _fail_with(exc: Exception) -> type[_AlwaysFails]:
    """Return a view class that raises ``exc`` on any method.

    Args:
        exc: The exception the view should raise.

    Returns:
        A fresh ``APIView`` subclass, so each test gets its own failure.
    """
    return type("_Fails", (_AlwaysFails,), {"exc": exc})


def _call(view: type[APIView], *, method: str = "get", path: str = "/api/v1/thing/") -> Any:
    """Dispatch a request through a view and return the response.

    A view that raises an exception DRF does not handle propagates it out of
    this helper, which is what the 500 test relies on.

    Args:
        view: The view class to exercise.
        method: Lowercase HTTP method name.
        path: Request path; only needs to be plausible.

    Returns:
        The DRF ``Response`` the view produced.
    """
    request = getattr(factory, method)(path)
    return view.as_view()(request)


# ── Domain errors ───────────────────────────────────────────────────────────


def test_domain_error_keeps_its_own_code_and_status() -> None:
    """A business rule violation is a 409 carrying the service's own code."""
    response = _call(_fail_with(InsufficientStock()))

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data == {
        "error": {"code": "insufficient_stock", "message": "Not enough stock is available."}
    }


def test_domain_error_code_is_not_flattened_onto_one_generic_value() -> None:
    """The envelope must not collapse every failure onto a single code."""
    response = _call(_fail_with(InvalidStateTransition()))

    assert response.data["error"]["code"] == "invalid_state_transition"


def test_domain_error_message_override_is_preserved() -> None:
    """A service can explain one specific failure in its own words."""
    view = _fail_with(InsufficientStock("Only 2 bottles left."))

    response = _call(view)

    assert response.data["error"]["message"] == "Only 2 bottles left."


def test_envelope_has_no_extra_top_level_keys() -> None:
    """The frontend reads `error` and nothing else at the root of a failure."""
    response = _call(_fail_with(InsufficientStock()))

    assert set(response.data) == {"error"}
    assert set(response.data["error"]) == {"code", "message"}


# ── Validation ───────────────────────────────────────────────────────────────


def test_field_validation_errors_become_details() -> None:
    """Serializer field errors arrive as {field: [messages]}."""
    exc = DrfValidationError({"amount": ["A number is required."]})
    response = _call(_fail_with(exc))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data == {
        "error": {
            "code": "validation_error",
            "message": "The submitted data is invalid.",
            "details": {"amount": ["A number is required."]},
        }
    }


def test_non_field_validation_errors_use_a_reserved_key() -> None:
    """A form-level error belongs to no field, so it gets an explicit one."""
    response = _call(_fail_with(DrfValidationError(["Pick a payment method."])))

    assert response.data["error"]["details"] == {"non_field_errors": ["Pick a payment method."]}


def test_multiple_field_errors_are_all_reported_at_once() -> None:
    """The client fixes a whole form in one pass, not one field per round trip."""
    exc = DrfValidationError({
        "amount": ["A number is required."],
        "method": ["This field is required."],
    })
    response = _call(_fail_with(exc))

    assert set(response.data["error"]["details"]) == {"amount", "method"}


@pytest.mark.django_db
def test_malformed_json_is_a_parse_error_not_a_validation_error() -> None:
    """A body truncated by a flaky connection is not the caller's mistake.

    Marked ``django_db`` because this is the module's only POST: D0 gives every
    unsafe request the write throttle (this view is ``AllowAny``, so permission
    passes and the throttle runs), and the throttle cache is the database.
    Without the mark the request dies in the cache rather than at the parser,
    which would be a false failure.
    """
    response = _call(_fail_with(ParseError("JSON parse error")), method="post")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data["error"]["code"] == "parse_error"


# ── Access and routing failures ─────────────────────────────────────────────


def test_permission_denied_is_403_with_its_own_code() -> None:
    """Forbidden means signed in but not allowed, which is not a sign-in prompt."""
    response = _call(_fail_with(PermissionDenied()))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["error"]["code"] == "permission_denied"


def test_not_found_is_404_with_its_own_code() -> None:
    response = _call(_fail_with(NotFound()))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data["error"]["code"] == "not_found"


def test_throttled_keeps_its_retry_after_header() -> None:
    """Rewriting the body must not strip the header that says when to retry.

    Building a fresh Response instead of rewriting ``data`` in place drops every
    header DRF attached, and ``Retry-After`` is the one a client needs in order
    to handle a 429 without guessing at a backoff.
    """
    response = _call(_fail_with(Throttled(wait=42)))

    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert response.data["error"]["code"] == "throttled"
    assert response["Retry-After"] == "42"


# ── Bugs must stay bugs ─────────────────────────────────────────────────────


def test_unhandled_exception_is_not_converted_into_a_business_response() -> None:
    """A bug must remain a bug.

    Answering with an envelope for an unrecognised exception turns every
    AttributeError in every service into a tidy 4xx that looks deliberate. The
    first person to find out would be a user staring at a broken screen and a
    support log full of 400s with no traceback.
    """
    with pytest.raises(ZeroDivisionError):
        _call(_fail_with(ZeroDivisionError()))


def test_handler_returns_none_for_unrecognised_exceptions() -> None:
    """None is the signal that makes DRF re-raise instead of answering."""
    assert exception_handler(ZeroDivisionError(), {}) is None
