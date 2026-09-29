"""Domain exceptions and their API representation (spec §20.2).

A business rule violation is a normal outcome, not a server fault. A cashier
insufficiently stocked, a double count, a voided sale — these must come back as
a clear 4xx with a stable machine-readable ``code``, never as a 500 with a
traceback (principle P09, spec §24.1).

The distinction enforced here:

- :class:`BarkotDomainError` subclasses carry a ``code`` and an HTTP ``status``.
  They are raised deliberately by services when an invariant is violated.
- Anything else is a bug and surfaces as a 500. Wrapping a programming error in
  a ``DomainError`` would hide it behind a "valid" business response.
"""

from __future__ import annotations

from typing import Any

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class BarkotDomainError(Exception):
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


class InsufficientStock(BarkotDomainError):
    """A sale or stock-out would drive available stock below zero (spec §12.2)."""

    code = "insufficient_stock"
    status_code = status.HTTP_409_CONFLICT
    default_message = "Not enough stock is available."


class InvalidStateTransition(BarkotDomainError):
    """A record is not in a state that allows the requested operation.

    Examples: voiding an already-voided sale, approving a cancelled payroll run,
    receiving stock against a completed receipt.
    """

    code = "invalid_state_transition"
    status_code = status.HTTP_409_CONFLICT
    default_message = "This operation is not allowed in the current state."


class ImmutableRecord(BarkotDomainError):
    """An attempt to edit a record that must never change after creation.

    The append-only stock ledger (spec §12) and completed payroll line items are
    examples: to correct one, void the originating document rather than editing
    the ledger row.
    """

    code = "immutable_record"
    status_code = status.HTTP_409_CONFLICT
    default_message = "This record cannot be modified."


class InconsistentTotals(BarkotDomainError):
    """Supplied subtotals do not reconcile with the underlying line items.

    Raised instead of silently recomputing, so a client-side calculation bug
    surfaces immediately rather than producing a subtly wrong total.
    """

    code = "inconsistent_totals"
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "The supplied totals do not match the line items."


def domain_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Render a :class:`BarkotDomainError` as ``{"error": {"code", "message"}}``.

    Wired in via ``REST_FRAMEWORK["EXCEPTION_HANDLER"]``. Without it, a
    business rule violation surfaces as a bare 400 ``{"detail": "..."}`` with no
    machine-readable code, and the frontend has to pattern-match prose.

    Everything else is delegated to DRF's own ``exception_handler``, which turns
    validation errors, permission denials and authentication failures into their
    normal 4xx shapes.

    Returning ``None`` would *not* delegate: ``APIView.handle_exception`` treats a
    ``None`` result as "unhandled" and re-raises, turning every DRF 4xx into a
    500. Genuinely unhandled exceptions still come back as ``None`` from DRF and
    are re-raised, which is the behaviour we want for real bugs.

    Args:
        exc: The exception raised.
        context: DRF's exception context.

    Returns:
        A DRF ``Response``, or ``None`` when the exception is not one DRF knows
        how to represent (which makes Django raise it as a 500).
    """
    if isinstance(exc, BarkotDomainError):
        return Response(
            {"error": {"code": exc.code, "message": exc.message}},
            status=exc.status_code,
        )
    return drf_exception_handler(exc, context)
