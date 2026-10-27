"""Staff business profiles and the employee register (spec §5, §6.2, §14.2, ADR-0003 D5).

Spec §6.2 assigns user profile and business role data to ``users``; §14.2
describes a single ``Employee`` object carrying ``name, position, start_date,
monthly_wage, status``. Those two cannot both hold without duplicating fields,
so the person lives here and the monthly-payroll subject lives in
``apps.payroll.models.Employee`` as a one-to-one companion.

This module therefore holds only who the person *is*, plus the employment
contract they signed. Compensation, payroll runs and payment status are
deliberately absent — they belong to ``payroll`` and creating them from here
would make payroll a sub-feature of staff records.

The register is independent of logins: a new hire is registered here on day
one whether or not an account exists yet, and archiving rather than deleting
is what keeps payroll history and the audit trail reconstructable.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.business_time import now_utc
from apps.core.enums import ContractType
from apps.core.models import TimeStampedModel

#: Subdirectory of ``MEDIA_ROOT`` holding employee documents. Named rather than
#: implied by an app label so an operator looking at the volume can tell what is
#: in it without opening the code.
DOCUMENT_DIRECTORY = "employee_documents"


def employee_document_path(instance: EmployeeProfile, filename: str) -> str:
    """Return the storage path for an uploaded employee document.

    The client's filename is deliberately ignored rather than sanitised. A
    basename is the only part of an upload a caller controls, and every scheme
    for cleaning one has had a bypass (``..``, reserved names, an NTFS alternate
    stream, a name that is fine on the author's OS and not on this one). Deriving
    the name from the row's own primary key and a random UUID removes the whole
    class of problem: nothing from the request reaches the path, so path
    traversal has nothing to traverse *with*, and two uploads of
    ``contract.pdf`` cannot overwrite each other.

    The extension is a literal ``.pdf`` because PDF is the only format the
    upload endpoint accepts — see ``apps.users.serializers`` — so a caller cannot
    smuggle a different suffix through this function either.

    Args:
        instance: The profile being saved. ``pk`` is set in the only flow that
            reaches here (a document is posted against an existing record);
            ``"new"`` is the belt-and-braces fallback for one that is not.
        filename: The client's original name. Unused, and present only because
            Django calls ``upload_to`` with that signature.

    Returns:
        A relative path under the media root.
    """
    del filename
    return f"{DOCUMENT_DIRECTORY}/{instance.pk or 'new'}/{uuid4().hex}.pdf"


class EmployeeProfileQuerySet(models.QuerySet["EmployeeProfile"]):
    """QuerySet for :class:`EmployeeProfile`."""

    def active(self) -> EmployeeProfileQuerySet:
        """Profiles that are not archived."""
        return self.filter(is_archived=False)


class EmployeeProfile(TimeStampedModel):
    """A staff member as a person, independent of their login.

    Kept separate from :class:`apps.accounts.models.User` because the two are
    not the same population. A profile can exist for a staff member who has no
    login (a new hire on their first day, a seasonal worker), and a login can
    exist with no profile (a system service identity).

    ``start_date`` is a date rather than a timestamp: employment begins on a day.
    """

    full_name = models.CharField(_("full name"), max_length=150)
    position = models.CharField(
        _("position"),
        max_length=100,
        help_text=_("Free-text job title, e.g. 'Barman' or 'Head Cashier'."),
    )
    phone_number = models.CharField(_("phone number"), max_length=32, blank=True)
    start_date = models.DateField(_("start date"))
    contract_type = models.CharField(
        _("contract type"),
        max_length=20,
        choices=ContractType.choices,
        default=ContractType.FULL_TIME,
        help_text=_("How the person is employed, independent of whether they are paid now."),
    )
    contract_end_date = models.DateField(
        _("contract end date"),
        null=True,
        blank=True,
        help_text=_("Last day of a fixed-term contract; empty for an open-ended one."),
    )
    document = models.FileField(
        _("contract document"),
        upload_to=employee_document_path,
        blank=True,
        max_length=255,
        help_text=_("PDF contract, stored outside the web root and never served over HTTP."),
    )
    is_archived = models.BooleanField(
        _("is archived"),
        default=False,
        help_text=_(
            "Set when the staff member leaves. Archiving preserves payroll and audit "
            "history; records are never deleted."
        ),
    )
    employee_id = models.IntegerField(
        _("employee ID"),
        unique=True,
        editable=False,
        default=0,
        help_text=_("Sequential integer assigned in order of registration."),
    )
    address = models.CharField(
        _("address"),
        max_length=200,
        blank=True,
        help_text=_("Home or work address of the employee."),
    )
    emergency_contact = models.CharField(
        _("emergency contact"),
        max_length=150,
        help_text=_("Name and phone number of emergency contact (required)."),
    )
    archived_at = models.DateTimeField(_("archived at"), null=True, blank=True, editable=False)
    notes = models.TextField(_("notes"), blank=True)

    #: Optional link to the login account, when the staff member has one.
    user = models.OneToOneField(
        "accounts.User",
        verbose_name=_("user account"),
        related_name="employee_profile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("Leave empty for a staff member who does not log in."),
    )

    objects = EmployeeProfileQuerySet.as_manager()

    class Meta:
        verbose_name = _("employee profile")
        verbose_name_plural = _("employee profiles")
        ordering = ["full_name"]
        permissions = (("manage_employees", "Can manage employee profiles"),)

    def save(self, *args, **kwargs):
        if self.employee_id == 0 or self.employee_id is None:
            max_id = EmployeeProfile.objects.aggregate(max_id=models.Max("employee_id"))["max_id"] or 0
            self.employee_id = max_id + 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.full_name

    @property
    def tenure_days(self) -> int:
        """Whole days employed as of today (business timezone)."""
        from apps.core.business_time import business_timezone

        return (now_utc().astimezone(business_timezone()).date() - self.start_date).days

    def archive(self) -> None:
        """Archive this profile.

        Archiving is not deletion: payroll runs and audit entries reference this
        person, and removing the row would make historical pay unreconstructable.
        """
        if self.is_archived:
            return
        self.is_archived = True
        self.archived_at = now_utc()

    def restore(self) -> None:
        """Undo :meth:`archive`, for someone who came back.

        Symmetric with archiving on purpose so the two cannot drift: clearing the
        flag but leaving ``archived_at`` set would report a person as archived
        by date while the filter said otherwise.
        """
        if not self.is_archived and self.archived_at is None:
            return
        self.is_archived = False
        self.archived_at = None

    @property
    def document_filename(self) -> str:
        """The stored document's name, or ``""`` when there is none.

        The basename of the server-generated path (see
        :func:`employee_document_path`), never a URL: documents are not served
        over HTTP, so a filename is what a UI can honestly show as
        "contract.pdf is on file".
        """
        name = self.document.name if self.document else ""
        return Path(name).name if name else ""

    @property
    def has_document(self) -> bool:
        """Whether a contract document is on file."""
        return bool(self.document)
