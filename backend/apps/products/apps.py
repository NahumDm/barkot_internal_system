"""Barkot Products application configuration for the products domain."""

from django.apps import AppConfig


class ProductsConfig(AppConfig):
    """AppConfig for the products domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.products"
