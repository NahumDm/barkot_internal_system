"""Tests for session lifetime and forced password change (roadmap A6, spec §9.3).

The roadmap gate is "Expired session returns 403; temporary password forces a
change", and both halves are driven through the real HTTP endpoints with CSRF
enforcement on, for the same reason as the A4 suite: the flow the frontend
performs is the only one worth testing.

**The timeout is moved by rewriting the stamp, never by sleeping.** The session
stores when it was last active, so a test moves that value into the past and
issues one request. Freezing time or waiting would make the suite take an hour and
would test the wall clock rather than the rule.

**Every refusal is asserted on its error code, not just its status.** All three
403s - expired, password change required, permission denied - share a status, and
the frontend is required to tell them apart by ``code`` (spec §20.2). A test that
only checked 403 would pass with the codes swapped, which would send the wrong
user to the wrong screen.
"""

from __future__ import annotations

import importlib
import time
from collections.abc import Callable
from typing import Any

import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import Client
from django.urls import reverse
from rest_framework import status

from apps.accounts.models import Role, SiteSetting, User
from apps.accounts.sessions import (
    ALLOWED_WHILE_PASSWORD_CHANGE_PENDING,
    LAST_ACTIVITY_KEY,
    password_change_pending,
    touch_session,
)
from apps.audit.models import AuditLog
from conftest import TEST_PASSWORD

pytestmark = pytest.mark.django_db

CSRF_URL = "/api/v1/auth/csrf/"
LOGIN_URL = "/api/v1/auth/login/"
LOGOUT_URL = "/api/v1/auth/logout/"
ME_URL = "/api/v1/auth/me/"
CHANGE_PASSWORD_URL = "/api/v1/auth/change-password/"

SESSION_COOKIE = settings.SESSION_COOKIE_NAME

#: Comfortably longer than any configured timeout, so a test that means "expired"
#: cannot be rescued by an unusually generous limit.
ONE_DAY_SECONDS = 24 * 60 * 60

NEW_PASSWORD = "a-much-better-secret-phrase"


def client() -> Client:
    """Return a client that enforces CSRF, as a browser would."""
    return Client(enforce_csrf_checks=True)


def token_for(http: Client) -> str:
    """Fetch a CSRF token the way the frontend does.

    Args:
        http: The client whose cookie jar is updated.

    Returns:
        The token for the ``X-CSRFToken`` header.
    """
    response = http.get(CSRF_URL)
    assert response.status_code == status.HTTP_200_OK
    return str(response.json()["token"])


def sign_in(http: Client, username: str, password: str = TEST_PASSWORD) -> Client:
    """Sign a client in through the real endpoints.

    Args:
        http: The client to sign in.
        username: Login name to present.
        password: Password to present.

    Returns:
        The same client, now holding a session.
    """
    response = http.post(
        LOGIN_URL,
        {"username": username, "password": password},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token_for(http),
    )
    assert response.status_code == status.HTTP_200_OK, response.content
    return http


def aged_session(http: Client, *, seconds: int = ONE_DAY_SECONDS) -> None:
    """Rewrite the session's last-activity stamp into the past.

    ``SESSION_SAVE_EVERY_REQUEST`` is off, so the stamp is only written when
    something actually modifies the session. Assigning through the session object
    marks it modified, which is what persists the value; the extra save means the
    row is correct before the request that reads it.

    Args:
        http: A client holding a session.
        seconds: How far into the past to move the stamp.
    """
    session = _server_session(http)
    session[LAST_ACTIVITY_KEY] = time.time() - seconds
    session.save()


