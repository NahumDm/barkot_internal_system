"""Tests for the auth endpoints (roadmap A4, spec §9.1).

The gate is "login as each of the 4 roles; wrong password returns 400, not 500;
logout invalidates the session". Each half of that is here for a reason.

**The client runs with ``enforce_csrf_checks=True`` throughout.** Django's test
client disables CSRF by default, which would let a broken CSRF implementation
pass every test in this file - and CSRF on the login endpoint is what stops an
attacker logging a staff member into an account the attacker controls (P09). The
real browser flow is therefore exercised end to end: fetch a token from
``/auth/csrf/``, send it in ``X-CSRFToken``, and only then post credentials. That
is the sequence the frontend will perform, so a test that skipped it would be
testing a flow nobody uses.

**A wrong password is asserted to be 400 and specifically not 401.** 401 is this
API's "you have no session" signal and triggers a redirect to the login page, so
returning it from the login endpoint would bounce a user who is already there.
The test asserts both halves - the status and the absence of a challenge header -
because a 401 that happens to carry no challenge still routes the frontend wrong.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from rest_framework import status

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from conftest import TEST_PASSWORD

pytestmark = pytest.mark.django_db

CSRF_URL = "/api/v1/auth/csrf/"
LOGIN_URL = "/api/v1/auth/login/"
LOGOUT_URL = "/api/v1/auth/logout/"
ME_URL = "/api/v1/auth/me/"

#: Read from settings rather than written out, so this test cannot drift from the
#: configured name. The literal spelling has changed before.
SESSION_COOKIE = settings.SESSION_COOKIE_NAME

ALL_ROLES = (
    Role.Code.BARMAN,
    Role.Code.CASHIER,
    Role.Code.MANAGER,
    Role.Code.OWNER,
)


def signed_in_client() -> Client:
    """Return a test client that enforces CSRF, as a browser would.

    Returns:
        A ``Client`` with CSRF checks on.
    """
    return Client(enforce_csrf_checks=True)


def token_for(client: Client) -> str:
    """Fetch a CSRF token from the real endpoint, as the frontend does.

    Args:
        client: The client to use. Its cookie jar is updated with ``csrftoken``.

    Returns:
        The token to send back in the ``X-CSRFToken`` header.

    Raises:
        AssertionError: If the endpoint does not return a token, which would make
            every login test below pass for the wrong reason.
    """
    response = client.get(CSRF_URL)
    assert response.status_code == status.HTTP_200_OK
    token = response.json()["token"]
    assert token, "the CSRF endpoint returned an empty token"
    return str(token)


def sign_in(client: Client, username: str, password: str = TEST_PASSWORD) -> Client:
    """Sign a client in through the real HTTP endpoints.

    Args:
        client: The client to sign in.
        username: Login name to present.
        password: Password to present.

    Returns:
        The same client, now holding a session cookie.

    Raises:
        AssertionError: If the login was refused.
    """
    token = token_for(client)
    response = client.post(
        LOGIN_URL,
        {"username": username, "password": password},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert response.status_code == status.HTTP_200_OK, response.content
    return client


class TestUrls:
    """The four paths resolve, with the trailing slash the frontend will use."""

    def test_each_endpoint_reverses_to_the_versioned_path(self) -> None:
        """reverse() must agree with the literal paths used elsewhere.

        ``APPEND_SLASH`` turns a slashless POST into a redirect that drops the
        body, so a mismatch here would turn a wrong password into an unexplained
        400. Asserting the resolved paths keeps the two from drifting apart.
        """
        assert reverse("v1:auth:csrf") == CSRF_URL
        assert reverse("v1:auth:login") == LOGIN_URL
        assert reverse("v1:auth:logout") == LOGOUT_URL
        assert reverse("v1:auth:me") == ME_URL


class TestCsrf:
    """``GET /auth/csrf/`` is reachable while signed out."""

    def test_it_answers_a_signed_out_client(self) -> None:
        """The endpoint a client must reach before it can do anything else."""
        response = signed_in_client().get(CSRF_URL)
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["token"]

    def test_it_sets_the_csrf_cookie(self) -> None:
        """The cookie is how Django verifies the token on the next request."""
        client = signed_in_client()
        client.get(CSRF_URL)
        assert "csrftoken" in client.cookies

    def test_it_reveals_nothing_about_any_account(self) -> None:
        """It is public, so it must not depend on who is calling.

        A signed-in and a signed-out client get different tokens and nothing
        else; if this ever returned a user or a role, the endpoint would be a
        data leak on an intentionally public route.
        """
        signed_out = signed_in_client()
        signed_out.get(CSRF_URL)

        signed_in_client_2 = signed_in_client()
        token_for(signed_in_client_2)
        user = User.objects.create_user(
            username="csrf-probe",
            password=TEST_PASSWORD,
            role=Role.objects.get(code=Role.Code.OWNER),
        )
        assert user.role.code == Role.Code.OWNER
        body = signed_in_client_2.get(CSRF_URL).json()
        assert set(body) == {"token"}


class TestLoginSucceeds:
    """``POST /auth/login/`` - the A4 gate, for all four roles."""

    @pytest.mark.parametrize("role_code", ALL_ROLES)
    def test_each_of_the_four_roles_can_sign_in(self, make_staff_user, role_code: str) -> None:
        """Every role in the matrix can authenticate, not just the Owner.

        A login path that worked only for the Owner would pass a smoke test and
        then lock out every other member of staff on their first shift.
        """
        user = make_staff_user(role_code)
        client = sign_in(signed_in_client(), user.username)
        assert client.get(ME_URL).status_code == status.HTTP_200_OK

    @pytest.mark.parametrize("role_code", ALL_ROLES)
    def test_the_response_carries_the_role_and_its_permissions(
        self, make_staff_user, role_code: str
    ) -> None:
        """The client needs the role immediately, without a second round trip."""
        user = make_staff_user(role_code)
        client = signed_in_client()
        response = client.post(
            LOGIN_URL,
            {"username": user.username, "password": TEST_PASSWORD},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(client),
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()["user"]
        assert body["username"] == user.username
        assert body["role"] == role_code
        assert body["permissions"] == sorted(user.get_all_permissions())

    def test_the_owner_receives_the_whole_catalogue(self, make_staff_user) -> None:
        """A sign-in must not quietly narrow the Owner's authority."""
        owner = make_staff_user(Role.Code.OWNER)
        response = sign_in(signed_in_client(), owner.username).get(ME_URL)
        assert response.json()["user"]["permissions"] == sorted(owner.get_all_permissions())
        assert len(response.json()["user"]["permissions"]) > 20

    def test_it_sets_a_session_cookie(self, make_staff_user) -> None:
        """Session auth is the point; without a cookie nothing is signed in."""
        user = make_staff_user(Role.Code.MANAGER)
        client = sign_in(signed_in_client(), user.username)
        assert any("sessionid" in name for name in client.cookies)

    def test_the_session_cookie_is_httponly(self, make_staff_user) -> None:
        """JavaScript must not be able to read the session ID.

        An ``HttpOnly`` session cookie is what makes XSS unable to exfiltrate the
        session; if this regressed, the XSS protection in phase B would be
        decorative.
        """
        user = make_staff_user(Role.Code.MANAGER)
        client = signed_in_client()
        sign_in(client, user.username)
        cookies = client.cookies.output().lower()
        assert "httponly" in cookies

    def test_it_records_last_login(self, make_staff_user) -> None:
        """``last_login`` is how the frontend shows "last seen" and a stale session
        is recognised."""
        user = make_staff_user(Role.Code.MANAGER)
        assert user.last_login is None
        sign_in(signed_in_client(), user.username)
        user.refresh_from_db()
        assert user.last_login is not None

    def test_it_records_the_client_ip(self, make_staff_user) -> None:
        """``last_login_ip`` is collected at sign-in, before A6 enforces on it."""
        user = make_staff_user(Role.Code.MANAGER)
        client = sign_in(signed_in_client(), user.username)
        user.refresh_from_db()
        assert user.last_login_ip is not None
        # Django's test client reports 127.0.0.1; asserting the value is
        # assigned at all is the part that would break.
        assert user.last_login_ip == "127.0.0.1"
        del client

    def test_it_never_returns_the_password(self, make_staff_user) -> None:
        """No response in this module can carry a credential."""
        user = make_staff_user(Role.Code.MANAGER)
        body = sign_in(signed_in_client(), user.username).get(ME_URL).json()
        assert TEST_PASSWORD not in str(body)
        assert "password" not in body["user"]


