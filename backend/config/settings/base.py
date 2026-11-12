"""Base Django settings shared by every environment.

Phase 0B scope: session authentication (spec §9.1) over the custom staff user
and role model in :mod:`apps.accounts`. There is deliberately no
``django.contrib.admin``: the specification describes an internal system with a
separate Next.js frontend, and an unreviewed second UI is a liability rather
than a convenience.

Password hashing uses Django's PBKDF2 default. Argon2 is the stronger per-hash
choice but adds a native dependency the spec does not ask for;
``PASSWORD_HASHERS`` in :mod:`config.settings.prod` is where it would go.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ── Security basics ────────────────────────────────────────────────────────
# SECURITY WARNING: keep SECRET_KEY secret in production (spec §20.2).
#
# The fallback exists so `manage.py` runs in development and CI with no
# configuration. It is a published value, so anything that ships must refuse to
# boot while it is still in effect: `config.settings.prod` raises
# ImproperlyConfigured rather than trusting it. Named so the production guard
# compares against the same string instead of a second copy of it.
DEV_INSECURE_SECRET_KEY = "dev-only-insecure-secret-change-me"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", DEV_INSECURE_SECRET_KEY)

# DEBUG is not decided here. Each environment module pins it (dev.py True,
# prod.py False) so that no environment variable can turn debugging on in a
# production process. DJANGO_DEBUG was previously documented in
# .env.example, CI and both compose files but read by nothing; it has been
# removed rather than wired up, because a switch that silently does nothing is
# a trap. See ADR-0004 and the roadmap task A1.

# Comma-separated in env, e.g. DJANGO_ALLOWED_HOSTS=api.barkotbar.com
_allowed_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [host.strip() for host in _allowed_hosts.split(",") if host.strip()]

# Same-origin web architecture (spec P09). Frontend origin allowed for CSRF.
_csrf_origins = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in _csrf_origins.split(",") if origin.strip()]

# ── Applications ────────────────────────────────────────────────────────────
# auth/contenttypes/sessions back the session authentication in §9.1. Admin is
# intentionally absent: the spec has no admin surface.
#
# drf_spectacular and django_filters carry no models, so only the relative order
# of the domain apps below is relevant to makemigrations.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "apps.core",
    "apps.accounts",
    "apps.users",
    "apps.products",
    "apps.sales",
    "apps.inventory",
    "apps.finance",
    "apps.payroll",
    "apps.bono",
    "apps.reports",
    "apps.dashboard",
    "apps.audit",
    "apps.integrations",
]

# SessionMiddleware must precede AuthenticationMiddleware, and
# CsrfViewMiddleware must follow AuthenticationMiddleware so request.user exists
# when CSRF is validated (Django check admin.E408). DRF's SessionAuthentication
# repeats the CSRF check on unsafe methods; this ordering is the
# security-relevant part.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.RequestContextMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ── Database ───────────────────────────────────────────────────────────────
# PostgreSQL is the system of record (spec P02). Use SQLite in-memory for tests if requested.
DATABASES: dict[str, dict[str, str | int]]
if os.environ.get("USE_SQLITE") == "1" or os.environ.get("DJANGO_TEST_USE_SQLITE") == "1":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DJANGO_DB_NAME", "barkot"),
            "USER": os.environ.get("DJANGO_DB_USER", "barkot"),
            "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
            "HOST": os.environ.get("DJANGO_DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DJANGO_DB_PORT", "5432"),
            "CONN_MAX_AGE": int(os.environ.get("DJANGO_DB_CONN_MAX_AGE", "60")),
        }
    }

# ── Internationalisation / time ────────────────────────────────────────────
# Timestamps stored in UTC; business reports computed in BUSINESS_TIMEZONE
# (spec §11.4, P10). Currency is ETB-only for the MVP (spec §10.3).
LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

BUSINESS_TIMEZONE = os.environ.get("BUSINESS_TIMEZONE", "Africa/Addis_Ababa")
BUSINESS_CURRENCY = os.environ.get("BUSINESS_CURRENCY", "ETB")

# ── Authentication / sessions (spec §9.1) ──────────────────────────────────
# Session cookies with HttpOnly and SameSite=Lax, not a JWT. A token in
# localStorage is readable by any injected script; an HttpOnly session cookie is
# not, and the CSRF token below is what protects it from cross-site writes.
#
# CSRF_COOKIE_HTTPONLY stays False because the browser client must read the
# token to send it back. /api/v1/auth/csrf is the sanctioned way to obtain it
# and is the only reason this setting is not True.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_NAME = "barkot_sessionid"
SESSION_SAVE_EVERY_REQUEST = False
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_NAME = "csrftoken"
CSRF_USE_SESSIONS = False

AUTHENTICATION_BACKENDS = (
    # Adds the permissions seeded onto Role.permissions_granted to the ones
    # ModelBackend already sees, so `user.has_perm()` is the single
    # enforcement point (spec §9.2, P06). ModelBackend stays in the list and
    # is listed first so password authentication and direct user/group
    # grants keep working unchanged.
    "django.contrib.auth.backends.ModelBackend",
    "apps.accounts.backends.RolePermissionBackend",
)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/api/v1/auth/login"

# Barkot's own user model, carrying the mandatory business role. This must be set
# before the first migration: swapping the user model later on a populated
# database requires a custom migration, so it is not a decision to defer.
AUTH_USER_MODEL = "accounts.User"

# ── REST / OpenAPI ─────────────────────────────────────────────────────────
# SessionAuthentication enforces CSRF on unsafe methods, so P09 holds by
# construction rather than by convention. IsAuthenticated is the global default
# per §9.2: a new endpoint is private until explicitly opened.
# - Rate limiting (spec 9.3, A5) -
# DRF throttles count in django.core.cache. Gunicorn runs two workers, so the
# backend has to be shared between processes or each worker grants its own budget
# and the documented limit becomes twice as generous as it reads. DatabaseCache is
# that shared store; apps.core.migrations creates the table, so `migrate` is enough
# and no separate createcachetable step can be forgotten.
#
# Redis is the right answer once there is real asynchronous workload. It is not in
# this stack yet, so the database - already the system of record, already backed up
# - holds a handful of integers per client address instead.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        # Any unused table name. The default would be "cache_table", which reads as
        # generic enough to collide with something else in the database.
        "LOCATION": "barket_throttle_cache",
        # A throttle entry only has to outlive its own window, so a long default
        # would just keep dead counters around.
        "TIMEOUT": 300,
    }
}

# Whether a proxy in front of Django is trusted to set X-Forwarded-For.
#
# Default is False, and it has to be: the header is written by whoever sent the
# request, so believing it unconditionally lets any caller choose a fresh throttle
# bucket per attempt and brute force a password forever. apps.core.throttling reads
# REMOTE_ADDR unless this is on.
#
# Behind the Nginx in infrastructure/nginx - which sets X-Forwarded-For itself -
# set DJANGO_TRUSTED_PROXY=true. Leaving it off there is not merely conservative:
# every client then shares the proxy's budget, so one user's bad password locks out
# everyone. That is why this is an explicit switch rather than a guess.
TRUSTED_PROXY = os.environ.get("DJANGO_TRUSTED_PROXY", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_PARSER_CLASSES": ("rest_framework.parsers.JSONParser",),
    "DEFAULT_AUTHENTICATION_CLASSES": ("apps.core.authentication.BarkotSessionAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.BarkotPagination",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.exception_handler",
    # Two scopes (spec 9.3, A5 + D0). `login` (5/m) is the A5 gate - "6th attempt
    # from one IP returns 429" - and only LoginView asks for it. `write` (60/m) is
    # D0: every unsafe method on every endpoint, one budget per client address.
    # The rates use the same per-minute shape nginx.conf uses for its own zones;
    # apps.core.throttling explains why 60 matches the edge's api zone.
    #
    # DEFAULT_THROTTLE_CLASSES is what makes D0 hold for endpoints that do not
    # exist yet: a new view inherits the write limit the way it already inherits
    # IsAuthenticated, rather than depending on whoever writes it remembering.
    # A view that must be exempt has to override throttle_classes deliberately -
    # the only one today is LoginView, whose 5/m scope is stricter than this
    # default and replaces it rather than stacking with it.
    "DEFAULT_THROTTLE_RATES": {"login": "5/m", "write": "60/m"},
    "DEFAULT_THROTTLE_CLASSES": ("apps.core.throttling.WriteRateThrottle",),
    # The version is in the path, so DRF only has to agree which paths count as
    # versioned. NamespaceVersioning reads the `namespace` given by the URLconf,
    # which means /api/v2/ cannot quietly resolve against v1 views: it 404s until
    # someone adds a real v2. That is the behaviour we want from a version bump.
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.NamespaceVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ("v1",),
    "VERSION_PARAM": "version",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Barkot Bar & Restaurant API",
    "DESCRIPTION": (
        "Internal business operations API for Barkot Bar & Restaurant (spec §8.1). "
        "All business endpoints live under `/api/v1/`. Every error response uses "
        "the envelope documented on the `ErrorResponse` schema: a stable "
        "machine-readable `code`, a human `message`, and field-level `details` "
        "only for validation failures."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # The schema is the integration contract for an internal system: every app
    # schema is a source of truth the frontend generates types from, so it is
    # worth reading, not a debugging extra. It still requires a session - see
    # SERVE_PERMISSIONS - because it enumerates the whole internal surface.
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
    "SERVE_AUTHENTICATION": ["apps.core.authentication.BarkotSessionAuthentication"],
    # Paths keep the /api/v1/ prefix in the schema. Trimming it is cosmetically
    # nicer but only correct if the schema also advertises a server URL, and a
    # generated client that silently drops the version prefix is the exact
    # failure that versioning exists to prevent.
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": True,
    "SWAGGER_UI_SETTINGS": {"persistAuthorization": True, "displayOperationId": True},
    # Enum naming is deliberately not configured here. Two of the domain enums
    # (StockCountStatus and ReceiptStatus) currently carry identical member sets,
    # so naming them now would mean two names for one generated schema object -
    # drf-spectacular rejects that as ambiguous, and it is right to. Each enum is
    # named in the task that first exposes it on an endpoint, where the choice of
    # name has an actual consumer to answer to.
}

# ── Static files ───────────────────────────────────────────────────────────
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ── Uploaded documents ─────────────────────────────────────────────────────
# Employee contract documents (spec §5) are written here and are deliberately
# never served: config/urls.py mounts no /media/ route, no endpoint returns a
# file's bytes, and no serializer emits a URL for one, so there is no link to
# leak in the first place. Only the API's own screens can tell you a document is
# on file, which is the requirement rather than a shortcut.
#
# In Docker this is a named volume (see docker-compose.yml) so a rebuilt image
# does not lose the paperwork.
MEDIA_ROOT = BASE_DIR / "media"

# Hard ceiling on one uploaded document, read from the environment so a
# deployment with larger scans can raise it without a code change. Anything
# bigger is refused by the upload serializer before a byte is written to disk.
EMPLOYEE_DOCUMENT_MAX_BYTES = int(
    os.environ.get("EMPLOYEE_DOCUMENT_MAX_BYTES", str(5 * 1024 * 1024))
)

# ── Defaults ───────────────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
