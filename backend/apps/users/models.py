"""Staff business profiles (spec §6.2, §14.2, ADR-0003 deviation D5).

Spec §6.2 assigns user profile and business role data to ``users``; §14.2
describes a single ``Employee`` object carrying ``name, position, start_date,
monthly_wage, status``. Those two cannot both hold without duplicating fields,
so the person lives here and the monthly-payroll subject lives in
``apps.payroll.models.Employee`` as a one-to-one companion.

This module therefore holds only who the person *is*. Compensation, payroll runs
and payment status are deliberately absent — they belong to ``payroll`` and
creating them from here would make payroll a sub-feature of staff records.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.business_time import now_utc
from apps.core.models import TimeStampedModel


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
    is_archived = models.BooleanField(
        _("is archived"),
        default=False,
        help_text=_(
            "Set when the staff member leaves. Archiving preserves payroll and audit "
            "history; records are never deleted."
        ),
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
