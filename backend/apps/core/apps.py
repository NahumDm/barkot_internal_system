"""Barkot Core application configuration for the core domain."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """AppConfig for the core domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
