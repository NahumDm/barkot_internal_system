"""Barkot Accounts application configuration for the accounts domain."""

from django.apps import AppConfig
from django.apps import apps as global_apps
from django.db.models.signals import post_migrate


def _last_app_with_models_label() -> str:
    """Return the label of the last installed app that defines models.

    ``post_migrate`` is emitted once per app config, and Django's
    ``create_permissions`` receiver only creates permissions for the models of
    the app that was just migrated. Seeding on the first such signal would
    therefore find almost no ``auth.Permission`` rows and grant every role
    almost nothing.

    Waiting for the final app with models means every ``Meta.permissions``
    entry in the project exists by the time the role matrix is applied.

    Returns:
        The last app label, or an empty string if no installed app defines models.
    """
    labels = [
        config.label for config in global_apps.get_app_configs() if config.models_module is not None
    ]
    return labels[-1] if labels else ""


def seed_roles_after_migrate(sender, **kwargs):
    """Apply the role matrix once every app's permissions exist.

    Args:
        sender: The ``AppConfig`` that just finished migrating.
        **kwargs: Other signal arguments, unused.
    """
    if getattr(sender, "label", None) != _last_app_with_models_label():
        return

    from apps.accounts.role_seeding import seed_roles

    seed_roles()


class AccountsConfig(AppConfig):
    """AppConfig for the accounts domain (spec §6.2)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"

    def ready(self) -> None:
        """Connect the role-seeding receiver.

        Connecting from ``ready()`` rather than at import time guarantees the app
        registry is populated, and ``dispatch_uid`` makes the registration
        idempotent if ``ready()`` is ever called more than once.
        """
        post_migrate.connect(
            seed_roles_after_migrate,
            dispatch_uid="apps.accounts.seed_roles_after_migrate",
        )
