"""Session authentication endpoints (spec §9.1, ADR-0003 D8).

Four endpoints, and the whole of the login flow: ``/auth/csrf`` to obtain a
token, ``/auth/login`` to exchange credentials for a session, ``/auth/logout`` to
end it, ``/auth/me`` to read it back.

**Sessions, not tokens.** The browser receives an opaque session ID in an
``HttpOnly`` cookie. There is no JWT to store, no signing key to manage, and no
external identity provider. That is the whole reason ``BarketSessionAuthentication``
goes out of its way to return a challenge header: the frontend has to be able to
tell an expired session (401, sign in again) from a forbidden action (403, stay
signed in and explain why).

**CSRF is enforced on every unsafe method.** ``/auth/csrf`` exists because that
makes the browser flow impossible otherwise - the very first ``POST /auth/login/``
would be rejected for want of a token, and there is no way to obtain one. The
token is obtained *before* authenticating, which is why both endpoints are
public and why both carry a declared exemption in the contract suite.

Three deliberate choices in the failure paths, since "wrong password returns 400,
not 500" is the A4 gate and the reason behind it matters:

- **A wrong password is a validation failure, not an authentication failure.**
  DRF's ``AuthenticationFailed`` is the natural fit for bad credentials, but it
  carries status 401, which this API reserves for "you have no session". A 401
  on the login endpoint itself would tell the frontend to redirect to a login page
  it is already on. So bad credentials produce 400 ``validation_error`` through
  the ordinary serializer, exactly as a malformed request body does.
- **The failure message never distinguishes "no such user" from "wrong
  password".** Returning "unknown username" would confirm which accounts exist to
  anyone who can reach the login endpoint. The response is identical either way,
  and the audit log records which it was - the log is for the operator, the
  response is for the attacker.
- **A deactivated or non-login role cannot authenticate.** ``is_active`` and
  ``Role.is_staff_role`` are the login gates, and they are checked explicitly
  rather than left to the authentication backend, because
  ``ModelBackend.user_can_authenticate`` already refuses inactive users and a
  service identity with a role that may not log in must not authenticate either.
"""

from __future__ import annotations

import logging

from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.csrf import enforce_csrf
from apps.accounts.models import User
from apps.accounts.schemas import (
    CsrfResponseSerializer,
    LoginRequestSerializer,
    LoginResponseSerializer,
    UserSerializer,
)
from apps.audit.models import AuditLog

logger = logging.getLogger(__name__)

#: Audit ``object_type`` for sign-in events. The log reference is a string by
#: design, so an auth event is identified the same way a deleted record is.
AUTH_OBJECT_TYPE = "accounts.User"

#: One message for every credential failure. Deliberately uniform; see the module
#: docstring. Not a translation string with an f-string in it, because the point
#: is that there is only ever one of them.
INVALID_CREDENTIALS = _("Incorrect username or password.")

#: Same uniformity, for an account that exists and cannot log in.
ACCOUNT_NOT_ENABLED = _("This account cannot sign in. Contact the Owner.")


