"""Session authentication for the browser client (spec §9.1, §9.2).

Two things differ from DRF's stock ``SessionAuthentication``, and both are
about the error contract rather than about how authentication works.

**401 rather than 403.** DRF returns 403 when a request carries no credentials
because ``SessionAuthentication.authenticate_header`` returns ``None`` and DRF
interprets that as "this authentication scheme cannot challenge". The frontend
then cannot tell "your session expired, sign in again" from "you are signed in
but not allowed to do this", and those need very different handling: the first
is a redirect to login, the second is an error message that must not log the
user out. Returning a challenge header makes DRF answer 401 for the first case
and leaves 403 meaning genuinely forbidden.

**CSRF stays enforced.** ``SessionAuthentication.authenticate`` runs Django's
CSRF check on unsafe methods, which is the property principle P09 depends on.
This class does not touch that; it only supplies the challenge header.

**Idle timeout and forced password change are applied here** (spec §9.3, A6), once
the user is known and before the view runs. This is the only place that runs for
every endpoint, which is what makes the rules unbypassable: a view that forgot to
call the check would still be protected. The refusals are 403s carrying their own
error codes, so they stay distinguishable from an ordinary permission denial -
see :mod:`apps.accounts.sessions` for why expiry is not a 401.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request

from apps.accounts.sessions import enforce_session_rules, touch_session


class BarkotSessionAuthentication(SessionAuthentication):
    """Session authentication whose missing-credentials answer is 401."""

    def authenticate_header(self, request: HttpRequest) -> str:
        """Return the challenge DRF uses to select a 401 over a 403.

        The value is written to ``WWW-Authenticate``. Barkot's client is a
        browser bundle that authenticates with a cookie, so the scheme name is
        informational - it makes the challenge well-formed and, more to the
        point, makes DRF choose 401. It is deliberately not ``Basic`` or
        ``Bearer``: nothing should prompt the browser for credentials, and no
        token scheme is in use.

        Args:
            request: The incoming request. Unused; DRF passes it for schemes
                that name a realm per request.

        Returns:
            A challenge header value.
        """
        return 'Session realm="barkot"'

    def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        """Authenticate, then apply the session lifetime rules (spec §9.3).

        Runs in the authenticator rather than in a view or a permission class so
        that the rules apply to every endpoint, including any added later without
        remembering to opt in. The order is authenticate, then judge, then stamp:
        the timeout is measured from the last request this one is allowed to
        count, and a refused request must not extend the session it just failed.

        Args:
            request: The incoming request.

        Returns:
            Whatever the parent returns, unchanged.

        Raises:
            apps.accounts.sessions.SessionExpired: If the session has idled past
                the configured limit. The session is ended before the refusal, so
                the refusal cannot be retried into a pass.
            apps.accounts.sessions.PasswordChangeRequired: If the account is on a
                temporary password and this endpoint is not one of the permitted
                few.
        """
        result = super().authenticate(request)
        if result is None:
            # Signed out, or carrying no session at all. That is the 401 path and
            # it is decided before any session rule can apply: there is no session
            # whose age could have expired. The CSRF check the parent skipped for
            # this case is not skipped here - the login endpoint enforces it
            # itself, deliberately, because being unauthenticated is the state it
            # is designed to accept (see apps.accounts.csrf).
            return None

        enforce_session_rules(request, result[0], view_key=view_key_for(request))
        touch_session(request)
        return result


def view_key_for(request: Request) -> str:
    """Return the dotted ``module.ClassName`` of the view being called.

    The forced-password-change rule needs to know which view is asking, so it can
    let ``/auth/me``, ``/auth/logout`` and the change endpoint through. Matching
    on view classes rather than on paths is deliberate: a path is a string that a
    refactor changes without meaning to, and the failure would be a silently
    wider escape hatch.

    Args:
        request: The incoming request.

    Returns:
        The dotted path, or an empty string when no view is resolved. An empty key
        matches nothing in the allow list, so an unrecognised view is refused
        rather than waved through - the safe direction for a rule whose purpose is
        to close things off.
    """
    match = getattr(request, "resolver_match", None)
    if match is None:
        # DRF wraps the Django request; resolution lands on the inner one.
        match = getattr(getattr(request, "_request", None), "resolver_match", None)
    view = getattr(match, "func", None)
    view = getattr(view, "cls", view)
    module = getattr(view, "__module__", "")
    name = getattr(view, "__qualname__", "")
    return f"{module}.{name}"
