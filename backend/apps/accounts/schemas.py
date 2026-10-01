"""Request and response bodies for the auth endpoints (spec §9.1).

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

from apps.accounts.models import User


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
