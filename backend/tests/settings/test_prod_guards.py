"""Production settings guards (spec §20.2).

A production deploy that boots with the development secret key can have its
session cookies, CSRF tokens and password resets forged by anyone who has read
this repository. These tests pin the refusal to boot, because that refusal is
the only thing standing between a missing environment variable and a compromised
deployment.

The guard is in :mod:`config.settings.prod`, which is a settings module rather
than importable application code, so it is exercised in a subprocess with
``DJANGO_SETTINGS_MODULE`` pointed at it. Importing it in-process would poison
``django.conf.settings`` for the rest of the suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from django.core.management.utils import get_random_secret_key

BACKEND_DIR = Path(__file__).resolve().parents[2]

BOOT_PROBE = (
    "import django; django.setup(); from django.conf import settings; print(settings.SECRET_KEY)"
)


def _boot(settings_module: str, secret_key: str | None) -> subprocess.CompletedProcess[str]:
    """Import a settings module in a clean subprocess and report what happened.

    Args:
        settings_module: Dotted path to the settings module to import.
        secret_key: Value for ``DJANGO_SECRET_KEY``, or ``None`` to leave it unset.

    Returns:
        The completed process, whose stderr holds the guard's message on refusal.
    """
    env = dict(os.environ)
    env.pop("DJANGO_SECRET_KEY", None)
    env["DJANGO_SETTINGS_MODULE"] = settings_module
    env["PYTHONPATH"] = str(BACKEND_DIR)
    if secret_key is not None:
        env["DJANGO_SECRET_KEY"] = secret_key
    return subprocess.run(
        [sys.executable, "-c", BOOT_PROBE],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND_DIR),
        check=False,
    )


class TestProductionRefusesAnUnsafeSecretKey:
    """Each of these is a way a production deploy ends up signing with a known key."""

    def test_unset_secret_key_refuses_to_boot(self) -> None:
        result = _boot("config.settings.prod", None)
        assert result.returncode != 0
        assert "DJANGO_SECRET_KEY must be set" in result.stderr

    def test_blank_secret_key_refuses_to_boot(self) -> None:
        result = _boot("config.settings.prod", "   ")
        assert result.returncode != 0
        assert "DJANGO_SECRET_KEY must be set" in result.stderr

    def test_development_placeholder_refuses_to_boot(self) -> None:
        """The value in ``base.py`` is published, so it must never reach production."""
        from config.settings.base import DEV_INSECURE_SECRET_KEY

        result = _boot("config.settings.prod", DEV_INSECURE_SECRET_KEY)
        assert result.returncode != 0
        assert "development placeholder" in result.stderr

    @pytest.mark.parametrize("weak", ["short", "a" * 20, "x" * 49])
    def test_short_secret_key_refuses_to_boot(self, weak: str) -> None:
        result = _boot("config.settings.prod", weak)
        assert result.returncode != 0
        assert "at least 50" in result.stderr

    def test_a_generated_key_is_accepted(self) -> None:
        """The command in the error message must actually work.

        Django's ``get_random_secret_key`` yields lowercase alphanumeric
        characters only, so a guard that demanded mixed case or punctuation
        would reject the key it just told the operator to generate.
        """
        result = _boot("config.settings.prod", get_random_secret_key())
        assert result.returncode == 0, result.stderr


class TestDevelopmentIsUnaffected:
    """The guard must not make local development or CI require configuration."""

    def test_dev_settings_boot_without_a_secret_key(self) -> None:
        result = _boot("config.settings.dev", None)
        assert result.returncode == 0, result.stderr

    def test_base_settings_boot_without_a_secret_key(self) -> None:
        result = _boot("config.settings.base", None)
        assert result.returncode == 0, result.stderr

    def test_dev_fallback_is_still_the_published_placeholder(self) -> None:
        """Documents the deliberate coupling: base falls back, prod refuses it."""
        from config.settings.base import DEV_INSECURE_SECRET_KEY, SECRET_KEY

        assert SECRET_KEY == DEV_INSECURE_SECRET_KEY


class TestProductionHardeningIsStillApplied:
    """A valid key must not be the only production difference."""

    def test_debug_is_off_and_transport_is_pinned(self) -> None:
        probe = textwrap.dedent(
            """
            import django
            django.setup()
            from django.conf import settings
            print(
                f"{settings.DEBUG}|{settings.SESSION_COOKIE_SECURE}|"
                f"{settings.SESSION_COOKIE_HTTPONLY}|{settings.CSRF_COOKIE_SECURE}|"
                f"{settings.SECURE_HSTS_SECONDS}|{settings.X_FRAME_OPTIONS}"
            )
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": str(BACKEND_DIR),
                "DJANGO_SETTINGS_MODULE": "config.settings.prod",
                "DJANGO_SECRET_KEY": get_random_secret_key(),
            },
            cwd=str(BACKEND_DIR),
            check=False,
        )
        assert result.returncode == 0, result.stderr
        debug, session_secure, session_httponly, csrf_secure, hsts, frame = (
            result.stdout.strip().split("|")
        )
        assert debug == "False"
        assert session_secure == "True"
        assert session_httponly == "True"
        assert csrf_secure == "True"
        assert int(hsts) > 0
        assert frame == "DENY"
