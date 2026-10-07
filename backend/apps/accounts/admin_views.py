"""Owner account-administration endpoints (roadmap C5).

Three Owner-only resources, mounted at the API root (``/users/``, ``/roles/``,
``/settings/``) because the admin catalogue has no domain prefix of its own:

* ``users`` / ``users/{id}`` — create and maintain staff accounts. Create only
  with an explicit role and an optional initial password; update can change the
  role, contact fields and the active flag. Deletion is deliberately absent:
  removing a staff record would break the audit trail's referent, so the Owner
  deactivates instead.
* ``roles`` / ``roles/{id}`` — read-only catalogue of the fixed business roles.
  Roles are spec fixpoints (§9.2) and are never edited at runtime.
* ``settings`` — the singleton system settings row, read and patched.

Every endpoint is Owner-only via ``CanManageUsers``/``CanManageRoles``/
``CanManageSettings``. The Manager role carries none of those grants, so C5's
acceptance criterion ("a Manager is refused") holds by construction and is
pinned by :mod:`apps.accounts.tests.test_admin_api`.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role, SiteSetting, User
from apps.accounts.permissions import CanManageRoles, CanManageSettings, CanManageUsers
from apps.accounts.schemas import (
    RoleSerializer,
    SiteSettingsSerializer,
    StaffUserCreateSerializer,
    StaffUserSerializer,
    StaffUserUpdateSerializer,
)
from apps.accounts.services import create_user, update_site_settings, update_user
from apps.core.pagination import BarkotPagination


@extend_schema_view(
    list=extend_schema(
        summary="List staff users",
        description=(
            "Paginated staff accounts, each with its role. Filter by ``role``, "
            "``active`` or a free-text ``search``."
        ),
        parameters=[
            OpenApiParameter(
                name="role",
                description="Role code to keep, e.g. ``MANAGER``.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="active",
                description="``true`` keeps active accounts, ``false`` inactive ones.",
                required=False,
                type=bool,
            ),
            OpenApiParameter(
                name="search",
                description="Case-insensitive match on username, name or email.",
                required=False,
                type=str,
            ),
        ],
        tags=["admin"],
    ),
    retrieve=extend_schema(summary="Get a staff user", tags=["admin"]),
    create=extend_schema(summary="Create a staff user", tags=["admin"]),
    update=extend_schema(summary="Replace a staff user", tags=["admin"]),
    partial_update=extend_schema(summary="Update a staff user", tags=["admin"]),
)
class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Staff accounts: list, retrieve, create and update — never delete."""

    queryset = User.objects.select_related("role").order_by("username")
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_queryset(self) -> QuerySet[User]:
        """Apply the list filters (``role``, ``active``, ``search``) when present.

        Returns:
            The filtered, ordered queryset.
        """
        qs = super().get_queryset()
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role__code=role)
        active = self.request.query_params.get("active")
        if active is not None:
            qs = qs.filter(is_active=active.lower() == "true")
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(username__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
            )
        return qs

    def get_serializer_class(self) -> type[serializers.Serializer]:
        """Choose the body type by action: create/update take their own shapes."""
        if self.action == "create":
            return StaffUserCreateSerializer
        if self.action in {"update", "partial_update"}:
            return StaffUserUpdateSerializer
        return StaffUserSerializer

    def get_permissions(self) -> list[BasePermission]:
        """Every user-admin action is Owner-only (C5)."""
        return [IsAuthenticated(), CanManageUsers()]

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create a staff account via the service, then return it at 201."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = create_user(
            actor=request.user,  # type: ignore[arg-type]
            username=serializer.validated_data["username"],
            role=serializer.validated_data["role"],
            email=serializer.validated_data.get("email", ""),
            phone_number=serializer.validated_data.get("phone_number", ""),
            password=serializer.validated_data.get("password"),
        )
        return Response(StaffUserSerializer(user).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Apply a full replacement (unused in practice; partial update is the UI path)."""
        return self._apply_update(request, *args, **kwargs)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Apply the supplied fields via the update service."""
        return self._apply_update(request, *args, **kwargs)

    def _apply_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Shared update handler: validate, delegate to the service, return fresh body.

        Args:
            request: The incoming request.
            *args: Viewset positional arguments (unused).
            **kwargs: Viewset keyword arguments, including the object pk.

        Returns:
            The updated user as :class:`StaffUserSerializer`.
        """
        user = self.get_object()
        serializer = self.get_serializer(
            user,
            data=request.data,
            partial=self.action == "partial_update",
        )
        serializer.is_valid(raise_exception=True)
        updated = update_user(actor=request.user, user=user, **serializer.validated_data)  # type: ignore[arg-type]
        return Response(StaffUserSerializer(updated).data)


@extend_schema_view(
    list=extend_schema(summary="List business roles", tags=["admin"]),
    retrieve=extend_schema(summary="Get a business role", tags=["admin"]),
)
class RoleViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """The fixed business-roles catalogue, read-only (spec §9.2, C5)."""

    queryset = Role.objects.prefetch_related("permissions_granted").order_by("code")
    serializer_class = RoleSerializer
    pagination_class = BarkotPagination
    paginator = BarkotPagination()

    def get_permissions(self) -> list[BasePermission]:
        """Every role-admin action is Owner-only (C5)."""
        return [IsAuthenticated(), CanManageRoles()]


@extend_schema(tags=["admin"])
class SiteSettingsView(APIView):
    """The singleton system settings row (spec §9.2, §20.2, C5).

    A plain APIView rather than a viewset: there is exactly one row, so there
    is nothing to paginate or collect.
    """

    permission_classes = [IsAuthenticated, CanManageSettings]

    @extend_schema(
        summary="Read system settings",
        responses=SiteSettingsSerializer,
    )
    def get(self, request: Request) -> Response:
        """Return the current settings row, creating it on first access."""
        return Response(SiteSettingsSerializer(SiteSetting.load()).data)

    @extend_schema(
        summary="Update system settings",
        request=SiteSettingsSerializer,
        responses=SiteSettingsSerializer,
    )
    def patch(self, request: Request) -> Response:
        """Apply the supplied settings fields and return the refreshed row."""
        instance = SiteSetting.load()
        serializer = SiteSettingsSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = update_site_settings(
            actor=request.user,  # type: ignore[arg-type]
            values=serializer.validated_data,
        )
        return Response(SiteSettingsSerializer(updated).data)
