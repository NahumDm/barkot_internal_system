"""Employee register API acceptance tests (spec §5).

The register exists precisely because it is *not* the login table, so the
tests here are weighted toward the guarantees a future refactor is most likely
to break: registering a person creates no account, archiving keeps the row
(there is no ``DELETE`` to reach for), and an uploaded contract comes back as
a server-generated filename rather than a URL. Permissions follow the role
matrix as it stands - Owner and Manager hold ``users.manage_employees``, the
Cashier and Barman hold neither the read nor the write.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.users.models import EmployeeProfile

pytestmark = pytest.mark.django_db

EMPLOYEES_URL = "/api/v1/employees/"

#: Every conforming PDF starts with these five bytes; the rest is just enough
#: body for the file to be a file (spec §5: content, not name, decides).
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< >>\n%%EOF\n"

#: Honest text with a dishonest ``.pdf`` name - the case the magic-byte check
#: exists for.
TEXT_BYTES = b"This is a contract, honestly.\n"

#: The ``object_type`` every register audit row carries (apps.users.services).
OBJECT_TYPE = "users.EmployeeProfile"

User = get_user_model()


@pytest.fixture(autouse=True)
def documents_are_stored_in_a_temporary_directory(tmp_path: Path, settings: Any) -> None:
    """Keep uploaded documents out of ``backend/media`` for this module.

    Upload tests write real files through the real storage, and a file does not
    roll back with the database row the way the row does. Pointing
    ``MEDIA_ROOT`` at a per-test directory keeps the repository clean and gives
    every test an empty store to start from.

    Args:
        tmp_path: pytest's per-test temporary directory.
        settings: pytest-django's live settings wrapper.
    """
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def profile() -> EmployeeProfile:
    """A current register record for the detail endpoints to act on."""
    return EmployeeProfile.objects.create(
        full_name="Selam Bekele",
        position="Head Cashier",
        phone_number="+251911234567",
        start_date=date(2026, 1, 5),
    )


@pytest.fixture
def archived_profile(profile: EmployeeProfile) -> EmployeeProfile:
    """The same record after leaving: archived, but still a row.

    Archived through the model rather than the API so this fixture brings no
    audit row of its own - a test asserting how many rows a *request* writes
    must not inherit one from its setup.
    """
    profile.archive()
    profile.save(update_fields=["is_archived", "archived_at", "updated_at"])
    return profile


def _create_body(**overrides: Any) -> dict[str, Any]:
    """A valid register-create body, with any field replaced by ``overrides``."""
    body: dict[str, Any] = {
        "full_name": "Rahel Tesfaye",
        "position": "Barista",
        "phone_number": "+251911223344",
        "start_date": "2026-02-02",
    }
    body.update(overrides)
    return body


def _post_json(client: Client, url: str, body: dict[str, Any]) -> Any:
    """POST ``body`` as JSON (the API's default content type)."""
    return client.post(url, body, content_type="application/json")


def _upload_document(
    client: Client,
    pk: int,
    name: str = "contract.pdf",
    payload: bytes = PDF_BYTES,
) -> Any:
    """Multipart-POST ``payload`` as the record's contract document."""
    document = SimpleUploadedFile(name, payload, content_type="application/pdf")
    return client.post(f"{EMPLOYEES_URL}{pk}/document/", {"document": document})


def _register(client: Client, body: dict[str, Any] | None = None) -> Any:
    """POST a create body to the register, asserting it was accepted first."""
    response = _post_json(client, EMPLOYEES_URL, body or _create_body())
    assert response.status_code == 201, response.content
    return response


def _register_rows(action: str) -> Any:
    """The audit rows a register write of ``action`` produces."""
    return AuditLog.objects.filter(action=action, object_type=OBJECT_TYPE)


# ── Access ──────────────────────────────────────────────────────────────────


def test_a_signed_out_request_gets_the_login_challenge(client: Client) -> None:
    """No session means 401 with the code the frontend acts on, read or write."""
    responses = [
        client.get(EMPLOYEES_URL),
        _post_json(client, EMPLOYEES_URL, _create_body()),
    ]

    for response in responses:
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_authenticated"


@pytest.mark.parametrize("role", [Role.Code.OWNER, Role.Code.MANAGER], ids=["owner", "manager"])
def test_the_owner_and_the_manager_can_read_the_register(
    client: Client,
    staff_login: Any,
    profile: EmployeeProfile,
    role: str,
) -> None:
    """Both roles holding ``users.manage_employees`` can list and open a record.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as a given role.
        profile: The register record to read.
        role: The role under test.
    """
    staff_login(client, role)

    listing = client.get(EMPLOYEES_URL)
    detail = client.get(f"{EMPLOYEES_URL}{profile.pk}/")

    assert listing.status_code == 200, listing.content
    body = listing.json()
    assert set(body) == {"count", "page_size", "page", "pages", "results"}
    assert body["count"] == 1
    assert body["results"][0]["full_name"] == "Selam Bekele"
    assert detail.status_code == 200, detail.content
    assert detail.json()["id"] == profile.pk


@pytest.mark.parametrize("role", [Role.Code.CASHIER, Role.Code.BARMAN], ids=["cashier", "barman"])
@pytest.mark.parametrize("action", ["list", "retrieve", "create", "edit", "archive", "document"])
def test_the_shopfloor_roles_are_refused_every_register_action(
    client: Client,
    staff_login: Any,
    profile: EmployeeProfile,
    role: str,
    action: str,
) -> None:
    """Neither shopfloor role may read or write the register, on any action.

    The register shows who works here, what they are paid for and when their
    contract ends; the matrix gives ``users.manage_employees`` to the Owner and
    the Manager only, so every one of these must be a 403 - not a 404 and not
    a 401, which would mean the wrong gate answered.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as a given role.
        profile: The record being refused.
        role: The role under test.
        action: Which register action is being attempted.
    """
    staff_login(client, role)

    if action == "list":
        response = client.get(EMPLOYEES_URL)
    elif action == "retrieve":
        response = client.get(f"{EMPLOYEES_URL}{profile.pk}/")
    elif action == "create":
        response = _post_json(client, EMPLOYEES_URL, _create_body())
    elif action == "edit":
        response = client.patch(
            f"{EMPLOYEES_URL}{profile.pk}/",
            {"position": "Chief Barista"},
            content_type="application/json",
        )
    elif action == "archive":
        response = client.post(
            f"{EMPLOYEES_URL}{profile.pk}/archive/", {}, content_type="application/json"
        )
    else:  # document: a real multipart upload, refused before the body is read
        document = SimpleUploadedFile("contract.pdf", PDF_BYTES, content_type="application/pdf")
        response = client.post(f"{EMPLOYEES_URL}{profile.pk}/document/", {"document": document})

    assert response.status_code == 403, response.content
    assert response.json()["error"]["code"] == "permission_denied"


# ── Create ──────────────────────────────────────────────────────────────────


def test_registering_a_person_creates_no_login_account(client: Client, staff_login: Any) -> None:
    """A register entry is a person, not a user: no username, no password."""
    owner = staff_login(client, Role.Code.OWNER)
    users_before = User.objects.count()

    response = _register(client)

    assert User.objects.count() == users_before
    payload = response.json()
    assert payload["user"] is None
    assert payload["username"] == ""
    created = EmployeeProfile.objects.get(pk=payload["id"])
    assert created.user is None

    entry = _register_rows(AuditLog.Action.CREATE).get()
    assert entry.actor == owner
    assert entry.object_id == str(created.pk)
    assert entry.summary


def test_a_register_entry_names_the_person_position_and_first_day(
    client: Client, staff_login: Any
) -> None:
    """The three fields every row needs are required, and only those three."""
    staff_login(client, Role.Code.OWNER)

    response = _post_json(client, EMPLOYEES_URL, {})

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert set(error["details"]) == {"full_name", "position", "start_date"}
    assert EmployeeProfile.objects.count() == 0


def test_a_contract_cannot_end_before_it_starts(client: Client, staff_login: Any) -> None:
    """The dates are a business fact, so the rule lives server-side."""
    staff_login(client, Role.Code.OWNER)

    response = _post_json(
        client,
        EMPLOYEES_URL,
        _create_body(start_date="2026-03-01", contract_end_date="2026-02-01"),
    )

    assert response.status_code == 400
    assert (
        "cannot end before it starts" in response.json()["error"]["details"]["contract_end_date"][0]
    )
    assert EmployeeProfile.objects.count() == 0


def test_moving_only_the_start_date_is_checked_against_the_saved_end(
    client: Client, staff_login: Any, profile: EmployeeProfile
) -> None:
    """A PATCH cannot leave a contract ending before it starts."""
    staff_login(client, Role.Code.OWNER)
    profile.contract_end_date = date(2026, 6, 30)
    profile.save(update_fields=["contract_end_date", "updated_at"])

    response = client.patch(
        f"{EMPLOYEES_URL}{profile.pk}/",
        {"start_date": "2026-07-01"},
        content_type="application/json",
    )

    assert response.status_code == 400, response.content
    assert (
        "cannot end before it starts" in response.json()["error"]["details"]["contract_end_date"][0]
    )
    profile.refresh_from_db()
    assert profile.start_date == date(2026, 1, 5)


# ── Edit ────────────────────────────────────────────────────────────────────


def test_the_manager_edits_one_field_without_restating_the_record(
    client: Client, staff_login: Any, profile: EmployeeProfile
) -> None:
    """A PATCH changes what was sent and leaves everything else exactly as it was.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as the Manager.
        profile: The record being edited.
    """
    manager = staff_login(client, Role.Code.MANAGER)
    profile.contract_end_date = date(2026, 12, 31)
    profile.save(update_fields=["contract_end_date", "updated_at"])

    response = client.patch(
        f"{EMPLOYEES_URL}{profile.pk}/",
        {"position": "Store Supervisor"},
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    payload = response.json()
    assert payload["position"] == "Store Supervisor"
    assert payload["full_name"] == "Selam Bekele"
    assert payload["contract_end_date"] == "2026-12-31"

    profile.refresh_from_db()
    assert profile.position == "Store Supervisor"
    entry = _register_rows(AuditLog.Action.UPDATE).get()
    assert entry.actor == manager
    assert entry.object_id == str(profile.pk)


def test_an_explicit_null_clears_a_fixed_term_contract_end_date(
    client: Client, staff_login: Any, profile: EmployeeProfile
) -> None:
    """``null`` and "field absent" are different requests and must stay so.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as the Owner.
        profile: The record whose contract end date is being cleared.
    """
    staff_login(client, Role.Code.OWNER)
    profile.contract_end_date = date(2026, 12, 31)
    profile.save(update_fields=["contract_end_date", "updated_at"])

    response = client.patch(
        f"{EMPLOYEES_URL}{profile.pk}/",
        {"contract_end_date": None},
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    assert response.json()["contract_end_date"] is None
    profile.refresh_from_db()
    assert profile.contract_end_date is None


# ── Archive and restore ─────────────────────────────────────────────────────


def test_archiving_keeps_the_row_and_records_when_they_left(
    client: Client, staff_login: Any, profile: EmployeeProfile
) -> None:
    """Archiving is the removal: the row survives, twice-archived or not.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as the Owner.
        profile: The record leaving.
    """
    staff_login(client, Role.Code.OWNER)

    first = client.post(
        f"{EMPLOYEES_URL}{profile.pk}/archive/", {}, content_type="application/json"
    )
    second = client.post(
        f"{EMPLOYEES_URL}{profile.pk}/archive/", {}, content_type="application/json"
    )

    assert first.status_code == 200, first.content
    assert first.json()["is_archived"] is True
    assert first.json()["archived_at"] is not None
    assert second.status_code == 200, second.content
    assert EmployeeProfile.objects.filter(pk=profile.pk).exists()
    # One audit row, not two: the second call changed nothing, and an audit
    # trail that records work that did not happen is worse than a short one.
    assert _register_rows(AuditLog.Action.UPDATE).count() == 1


def test_a_register_record_cannot_be_deleted(
    client: Client, staff_login: Any, profile: EmployeeProfile
) -> None:
    """No method removes the row - not on the record, not on the list.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as the Owner.
        profile: The record that must survive the attempt.
    """
    staff_login(client, Role.Code.OWNER)

    detail = client.delete(f"{EMPLOYEES_URL}{profile.pk}/")
    listing = client.delete(EMPLOYEES_URL)

    assert detail.status_code == 405, detail.content
    assert listing.status_code == 405, listing.content
    assert EmployeeProfile.objects.filter(pk=profile.pk).exists()


def test_an_archived_record_can_be_restored(
    client: Client, staff_login: Any, archived_profile: EmployeeProfile
) -> None:
    """Restore undoes archiving completely - flag and timestamp together.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as the Owner.
        archived_profile: The record that has left.
    """
    staff_login(client, Role.Code.OWNER)

    response = client.post(
        f"{EMPLOYEES_URL}{archived_profile.pk}/restore/", {}, content_type="application/json"
    )

    assert response.status_code == 200, response.content
    assert response.json()["is_archived"] is False
    assert response.json()["archived_at"] is None
    archived_profile.refresh_from_db()
    assert archived_profile.archived_at is None
    entry = _register_rows(AuditLog.Action.UPDATE).get()
    assert entry.object_id == str(archived_profile.pk)


def test_restoring_a_current_record_changes_nothing(
    client: Client, staff_login: Any, profile: EmployeeProfile
) -> None:
    """The mirror of double-archiving: a no-op answers 200 and writes no row.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as the Owner.
        profile: A record that never left.
    """
    staff_login(client, Role.Code.OWNER)

    response = client.post(
        f"{EMPLOYEES_URL}{profile.pk}/restore/", {}, content_type="application/json"
    )

    assert response.status_code == 200, response.content
    assert _register_rows(AuditLog.Action.UPDATE).count() == 0


def test_the_archived_filter_splits_the_register(
    client: Client, staff_login: Any, profile: EmployeeProfile
) -> None:
    """The register keeps its history, and the filter is how you read either half.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as the Owner.
        profile: The current record; a second, archived one is created here.
    """
    staff_login(client, Role.Code.OWNER)
    left = EmployeeProfile.objects.create(
        full_name="Yonas Girma",
        position="Barman",
        start_date=date(2025, 6, 1),
    )
    left.archive()
    left.save(update_fields=["is_archived", "archived_at", "updated_at"])

    def _names(query: str = "") -> list[str]:
        response = client.get(f"{EMPLOYEES_URL}{query}")
        assert response.status_code == 200, response.content
        return [row["full_name"] for row in response.json()["results"]]

    assert _names("?archived=true") == ["Yonas Girma"]
    assert _names("?archived=false") == ["Selam Bekele"]
    assert _names() == ["Selam Bekele", "Yonas Girma"]
    # An unrecognised value is ignored rather than honoured as "archived":
    # a typo must not silently hide half the register.
    assert _names("?archived=perhaps") == ["Selam Bekele", "Yonas Girma"]


# ── Documents ───────────────────────────────────────────────────────────────


def test_a_contract_pdf_is_stored_without_its_client_name_or_a_url(
    client: Client, staff_login: Any, profile: EmployeeProfile
) -> None:
    """The server picks the name, and the response offers a filename, never a link.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as the Owner.
        profile: The record receiving the document.
    """
    staff_login(client, Role.Code.OWNER)

    response = _upload_document(client, profile.pk)

    assert response.status_code == 200, response.content
    payload = response.json()
    assert payload["has_document"] is True
    assert payload["document_filename"].endswith(".pdf")
    assert payload["document_filename"] != "contract.pdf"
    assert "document" not in payload
    assert not [
        value
        for value in payload.values()
        if isinstance(value, str) and value.startswith(("http://", "https://", "/media"))
    ]

    profile.refresh_from_db()
    stored_name = profile.document.name or ""
    assert stored_name.startswith(f"employee_documents/{profile.pk}/")
    assert Path(profile.document.path).is_file()


def test_uploading_a_replacement_leaves_one_file(
    client: Client,
    staff_login: Any,
    profile: EmployeeProfile,
    django_capture_on_commit_callbacks: Any,
) -> None:
    """One record, one document: the previous file is removed, not orphaned.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as the Owner.
        profile: The record whose contract is being re-uploaded.
        django_capture_on_commit_callbacks: Runs ``on_commit`` hooks after the
            requests, as a real commit would. The deletion is deferred so a
            rollback cannot lose the file the database still points at.
    """
    staff_login(client, Role.Code.OWNER)

    with django_capture_on_commit_callbacks(execute=True):
        first = _upload_document(client, profile.pk, payload=PDF_BYTES + b"\n% first draft\n")
        second = _upload_document(client, profile.pk, payload=PDF_BYTES + b"\n% signed draft\n")

    assert first.status_code == 200, first.content
    assert second.status_code == 200, second.content
    assert first.json()["document_filename"] != second.json()["document_filename"]

    profile.refresh_from_db()
    stored = Path(profile.document.path)
    assert len(list(stored.parent.glob("*.pdf"))) == 1


def test_a_file_that_is_not_actually_a_pdf_is_refused(
    client: Client, staff_login: Any, profile: EmployeeProfile
) -> None:
    """The content decides, not the extension: text named ``.pdf`` gets a 400.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as the Owner.
        profile: The record that must end up with no document.
    """
    staff_login(client, Role.Code.OWNER)

    response = _upload_document(client, profile.pk, payload=TEXT_BYTES)

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "not a PDF" in error["details"]["document"][0]
    profile.refresh_from_db()
    assert not profile.has_document
    assert _register_rows(AuditLog.Action.UPDATE).count() == 0


def test_a_wrong_extension_is_refused_even_with_pdf_bytes(
    client: Client, staff_login: Any, profile: EmployeeProfile
) -> None:
    """The extension check runs first, so the message names the rule that failed.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as the Owner.
        profile: The record that must end up with no document.
    """
    staff_login(client, Role.Code.OWNER)

    response = _upload_document(client, profile.pk, name="contract.txt")

    assert response.status_code == 400
    assert "Only PDF documents" in response.json()["error"]["details"]["document"][0]
    profile.refresh_from_db()
    assert not profile.has_document


def test_an_oversized_document_is_refused_before_it_is_written(
    client: Client, staff_login: Any, profile: EmployeeProfile
) -> None:
    """The size ceiling is enforced in the API, not hoped for at the proxy.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as the Owner.
        profile: The record that must end up with no document.
    """
    staff_login(client, Role.Code.OWNER)

    with override_settings(EMPLOYEE_DOCUMENT_MAX_BYTES=64):
        response = _upload_document(client, profile.pk, payload=PDF_BYTES + b"x" * 512)

    assert response.status_code == 400
    assert "larger than" in response.json()["error"]["details"]["document"][0]
    profile.refresh_from_db()
    assert not profile.has_document


def test_the_document_endpoint_only_accepts_uploads(
    client: Client, staff_login: Any, profile: EmployeeProfile
) -> None:
    """The upload route is POST-only: there is no way to fetch a document back.

    Args:
        client: The Django test client.
        staff_login: Fixture signing the client in as the Owner.
        profile: The record with a document on file.
    """
    staff_login(client, Role.Code.OWNER)
    assert _upload_document(client, profile.pk).status_code == 200

    for method in ("get", "put"):
        response = getattr(client, method)(f"{EMPLOYEES_URL}{profile.pk}/document/")
        assert response.status_code == 405, response.content
