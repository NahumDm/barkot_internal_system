"""Production settings.

Nginx terminates TLS on the host (spec §8.3); Django still enforces HTTPS
cookie policies and, when DJANGO_SECURE_SSL_REDIRECT is set, redirects.
"""

import os

from .base import *  # noqa: F403

DEBUG = False

if os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "false").lower() in {"1", "true", "yes"}:
    SECURE_SSL_REDIRECT = True

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
