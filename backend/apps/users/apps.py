"""Barkot Users application configuration for the users domain."""

from django.apps import AppConfig


class UsersConfig(AppConfig):
    """AppConfig for the users domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.users"