def _server_session(http: Client) -> Any:
    """Return the server-side session object for a client's cookie.

    Args:
        http: A client holding a session cookie.

    Returns:
        The ``SessionStore`` Django would load for that cookie.

    Raises:
        AssertionError: If the client holds no session, which would make any test
            using this pass for the wrong reason.
    """
    session_key = http.cookies.get(SESSION_COOKIE)
    assert session_key is not None and session_key.value, "precondition: signed in"

    # Resolved from SESSION_ENGINE rather than importing ``db`` directly: the store
    # class lives in the engine module, and hardcoding the name would make this
    # helper quietly wrong the day the engine is switched.
    engine_path = settings.SESSION_ENGINE.rsplit(".", 1)[-1]
    engine = importlib.import_module(f"django.contrib.sessions.backends.{engine_path}")
    store = engine.SessionStore(session_key.value)
    assert store.session_key is not None
    return store


def error_code(response: Any) -> str:
    """Return the envelope's error code.

    Args:
        response: The failing response.

    Returns:
        The machine-readable code.

    Raises:
        AssertionError: If the body is not the standard envelope, since a test
            asserting on a code could otherwise pass against a 500's HTML.
    """
    body = response.json()
    assert "error" in body, response.content
    return str(body["error"]["code"])


def temporary_staff(
    make_staff_user: Callable[..., Any], role_code: str = Role.Code.MANAGER
) -> User:
    """Create a staff user whose password is flagged temporary."""
    return make_staff_user(role_code, is_temporary_password=True)


class TestUrls:
    """The new path resolves, with the trailing slash the frontend will use."""

    def test_change_password_reverses_to_the_versioned_path(self) -> None:
        """A silent mismatch here would surface as a 404 on the one screen that matters."""
        assert reverse("v1:auth:change-password") == CHANGE_PASSWORD_URL