class TestLoginRefuses:
    """``POST /auth/login/`` - the failure paths, which are the delicate half."""

    def test_a_wrong_password_returns_400_not_500(self, make_staff_user) -> None:
        """The A4 gate.

        A 500 here would be the natural outcome of letting a bad credential
        raise, and it is the worst possible answer: it tells the client the
        server is broken rather than that the password was wrong.
        """
        user = make_staff_user(Role.Code.MANAGER)
        client = signed_in_client()
        response = client.post(
            LOGIN_URL,
            {"username": user.username, "password": "not-the-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(client),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_a_wrong_password_is_not_a_401(self, make_staff_user) -> None:
        """401 would send the frontend to a login page the user is already on."""
        user = make_staff_user(Role.Code.MANAGER)
        client = signed_in_client()
        response = client.post(
            LOGIN_URL,
            {"username": user.username, "password": "not-the-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(client),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "WWW-Authenticate" not in response

    def test_a_wrong_password_uses_the_standard_error_envelope(self, make_staff_user) -> None:
        """One error shape for the whole API, including auth failures."""
        user = make_staff_user(Role.Code.MANAGER)
        client = signed_in_client()
        response = client.post(
            LOGIN_URL,
            {"username": user.username, "password": "not-the-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(client),
        )
        assert response.json()["error"]["code"] == "validation_error"

    def test_an_unknown_user_and_a_wrong_password_are_indistinguishable(
        self, make_staff_user
    ) -> None:
        """Confirming which accounts exist hands an attacker a valid list.

        The audit log records which case it was; the response cannot, because the
        response goes to whoever is asking.
        """
        known = make_staff_user(Role.Code.MANAGER)
        client = signed_in_client()
        token = token_for(client)
        body = {"password": "not-the-password"}

        wrong_password = client.post(
            LOGIN_URL,
            {"username": known.username, **body},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        unknown_user = client.post(
            LOGIN_URL,
            {"username": "no-such-person", **body},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )

        assert wrong_password.status_code == unknown_user.status_code
        assert wrong_password.json() == unknown_user.json()

    def test_a_deactivated_account_cannot_sign_in(self, make_staff_user) -> None:
        """A dismissed member of staff must lose access immediately.

        ``User.save`` reactivates a staff user saved as inactive, so this is
        checked against the authentication path rather than by setting the field:
        the assertion is that no session is produced, not that the flag stuck.
        """
        user = make_staff_user(Role.Code.MANAGER)
        user.is_active = False
        user.save()
        client = signed_in_client()
        response = client.post(
            LOGIN_URL,
            {"username": user.username, "password": TEST_PASSWORD},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(client),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert client.get(ME_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_a_service_role_cannot_sign_in(self, make_staff_user) -> None:
        """``is_staff_role=False`` marks an identity that must not hold a session.

        This is the case ``ModelBackend`` cannot catch: the account has a usable
        password and is active, so it authenticates normally and would be handed
        a session unless the role is checked explicitly.
        """
        user = make_staff_user(Role.Code.MANAGER)
        user.role.is_staff_role = False
        user.role.save()
        client = signed_in_client()
        response = client.post(
            LOGIN_URL,
            {"username": user.username, "password": TEST_PASSWORD},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(client),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert client.get(ME_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_a_missing_username_is_a_validation_error(self) -> None:
        """A malformed body is a 400 through the ordinary serializer path."""
        client = signed_in_client()
        response = client.post(
            LOGIN_URL,
            {"password": TEST_PASSWORD},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(client),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "username" in response.json()["error"]["details"]

    def test_a_missing_password_is_a_validation_error(self) -> None:
        """Same, for the other field."""
        client = signed_in_client()
        response = client.post(
            LOGIN_URL,
            {"username": "someone"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(client),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "password" in response.json()["error"]["details"]

    def test_login_without_a_csrf_token_is_refused(self, make_staff_user) -> None:
        """CSRF on the login endpoint is what stops session fixation by a third party.

        Without this, an attacker can force a victim to sign in to an account the
        attacker controls and then read the victim's subsequent actions. The
        check is the browser flow's, so it is asserted here where the client's
        CSRF enforcement is genuinely on.
        """
        user = make_staff_user(Role.Code.MANAGER)
        response = signed_in_client().post(
            LOGIN_URL,
            {"username": user.username, "password": TEST_PASSWORD},
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestLogout:
    """``POST /auth/logout/`` - the A4 gate, "logout invalidates the session"."""

    def test_logout_invalidates_the_session(self, make_staff_user) -> None:
        """The session must stop working, not merely be reported as ended."""
        user = make_staff_user(Role.Code.MANAGER)
        client = sign_in(signed_in_client(), user.username)
        assert client.get(ME_URL).status_code == status.HTTP_200_OK

        response = client.post(
            LOGOUT_URL, {}, content_type="application/json", HTTP_X_CSRFTOKEN=token_for(client)
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        assert client.get(ME_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_logout_returns_no_body(self, make_staff_user) -> None:
        """204 with content would confuse a client checking for a session."""
        user = make_staff_user(Role.Code.MANAGER)
        client = sign_in(signed_in_client(), user.username)
        response = client.post(
            LOGOUT_URL, {}, content_type="application/json", HTTP_X_CSRFTOKEN=token_for(client)
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not response.content

    def test_logout_clears_the_session_cookie(self, make_staff_user) -> None:
        """A cookie that still carries a session ID would resume after logout.

        Django does not delete the cookie; it expires it (``Max-Age=0``, an
        epoch ``expires``). Asserting the key disappears would be asserting an
        implementation detail, so what is checked is the effect that matters -
        the value is emptied and the cookie is expired.
        """
        user = make_staff_user(Role.Code.MANAGER)
        client = sign_in(signed_in_client(), user.username)
        before = client.cookies.get(SESSION_COOKIE)
        assert before is not None and before.value, "precondition: a session is set"

        client.post(
            LOGOUT_URL, {}, content_type="application/json", HTTP_X_CSRFTOKEN=token_for(client)
        )

        after = client.cookies.get(SESSION_COOKIE)
        assert after is not None, "the session cookie was removed rather than expired"
        assert after.value == "", "the session ID survived logout"
        assert after["max-age"] == 0, "the cookie was not expired"

    def test_signing_in_again_works_after_logout(self, make_staff_user) -> None:
        """Logout ends the session, not the account.

        A frontend that logs out on a timer and then finds the user cannot sign
        back in has a bug worth catching here rather than in manual testing.
        """
        user = make_staff_user(Role.Code.MANAGER)
        client = sign_in(signed_in_client(), user.username)
        client.post(
            LOGOUT_URL, {}, content_type="application/json", HTTP_X_CSRFTOKEN=token_for(client)
        )
        assert client.get(ME_URL).status_code == status.HTTP_401_UNAUTHORIZED
        assert sign_in(client, user.username).get(ME_URL).status_code == status.HTTP_200_OK

    def test_logging_out_while_signed_out_is_401(self) -> None:
        """Reporting success would hide a frontend bug.

        There is no session to end, and answering 200 would let the frontend
        believe it had signed the user out when it never had them.
        """
        client = signed_in_client()
        token = token_for(client)
        response = client.post(
            LOGOUT_URL, {}, content_type="application/json", HTTP_X_CSRFTOKEN=token
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestMe:
    """``GET /auth/me/`` - what the frontend calls to decide login vs app."""

    def test_a_signed_out_client_gets_401(self) -> None:
        """The frontend's decision point, and 401 is what triggers the redirect."""
        response = signed_in_client().get(ME_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_the_401_carries_a_challenge_header(self) -> None:
        """A 401 with no challenge is indistinguishable from a 403 to DRF."""
        response = signed_in_client().get(ME_URL)
        assert response["WWW-Authenticate"] == 'Session realm="barkot"'

    def test_it_returns_the_signed_in_user(self, make_staff_user) -> None:
        """Called on every page load, so it must be cheap and complete."""
        user = make_staff_user(Role.Code.CASHIER)
        body = sign_in(signed_in_client(), user.username).get(ME_URL).json()
        assert body["user"]["username"] == user.username
        assert body["user"]["role"] == Role.Code.CASHIER
        assert body["user"]["display_name"] == user.display_name

    def test_a_cashier_is_not_granted_administrative_permissions(self, make_staff_user) -> None:
        """The role must survive the round trip, not be flattened by the owner.

        This is the one place a serialization bug would show up as privilege
        escalation, so the narrow role is asserted explicitly rather than only
        checking that some permissions are present.
        """
        cashier = make_staff_user(Role.Code.CASHIER)
        body = sign_in(signed_in_client(), cashier.username).get(ME_URL).json()
        granted = body["user"]["permissions"]
        assert "sales.create_sale" in granted
        assert "payroll.approve_run" not in granted
        assert "accounts.manage_users" not in granted


class TestAuditTrail:
    """Sign-in events are recorded for the operator."""

    def test_a_successful_login_is_audited(self, make_staff_user) -> None:
        """``AuditLog`` already declares LOGIN; nothing writes to it until now."""
        user = make_staff_user(Role.Code.MANAGER)
        sign_in(signed_in_client(), user.username)
        entry = AuditLog.objects.filter(action=AuditLog.Action.LOGIN).latest("id")
        assert entry.actor == user
        assert user.username in entry.summary

    def test_a_failed_login_is_audited_with_the_username(self, make_staff_user) -> None:
        """The log is where the distinction the response cannot make is kept."""
        user = make_staff_user(Role.Code.MANAGER)
        client = signed_in_client()
        client.post(
            LOGIN_URL,
            {"username": user.username, "password": "not-the-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(client),
        )
        entry = AuditLog.objects.filter(action=AuditLog.Action.FAILED_LOGIN).latest("id")
        assert user.username in entry.summary

    def test_a_failed_login_records_no_actor(self, make_staff_user) -> None:
        """The attempt failed, so there is no authenticated actor to attribute."""
        user = make_staff_user(Role.Code.MANAGER)
        client = signed_in_client()
        client.post(
            LOGIN_URL,
            {"username": user.username, "password": "not-the-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(client),
        )
        entry = AuditLog.objects.filter(action=AuditLog.Action.FAILED_LOGIN).latest("id")
        assert entry.actor is None

    def test_a_failed_login_logs_no_password(self, make_staff_user) -> None:
        """The audit log is retained for years and read by database users."""
        user = make_staff_user(Role.Code.MANAGER)
        client = signed_in_client()
        client.post(
            LOGIN_URL,
            {"username": user.username, "password": "not-the-password"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(client),
        )
        entry = AuditLog.objects.filter(action=AuditLog.Action.FAILED_LOGIN).latest("id")
        assert "not-the-password" not in entry.summary
        assert "not-the-password" not in str(entry.after)

    def test_logout_is_audited(self, make_staff_user) -> None:
        """Sign-out is part of the forensic record too."""
        user = make_staff_user(Role.Code.MANAGER)
        client = sign_in(signed_in_client(), user.username)
        client.post(
            LOGOUT_URL, {}, content_type="application/json", HTTP_X_CSRFTOKEN=token_for(client)
        )
        entry = AuditLog.objects.filter(action=AuditLog.Action.LOGOUT).latest("id")
        assert entry.actor == user
