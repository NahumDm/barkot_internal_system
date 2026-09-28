"""Barkot Sales application configuration for the sales domain."""

from django.apps import AppConfig


class SalesConfig(AppConfig):
    """AppConfig for the sales domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sales"
