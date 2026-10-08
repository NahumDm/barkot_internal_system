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
import re
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


def _boot(
    settings_module: str,
    secret_key: str | None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Import a settings module in a clean subprocess and report what happened.

    Args:
        settings_module: Dotted path to the settings module to import.
        secret_key: Value for ``DJANGO_SECRET_KEY``, or ``None`` to leave it unset.
        extra_env: Additional environment variables, used to prove that a
            variable which looks like a switch has no effect.

    Returns:
        The completed process, whose stderr holds the guard's message on refusal.
    """
    env = dict(os.environ)
    env.pop("DJANGO_SECRET_KEY", None)
    env["DJANGO_SETTINGS_MODULE"] = settings_module
    env["PYTHONPATH"] = str(BACKEND_DIR)
    if secret_key is not None:
        env["DJANGO_SECRET_KEY"] = secret_key
    if extra_env:
        env.update(extra_env)
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


PROXY_HEADER_PROBE = (
    "import django; django.setup(); "
    "from django.conf import settings; print(settings.SECURE_PROXY_SSL_HEADER)"
)


class TestProxySslHeaderIsTrustedOnlyWhenProxyIsTrusted:
    """Nginx terminates TLS and forwards the original scheme.

    Django only learns that a proxied request was already https from
    ``X-Forwarded-Proto``, and only honours it when ``SECURE_PROXY_SSL_HEADER``
    is configured. Without it, a production stack with ``SECURE_SSL_REDIRECT``
    on (the compose default) answers every proxied request with an endless
    https redirect. The header must be wired only for the same ``TRUSTED_PROXY``
    switch that gates the throttle's client address, so a bare gunicorn that
    never set the header cannot be persuaded it was secure by one written by
    the caller.
    """

    def _proxy_header_of(self, axis: str) -> str:
        return subprocess.run(
            [sys.executable, "-c", PROXY_HEADER_PROBE],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": str(BACKEND_DIR),
                "DJANGO_SETTINGS_MODULE": "config.settings.prod",
                "DJANGO_SECRET_KEY": get_random_secret_key(),
                "DJANGO_TRUSTED_PROXY": axis,
            },
            cwd=str(BACKEND_DIR),
            check=False,
        ).stdout.strip()

    def test_trusted_proxy_trusts_the_forwarded_proto(self) -> None:
        assert self._proxy_header_of("true") == "('HTTP_X_FORWARDED_PROTO', 'https')"

    def test_untrusted_proxy_ignores_the_forwarded_proto(self) -> None:
        assert self._proxy_header_of("false") == "None"


DEBUG_PROBE = (
    "import django; django.setup(); from django.conf import settings; print(settings.DEBUG)"
)


def _debug_of(settings_module: str, extra_env: dict[str, str] | None = None) -> str:
    """Return the DEBUG value a settings module resolves to in a clean process."""
    result = subprocess.run(
        [sys.executable, "-c", DEBUG_PROBE],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(BACKEND_DIR),
            "DJANGO_SETTINGS_MODULE": settings_module,
            "DJANGO_SECRET_KEY": get_random_secret_key(),
            **(extra_env or {}),
        },
        cwd=str(BACKEND_DIR),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class TestDebugIsPinnedNotConfigurable:
    """``DJANGO_DEBUG`` used to be documented in four places and read by none.

    Wiring it up was rejected in favour of removing it: a switch an operator
    sets and sees nothing happen is worse than no switch, and a production
    process that can be flipped into debug mode serves tracebacks and settings
    to whoever asks.
    """

    def test_production_is_debug_off(self) -> None:
        assert _debug_of("config.settings.prod") == "False"

    def test_development_is_debug_on(self) -> None:
        assert _debug_of("config.settings.dev") == "True"

    @pytest.mark.parametrize("value", ["true", "True", "1", "yes"])
    def test_production_ignores_django_debug_true(self, value: str) -> None:
        """No environment value can turn debug mode on in production."""
        assert _debug_of("config.settings.prod", {"DJANGO_DEBUG": value}) == "False"

    def test_development_ignores_django_debug_false(self) -> None:
        """The same holds in reverse: development is not switchable off by env."""
        assert _debug_of("config.settings.dev", {"DJANGO_DEBUG": "false"}) == "True"

    def test_the_variable_is_absent_from_the_shipped_configuration(self) -> None:
        """The dead variable must not reappear in the files operators copy."""
        repo_root = BACKEND_DIR.parent
        offenders: list[str] = []
        candidates = [
            repo_root / ".env.example",
            repo_root / "docker-compose.yml",
            repo_root / "docker-compose.prod.yml",
            repo_root / ".github" / "workflows" / "ci.yml",
        ]
        for candidate in candidates:
            assert candidate.exists(), f"expected {candidate} to exist"
            text = candidate.read_text(encoding="utf-8")
            # Prose explaining why the variable is absent is welcome; a line
            # that actually sets it is the regression we are guarding against.
            assigns = re.search(r"^\s*DJANGO_DEBUG\s*[:=]", text, re.MULTILINE)
            if assigns:
                offenders.append(candidate.name)
        assert not offenders, f"DJANGO_DEBUG reappeared in: {offenders}"
