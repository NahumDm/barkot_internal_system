"""Append-only audit log (spec §11.1, §20.2).

Records who did what to which record, and when. This is the forensic backstop
behind the stock ledger: the ledger itself is protected at the model layer, but
a direct SQL client can still write to its table, and only an independently
written log can show that.

The table is :class:`apps.core.models.AppendOnlyModel`, so the ORM refuses to
update or delete a row. ``before``/``after`` are JSON snapshots written by the
service layer at the moment of the change; they are intentionally redundant with
the current row contents, because the point is to preserve what was true *then*.
"""

from __future__ import annotations

from typing import Any

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.business_time import now_utc
from apps.core.models import AppendOnlyModel


class AuditLog(AppendOnlyModel):
    """One recorded action (spec §20.2).

    ``object_type``/``object_id`` are a stringly-typed reference rather than a
    foreign key on purpose: an audit log that cannot record the deletion of the
    table it points at is not much of an audit log. Lookups go through
    :attr:`target` when the target still exists.
    """

    class Action(models.TextChoices):
        """What happened."""

        CREATE = "CREATE", _("Created")
        UPDATE = "UPDATE", _("Updated")
        DELETE = "DELETE", _("Deleted")
        VOID = "VOID", _("Voided")
        LOGIN = "LOGIN", _("Signed in")
        LOGOUT = "LOGOUT", _("Signed out")
        FAILED_LOGIN = "FAILED_LOGIN", _("Failed sign-in attempt")
        APPROVE = "APPROVE", _("Approved")

    actor = models.ForeignKey(
        "accounts.User",
        verbose_name=_("actor"),
        related_name="audit_entries",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text=_("Null when the acting user has since been deleted."),
    )
    action = models.CharField(_("action"), max_length=20, choices=Action.choices)
    object_type = models.CharField(
        _("object type"),
        max_length=100,
        help_text=_("Model label, e.g. 'sales.Sale'."),
    )
    object_id = models.CharField(_("object id"), max_length=64, blank=True)
    summary = models.CharField(_("summary"), max_length=255, blank=True)
    before = models.JSONField(_("before"), null=True, blank=True)
    after = models.JSONField(_("after"), null=True, blank=True)
    ip_address = models.GenericIPAddressField(_("IP address"), null=True, blank=True)
    occurred_at = models.DateTimeField(_("occurred at"), default=now_utc)

    class Meta:
        verbose_name = _("audit log entry")
        verbose_name_plural = _("audit log entries")
        ordering = ["-occurred_at", "-id"]
        default_permissions = ("add", "view")
        permissions = (("view_audit_log", "Can view the audit log"),)
        indexes = [
            models.Index(fields=["object_type", "object_id"], name="idx_audit_object"),
            models.Index(fields=["-occurred_at"], name="idx_audit_time"),
            models.Index(fields=["actor", "-occurred_at"], name="idx_audit_actor_time"),
        ]

    def __str__(self) -> str:
        return f"{self.get_action_display()} {self.object_type} {self.object_id}"

    @classmethod
    def record(
        cls,
        *,
        action: str,
        object_type: str,
        object_id: Any = None,
        actor: Any | None = None,
        summary: str = "",
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> AuditLog:
        """Append one entry to the log."""
        return cls.objects.create(
            action=action,
            object_type=object_type,
            object_id="" if object_id is None else str(object_id),
            actor=actor,
            summary=summary,
            before=before,
            after=after,
            ip_address=ip_address,
        )
