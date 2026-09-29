"""OpenAPI schemas for the shared API envelope (spec §20.2).

These are documentation types, not validation types: they describe the
responses that :mod:`apps.core.exceptions` produces so the generated schema
shows the real body shape. They are declared in one place because every
endpoint in every domain returns the same envelopes, and a per-app
redefinition of "what an error looks like" is how seven domains end up with
seven error formats.
"""

from __future__ import annotations

from rest_framework import serializers


class ErrorDetailSerializer(serializers.Serializer):
    """The body of a failed request.

    ``code`` is the contract: the frontend switches on it and never parses
    ``message``, which is free to change wording at any time. ``details`` is
    present only when the failure is field-level, mapping a field name to the
    messages for that field; a form-level failure uses ``non_field_errors``.
    """

    code = serializers.CharField(
        help_text=(
            "Stable, machine-readable identifier such as `insufficient_stock`, "
            "`validation_error` or `not_authenticated`. Switch on this; never "
            "parse `message`."
        )
    )
    message = serializers.CharField(help_text="Human-readable summary, safe to display to staff.")
    details = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        required=False,
        allow_null=True,
        help_text=(
            "Field name to messages, for validation failures only. Form-level "
            "errors use the key `non_field_errors`. Absent otherwise."
        ),
    )


class ErrorResponseSerializer(serializers.Serializer):
    """Top-level error body: a single ``error`` key, nothing else at the root."""

    error = ErrorDetailSerializer()


class ApiRootSerializer(serializers.Serializer):
    """``GET /api/v1/`` - which API this is, and what it can do."""

    service = serializers.CharField(help_text="Human-readable service name.")
    version = serializers.CharField(help_text="The API version serving this URL.")
    documentation = serializers.CharField(
        help_text="Path to the OpenAPI schema, for generated clients and humans."
    )
