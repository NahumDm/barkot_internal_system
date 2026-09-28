"""Scaffolding sanity checks for the accounts domain (spec §6.2)."""

from django.apps import apps


def test_app_is_installed():
    assert apps.is_installed("apps.accounts")


def test_app_config_label():
    assert apps.get_app_config("accounts").name == "apps.accounts"
