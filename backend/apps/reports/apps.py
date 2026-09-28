"""Barkot Reports application configuration for the reports domain."""

from django.apps import AppConfig


class ReportsConfig(AppConfig):
    """AppConfig for the reports domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reports"
