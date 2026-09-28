"""Scaffolding sanity checks for the payroll domain (spec §6.2)."""

from django.apps import apps


def test_app_is_installed():
    assert apps.is_installed("apps.payroll")


def test_app_config_label():
    assert apps.get_app_config("payroll").name == "apps.payroll"
