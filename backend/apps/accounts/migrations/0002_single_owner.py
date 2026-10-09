"""Enforce at most one Owner account (roadmap A7).

The application-level guard lives in the ``create_owner`` command and in
``apps.accounts.services``. Those are necessary but not sufficient: a service
guard can be bypassed by a management shell, a data migration or a fixture, and
the command's check-then-insert is only race-free because it holds a row lock.
This migration adds the invariant to PostgreSQL itself, so it cannot be violated
by any code path.

A partial unique index would be the natural tool, but PostgreSQL does not allow a
subquery in an index predicate, and "the role whose code is ``OWNER``" is a row
lookup rather than a constant. A constraint trigger expresses the same rule: on
insert, or on an update that could change a user's role, it re-counts the Owners
and aborts if there is more than one. The count is taken under a transaction-
scoped advisory lock so two concurrent owner inserts serialise; the second waits
for the first to commit and then sees the committed row.

The trigger is deliberately generic: it resolves the Owner role by ``code`` at
run time, so it survives role reseeding (which resets the role primary keys) and
needs no literal id that could go stale.
"""

from __future__ import annotations

from django.db import migrations

#: Create the trigger function. The advisory lock is taken only when the row's
#: role is the Owner, so ordinary staff writes pay no locking cost. The count
#: includes the row being written (an AFTER trigger sees its own row), so the
#: first Owner is a count of 1 and a second is a count of 2.
CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION barkot_assert_single_owner()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.role_id = (SELECT id FROM accounts_role WHERE code = 'OWNER') THEN
        PERFORM pg_advisory_xact_lock(8246557301);
    END IF;

    IF (
        SELECT COUNT(*)
        FROM accounts_user u
        JOIN accounts_role r ON r.id = u.role_id
        WHERE r.code = 'OWNER'
    ) > 1 THEN
        RAISE EXCEPTION 'Only one Owner account is permitted.'
            USING ERRCODE = 'unique_violation',
                  CONSTRAINT = 'barkot_single_owner';
    END IF;

    RETURN NULL;
END;
$$;
"""

#: A plain AFTER trigger: the invariant is checked at the moment of the write,
#: which is when the offending insert can still be reported against the row that
#: caused it.
CREATE_TRIGGER = """
CREATE TRIGGER barkot_single_owner
AFTER INSERT OR UPDATE ON accounts_user
FOR EACH ROW
EXECUTE FUNCTION barkot_assert_single_owner();
"""

DROP_TRIGGER = "DROP TRIGGER IF EXISTS barkot_single_owner ON accounts_user;"
DROP_FUNCTION = "DROP FUNCTION IF EXISTS barkot_assert_single_owner();"

#: PostgreSQL, not Django, enforces the trigger, so an already-invalid database
#: must be surfaced before the migration claims success.
PROBE = """
DO $$
BEGIN
    IF (SELECT COUNT(*) FROM accounts_user WHERE role_id = (
            SELECT id FROM accounts_role WHERE code = 'OWNER'
        )) > 1 THEN
        RAISE EXCEPTION
            'This database already has more than one Owner; resolve that before applying 0002.';
    END IF;
END;
$$;
"""


class Migration(migrations.Migration):
    """Install the single-Owner trigger."""

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(PROBE, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(CREATE_FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.RunSQL(DROP_TRIGGER, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(CREATE_TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
