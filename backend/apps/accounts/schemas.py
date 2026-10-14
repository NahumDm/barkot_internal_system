"""Request and response bodies for the auth and admin endpoints (spec §9.1, §9.2).

Kept beside the views rather than in :mod:`apps.core.schemas`, which holds the
envelopes every domain shares. These types describe one endpoint's own contract,
and putting them in the shared module would suggest they are part of the common
envelope when they are not.

Two decisions worth naming.

**The login response repeats the user instead of referencing it.** A client that
has just signed in needs the role and permissions immediately to decide what to
render, and making it call ``/auth/me`` straight afterwards would be a second
round trip on the one request where the user is guaranteed to be waiting. The
shared ``UserSerializer`` below is what both return, so the two cannot drift.

**``password`` is write-only.** The login view is the only thing that reads it,
and no response type declares it, so the generated schema shows the field as
input-only. Nothing in this module can leak a password into a response.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.models import Role, SiteSetting, User


class UserSerializer(serializers.ModelSerializer):
    """Who is signed in, and what they may do.

    The permission list is the role matrix resolved to codenames, which is the
    same set ``RolePermissionBackend`` authorises against. It is included so the
    frontend can hide what a user cannot do instead of letting them click into a
    403 - but it is presentation only: the server never trusts it, and every
    endpoint re-checks permissions (spec §9.2).
    """

    permissions = serializers.SerializerMethodField()
    display_name = serializers.CharField(read_only=True)
    role = serializers.CharField(source="role.code", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "display_name",
            "role",
            "role_name",
            "permissions",
            "email",
            "phone_number",
            "is_temporary_password",
            "last_login",
        ]
        read_only_fields = fields

    def get_permissions(self, instance: User) -> list[str]:
        """Return the user's effective permission codenames, sorted.

        Args:
            instance: The user being serialised.

        Returns:
            Sorted codenames from the role matrix plus any direct or group grants.
        """
        return sorted(instance.get_all_permissions())


class StaffUserSerializer(serializers.ModelSerializer):
    """One staff account, as the Owner's admin screen sees it (roadmap C5).

    Read-only in this shape: creation and update take their own request
    bodies below, and this type is what every admin read returns.
    """

    display_name = serializers.CharField(read_only=True)
    role = serializers.CharField(source="role.code", read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "display_name",
            "role",
            "role_name",
            "email",
            "phone_number",
            "is_active",
            "is_staff",
            "is_temporary_password",
            "last_login",
        ]
        read_only_fields = fields


class StaffUserCreateSerializer(serializers.Serializer):
    """Body of ``POST /users/``.

    ``role`` is addressed by its stable ``code``, not by id: the code survives
    reseeding and is what the Owner sees in the UI. ``password`` is optional
    because a new hire can be onboarded locked and given a password later.
    """

    username = serializers.CharField(
        max_length=150,
        trim_whitespace=True,
        help_text="Login name. Unique and permanent.",
    )
    role = serializers.SlugRelatedField(
        queryset=Role.objects.all(),
        slug_field="code",
        help_text="Business role code (spec §9.2).",
    )
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
        help_text="Optional; Barkot signs staff in by username.",
    )
    phone_number = serializers.CharField(
        max_length=32,
        trim_whitespace=True,
        allow_blank=False,
        help_text="Contact number. Required for every new staff account.",
    )
    password = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=False,
        style={"input_type": "password"},
        write_only=True,
        help_text=(
            "Optional initial password. Omit it to create a locked account "
            "that cannot be used until the Owner sets a password."
        ),
    )

    def validate_username(self, value: str) -> str:
        """Refuse a login name that mirrors an existing account.

        Args:
            value: The submitted username.

        Returns:
            The username, when it is free.

        Raises:
            serializers.ValidationError: If the name is already taken.
        """
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("That login name is already in use.")
        return value

    def validate_phone_number(self, value: str) -> str:
        """Refuse a phone number that is only whitespace.

        ``trim_whitespace`` runs after DRF's blank check, so a value of spaces
        would otherwise slip through as an empty string.
        """
        value = value.strip()
        if not value:
            raise serializers.ValidationError("A phone number is required.")
        return value


class StaffUserUpdateSerializer(serializers.Serializer):
    """Body of ``PATCH /users/{id}/`` (roadmap C5).

    Partial by design: only the supplied fields change. The Owner may change
    any staff member's role, contact details and active flag, except their own
    role and active flag - the service refuses those so an Owner cannot lock
    the last administrator out.
    """

    role = serializers.SlugRelatedField(
        queryset=Role.objects.all(),
        slug_field="code",
        required=False,
        help_text="Replacement business role code.",
    )
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
        help_text="Replacement address, or empty to clear it.",
    )
    phone_number = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=32,
        help_text="Replacement number, or empty to clear it.",
    )
    is_active = serializers.BooleanField(
        required=False,
        help_text=(
            "False deactivates the account; true re-activates it. You cannot "
            "change your own active flag."
        ),
    )


class RoleSerializer(serializers.ModelSerializer):
    """One business role from the fixed catalogue (roadmap C5, spec §9.2).

    ``permissions`` lists the resolved ``app_label.codename`` grants so the
    Owner can see in one place what a role can do, without a client having to
    join the role matrix itself.
    """

    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ["code", "name", "description", "is_staff_role", "permissions"]
        read_only_fields = fields

    def get_permissions(self, instance: Role) -> list[str]:
        """Return the role's granted permission codenames, sorted.

        Args:
            instance: The role being serialised.

        Returns:
            Sorted ``app_label.codename`` strings.
        """
        return sorted(
            f"{p.content_type.app_label}.{p.codename}" for p in instance.permissions_granted.all()
        )


class SiteSettingsSerializer(serializers.ModelSerializer):
    """The singleton system settings row (roadmap C5, spec §20.2).

    ``updated_at``/``updated_by`` are read-only provenance: the Owner screen
    shows who last changed the settings, but cannot set them through this body.
    """

    updated_by = serializers.SerializerMethodField()
    session_timeout_minutes = serializers.IntegerField(
        min_value=1,
        help_text="Idle minutes before a staff session must sign in again.",
    )
    password_max_age_days = serializers.IntegerField(
        min_value=0,
        help_text="0 means passwords do not expire by age.",
    )

    class Meta:
        model = SiteSetting
        fields = [
            "session_timeout_minutes",
            "password_max_age_days",
            "require_password_change_for_new_users",
            "updated_at",
            "updated_by",
        ]
        read_only_fields = ["updated_at", "updated_by"]

    def get_updated_by(self, instance: SiteSetting) -> str | None:
        """Return the username who last changed the settings, if any.

        Args:
            instance: The settings row.

        Returns:
            The username, or None if the row has never been touched.
        """
        if instance.updated_by is None:
            return None
        return instance.updated_by.username


class LoginRequestSerializer(serializers.Serializer):
    """Credentials posted to ``/auth/login/``.

    ``username`` rather than ``email``, because Barkot signs staff in by the
    login name the Owner gave them (spec §9.1); an email address is not
    guaranteed to be on file.
    """

    username = serializers.CharField(
        max_length=150,
        trim_whitespace=True,
        help_text="Login name, as created by the Owner. Not an email address.",
    )
    password = serializers.CharField(
        style={"input_type": "password"},
        trim_whitespace=False,
        write_only=True,
        help_text="The account password. Sent in the request body and never echoed back.",
    )


class LoginResponseSerializer(serializers.Serializer):
    """The signed-in user, returned by ``/auth/login/`` and ``/auth/me/``."""

    user = UserSerializer()


class ChangePasswordRequestSerializer(serializers.Serializer):
    """Body of ``POST /auth/change-password/`` (spec §9.3).

    Takes the current password as well as the new one. Without it, anyone who
    reached an unattended but still-unlocked session could set a new password and
    take the account over; and the case that matters most here is a temporary
    password, which is exactly the credential most likely to be known to whoever
    issued it.
    """

    current_password = serializers.CharField(
        style={"input_type": "password"},
        trim_whitespace=False,
        write_only=True,
        help_text=(
            "The password in force right now. Confirmed so that an unlocked "
            "session cannot be used to take the account over."
        ),
    )
    new_password = serializers.CharField(
        style={"input_type": "password"},
        trim_whitespace=False,
        write_only=True,
        help_text="The replacement. Checked against the configured password validators.",
    )
    new_password_confirm = serializers.CharField(
        style={"input_type": "password"},
        trim_whitespace=False,
        write_only=True,
        help_text="Must be identical to `new_password`.",
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Check the confirmation, the current password, then the validators.

        The order is deliberate. The confirmation is checked first because it is
        free and its answer is unambiguous; the current password next, because a
        user who got that wrong has nothing else to act on; and the new password
        last, so someone working through a password policy does not also have to
        guess whether the rejection was about their old password.

        Args:
            attrs: Field values after per-field validation.

        Returns:
            The validated attributes.

        Raises:
            rest_framework.serializers.ValidationError: If the two new passwords
                differ, the current password is wrong, or the new one fails the
                configured validators. Each failure is reported against the field
                it belongs to, so the client can highlight the right input.
        """
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError({
                "new_password_confirm": ["The two passwords do not match."]
            })

        user = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError({
                "current_password": ["That is not the current password."]
            })

        # Called with the user so UserAttributeSimilarityValidator can reject a
        # password containing the username or display name.
        #
        # The exception is django.core.exceptions.ValidationError, which is what
        # validate_password raises; password_validation.PasswordValidationError does
        # not exist, so naming that would raise AttributeError from inside the except
        # clause and turn every policy rejection into a 500. Aliased to tell it apart
        # from the DRF ValidationError raised just above.
        try:
            password_validation.validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc

        return attrs


class ChangePasswordResponseSerializer(serializers.Serializer):
    """Confirmation that the password was changed, plus the refreshed user.

    The user comes back so the client can continue into the application without a
    second call, and so ``is_temporary_password`` flipping to false is seen
    through the same contract the login response already returns.
    """

    user = UserSerializer()


class CsrfResponseSerializer(serializers.Serializer):
    """The CSRF token handed to the browser client.

    ``token`` is duplicated here even though ``get_token`` also sets the cookie.
    A client that stores the token in memory and sends it in the ``X-CSRFToken``
    header never needs to read the cookie, and ``HttpOnly`` cannot be set on the
    CSRF cookie without breaking exactly that flow.
    """

    token = serializers.CharField(
        help_text=(
            "CSRF token to send in the `X-CSRFToken` header on unsafe requests. "
            "Also set as the `csrftoken` cookie."
        )
    )
