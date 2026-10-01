"""OpenAPI schema customisations (spec §10).

drf-spectacular documents each authenticator it recognises by shipping an
``OpenApiAuthenticationExtension`` for it. Anything else it cannot resolve: it
emits ``could not resolve authenticator ... No OpenApiAuthenticationExtension
registered for that class`` and drops the endpoint's security requirement, so the
generated schema would claim that ``/auth/logout/`` and ``/auth/me/`` need no
credentials at all. That is the opposite of the truth, and the sort of thing that
sends a frontend developer off to build the wrong client.

So the extension is declared here. It registers the session cookie as an
``apiKey`` security scheme in the cookie parameter, which is how OpenAPI 3
expresses cookie authentication - there is no dedicated cookie scheme.

This module has to be imported for the registration to take effect, so
``apps.core.apps.CoreConfig.ready`` imports it. The app config is the single
place that knows the module must be loaded.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension

from apps.core.authentication import BarkotSessionAuthentication


class BarkotSessionScheme(OpenApiAuthenticationExtension):
    """Document the session cookie as an OpenAPI ``apiKey`` security scheme."""

    target_class = BarkotSessionAuthentication
    name = "sessionCookie"
    priority = 1

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        """Describe the session cookie to the schema generator.

        Args:
            auto_schema: The view's schema instance. Unused; the scheme is the
                same for every endpoint.

        Returns:
            An OpenAPI security scheme object naming the cookie.
        """
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "barkot_sessionid",
        }
