"""Employee register write services (spec §5, P06).

Every state change to a register record goes through a function here, for the
reason payroll and finance already do: the business rule and its audit row are
written in the same transaction, so a record cannot change without the trail
that explains who changed it.

Three rules the API layer does not get to decide, because they are the ones a
future endpoint would be most likely to break:

- **Archiving is the only removal.** Nothing here deletes an
  :class:`~apps.users.models.EmployeeProfile`. Payroll runs and audit entries
  reference the person, and dropping the row would make historical pay
  unreconstructable.
- **A document replaces the document.** Storing a new PDF orphans the old one
  on disk, so the previous file is removed in the same transaction as the
  column update. One record, one file, no quietly accumulating copies.
- **No writes happen outside a transaction.** The model row and its audit entry
  commit together or not at all.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from django.db import transaction

from apps.audit.models import AuditLog
from apps.core.enums import ContractType
from apps.users.models import EmployeeProfile

if TYPE_CHECKING:  # pragma: no cover
    from django.core.files.base import File

    from apps.accounts.models import User

#: ``object_type`` every employee-register audit row carries. One string rather
#: than a literal per call site, so a typo in the most-used of them cannot make
#: a whole class of entry invisible to a query by object type.
OBJECT_TYPE = "users.EmployeeProfile"


@transaction.atomic
def create_employee(
    *,
    full_name: str,
    position: str,
    start_date: date,
    phone_number: str = "",
    contract_type: str = ContractType.FULL_TIME,
    contract_end_date: date | None = None,
    notes: str = "",
    address: str = "",
    emergency_contact: str = "",
    actor: User | None = None,
) -> EmployeeProfile:
    """Register a staff member (spec §5).

    Deliberately creates a profile and nothing else: a register entry is not a
    login, and minting an account here would make \"who can sign in\" a side
    effect of adding a name to a list.

    Args:
        full_name: The person's name.
        position: Job title.
        start_date: First day of employment.
        phone_number: Contact number, optional.
        contract_type: A :class:`apps.core.enums.ContractType` value.
        contract_end_date: Last day of a fixed-term contract, if any.
        notes: Free text.
        address: Address of the employee.
        emergency_contact: Name and phone of emergency contact (required).
        actor: The staff member registering them.

    Returns:
        The created :class:`EmployeeProfile`.
    """
    profile = EmployeeProfile.objects.create(
        full_name=full_name,
        position=position,
        start_date=start_date,
        phone_number=phone_number,
        contract_type=contract_type,
        contract_end_date=contract_end_date,
        notes=notes,
        address=address,
        emergency_contact=emergency_contact,
    )
    AuditLog.record(
        action=AuditLog.Action.CREATE,
        object_type=OBJECT_TYPE,
        object_id=profile.pk,
        actor=actor,
        summary=f"Registered employee {profile.full_name} ({profile.position})",
    )
    return profile


@transaction.atomic
def update_employee(
    *,
    profile: EmployeeProfile,
    changes: dict[str, Any],
    actor: User | None = None,
) -> EmployeeProfile:
    """Apply a set of field changes to a register record in place.

    The caller's ``validated_data`` *is* the change set: the update serializer
    declares exactly the fields a person record may be edited with, so passing
    the whole of it means there is no second list of editable fields to keep in
    step, and a field nobody may edit cannot arrive here by accident.

    Args:
        profile: The record to change.
        changes: Field name to new value. Empty means nothing was submitted, and
            is a no-op rather than an empty audit entry.
        actor: The staff member making the change.

    Returns:
        The updated :class:`EmployeeProfile`.

    Raises:
        KeyError: If ``changes`` names a field the model does not have, which
            can only come from a serializer declaring one — a programming error
            that should not be silently absorbed.
    """
    if not changes:
        return profile

    for field, value in changes.items():
        setattr(profile, field, value)
    profile.save(update_fields=[*changes, "updated_at"])

    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type=OBJECT_TYPE,
        object_id=profile.pk,
        actor=actor,
        summary=f"Updated employee {profile.full_name}",
    )
    return profile


@transaction.atomic
def archive_employee(*, profile: EmployeeProfile, actor: User | None = None) -> EmployeeProfile:
    """Archive a staff member who has left (spec §5).

    Idempotent: archiving an already-archived record is a no-op rather than an
    error, so a double-clicked button and a retried request both leave the
    register — and the audit trail — in the same state as one clean call.

    Args:
        profile: The record to archive.
        actor: The staff member archiving them.

    Returns:
        The archived :class:`EmployeeProfile`.
    """
    if profile.is_archived:
        return profile

    profile.archive()
    profile.save(update_fields=["is_archived", "archived_at", "updated_at"])
    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type=OBJECT_TYPE,
        object_id=profile.pk,
        actor=actor,
        summary=f"Archived employee {profile.full_name}",
    )
    return profile


@transaction.atomic
def restore_employee(*, profile: EmployeeProfile, actor: User | None = None) -> EmployeeProfile:
    """Bring an archived staff member back onto the register.

    The mirror of :func:`archive_employee`, including its idempotence: restoring
    someone who was never archived changes nothing and writes no row, so the
    action stays honest about whether the register actually moved.

    Args:
        profile: The record to restore.
        actor: The staff member restoring them.

    Returns:
        The restored :class:`EmployeeProfile`.
    """
    if not profile.is_archived and profile.archived_at is None:
        return profile

    profile.restore()
    profile.save(update_fields=["is_archived", "archived_at", "updated_at"])
    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type=OBJECT_TYPE,
        object_id=profile.pk,
        actor=actor,
        summary=f"Restored employee {profile.full_name}",
    )
    return profile


@transaction.atomic
def store_document(
    *, profile: EmployeeProfile, document: File, actor: User | None = None
) -> EmployeeProfile:
    """Put a contract PDF on file against a register record.

    Validation happened in
    :class:`apps.users.serializers.EmployeeDocumentSerializer` before this ran;
    this function's job is the part a serializer must not do — writing the row,
    removing the file it replaced, and recording who did it.

    Args:
        profile: The record the document belongs to.
        document: The already-validated upload.
        actor: The staff member uploading it.

    Returns:
        The updated :class:`EmployeeProfile`.
    """
    replaced = profile.document if profile.document else None

    profile.document = document
    profile.save(update_fields=["document", "updated_at"])

    # Delete only after the transaction commits. The column already points at
    # the new file, but if the audit write or commit fails the database rolls
    # back to the old path; deleting earlier would leave that path pointing at
    # a file that no longer exists.
    if replaced is not None:
        transaction.on_commit(lambda: replaced.delete(save=False))

    AuditLog.record(
        action=AuditLog.Action.UPDATE,
        object_type=OBJECT_TYPE,
        object_id=profile.pk,
        actor=actor,
        summary=f"Uploaded a contract document for {profile.full_name}",
    )
    return profile


__all__ = [
    "OBJECT_TYPE",
    "archive_employee",
    "create_employee",
    "restore_employee",
    "store_document",
    "update_employee",
]
