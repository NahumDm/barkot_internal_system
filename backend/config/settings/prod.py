"""Production settings.

Nginx terminates TLS on the host (spec §8.3); Django still enforces HTTPS
cookie policies and, when DJANGO_SECURE_SSL_REDIRECT is set, redirects.

This module refuses to import unless it is given a real secret key. An unset
``DJANGO_SECRET_KEY`` falls back to a value published in the repository, and a
system that boots with it will sign session cookies, CSRF tokens and password
reset links with a key an attacker can read. Failing at import is deliberate:
a refused start is recoverable, a forged session is not, and the failure is
visible in the deploy log rather than discovered later in production.
"""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import DEV_INSECURE_SECRET_KEY, TRUSTED_PROXY

# Not configurable. There is deliberately no DJANGO_DEBUG escape hatch: a
# production process that can be talked into debug mode serves tracebacks,
# SQL and settings to whoever asks. Removing this needs a code change and a
# review, which is the point.
DEBUG = False


def _require_real_secret_key() -> None:
    """Refuse to boot on a missing, default or trivially weak secret key.

    Raises:
        ImproperlyConfigured: If ``SECRET_KEY`` is unset, still the development
            default, or too short to resist brute force.
    """
    configured = os.environ.get("DJANGO_SECRET_KEY", "").strip()

    if not configured:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set in production. Generate one with "
            '`python -c "from django.core.management.utils import '
            'get_random_secret_key as k; print(k())"` and supply it through '
            "the environment or secret manager, never in source control."
        )

    if configured == DEV_INSECURE_SECRET_KEY:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is still the development placeholder "
            f"({DEV_INSECURE_SECRET_KEY!r}), which is published in this "
            "repository. Set a unique value per environment."
        )

    if len(configured) < 50:
        raise ImproperlyConfigured(
            f"DJANGO_SECRET_KEY is only {len(configured)} characters; use at "
            "least 50. This is the signing key for sessions, CSRF tokens and "
            "password resets."
        )


_require_real_secret_key()

if os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "false").lower() in {"1", "true", "yes"}:
    SECURE_SSL_REDIRECT = True

# Nginx (infrastructure/nginx) terminates TLS and forwards the caller's original
# scheme in X-Forwarded-Proto. Without this, Django would see every proxied
# request as plain http and, with SECURE_SSL_REDIRECT on, answer with an endless
# https redirect from behind the proxy. It is behind the same TRUSTED_PROXY
# switch as the throttle client-IP logic: a bare gunicorn that never set the
# header must not be led by one written by whoever sent the request.
if TRUSTED_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if os.environ.get("DJANGO_SESSION_COOKIE_SECURE", "true").lower() in {"1", "true", "yes"}:
    SESSION_COOKIE_SECURE = True

if os.environ.get("DJANGO_CSRF_COOKIE_SECURE", "true").lower() in {"1", "true", "yes"}:
    CSRF_COOKIE_SECURE = True

SESSION_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

from config.logging import get_logging_config  # noqa: E402

LOGGING = get_logging_config()
