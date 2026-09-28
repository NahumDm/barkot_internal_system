"""Barkot Integrations application configuration for the integrations domain."""

from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    """AppConfig for the integrations domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.integrations"
