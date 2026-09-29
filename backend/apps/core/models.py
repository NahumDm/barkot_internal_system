"""Abstract base models shared by every Barkot domain table (spec §11.1, §11.3).

Spec §11.3 requires audit columns on every table, and §20.2 requires financial and
stock records to be non-deletable. These bases encode both rules once so no
domain model can forget them:

- :class:`TimeStampedModel` adds ``created_at`` / ``updated_at``.
- :class:`ActorStampedModel` adds the creating and updating user, with
  ``SET_NULL`` on delete so removing a staff account never destroys history.
- :class:`VoidableModel` adds the void state, so a wrong financial record is
  reversed by voiding it and never by deleting it.

A model that is financial or inventory-affecting should inherit
:class:`VoidableModel`; a model that is pure configuration (a product, a
category) should inherit :class:`TimeStampedModel` only, because those are
corrected by editing.
"""

from __future__ import annotations

from typing import Any

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.business_time import now_utc
from apps.core.exceptions import ImmutableRecord


class TimeStampedModel(models.Model):
    """Abstract base with creation and modification timestamps (spec §11.3)."""

    created_at = models.DateTimeField(
        _("created at"),
        default=now_utc,
        editable=False,
        help_text=_("UTC. Reports must convert to BUSINESS_TIMEZONE before grouping by day."),
    )
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True


class ActorStampedModel(TimeStampedModel):
    """Abstract base recording who created and last changed a row.

    The FK is ``SET_NULL`` and nullable: when a staff account is deleted, the
    business records it touched must survive with an unknown actor. Cascading a
    delete into a sale history would be a data-loss bug.
    """

    created_by = models.ForeignKey(
        "accounts.User",
        verbose_name=_("created by"),
        related_name="%(app_label)s_%(class)s_created",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    updated_by = models.ForeignKey(
        "accounts.User",
        verbose_name=_("updated by"),
        related_name="%(app_label)s_%(class)s_updated",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        abstract = True


class VoidableQuerySet(models.QuerySet[Any]):
    """Queryset mixin for models that can be voided rather than deleted.

    Voids are stored, not removed (spec §20.2), so a manager that hides them by
    default saves every report and list view from having to remember to exclude
    them — and getting that wrong is how a voided expense ends up in a profit
    total.
    """

    def active(self) -> VoidableQuerySet:
        """Rows that have not been voided."""
        return self.filter(voided_at__isnull=True)

    def voided(self) -> VoidableQuerySet:
        """Rows that have been voided."""
        return self.filter(voided_at__isnull=False)


class VoidableManager(models.Manager.from_queryset(VoidableQuerySet)):  # type: ignore[misc]
    """Manager whose default queryset excludes voided rows.

    Declared on each concrete model rather than on the abstract
    :class:`VoidableModel`. Two reasons:

    - a manager attached to an abstract base is copied onto every subclass, but
      the type checker then pins the manager's model parameter to the *base*
      class, so ``Expense.objects.filter(category=...)`` would be checked
      against ``VoidableModel``'s fields and reject every real lookup;
    - a manager that silently hides rows should be visible at the point of use,
      not inherited invisibly.

    Voided rows are reachable through :class:`AllRowsManager` (``all_rows``),
    which is what reference-number allocation, audit screens and history views
    use.
    """

    def get_queryset(self) -> VoidableQuerySet:
        """Exclude voided rows from every lookup.

        Code that genuinely needs voided rows must go through the model's
        ``all_rows`` manager, e.g. ``Expense.all_rows.voided()``.
        """
        return super().get_queryset().filter(voided_at__isnull=True)

    def voided(self) -> VoidableQuerySet:
        """Always raise: voided rows are not reachable through ``objects``.

        ``Manager.from_queryset`` copies :meth:`VoidableQuerySet.voided` onto
        this manager, where it would silently return an empty list forever,
        because :meth:`get_queryset` has already removed every voided row. A
        voided-items report that quietly returns nothing is worse than a crash,
        so this points at the manager that can actually answer the question.

        Raises:
            AttributeError: Always. Use ``Model.all_rows.voided()``.
        """
        raise AttributeError(
            "Voided rows are hidden by this manager, so .voided() on "
            "'objects' can never match. Use the 'all_rows' manager instead, "
            "e.g. Model.all_rows.voided()."
        )


class AllRowsManager(models.Manager.from_queryset(VoidableQuerySet)):  # type: ignore[misc]
    """Manager that includes voided rows, for audit and reporting screens.

    Paired with :class:`VoidableManager` on each voidable model:
    ``Model.objects`` is what staff see, ``Model.all_rows`` is what an auditor
    or a voided-items report needs.
    """


class VoidableModel(ActorStampedModel):
    """Abstract base for records that must be reversed, never deleted (spec §20.2).

    Voiding requires a reason. A silent void is indistinguishable from a
    deleted row when reading the audit log, which defeats the point of keeping
    the row at all.
    """

    voided_at = models.DateTimeField(_("voided at"), null=True, blank=True, editable=False)
    voided_by = models.ForeignKey(
        "accounts.User",
        verbose_name=_("voided by"),
        related_name="%(app_label)s_%(class)s_voided",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    void_reason = models.TextField(_("void reason"), blank=True)

    class Meta:
        abstract = True

    @property
    def is_voided(self) -> bool:
        """Whether this record has been reversed."""
        return self.voided_at is not None

    def void(self, *, reason: str, actor: Any | None = None) -> None:
        """Mark the record as voided.

        Args:
            reason: Why the record is being reversed. Required.
            actor: The user performing the void, if known.

        Raises:
            ValueError: If ``reason`` is blank, or the record is already voided.
                Voiding twice is a bug, not a no-op — it would hide a real
                second reversal attempt.
        """
        if self.is_voided:
            raise ValueError(f"{type(self).__name__} {self.pk} is already voided.")
        if not reason or not reason.strip():
            raise ValueError("A void reason is required.")

        self.voided_at = now_utc()
        self.void_reason = reason.strip()
        if actor is not None:
            self.voided_by = actor


class AppendOnlyModel(TimeStampedModel):
    """Abstract base for rows that may be inserted but never altered or removed.

    The stock ledger (spec §12) is the reason this exists. Current stock is
    defined as the sum of movements, so editing or deleting a single movement
    silently rewrites history and leaves no trace — a discrepancy found months
    later becomes unresolvable because the evidence was altered in place.

    Django's ORM will happily do both, so this base raises instead. Note the
    guard is on the *model*, not the database: a sufficiently direct SQL client
    can still write to the table, and the audit log is the backstop for that.
    """

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Allow inserts only; refuse to update an already-persisted row.

        Raises:
            ImmutableRecord: If the row already exists in the database.
        """
        if self.pk is not None and not self._state.adding:
            raise ImmutableRecord(
                f"{type(self).__name__} is append-only and cannot be modified. "
                "Record a correcting movement instead."
            )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        """Always raise.

        Returns ``Any`` only to match Django's ``Model.delete`` signature; no
        value is ever returned because this always raises.

        Raises:
            ImmutableRecord: Always.
        """
        raise ImmutableRecord(
            f"{type(self).__name__} is append-only and cannot be deleted. "
            "Record a correcting movement instead."
        )
