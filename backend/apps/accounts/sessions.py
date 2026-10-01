"""Session lifetime and forced password change (spec §9.3, roadmap A6).

§9.3 asks for "session timeout and logout/invalidation" and names no number, so
this module implements the two rules the spec is explicit about and reads the
durations from :class:`~apps.accounts.models.SiteSetting`, which the Owner can
change at runtime.

**Idle timeout, enforced here rather than by Django.** Django's
``SESSION_COOKIE_AGE`` is an *absolute* lifetime measured from when the session was
created, and it expires the cookie rather than the session row. A shift is not
eight hours of continuous clicking, so what an operator means by "the session
timed out" is time since the last request. Django can do that with
``SESSION_SAVE_EVERY_REQUEST``, but it makes every API call a database write just
to move an expiry, on the one path that has to stay fast. Instead the last-activity
timestamp is stamped in the session itself and the age is checked here, so a
request either touches the session row or does not.

**Why the refusal is 403 and not 401.** The A4 contract is that 401 means "no
session, sign in again" and 403 means "signed in, not allowed to do this", and the
frontend branches on exactly that. Django's own expiry produces the 401 case,
because the session row is gone and there is no user to attribute. This timeout is
a different situation: the session is intact and the user is known, and Barkot is
saying *this session has run out*. Answering 401 would collapse it into the
identical-looking no-session case. So both refusals here are
:class:`~apps.core.exceptions.BARKOTDomainError` subclasses carrying their own
``code``, which is the distinction the frontend switches on:

- :class:`~apps.core.exceptions.SessionExpired` - sign in again.
- :class:`~apps.core.exceptions.PasswordChangeRequired` - set a new password, then
  continue.
- ``permission_denied`` - the session is fine and the answer is still no.

**The session is flushed when the timeout trips.** Leaving it in place would let
the user proceed on a later request if the clock moved backwards, or if a second
request raced this one between the check and the flush. Deleting the row makes the
refusal unconditional, and the frontend's next call is then an honest 401.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.contrib.sessions.models import Session
from django.http import HttpRequest
from django.utils import timezone
from rest_framework.request import Request

from apps.accounts.models import User
from apps.core.exceptions import PasswordChangeRequired, SessionExpired

#: Key the last-activity timestamp is stored under in the session dict. Django
#: exposes that dict as ``request.session`` and stores it server-side, so a client
#: can neither read the stamp nor forge it to look fresh.
LAST_ACTIVITY_KEY = "barkov_last_activity"

#: Fallback idle timeout when the settings row cannot be read. Eight hours is one
#: shift: long enough not to interrupt work, short enough that a terminal left open
#: overnight is not a valid session in the morning.
DEFAULT_IDLE_TIMEOUT_MINUTES = 480

#: Views reachable while a forced password change is outstanding. Everything else
#: answers ``password_change_required``. Identified by view class rather than by
#: path so a path refactor cannot silently widen the escape hatch, and deliberately
#: short: ``/auth/me`` so the client can render the change screen, ``/auth/logout``
#: so nobody is trapped in a session they are not allowed to use, the change endpoint
#: itself, and ``/auth/csrf`` because the client cannot POST the change without a
#: token - allowing everything except that last one makes the forced change
#: impossible to complete.
ALLOWED_WHILE_PASSWORD_CHANGE_PENDING = frozenset({
    "apps.accounts.views.ChangePasswordView",
    "apps.accounts.views.CsrfView",
    "apps.accounts.views.LogoutView",
    "apps.accounts.views.MeView",
})


def idle_timeout_minutes() -> int:
    """Return the idle timeout in minutes.

    ``settings.SESSION_TIMEOUT_MINUTES`` takes precedence when it is a positive
    integer: a limit that can only be changed through a UI cannot be tightened
    during an incident without that UI, which is exactly when tightening it is the
    response.

    Returns:
        The timeout in minutes. Never zero, because zero would mean "expire on the
        next request", and a zero is far more likely to be an unset field than a
        deliberate instruction.
    """
    configured = getattr(settings, "SESSION_TIMEOUT_MINUTES", None)
    if isinstance(configured, int) and configured > 0:
        return configured

    try:
        from apps.accounts.models import SiteSetting

        return max(1, SiteSetting.load().session_timeout_minutes)
    except Exception:
        # The settings row is unavailable: no database, or the table has not been
        # migrated. Falling back keeps the endpoint answering 401/403 rather than
        # turning an authentication decision into a 500. The broad catch is
        # deliberate - a missing table and a connection error are both "the
        # settings could not be read", and neither should surface as a crash.
        return DEFAULT_IDLE_TIMEOUT_MINUTES


def touch_session(request: Request | HttpRequest) -> None:
    """Stamp the session as active right now.

    Called on sign-in and on every authenticated request. Assigning into the
    session dict marks it modified, so Django persists the new expiry at the end of
    the response even though ``SESSION_SAVE_EVERY_REQUEST`` is off.

    Args:
        request: The incoming request, carrying the session to stamp.
    """
    request.session[LAST_ACTIVITY_KEY] = timezone.now().timestamp()


def idle_seconds(request: Request | HttpRequest) -> float | None:
    """Return how long the session has been idle, or None when unknown.

    ``None`` means "do not enforce", not "expired". It is returned for a session
    with no timestamp: one created before this code shipped, or one stamped by a
    path that does not authenticate. Refusing those would lock out every member of
    staff the moment the deployment rolled over, which is the worst failure mode
    available to a security control - it looks like it is working because it is
    refusing everyone.

    Args:
        request: The incoming request, carrying the session to inspect.

    Returns:
        Idle time in seconds, or None when the session carries no stamp to judge.
    """
    stamp = request.session.get(LAST_ACTIVITY_KEY)
    if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
        return None
    # A clock that moved backwards, or a stamp written by a host whose clock is
    # ahead, must not read as a huge idle time. Clamping to zero means such a
    # session gets a full window rather than being ended immediately.
    return max(0.0, timezone.now().timestamp() - stamp)


def is_expired(request: Request | HttpRequest) -> bool:
    """Whether this session has been idle past the configured limit.

    Args:
        request: The incoming request, carrying the session to judge.

    Returns:
        True when the session may be ended.
    """
    idle = idle_seconds(request)
    return idle is not None and idle > idle_timeout_minutes() * 60


def password_change_pending(user: User) -> bool:
    """Whether this user must be made to set a new password first.

    Reads only ``User.is_temporary_password``, with no per-session copy of the
    decision. A second source of truth would be wrong in both directions: an
    administrative reset of the model flag could not clear a stale per-session
    marker, so a restored account would stay blocked until that session expired.
    Since DRF reloads the user from the database on every request, the model field
    is already current - clearing it takes effect on the very next call, with no
    re-login.

    Args:
        user: The authenticated user.

    Returns:
        True when a forced change is outstanding.
    """
    return bool(user.is_temporary_password)


def enforce_session_rules(request: Request, user: Any, view_key: str) -> None:
    """Apply both session rules, or let the request through.

    They live together because they answer one question - may this user use this
    endpoint - and a new endpoint that opted into one but not the other would be
    reachable by a session that should not be able to use it. Order is fixed:
    expiry first, because an expired session is refused regardless of what
    else is wrong with it, and the client needs to be told to sign in again
    rather than to fix a password in a session that is already gone.

    Args:
        request: The incoming request, carrying the session to judge.
        user: The user the authenticator just resolved.
        view_key: Dotted ``module.ClassName`` of the view being called.

    Raises:
        SessionExpired: If the session has idled past the limit. The session is
            ended first, so the refusal cannot be undone by a retry.
        PasswordChangeRequired: If a change is outstanding and this endpoint is not
            one of :data:`ALLOWED_WHILE_PASSWORD_CHANGE_PENDING`.
    """
    if user is None or not user.is_authenticated:
        # No session at all: that is a 401, decided by the authenticator before
        # this point. Refusing here would replace it with a 403 and break the
        # frontend's redirect-to-login behaviour.
        return

    if is_expired(request):
        end_session(request)
        raise SessionExpired

    if password_change_pending(user) and (view_key not in ALLOWED_WHILE_PASSWORD_CHANGE_PENDING):
        raise PasswordChangeRequired


def end_session(request: Request | HttpRequest) -> None:
    """End the session server-side and expire the browser's cookie.

    Deliberately does not call ``django.contrib.auth.logout``. That function reads
    ``request.user`` to decide whether there is anyone to sign out, and on a DRF
    ``Request`` that attribute is a property which performs authentication on
    access. This runs from *inside* authentication, so reading it restarts the very
    authenticator that called it and recurses until the stack limit. Flushing the
    session directly does what logout was wanted for here, without the read.

    The row is deleted explicitly as well, because an expired session is by
    definition one that was never touched, and an untouched session is left for
    ``expire_date`` to collect.

    Args:
        request: The request whose session is being ended.
    """
    session_key = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
    request.session.flush()
    if session_key:
        Session.objects.filter(session_key=session_key).delete()
