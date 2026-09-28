"""Barkot Accounts application configuration for the accounts domain."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """AppConfig for the accounts domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
