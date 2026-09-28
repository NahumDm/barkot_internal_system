"""Barkot Finance application configuration for the finance domain."""

from django.apps import AppConfig


class FinanceConfig(AppConfig):
    """AppConfig for the finance domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.finance"
