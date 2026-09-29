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
"""

from __future__ import annotations

from django.http import HttpRequest
from rest_framework.authentication import SessionAuthentication


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