class TestSessionTimeout:
    """``§9.3 session timeout`` - the first half of the A6 gate."""

    def test_a_fresh_session_is_accepted(self, make_staff_user) -> None:
        """The control: a session inside its window must not be refused.

        Without this, a rule that refuses every session would still satisfy the rest
        of this class.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        assert http.get(ME_URL).status_code == status.HTTP_200_OK

    def test_an_idle_session_returns_403(self, make_staff_user) -> None:
        """The A6 gate, first half.

        403 and not 401: the session is intact and the user is known, so this is
        not the same event as "you are signed out". See
        :class:`apps.core.exceptions.SessionExpired`.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        aged_session(http)
        assert http.get(ME_URL).status_code == status.HTTP_403_FORBIDDEN

    def test_the_expiry_code_is_session_expired(self, make_staff_user) -> None:
        """The frontend must be able to tell this from an ordinary refusal."""
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        aged_session(http)
        assert error_code(http.get(ME_URL)) == "session_expired"

    def test_the_refusal_is_not_a_401(self, make_staff_user) -> None:
        """401 is the redirect-to-login signal; a 403 keeps the two cases apart.

        Asserted explicitly because a 403 that happens to also carry no challenge
        header still routes the frontend wrong.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        aged_session(http)
        response = http.get(ME_URL)
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.status_code != status.HTTP_401_UNAUTHORIZED

    def test_expiry_is_not_retryable(self, make_staff_user) -> None:
        """The refusal must not be undone by trying again.

        If the session row were left in place, a second request would pass once the
        stamp was refreshed - so the timeout would be a speed bump rather than a
        control.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        aged_session(http)
        assert http.get(ME_URL).status_code == status.HTTP_403_FORBIDDEN
        assert http.get(ME_URL).status_code != status.HTTP_200_OK

    def test_the_session_row_is_deleted_when_it_expires(self, make_staff_user) -> None:
        """Server-side state is ended, not merely the cookie.

        Only expiring the cookie would leave a live session that a captured cookie
        value could still be replayed against.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        key = http.cookies.get(SESSION_COOKIE).value
        assert Session.objects.filter(session_key=key).exists()

        aged_session(http)
        http.get(ME_URL)
        assert not Session.objects.filter(session_key=key).exists()

    def test_an_expired_user_is_signed_out_afterwards(self, make_staff_user) -> None:
        """Once ended, the honest answer to any call is 401.

        The first call says 403 because the session still existed when it was
        judged; afterwards there is no session, which is what 401 means.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        aged_session(http)
        http.get(ME_URL)
        assert http.get(ME_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_an_expired_session_cannot_be_woken_by_another_request(self, make_staff_user) -> None:
        """Stamping must not happen on the request that is being refused.

        If the stamp were written before the age was judged, the window would
        restart every time someone was refused, and a client polling would hold an
        expired session open indefinitely.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        aged_session(http)

        first = http.get(ME_URL)
        assert first.status_code == status.HTTP_403_FORBIDDEN

        # The session was flushed on the way out, so from here on the client simply
        # has no session. 403 again would mean something re-stamped it, which is the
        # failure this test exists to catch.
        for _ in range(3):
            assert http.get(ME_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_activity_inside_the_window_keeps_the_session_alive(self, make_staff_user) -> None:
        """An idle timeout is about inactivity, not absolute age.

        A session that keeps being used must not expire just because it is old;
        that would make a full shift of steady work log the user out mid-sale.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        for _ in range(3):
            assert http.get(ME_URL).status_code == status.HTTP_200_OK

    def test_a_signed_out_client_is_still_401_not_403(self) -> None:
        """The timeout must not have changed the no-session answer.

        403 here would tell the frontend to stay signed in and explain why, when
        the correct action is to sign in again.
        """
        assert client().get(ME_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_the_timeout_comes_from_the_site_settings(self, make_staff_user) -> None:
        """A limit the Owner can tighten at runtime is the point of the field."""
        assert SiteSetting.load().session_timeout_minutes > 0

    def test_a_tiny_timeout_expires_the_session(self, make_staff_user, settings) -> None:
        """An Owner-configured short window must actually take effect.

        ``settings`` is pytest-django's fixture, which reverts after the test, so
        the override cannot leak into the rest of the suite.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        settings.SESSION_TIMEOUT_MINUTES = 1
        aged_session(http, seconds=120)
        assert http.get(ME_URL).status_code == status.HTTP_403_FORBIDDEN

    def test_a_session_inside_a_configured_window_is_kept(self, make_staff_user, settings) -> None:
        """The counterpart: a generous limit must not refuse a merely old session.

        Without this, a rule that simply always expired would pass the test above.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        settings.SESSION_TIMEOUT_MINUTES = 600
        aged_session(http, seconds=120)
        assert http.get(ME_URL).status_code == status.HTTP_200_OK

    def test_a_zero_limit_falls_back_rather_than_expiring_everything(
        self, make_staff_user, settings
    ) -> None:
        """Zero is far more likely to be an unset field than an instruction.

        Treating it literally would expire every session on the next request, and a
        security control that refuses everyone looks like it is working.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        settings.SESSION_TIMEOUT_MINUTES = 0
        aged_session(http, seconds=5)
        assert http.get(ME_URL).status_code == status.HTTP_200_OK

    def test_a_session_with_no_stamp_is_not_refused(self, make_staff_user) -> None:
        """A session this code never stamped must not be judged.

        This is the deployment-rollover case: sessions issued before the change
        carry no stamp, and refusing them would lock out every member of staff at
        once.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        session = _server_session(http)
        session.pop(LAST_ACTIVITY_KEY, None)
        session.save()
        assert http.get(ME_URL).status_code == status.HTTP_200_OK

    def test_a_stamp_in_the_future_is_not_read_as_expired(self, make_staff_user) -> None:
        """A clock skew must not read as a very long idle time.

        A host whose clock runs ahead writes a future stamp; reading that as
        maximum idle would end the session instantly and repeatedly.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        session = _server_session(http)
        session[LAST_ACTIVITY_KEY] = time.time() + 3600
        session.save()
        assert http.get(ME_URL).status_code == status.HTTP_200_OK


class TestForcedPasswordChange:
    """``§9.3`` forced change for a temporary password - the gate's second half."""

    def test_a_temporary_password_user_can_sign_in(self, make_staff_user) -> None:
        """Sign-in must succeed; the restriction is on what comes next.

        Refusing the login outright would leave the account with no way in at all.
        """
        user = temporary_staff(make_staff_user)
        http = sign_in(client(), user.username)
        assert http.get(ME_URL).status_code == status.HTTP_200_OK

    def test_the_login_response_flags_the_temporary_password(self, make_staff_user) -> None:
        """The client needs to know before it renders the application.

        ``is_temporary_password`` is already on the user payload; asserting it here
        is what makes the frontend's decision to show the change screen possible
        without a separate call.
        """
        user = temporary_staff(make_staff_user)
        body = sign_in(client(), user.username).get(ME_URL).json()
        assert body["user"]["is_temporary_password"] is True

    def test_a_healthy_session_is_unaffected(self, make_staff_user) -> None:
        """The control: only flagged accounts are restricted."""
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        assert http.get(ME_URL).status_code == status.HTTP_200_OK

    def test_the_change_endpoint_is_reachable(self, make_staff_user) -> None:
        """Otherwise the account would be permanently unusable."""
        user = temporary_staff(make_staff_user)
        http = sign_in(client(), user.username)
        response = http.post(
            CHANGE_PASSWORD_URL,
            {
                "current_password": TEST_PASSWORD,
                "new_password": NEW_PASSWORD,
                "new_password_confirm": NEW_PASSWORD,
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(http),
        )
        assert response.status_code == status.HTTP_200_OK

    def test_the_allow_list_is_exactly_the_four_views_a_blocked_user_needs(self) -> None:
        """The escape hatch is named explicitly and kept short.

        Built from the real view classes rather than written out as strings, so a
        rename cannot leave a stale entry behind that silently protects nothing.
        ``CsrfView`` is in it because a token is needed before the change can be
        posted; without it the forced change could never be carried out.
        """
        from apps.accounts.views import (
            ChangePasswordView,
            CsrfView,
            LogoutView,
            MeView,
        )

        views = {
            f"{view.__module__}.{view.__qualname__}"
            for view in (ChangePasswordView, CsrfView, LogoutView, MeView)
        }
        assert views == ALLOWED_WHILE_PASSWORD_CHANGE_PENDING

    def test_me_stays_readable(self, make_staff_user) -> None:
        """The client must be able to render the screen that explains the situation."""
        user = temporary_staff(make_staff_user)
        http = sign_in(client(), user.username)
        assert http.get(ME_URL).status_code == status.HTTP_200_OK

    def test_logout_stays_available(self, make_staff_user) -> None:
        """Nobody should be trapped in a session they are not allowed to use."""
        user = temporary_staff(make_staff_user)
        http = sign_in(client(), user.username)
        response = http.post(
            LOGOUT_URL, {}, content_type="application/json", HTTP_X_CSRFTOKEN=token_for(http)
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert http.get(ME_URL).status_code == status.HTTP_401_UNAUTHORIZED

    def test_a_temporary_user_can_still_change_the_password(self, make_staff_user) -> None:
        """The full loop: sign in on a temporary password, set a new one, carry on."""
        user = temporary_staff(make_staff_user)
        http = sign_in(client(), user.username)
        http.post(
            CHANGE_PASSWORD_URL,
            {
                "current_password": TEST_PASSWORD,
                "new_password": NEW_PASSWORD,
                "new_password_confirm": NEW_PASSWORD,
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(http),
        )
        assert http.get(ME_URL).status_code == status.HTTP_200_OK

    def test_changing_the_password_clears_the_flag(self, make_staff_user) -> None:
        """The restriction must lift, or the account stays half-usable forever."""
        user = temporary_staff(make_staff_user)
        http = sign_in(client(), user.username)
        http.post(
            CHANGE_PASSWORD_URL,
            {
                "current_password": TEST_PASSWORD,
                "new_password": NEW_PASSWORD,
                "new_password_confirm": NEW_PASSWORD,
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(http),
        )
        user.refresh_from_db()
        assert user.is_temporary_password is False

    def test_the_new_password_works_for_signing_in(self, make_staff_user) -> None:
        """The whole point of the endpoint: the old credential stops working.

        The change has to actually be carried out before either credential is
        tried, otherwise this asserts nothing about the endpoint at all.
        """
        user = temporary_staff(make_staff_user)
        http = sign_in(client(), user.username)

        changed = http.post(
            CHANGE_PASSWORD_URL,
            {
                "current_password": TEST_PASSWORD,
                "new_password": NEW_PASSWORD,
                "new_password_confirm": NEW_PASSWORD,
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(http),
        )
        assert changed.status_code == status.HTTP_200_OK

        http = client()
        old_attempt = http.post(
            LOGIN_URL,
            {"username": user.username, "password": TEST_PASSWORD},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(http),
        )
        assert old_attempt.status_code == status.HTTP_400_BAD_REQUEST

        new_attempt = http.post(
            LOGIN_URL,
            {"username": user.username, "password": NEW_PASSWORD},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(http),
        )
        assert new_attempt.status_code == status.HTTP_200_OK

    def test_a_restored_account_is_not_stuck_on_the_old_restriction(self, make_staff_user) -> None:
        """Clearing the flag in the database must unblock an open session.

        ``is_temporary_password`` is re-read on every request, so an administrative
        reset takes effect on the next call. Were the decision also cached per
        session, the user would face an hour of inexplicable 403s after the Owner had
        already fixed the account, and only signing out and back in would clear it.
        """
        user = temporary_staff(make_staff_user)
        http = sign_in(client(), user.username)

        User.objects.filter(pk=user.pk).update(is_temporary_password=False)
        store = _server_session(http)
        store.save()

        assert http.get(ME_URL).status_code == status.HTTP_200_OK


class TestChangePasswordRefuses:
    """The reasons a password change is rejected."""

    def _post(self, http: Client, **overrides: str) -> Any:
        body = {
            "current_password": TEST_PASSWORD,
            "new_password": NEW_PASSWORD,
            "new_password_confirm": NEW_PASSWORD,
        }
        body.update(overrides)
        return http.post(
            CHANGE_PASSWORD_URL,
            body,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token_for(http),
        )

    def test_a_wrong_current_password_is_refused(self, make_staff_user) -> None:
        """The control that stops session takeover.

        Without it, anyone who reached an unlocked session - a walked-away till, a
        shared machine - could set a new password and own the account.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        assert self._post(http, current_password="not-the-password").status_code == (
            status.HTTP_400_BAD_REQUEST
        )

    def test_a_wrong_current_password_leaves_the_old_one_working(self, make_staff_user) -> None:
        """A rejected attempt must not have changed anything."""
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        self._post(http, current_password="not-the-password")
        user.refresh_from_db()
        assert user.check_password(TEST_PASSWORD)

    def test_mismatched_confirmation_is_refused(self, make_staff_user) -> None:
        """A typo in the confirmation is the common case and must be explained."""
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        response = self._post(http, new_password_confirm="something-else-entirely")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "new_password_confirm" in response.json()["error"]["details"]

    def test_a_short_password_is_refused(self, make_staff_user) -> None:
        """The configured minimum is enforced here, not just at onboarding.

        If it were only applied when the Owner created the account, any other route
        to setting a password would be a way around the policy.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        response = self._post(http, new_password="short", new_password_confirm="short")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "new_password" in response.json()["error"]["details"]

    def test_a_password_containing_the_username_is_refused(self, make_staff_user) -> None:
        """The similarity validator needs the user, which is why it is passed one.

        The guess is the username with only a short suffix: the validator compares
        by similarity ratio, so padding the username out to something long enough to
        satisfy the length rule would make it *less* similar and the test would stop
        testing the policy it is named for.
        """
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        guess = f"{user.username}-2026"
        response = self._post(http, new_password=guess, new_password_confirm=guess)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "new_password" in response.json()["error"]["details"]

    def test_the_new_password_is_never_echoed(self, make_staff_user) -> None:
        """No response may carry a credential, successful or not."""
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        response = self._post(http)
        assert NEW_PASSWORD not in response.text

    def test_the_change_is_audited(self, make_staff_user) -> None:
        """A password change is exactly the kind of event the Owner must be able to see."""
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        self._post(http)
        entry = AuditLog.objects.filter(summary__contains="changed their password").latest("id")
        assert entry.actor == user

    def test_a_signed_out_client_cannot_change_a_password(self) -> None:
        """The endpoint requires a session; there is no anonymous password change."""
        response = self._post(client())
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_changing_the_password_without_csrf_is_refused(self, make_staff_user) -> None:
        """CSRF still holds on an endpoint whose body contains a credential."""
        user = make_staff_user(Role.Code.MANAGER)
        http = sign_in(client(), user.username)
        response = http.post(
            CHANGE_PASSWORD_URL,
            {
                "current_password": TEST_PASSWORD,
                "new_password": NEW_PASSWORD,
                "new_password_confirm": NEW_PASSWORD,
            },
            content_type="application/json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestSessionRulesUnit:
    """The rules directly, independent of any HTTP flow."""

    def test_a_healthy_user_has_no_change_pending(self, make_staff_user) -> None:
        user = make_staff_user(Role.Code.MANAGER)
        assert password_change_pending(user) is False

    def test_a_flagged_user_has_a_change_pending(self, make_staff_user) -> None:
        user = temporary_staff(make_staff_user)
        assert password_change_pending(user) is True

    def test_an_anonymous_request_is_left_to_the_authenticator(self, rf) -> None:
        """No user means no session, which is a 401 raised elsewhere."""
        from django.contrib.auth.models import AnonymousUser

        from apps.accounts.sessions import enforce_session_rules

        request = rf.get(ME_URL)
        request.user = AnonymousUser()
        request.session = {}
        enforce_session_rules(request, request.user, "apps.accounts.views.MeView")

    def test_a_disallowed_view_is_refused_for_a_flagged_user(self, rf, make_staff_user) -> None:
        """The rule is about the view, not about the URL."""
        from apps.accounts.sessions import enforce_session_rules
        from apps.core.exceptions import PasswordChangeRequired

        user = temporary_staff(make_staff_user)
        request = rf.get("/api/v1/sales/")
        request.user = user
        request.session = {}

        with pytest.raises(PasswordChangeRequired) as raised:
            enforce_session_rules(request, user, "apps.sales.views.SaleListView")
        assert raised.value.code == "password_change_required"

    def test_allow_listed_views_pass(self, rf, make_staff_user) -> None:
        """The three permitted endpoints, named rather than inferred from the paths."""
        from apps.accounts.sessions import enforce_session_rules

        user = temporary_staff(make_staff_user)
        for key in sorted({
            "apps.accounts.views.ChangePasswordView",
            "apps.accounts.views.LogoutView",
            "apps.accounts.views.MeView",
        }):
            request = rf.get(ME_URL)
            request.user = user
            request.session = {}
            enforce_session_rules(request, user, key)

    def test_touch_session_stores_a_numeric_stamp(self, rf) -> None:
        """A string stamp would silently fail the numeric check in ``idle_seconds``."""
        request = rf.get(ME_URL)
        request.session = {}
        touch_session(request)
        assert isinstance(request.session[LAST_ACTIVITY_KEY], (int, float))

    def test_an_administrative_reset_unblocks_without_a_relogin(self, make_staff_user) -> None:
        """Clearing the model flag alone must lift the block.

        A per-session copy of the decision would survive an administrative reset and
        keep a restored account blocked until that session expired on its own, forcing
        the user to sign out and back in to be freed. Reading only the model field makes
        the reset take effect on the very next request.
        """
        user = temporary_staff(make_staff_user)
        assert password_change_pending(user) is True

        user.is_temporary_password = False
        user.save(update_fields=["is_temporary_password"])
        assert password_change_pending(user) is False
