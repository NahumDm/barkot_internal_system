"""Scaffolding sanity checks for the dashboard domain (spec §7.4)."""

from django.apps import apps


def test_app_is_installed():
    assert apps.is_installed("apps.dashboard")


def test_app_config_label():
    assert apps.get_app_config("dashboard").name == "apps.dashboard"
