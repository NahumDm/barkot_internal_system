# audit

Immutable, append-oriented audit records.

Owns: AuditLog (actor, timestamp, entity, action, reason/context).
Depends on: `accounts`, `core`.
Corrections are recorded as adjustments, never as erasure of evidence (spec P06).
