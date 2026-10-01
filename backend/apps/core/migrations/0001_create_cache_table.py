"""Create the table backing the database cache.

DRF's throttles count in ``django.core.cache`` (spec §9.3, A5), and this project
points ``CACHES["default"]`` at ``DatabaseCache`` because Gunicorn runs two worker
processes and a per-process cache would hand out two separate budgets. Django does
not create that table on ``migrate``; it is normally created by the
``createcachetable`` management command, which means a deployment can pass every
migration and still fail its first login on a missing table.

Creating it here removes that ordering hazard: ``migrate`` is the one step every
environment already runs, so the throttle has somewhere to count from the first
request. The command remains what an operator reaches for to rebuild the table, and
the forward direction defers to it rather than reimplementing the schema - that way
a future change to Django's cache table is picked up here for free.

Reverse drops the table. The rows are throttle counters, so rolling back costs at
worst one window of limits and never a business record.
"""

from django.conf import settings
from django.core.management import call_command
from django.db import migrations


def _cache_table_name() -> str:
    """Return the table the configured cache backend stores its rows in.

    ``DatabaseCache`` names its table after ``LOCATION`` verbatim, so reading the
    setting is enough and avoids reimplementing that rule.

    Returns:
        The table name.
    """
    return str(settings.CACHES["default"]["LOCATION"])


def create_cache_table(apps, schema_editor):
    """Create the cache table on the migration's connection.

    Delegating to ``createcachetable`` keeps the database router in the decision,
    so a future multi-database setup creates the table wherever ``allow_migrate``
    says rather than on whichever connection happens to be default.

    Args:
        apps: The historical app registry. Unused; the cache table is not a model.
        schema_editor: The schema editor for the connection being migrated.
    """
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


def drop_cache_table(apps, schema_editor):
    """Drop the cache table again.

    Issued as SQL rather than through the backend because the reverse of a
    creation has to work even if the cache configuration has since been changed or
    removed - the table name recorded in the migration's own settings read would no
    longer be the one that exists.

    Args:
        apps: The historical app registry. Unused.
        schema_editor: The schema editor for the connection being migrated.
    """
    table = _cache_table_name()
    schema_editor.execute(f'DROP TABLE IF EXISTS "{table}"')


class Migration(migrations.Migration):
    """Provision the store the login throttle counts in."""

    initial = True

    dependencies = []

    operations = [
        migrations.RunPython(create_cache_table, drop_cache_table),
    ]
