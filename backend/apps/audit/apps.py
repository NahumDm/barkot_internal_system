"""Barkot Audit application configuration for the audit domain."""

from django.apps import AppConfig


class AuditConfig(AppConfig):
    """AppConfig for the audit domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.audit"
