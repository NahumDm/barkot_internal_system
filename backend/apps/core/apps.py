"""Barkot Core application configuration for the core domain."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """AppConfig for the core domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self) -> None:
        """Import the modules the app registry needs but nothing imports for it.

        Two, and both are invisible to a reader who goes looking for them:

        - :mod:`apps.core.schema` registers the OpenAPI extension for the session
          authenticator. It is only found if this module is imported.
        - :mod:`apps.core.idempotency` defines :class:`IdempotencyRecord`, a concrete
          model rather than an abstract base. Django discovers models by importing
          ``<app>.models``, so a model declared in a sibling module is invisible until
          something imports it. Leaving it unregistered would mean ``migrate`` created
          no table and the mechanism failed at its first insert rather than at setup.

        Raises:
            ImportError: Propagated from either import, which would mean a module
                could not load and setup should fail loudly rather than silently
                omit a security scheme or a table.
        """
        from apps.core import idempotency, schema  # noqa: F401
