"""Barkot Bono token accountability application configuration."""

from django.apps import AppConfig


class BonoConfig(AppConfig):
    """AppConfig for Bono token accountability (owner configuration, allocation, reconciliation)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.bono"
