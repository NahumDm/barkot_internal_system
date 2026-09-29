"""Authentication backend that grants permissions from :class:`apps.accounts.models.Role`.

Spec §9.2 gives every user exactly one role, and principle P06 requires
server-authoritative permission checks. Django's stock ``ModelBackend`` reads
``user.user_permissions`` and ``user.groups`` only, so the permissions seeded
onto ``Role.permissions_granted`` would never reach ``user.has_perm()`` and
every authenticated request would be denied.

Rather than copying those grants onto every user (which would drift the moment a
role's permissions change), this backend *adds* the role's grants to whatever
``ModelBackend`` already decided. The effective permission set is therefore:

    role grants  UNION  direct user grants  UNION  group grants

``Role`` grants are intentionally additive rather than overriding: a direct
grant can widen a user's access, but stripping a role grant would be a silent
privilege escalation surface.

Inactive users get nothing. ``is_active`` is checked here rather than relying on
``ModelBackend`` because this backend is consulted for *permissions*, and
Django's own ``ModelBackend`` also grants permissions to inactive users.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Value
from django.db.models.functions import Concat

from apps.accounts.models import User


class RolePermissionBackend(ModelBackend):
    """``ModelBackend`` plus the grants attached to the user's role."""

    def get_role_permissions(self, user_obj: User | AnonymousUser) -> set[str]:
        """Return ``"app_label.codename"`` strings granted by the user's role.

        Returns an empty set for anonymous or inactive users, and for a user with
        no role. Failures resolving the role are treated as "no permissions"
        rather than propagating: an authorization lookup must never be the thing
        that takes the request down with a 500.
        """
        if not getattr(user_obj, "is_active", False):
            return set()

        if isinstance(user_obj, AnonymousUser):
            return set()

        try:
            role = user_obj.role
        except ObjectDoesNotExist:
            # A user row whose role row has gone missing is a data-integrity
            # failure, but an authorization lookup must not be what raises it.
            return set()

        if role is None:
            return set()

        return set(
            role.permissions_granted.annotate(
                app_label_codename=Concat("content_type__app_label", Value("."), "codename")
            ).values_list("app_label_codename", flat=True)
        )

    def get_all_permissions(self, user_obj: User | AnonymousUser, obj: Any = None) -> set[str]:
        """Union the role grants with Django's own user and group grants."""
        if obj is not None:
            # Barkot does not use object-level permissions; the role grants are
            # all model-level. Object checks fall through to the base behaviour
            # so a future object-level need is not silently satisfied.
            return super().get_all_permissions(user_obj, obj=obj)

        return {
            *super().get_all_permissions(user_obj, obj=obj),
            *self.get_role_permissions(user_obj),
        }
