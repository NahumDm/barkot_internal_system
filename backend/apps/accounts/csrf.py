"""Explicit CSRF enforcement for the unauthenticated write path (spec §9.1, P09).

DRF does not enforce CSRF on ``POST /auth/login/``, and the reason is a single
line in ``rest_framework.authentication.SessionAuthentication.authenticate``::

    # Unauthenticated, CSRF validation not required
    if not user or not user.is_active:
        return None

Every DRF view is ``csrf_exempt`` - that is what lets DRF re-implement CSRF
inside the authenticator - so a view reached while signed out is never checked
by Django either. On every endpoint in this project that is the safe direction
of failure: an unauthenticated request is rejected by ``IsAuthenticated``
anyway. The login endpoint is the exception, because being unauthenticated is
precisely the state it is designed to accept.

Left alone, that makes login-CSRF possible: an attacker serves a page that POSTs
the victim's browser to ``/auth/login/`` with the attacker's own credentials.
The victim is silently signed in to an account the attacker controls and then
does real work in it - recording sales under a name the attacker chose, with the
password the attacker knows. The attacker reads all of it afterwards. The
response is same-origin-readable by the attacker because the session cookie is
``HttpOnly`` but the *requests* are not blocked from being made.

So this module performs the check explicitly. Django's own machinery is reused
rather than reimplemented: ``CsrfViewMiddleware.process_view`` is run against the
request, which reads the ``csrftoken`` cookie and the ``X-CSRFToken`` header and
compares them. Inventing a second comparison would be a second thing to get
wrong, and this one is the thing ``django.middleware.csrf`` already gets right.

The failure is raised as ``PermissionDenied``, which the project renders as 403
``permission_denied``. That is the right status: the request was well-formed and
the caller was refused on a security ground, not because the body was invalid.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.http import HttpResponseBase
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request


def _unreachable(*args: Any, **kwargs: Any) -> HttpResponseBase:
    """Stand in for the callables ``CsrfViewMiddleware`` insists on receiving.

    ``CsrfViewMiddleware`` takes a ``get_response`` callable and a view callback,
    and it type-checks both. Neither is ever called here: ``_reject`` below
    intercepts the rejection path, and on the accept path ``process_view``
    returns the middleware's own response rather than the callback's. They are
    passed real callables rather than ``None`` because a ``None`` here would be a
    lie about the types, and would break the moment Django starts using either.

    Args:
        *args: Ignored. Present so any callable signature fits.
        **kwargs: Ignored, for the same reason.

    Raises:
        AssertionError: Always. Reaching this would mean the middleware called
            the callback, which contradicts the reasoning above.
    """
    raise AssertionError("the CSRF check must not call through to a view")


class _CsrfCheck(CsrfViewMiddleware):
    """CSRF middleware whose response step is never reached."""

    def _reject(self, request: Request, reason: str) -> str:
        """Record the rejection reason instead of returning an HTML response.

        Args:
            request: The request being checked.
            reason: Django's explanation of why it failed.

        Returns:
            The reason, which the caller turns into a DRF exception.
        """
        return reason


def enforce_csrf(request: Request) -> None:
    """Reject the request unless it carries a valid CSRF token.

    Args:
        request: The request to check. Its ``CSRF_COOKIE`` is populated from the
            cookie first, which is what ``process_view`` then compares against
            the ``X-CSRFToken`` header.

    Raises:
        rest_framework.exceptions.PermissionDenied: If the token is absent or does
            not match.
    """
    view_callback: Callable[..., HttpResponseBase] = _unreachable
    check = _CsrfCheck(_unreachable)
    # process_request is what copies the cookie into META["CSRF_COOKIE"].
    # Without it, process_view finds no cookie and rejects every request,
    # including ones carrying a correct header.
    check.process_request(request)
    reason = check.process_view(request, view_callback, (), {})
    if reason:
        raise PermissionDenied(f"CSRF Failed: {reason}")
