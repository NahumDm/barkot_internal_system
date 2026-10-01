"""Barkot Core application configuration for the core domain."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """AppConfig for the core domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self) -> None:
        """Register the OpenAPI extension for the session authenticator.

        The extension is only found if this module is imported, so this is where
        that import belongs.

        Raises:
            ImportError: Propagated from the imported module, which would mean
                the schema extension could not load and generation would fail
                loudly rather than silently omit the security scheme.
        """
        from apps.core import schema  # noqa: F401
