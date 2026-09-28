"""Base Django settings shared by every environment.

Phase 0A scope: this backend has no auth accounts, no sessions, no admin and
no models yet. Those middleware/apps are added in Phase 1 (spec §9) rather
than enabled empty now, so every setting here is used and honest.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ── Security basics ────────────────────────────────────────────────────────
# SECURITY WARNING: keep SECRET_KEY secret in production (spec §20.2).
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-secret-change-me")

DEBUG = False

# Comma-separated in env, e.g. DJANGO_ALLOWED_HOSTS=api.barkotbar.com
_allowed_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [host.strip() for host in _allowed_hosts.split(",") if host.strip()]

# Same-origin web architecture (spec P09). Frontend origin allowed for CSRF.
_csrf_origins = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in _csrf_origins.split(",") if origin.strip()]

# ── Applications ───────────────────────────────────────────────────────────
# DRF, filter backends and OpenAPI tooling (spec §7.1, §8.1, §26.2) carry no
# models, so makemigrations checks stay stable while Phase 0A has no domain
# models. `integrations` is an empty adapter boundary for principle P08; it
# gains adapters in Phase 6.
INSTALLED_APPS = [
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
    "apps.reports",
    "apps.audit",
    "apps.integrations",
]

# Middleware without auth/session — session + auth middleware arrive with
# Phase 1 accounts so nothing references uninstalled contrib apps.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ── Database ───────────────────────────────────────────────────────────────
# PostgreSQL is the system of record (spec P02). Never SQLite in any branch.
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

# ── REST / OpenAPI ─────────────────────────────────────────────────────────
# Authentication classes are empty until Phase 1 (spec §9.1). The default
# permission is IsAuthenticated per spec §9.2 (backend permissions are
# authoritative); DRF enforces it once auth classes land.
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_PARSER_CLASSES": ("rest_framework.parsers.JSONParser",),
    "DEFAULT_AUTHENTICATION_CLASSES": (),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": ("django_filters.rest_framework.DjangoFilterBackend",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Barkot Bar & Restaurant API",
    "DESCRIPTION": "Internal business operations API for Barkot Bar & Restaurant (spec §8.1).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ── Static files ───────────────────────────────────────────────────────────
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ── Defaults ───────────────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