class CsrfView(APIView):
    """``GET /api/v1/auth/csrf/`` - hand out a CSRF token.

    Public on purpose. This is the one endpoint a client must be able to reach
    while signed out, and it returns nothing about any account: ``get_token`` is a
    salted hash of the secret with no user attached.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        summary="Obtain a CSRF token",
        description=(
            "Returns a CSRF token and sets the `csrftoken` cookie. Call this "
            "before the first unsafe request. The token is sent back in the "
            "`X-CSRFToken` header. Requires no authentication."
        ),
        responses={200: CsrfResponseSerializer},
        tags=["auth"],
        auth=[],
    )
    def get(self, request: Request) -> Response:
        """Return a CSRF token.

        Args:
            request: The incoming request. Passed to ``get_token`` so the token is
                bound to this request's CSRF secret, which is what lets Django
                verify it later.

        Returns:
            A 200 with the token.
        """
        return Response({"token": get_token(request)})


class LoginView(APIView):
    """``POST /api/v1/auth/login/`` - exchange credentials for a session.

    Public on purpose: signing in is how a client obtains the session it needs
    for everything else. ``BarketSessionAuthentication`` is left in place rather
    than disabled, so a request that *already* carries a session still has its
    CSRF token validated by the authenticator.

    CSRF is additionally enforced here by :func:`enforce_csrf`, because DRF does
    not do it for a signed-out request. That is not a redundant belt-and-braces:
    ``SessionAuthentication.authenticate`` returns early precisely when there is
    no user, so on this endpoint it would skip the check entirely and leave
    login-CSRF open. See :mod:`apps.accounts.csrf`.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        summary="Sign in and start a session",
        description=(
            "Verifies the username and password and starts a session. On success "
            "the response carries the user, including their role and effective "
            "permissions, and a session cookie is set. A wrong password returns "
            "400 with code `validation_error`; it does not distinguish an unknown "
            "username from a wrong password. Requires a CSRF token: obtain one "
            "from `/auth/csrf/` first. Django rotates the token on sign-in, so "
            "fetch a fresh one before the next unsafe request."
        ),
        request=LoginRequestSerializer,
        responses={
            200: LoginResponseSerializer,
            400: None,
        },
        tags=["auth"],
        auth=[],
    )
    def post(self, request: Request) -> Response:
        """Verify credentials and sign the user in.

        Args:
            request: The incoming request.

        Returns:
            A 200 with the signed-in user, or a 400 validation error when the
            credentials are not accepted.

        Raises:
            rest_framework.exceptions.PermissionDenied: If the request carries no
                valid CSRF token. See :func:`enforce_csrf`.
            rest_framework.exceptions.ValidationError: If the body is malformed,
                or the credentials are rejected.
        """
        enforce_csrf(request)
        serializer = LoginRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = authenticate(
            request=request,
            username=serializer.validated_data["username"],
            password=serializer.validated_data["password"],
        )

        if user is None:
            self._record_failure(serializer.validated_data["username"], request)
            raise ValidationError({"non_field_errors": [str(INVALID_CREDENTIALS)]})

        # authenticate() already refuses inactive users, but a service identity
        # whose role may not log in is a separate case that the backend does not
        # know about: it has a usable password and is_active, so it authenticates
        # and would otherwise be handed a session.
        if not user.role.is_staff_role:
            self._record_failure(user.username, request)
            raise ValidationError({"non_field_errors": [str(ACCOUNT_NOT_ENABLED)]})

        login(request, user)
        self._record_success(user, request)
        return Response({"user": UserSerializer(user).data})

    def _record_success(self, user: User, request: Request) -> None:
        """Audit a successful sign-in.

        ``last_login_ip`` is set here rather than in A6 because the value comes
        from this request and A6's job is enforcing what to do with it, not
        collecting it.

        Args:
            user: The user who just authenticated.
            request: The request the sign-in arrived on, for the IP address.
        """
        user.last_login_ip = _client_ip(request)
        user.save(update_fields=["last_login_ip"])
        AuditLog.record(
            action=AuditLog.Action.LOGIN,
            object_type=AUTH_OBJECT_TYPE,
            object_id=user.pk,
            actor=user,
            summary=f"{user.username} signed in",
            ip_address=_client_ip(request),
        )

    def _record_failure(self, username: str, request: Request) -> None:
        """Audit a rejected sign-in attempt.

        The username is recorded as given even when no such account exists -
        that is the useful signal for a human investigating repeated attempts, and
        it is in the log rather than in the response, which is deliberately
        indistinguishable between the two cases.

        Args:
            username: The username as submitted.
            request: The request the attempt arrived on, for the IP address.
        """
        AuditLog.record(
            action=AuditLog.Action.FAILED_LOGIN,
            object_type=AUTH_OBJECT_TYPE,
            summary=f"Failed sign-in for {username!r}",
            ip_address=_client_ip(request),
        )
        # Not the password, not the hash, not a truncated credential. The audit
        # log is read by people with database access and is retained for years.
        logger.info("Rejected sign-in attempt for username %r", username)


class LogoutView(APIView):
    """``POST /api/v1/auth/logout/`` - end the session.

    Requires a session, so signing out twice is a 401 rather than a silent
    success. That is the honest answer: the second call has no session to end,
    and reporting success would hide a client bug where the frontend thinks it
    signed out twice over.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Sign out and end the session",
        description=(
            "Flushes the session server-side and clears the session cookie. "
            "Requires a session; signing out when signed out returns 401. Send "
            "an empty JSON object as the body: DRF's CSRF check parses the body "
            "to look for a form token, so a `multipart/form-data` POST is "
            "rejected with 415. The account is not affected and signing in again "
            "works immediately."
        ),
        request=None,
        responses={204: None},
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        """End the current session.

        The request body is not read, but the request must still be sent as
        ``application/json``: DRF's CSRF check reads ``request.POST`` to find a
        form-encoded token, and that read parses the body, so a POST arriving as
        ``multipart/form-data`` - the Django test client's default for a body-less
        POST - is rejected with 415 before this runs. Sending ``{}`` avoids it.

        Args:
            request: The incoming request, carrying the session to flush.

        Returns:
            A 204 with an empty body.
        """
        user: User = request.user  # type: ignore[assignment]
        logout(request)
        AuditLog.record(
            action=AuditLog.Action.LOGOUT,
            object_type=AUTH_OBJECT_TYPE,
            object_id=user.pk,
            actor=user,
            summary=f"{user.username} signed out",
            ip_address=_client_ip(request),
        )
        return Response(status=204)


class MeView(APIView):
    """``GET /api/v1/auth/me/`` - who am I, and what may I do.

    The frontend calls this on start-up to decide between the login screen and
    the application, and after a 401 anywhere else to confirm the session really
    is gone rather than merely rejected once.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Describe the signed-in user",
        description=(
            "Returns the signed-in user with their role and effective "
            "permissions. Requires a session; returns 401 when there is none."
        ),
        responses={200: LoginResponseSerializer},
        tags=["auth"],
    )
    def get(self, request: Request) -> Response:
        """Return the signed-in user.

        Args:
            request: The incoming request. ``request.user`` is authenticated by
                ``IsAuthenticated`` before this runs.

        Returns:
            A 200 with the user.
        """
        user: User = request.user  # type: ignore[assignment]
        return Response({"user": UserSerializer(user).data})


def _client_ip(request: Request) -> str | None:
    """Return the client IP for an audit entry.

    ``X-Forwarded-For`` is consulted because the production deployment runs
    behind Nginx, and the address that reached Django is the proxy's unless the
    header is read. The leftmost entry is the originating client. This is only
    ever used for the audit log and ``last_login_ip``; it is not an authorisation
    input, so an untrusted header cannot grant anything - A5 throttling is where a
    spoofed address would actually matter, and that is left to its own task to
    decide.

    Args:
        request: The incoming request.

    Returns:
        The client address, or None when it cannot be determined.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR")
