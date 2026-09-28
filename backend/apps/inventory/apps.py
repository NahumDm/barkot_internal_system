"""Barkot Inventory application configuration for the inventory domain."""

from django.apps import AppConfig


class InventoryConfig(AppConfig):
    """AppConfig for the inventory domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"
