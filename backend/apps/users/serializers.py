"""Serializers for the employee register (spec §5).

Three shapes, one per verb group, because the register has three different
contracts with its caller:

- :class:`EmployeeSerializer` reads a record back. Everything on it is either a
  stored field or a derived one, so a screen can render a row without asking a
  second endpoint.
- :class:`EmployeeCreateSerializer` and :class:`EmployeeUpdateSerializer` decide
  what a *person* record may be given. Pay and status are absent by design:
  ``monthly_wage`` belongs to payroll (ADR-0003 D5), and employment status is
  ``is_archived`` rather than a third thing that could disagree with it.
- :class:`EmployeeDocumentSerializer` is the only one that accepts a file, and
  it is the only place the upload rules are stated.

There is deliberately no ``document`` URL anywhere. Documents are stored
outside the web root and are never served over HTTP, so exposing a link would
be inventing a route the system does not have.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings
from rest_framework import serializers

from apps.core.enums import ContractType
from apps.users.models import EmployeeProfile

#: The PDF header every conforming PDF starts with (spec §5, "PDF only").
#: Checked in the file's *content* rather than trusting the extension or the
#: content type: both are chosen by whoever uploads, so a ``.pdf`` whose bytes
#: start with ``%PK`` is exactly the case the check exists for.
PDF_MAGIC = b"%PDF-"

#: How many bytes of the upload are read for the header check. Five is the
#: length of the marker itself; reading more would be reading the document.
PDF_MAGIC_LENGTH = len(PDF_MAGIC)


class EmployeeSerializer(serializers.ModelSerializer):
    """A register record as it stands.

    ``username`` is reported rather than a nested account: the register is
    independent of logins, so most rows have none and a nested object would be
    ``null`` most of the time — which a client then has to handle as a second
    shape. A bare string, empty when there is no login, is one shape.
    """

    username = serializers.SerializerMethodField()
    contract_type_display = serializers.CharField(
        source="get_contract_type_display", read_only=True
    )
    has_document = serializers.SerializerMethodField()
    document_filename = serializers.CharField(read_only=True)

    class Meta:
        model = EmployeeProfile
        fields = [
            "id",
            "full_name",
            "position",
            "phone_number",
            "start_date",
            "contract_type",
            "contract_type_display",
            "contract_end_date",
            "is_archived",
            "archived_at",
            "notes",
            "user",
            "username",
            "has_document",
            "document_filename",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_has_document(self, profile: EmployeeProfile) -> bool:
        """Whether a contract document is on file."""
        return profile.has_document

    def get_username(self, profile: EmployeeProfile) -> str:
        """The linked login name, or ``""`` when this person has no account.

        Empty rather than ``null``, which is the shape the class docstring
        argues for: most register rows have no login, and a client checking for
        null on one column of every row would be handling a second shape for no
        benefit.
        """
        user = profile.user
        return user.username if user is not None else ""


def _validate_contract_dates(start: date | None, end: date | None) -> None:
    """Refuse a fixed-term contract that ends before it begins.

    Both dates are business facts rather than presentation, so the check lives
    here rather than in the client: an end date before the start date is
    incoherent however the form is filled in.

    Args:
        start: Employment start, or ``None`` when the caller is not setting it.
        end: Contract end, or ``None`` for an open-ended contract.

    Raises:
        serializers.ValidationError: If ``end`` precedes ``start``.
    """
    if start is not None and end is not None and end < start:
        raise serializers.ValidationError({
            "contract_end_date": ["The contract cannot end before it starts."]
        })


class EmployeeCreateSerializer(serializers.Serializer):
    """Body for registering a new staff member."""

    full_name = serializers.CharField(max_length=150, trim_whitespace=True)
    position = serializers.CharField(max_length=100, trim_whitespace=True)
    phone_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    start_date = serializers.DateField()
    contract_type = serializers.ChoiceField(choices=ContractType.choices, default="FULL_TIME")
    contract_end_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        _validate_contract_dates(attrs.get("start_date"), attrs.get("contract_end_date"))
        return attrs


class EmployeeUpdateSerializer(serializers.Serializer):
    """Body for editing a register record.

    Every field is optional so a caller can change one thing without restating
    the rest — and so ``PATCH`` and ``PUT`` mean the same thing here as they do
    on the expense-category screen. An explicit ``null`` for
    ``contract_end_date`` clears a fixed-term end date; the field simply being
    absent leaves it alone, which is why the two are not the same value.
    """

    full_name = serializers.CharField(max_length=150, required=False, trim_whitespace=True)
    position = serializers.CharField(max_length=100, required=False, trim_whitespace=True)
    phone_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    start_date = serializers.DateField(required=False)
    contract_type = serializers.ChoiceField(choices=ContractType.choices, required=False)
    contract_end_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if self.instance is None:  # pragma: no cover - the view always sets one
            return attrs
        start = attrs.get("start_date", self.instance.start_date)
        # A PATCH that moves only the start date must still be checked against
        # the end date already on file; otherwise a contract can be left ending
        # before it starts with no field in this request to blame.
        end = attrs.get("contract_end_date", self.instance.contract_end_date)
        _validate_contract_dates(start, end)
        return attrs


class EmployeeDocumentSerializer(serializers.Serializer):
    """Body for putting a contract PDF on file against one record.

    All three checks are deliberate, and none of them is redundant:

    - the **extension** answers "what did the caller say this is", and gives a
      readable message when someone picks the wrong file;
    - the **magic bytes** answer "what is this actually", which is the one the
      extension cannot answer — a ``.exe`` renamed to ``.pdf`` passes the first
      check and fails this one;
    - the **size** limit stops a huge upload being written to disk at all,
      rather than being caught by a reverse proxy the deployment may not have.

    The rules are stated once, here, and the endpoint itself does no validation
    of its own — so a future caller that reaches the service has already been
    through the same gate.
    """

    document = serializers.FileField()

    def validate_document(self, value: Any) -> Any:
        """Apply the extension, content and size rules to an uploaded file.

        Args:
            value: The uploaded file.

        Returns:
            The file, unchanged, when it passes every rule.

        Raises:
            serializers.ValidationError: Naming the rule that failed.
        """
        max_bytes = settings.EMPLOYEE_DOCUMENT_MAX_BYTES
        if value.size > max_bytes:
            raise serializers.ValidationError(
                f"The document is larger than the {max_bytes // (1024 * 1024)} MB limit."
            )

        name = (value.name or "").lower()
        if not name.endswith(".pdf"):
            raise serializers.ValidationError("Only PDF documents can be uploaded.")

        # ``seek`` rather than a second open: an upload arriving over multipart
        # is already in memory or in a temp file, and seeking it back to the
        # start leaves it exactly as it was found for the storage write that
        # follows.
        value.seek(0)
        header = value.read(PDF_MAGIC_LENGTH)
        value.seek(0)
        if header != PDF_MAGIC:
            raise serializers.ValidationError("That file is not a PDF, whatever it is named.")
        return value


__all__ = [
    "EmployeeCreateSerializer",
    "EmployeeDocumentSerializer",
    "EmployeeSerializer",
    "EmployeeUpdateSerializer",
]
