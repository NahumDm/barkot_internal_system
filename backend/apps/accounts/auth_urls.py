"""URLs for the auth endpoints (spec §9.1).

Mounted by :mod:`config.api_urls` at ``/api/v1/auth/``, inside the version
prefix, so the ``versioned_path`` rule applies to these endpoints like any other
business endpoint.

Every path ends in a slash because ``APPEND_SLASH`` is on. That is not cosmetic:
without it, a ``POST`` to the slashless form is answered with a redirect, and a
redirect that drops the request body turns a wrong password into an unexplained
400 with an empty body. ``settings.LOGIN_URL`` is written without the trailing
slash, which is only used by ``redirect_to_login`` and never by these views, so
the two disagreeing is harmless - but a test asserts the real URLs resolve so a
future refactor cannot quietly introduce the mismatch that would matter.
"""

from __future__ import annotations

from django.urls import path

from apps.accounts.views import CsrfView, LoginView, LogoutView, MeView

app_name = "auth"

urlpatterns = [
    path("csrf/", CsrfView.as_view(), name="csrf"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
]
