"""Domain exceptions and the API error envelope (spec §20.2).

A business rule violation is a normal outcome, not a server fault. A cashier
insufficiently stocked, a double count, a voided sale — these must come back as
a clear 4xx with a stable machine-readable ``code``, never as a 500 with a
traceback (principle P09, spec §24.1).

Every 4xx and 5xx the API produces by choice has the same body shape::

    {"error": {"code": "insufficient_stock", "message": "...", "details": {...}}}

``code`` is the contract. The frontend switches on it and never parses
``message``. ``details`` is present only for field-level validation failures.

The distinction enforced here:

- :class:`BARKOTDomainError` subclasses carry a ``code`` and an HTTP
  ``status``. They are raised deliberately by services when an invariant is
  violated.
- Anything else is a bug and surfaces as a 500. Wrapping a programming error in
  a ``DomainError`` would hide it behind a "valid" business response.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    MethodNotAllowed,
    NotAcceptable,
    NotAuthenticated,
    NotFound,
    ParseError,
    PermissionDenied,
    Throttled,
    UnsupportedMediaType,
    ValidationError,
)
from rest_framework.response import Response


class BARKOTDomainError(Exception):
    """Base class for deliberate business-rule violations.

    Attributes:
        code: Stable, machine-readable identifier. The frontend switches on this
            and must not parse the human message.
        message: Human-readable explanation, safe to show a staff member.
        status_code: HTTP status for the API layer.
    """

    code: str = "domain_error"
    status_code: int = status.HTTP_400_BAD_REQUEST
    default_message: str = "The operation violates a business rule."

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        self.message = message or self.default_message
        if code is not None:
            self.code = code
        super().__init__(self.message)


class InsufficientStock(BARKOTDomainError):
    """A sale or stock-out would drive available stock below zero (spec §12.2)."""

    code = "insufficient_stock"
    status_code = status.HTTP_409_CONFLICT
    default_message = "Not enough stock is available."


class InvalidStateTransition(BARKOTDomainError):
    """A record is not in a state that allows the requested operation.

    Examples: voiding an already-voided sale, approving a cancelled payroll run,
    receiving stock against a completed receipt.
    """

    code = "invalid_state_transition"
    status_code = status.HTTP_409_CONFLICT
    default_message = "This operation is not allowed in the current state."


class ImmutableRecord(BARKOTDomainError):
    """An attempt to edit a record that must never change after creation.

    The append-only stock ledger (spec §12) and completed payroll line items are
    examples: to correct one, void the originating document rather than editing
    the ledger row.
    """

    code = "immutable_record"
    status_code = status.HTTP_409_CONFLICT
    default_message = "This record cannot be modified."


class InconsistentTotals(BARKOTDomainError):
    """Supplied subtotals do not reconcile with the underlying line items.

    Raised instead of silently recomputing, so a client-side calculation bug
    surfaces immediately rather than producing a subtly wrong total.
    """

    code = "inconsistent_totals"
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "The supplied totals do not match the line items."


class SessionExpired(BARKOTDomainError):
    """The session idled past the configured limit and has been ended (spec §9.3).

    403 carrying its own ``code``, not a 401. The A4 contract is that 401 means
    "no session, sign in again" and 403 means "signed in, not allowed"; Django's
    own expiry produces the 401 case, because the session row is gone. This is a
    different situation - the session is intact and the user is known, and Barkot
    is refusing it deliberately - so it is refused with a code the frontend can
    switch on, rather than a status that would collapse it into the identical
    no-session case. See :mod:`apps.accounts.sessions`.

    Declared here rather than beside the session rules because this module is the
    project's single registry of error codes; a client that has to look in two
    places to find every code the API can return will eventually miss one.
    """

    code = "session_expired"
    status_code = status.HTTP_403_FORBIDDEN
    default_message = "Your session has expired. Sign in again to continue."


class PasswordChangeRequired(BARKOTDomainError):
    """The account is on a temporary password and must set a new one (spec §9.3).

    Refused on every endpoint except the change endpoint, ``/auth/me`` and
    ``/auth/logout``. A temporary password exists because it was generated or set
    by somebody else, so continuing to work under it defeats the point of issuing
    one. The two read endpoints stay open so a user is not locked out of the screen
    that tells them what to do, or of the button that ends the session.
    """

    code = "password_change_required"
    status_code = status.HTTP_403_FORBIDDEN
    default_message = "Your password must be changed before you can continue."


class IdempotencyKeyReuse(BARKOTDomainError):
    """One idempotency key was presented with two different request bodies (spec §10.2).

    The key is a promise that "this exact request has already been handled". When a
    client reuses a key for a *different* body, one of two things has happened: the
    client generated its keys wrongly, or two callers collided. Neither is safe to
    serve, and silently returning the first result would be the worst answer of all -
    the caller would believe their second, different request had been applied.

    Refusing is also what makes the mechanism trustworthy: a key is a claim about
    *content*, not merely a de-duplication token.
    """

    code = "idempotency_key_reuse"
    status_code = status.HTTP_409_CONFLICT
    default_message = "That idempotency key was already used for a different request."


class IdempotencyInFlight(BARKOTDomainError):
    """A concurrent request holds the same idempotency key and has not finished.

    Distinct from :class:`IdempotencyKeyReuse` on purpose: nothing is wrong with the
    caller here, the request simply arrived while the first attempt was still
    running. A client that sees this should retry the same key shortly rather than
    minting a new one, which is what makes a double-click harmless.
    """

    code = "idempotency_in_flight"
    status_code = status.HTTP_409_CONFLICT
    default_message = "An identical request is still being processed. Retry shortly."


VALIDATION_MESSAGE = "The submitted data is invalid."
NON_FIELD_ERRORS = "non_field_errors"

#: (exception type, code, message) for every non-domain failure the API can
#: produce. Ordered most-specific first: ``NotAuthenticated`` subclasses
#: ``AuthenticationFailed``, and ``NotFound`` subclasses Django's ``Http404``,
#: so a reversed table would report the wrong code.
_ENVELOPE_CODES: tuple[tuple[type[Exception], str, str], ...] = (
    (
        NotAuthenticated,
        "not_authenticated",
        "Sign in to continue. Your session may have expired.",
    ),
    (
        AuthenticationFailed,
        "authentication_failed",
        "Those credentials were not accepted.",
    ),
    (PermissionDenied, "permission_denied", "You do not have permission to do that."),
    (DjangoPermissionDenied, "permission_denied", "You do not have permission to do that."),
    (NotFound, "not_found", "The requested resource does not exist."),
    (Http404, "not_found", "The requested resource does not exist."),
    (MethodNotAllowed, "method_not_allowed", "That HTTP method is not allowed here."),
    (NotAcceptable, "not_acceptable", "That response format is not available."),
    (ParseError, "parse_error", "The request body is not valid JSON."),
    (UnsupportedMediaType, "unsupported_media_type", "Send the request as JSON."),
    (
        Throttled,
        "throttled",
        "Too many requests. Wait a moment and try again.",
    ),
)


def _validation_details(detail: Any) -> dict[str, list[str]]:
    """Flatten a DRF ``ValidationError`` detail into ``{field: [messages]}``.

    DRF uses three shapes depending on where the error came from: a dict of
    field errors from a serializer, a bare list for a non-field error, or a
    string. They are normalised to one so the frontend has a single code path
    for "this field is wrong".

    Args:
        detail: The ``detail`` attribute of a DRF ``ValidationError``.

    Returns:
        Field names mapped to their messages, with ``non_field_errors`` used for
        errors that belong to no single field.
    """
    if isinstance(detail, dict):
        return {
            str(field): [str(message) for message in messages] for field, messages in detail.items()
        }
    if isinstance(detail, list):
        return {NON_FIELD_ERRORS: [str(message) for message in detail]}
    return {NON_FIELD_ERRORS: [str(detail)]}


def _describe(exc: Exception, response: Response) -> tuple[str, str, dict[str, list[str]] | None]:
    """Choose the envelope ``code`` and ``message`` for a non-domain error.

    Args:
        exc: The exception DRF did not raise itself.
        response: The response DRF's own handler produced, used only to recover
            its wording when the exception is not in :data:`_ENVELOPE_CODES`.

    Returns:
        A ``(code, message, details)`` triple. ``details`` is ``None`` unless
        this is a field-level validation failure.
    """
    if isinstance(exc, ValidationError):
        return "validation_error", VALIDATION_MESSAGE, _validation_details(exc.detail)

    for exc_type, code, message in _ENVELOPE_CODES:
        if isinstance(exc, exc_type):
            return code, message, None

    # An APIException added to DRF after this table was written. Keep DRF's own
    # wording rather than inventing one, but still return the envelope so the
    # frontend never has to handle two error shapes.
    fallback = ""
    if isinstance(response.data, dict):
        detail = response.data.get("detail")
        if isinstance(detail, str):
            fallback = detail
    return "api_error", fallback or "The request could not be completed.", None


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Render any API failure as ``{"error": {"code", "message", "details?"}}``.

    Wired in via ``REST_FRAMEWORK["EXCEPTION_HANDLER"]``. Without it, a
    business rule violation surfaces as a bare 400 ``{"detail": "..."}``, a
    serializer failure as ``{"amount": ["Enter a number."]}``, and a permission
    denial as a third shape again — so the frontend ends up pattern-matching
    three different error formats.

    Only ``response.data`` is rewritten. DRF has already chosen the status
    code and attached protocol headers that must survive the rewrite:
    ``Retry-After`` on a 429, ``WWW-Authenticate`` on a 401. Building a fresh
    ``Response`` here would silently drop both.

    Returns ``None`` for anything DRF does not recognise, which makes
    ``APIView.handle_exception`` re-raise it. Genuine bugs stay 500s with a
    traceback rather than being dressed up as a valid business response.

    Args:
        exc: The exception raised.
        context: DRF's exception context.

    Returns:
        A DRF ``Response``, or ``None`` when the exception is not one DRF knows
        how to represent (which makes Django raise it as a 500).
    """
    if isinstance(exc, BARKOTDomainError):
        return Response(
            {"error": {"code": exc.code, "message": exc.message}},
            status=exc.status_code,
        )

    # Imported here rather than at module scope. rest_framework.views reads
    # DEFAULT_AUTHENTICATION_CLASSES while it is being imported, which imports
    # apps.core.authentication, which imports apps.accounts.sessions, which needs
    # the domain errors declared in this module. Importing at the top made that a
    # cycle that only surfaced as an ImportError during settings resolution.
    # By the time any exception reaches this function the app registry is loaded,
    # so the deferred import always resolves.
    from rest_framework.views import exception_handler as drf_exception_handler

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    code, message, details = _describe(exc, response)
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    response.data = {"error": body}
    return response
