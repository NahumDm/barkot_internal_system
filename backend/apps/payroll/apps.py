"""Barkot Payroll application configuration for the payroll domain."""

from django.apps import AppConfig


class PayrollConfig(AppConfig):
    """AppConfig for the payroll domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payroll"
