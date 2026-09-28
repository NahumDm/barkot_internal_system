"""Scaffolding sanity checks for the sales domain (spec §6.2)."""

from django.apps import apps


def test_app_is_installed():
    assert apps.is_installed("apps.sales")


def test_app_config_label():
    assert apps.get_app_config("sales").name == "apps.sales"
