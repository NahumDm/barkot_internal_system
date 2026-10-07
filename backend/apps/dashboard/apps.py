"""Barkot Dashboard application configuration for the C6 summary domain."""

from django.apps import AppConfig


class DashboardConfig(AppConfig):
    """AppConfig for the dashboard summary (spec §7.4)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dashboard"
