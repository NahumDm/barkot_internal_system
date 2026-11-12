"""Roadmap D1: every state-changing endpoint writes the record P06 asks for.

Spec P06 requires sensitive operations to record the actor, timestamp, entity,
action and the relevant context. This module is the D1 gate from
``docs/roadmap.md`` - "a test per endpoint asserts the audit row" - and the
only way to keep that promise as the API grows is to derive the endpoint list
from the live URLconf instead of a list someone remembers to update:

* :func:`test_every_state_changing_endpoint_has_a_scenario` fails when the
  URLconf gains an unsafe endpoint no scenario here fires, and just as loudly
  when a scenario points at an endpoint that has been removed;
* :func:`test_the_request_writes_exactly_one_matching_audit_row` fires one
  scenario and checks the ``(action, object_type)`` pair it names grew by
  exactly one row, carrying the caller as ``actor``, a non-empty target
  ``object_id`` and a human-readable ``summary``.

Three details worth knowing before editing a scenario.

**DRF discovery already honours ``http_method_names``**: its schema
generator intersects each route's declared actions with the view's allowed
methods, so an endpoint the framework answers 405 to (sales
``PUT``/``PATCH``/``DELETE`` after D1) is not part of the writable surface and
needs no exemption here. If someone widens that list again, discovery
re-offers the endpoint, the completeness test fails, and the new scenario
forces the audit decision back into the open. The 405 behaviour itself is
pinned by
:func:`apps.sales.tests.test_sale_vertical.test_records_are_neither_editable_nor_deletable`.

**Owner is the actor everywhere.** The role holds every permission in the
matrix, so no scenario can fail for a permission reason and be mistaken for a
missing audit row. Scenarios that need a second user to modify build one with
:func:`make_staff_user` instead of touching the Owner, whose own row the
serializer refuses to change.

**The snapshot sits between ``prepare`` and the request.** Prerequisites are
allowed (and often required) to write their own audit rows; only rows the
request itself adds are counted, and the count is exact for the pair the
scenario names, so an endpoint that writes the same pair twice - or the wrong
pair - fails rather than slips through.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.bono.models import BonoIncidentKind, BonoReport, BonoType
from apps.bono.services import (
    add_pairings,
    approve_report,
    create_bono_type,
    create_incident,
    create_issue,
    create_report,
    submit_report,
    update_report,
)
from apps.core.business_time import business_date, now_utc
from apps.inventory.services import ReceiptLineInput, receive_stock
from apps.payroll.models import Employee, PayrollItem
from apps.payroll.services import generate_payroll_run
from apps.products.models import Category, Product, ProductPrice
from apps.products.services import set_product_price
from apps.users.models import EmployeeProfile
from conftest import TEST_PASSWORD
from tests.api.contract import discover_endpoints

pytestmark = pytest.mark.django_db

#: The password every scenario's Owner is created with (see ``conftest``).
NEW_PASSWORD = "a-much-better-secret-phrase"

#: Builds a prerequisite record and returns it as request context.
Preparer = Callable[[Client, Any, Callable[..., Any]], dict[str, Any]]

#: Fires the single request under test.
Requester = Callable[[Client, dict[str, Any]], Any]


@pytest.fixture(autouse=True)
def uploads_land_in_a_temporary_directory(tmp_path: Path, settings: Any) -> None:
    """Point ``MEDIA_ROOT`` at a throwaway directory for every scenario.

    The document-upload scenario is a real upload through the real service, and
    a file on disk does not roll back with the database row the way the audit
    assertion assumes: without this, each run would leave a PDF behind in
    ``backend/media``. No other scenario reads media, so redirecting it for all
    of them costs nothing.

    Args:
        tmp_path: pytest's per-test temporary directory.
        settings: pytest-django's live settings wrapper.
    """
    settings.MEDIA_ROOT = tmp_path


@dataclass(frozen=True)
class Scenario:
    """One unsafe endpoint and everything needed to exercise it.

    Attributes:
        action: The :class:`AuditLog.Action` the request must add a row for.
        object_type: The ``object_type`` that row must carry, e.g.
            ``"products.Product"``.
        prepare: Runs before the audit snapshot. Creates prerequisites and may
            return them as a dict merged into the request context; the client
            is already signed in as the Owner unless ``anonymous`` is set.
        request: The single request under test, returning the raw response.
        anonymous: Call the endpoint before signing in (sign-in itself).
    """

    action: AuditLog.Action
    object_type: str
    prepare: Preparer
    request: Requester
    anonymous: bool = False


# ------------------------------------------------------------------- request helpers


def _post(path: str, payload: dict[str, Any]) -> Requester:
    """Return a requester that POSTs ``payload`` to ``path``.

    ``path`` may contain ``{pk}`` (any placeholder the scenario's prepare
    returned), so a detail endpoint reads as one literal line next to its
    action and object type.

    Args:
        path: The URL, optionally with ``{pk}``-style placeholders.
        payload: The JSON body.

    Returns:
        A callable suitable for :attr:`Scenario.request`.
    """

    def _request(client: Client, ctx: dict[str, Any]) -> Any:
        return client.post(path.format(**ctx), payload, content_type="application/json")

    return _request


def _patch(path: str, payload: dict[str, Any]) -> Requester:
    """Like :func:`_post` with PATCH. See there for the argument contract."""

    def _request(client: Client, ctx: dict[str, Any]) -> Any:
        return client.patch(path.format(**ctx), payload, content_type="application/json")

    return _request


def _put(path: str, payload: dict[str, Any]) -> Requester:
    """Like :func:`_post` with PUT. See there for the argument contract."""

    def _request(client: Client, ctx: dict[str, Any]) -> Any:
        return client.put(path.format(**ctx), payload, content_type="application/json")

    return _request


def _delete(path: str) -> Requester:
    """Return a requester that DELETEs ``path`` (placeholders as in ``_post``)."""

    def _request(client: Client, ctx: dict[str, Any]) -> Any:
        return client.delete(path.format(**ctx))

    return _request


def _post_document(path: str) -> Requester:
    """Return a requester that multipart-POSTs a valid contract PDF to ``path``.

    The upload is a real file through the real parser rather than a stub, and
    the request deliberately carries no JSON content type: the endpoint's whole
    job is to receive multipart bytes, so a request shaped any other way would
    pass here while failing for every genuine caller. No ``content_type`` is
    given because the test client sets the multipart boundary itself.

    Args:
        path: The URL, optionally with ``{pk}``-style placeholders.

    Returns:
        A callable suitable for :attr:`Scenario.request`.
    """

    def _request(client: Client, ctx: dict[str, Any]) -> Any:
        upload = SimpleUploadedFile(
            "contract.pdf",
            b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< >>\n%%EOF\n",
            content_type="application/pdf",
        )
        return client.post(path.format(**ctx), {"document": upload})

    return _request


# ------------------------------------------------------------------ prepare helpers


def _no_prerequisites(client: Client, owner: Any, make_staff: Callable[..., Any]) -> dict[str, Any]:
    """Prepare nothing: the endpoint needs only the signed-in Owner.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        An empty context.
    """
    return {}


def _make_tracked_product() -> Product:
    """Return a fresh tracked product in its own category.

    Every product scenario gets its own row so the fixed SKU below never
    collides with another scenario's; a single test runs exactly one scenario.

    Returns:
        The created :class:`Product`.
    """
    category = Category.objects.create(name="Beverages", display_order=1)
    return Product.objects.create(
        category=category,
        name="Coffee 250g",
        sku="BEV-COF-250",
        is_stock_tracked=True,
    )


def _receive(product: Product, quantity: str) -> None:
    """Put ``quantity`` units of ``product`` on the shelf through the ledger.

    Args:
        product: The product being received.
        quantity: How many units arrive.
    """
    receive_stock(
        supplier_name="Test Supplier",
        lines=[
            ReceiptLineInput(
                product=product,
                quantity=Decimal(quantity),
                unit_cost=Decimal("18.00"),
            )
        ],
    )


def _prepare_product(client: Client, owner: Any, make_staff: Callable[..., Any]) -> dict[str, Any]:
    """A plain tracked product, addressed by a path's ``{pk}`` placeholder.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``.
    """
    return {"pk": _make_tracked_product().pk}


def _prepare_product_body(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A tracked product referred to from a request *body*, not a path.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``product_pk``.
    """
    return {"product_pk": _make_tracked_product().pk}


def _prepare_received_body(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A tracked product with stock, for a body that names it.

    Stock first because a write-off of units that were never received is
    refused with 409 - which would fail this suite on the precondition rather
    than on the audit row it exists to check.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``product_pk``.
    """
    product = _make_tracked_product()
    _receive(product, "12")
    return {"product_pk": product.pk}


def _prepare_grouped_receipt_product(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A crated product on a 100 ETB selling-price group.

    Grouped receiving re-reads the current price at save time, so the product
    needs a real ``ProductPrice`` row rather than only the product itself.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``product_pk``.
    """
    category = Category.objects.create(name="Grouped Beers", display_order=2)
    product = Product.objects.create(
        category=category,
        name="Grouped Lager",
        sku="BEV-GRP-001",
        bottles_per_crate=24,
        is_stock_tracked=True,
    )
    ProductPrice.objects.create(
        product=product,
        unit_price=Decimal("100.00"),
        currency="ETB",
        effective_from=now_utc(),
    )
    return {"product_pk": product.pk}


def _prepare_category(client: Client, owner: Any, make_staff: Callable[..., Any]) -> dict[str, Any]:
    """An unused category, ready for edit, delete, or a product pointing at it.

    Both key spellings are provided: ``pk`` for a path placeholder,
    ``category_pk`` for a body field, so one prepare serves every shape.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk`` and ``category_pk``.
    """
    category = Category.objects.create(name="Pantry", display_order=1)
    return {"pk": category.pk, "category_pk": category.pk}


def _prepare_stocked_product(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A priced product with stock, for a body that names it.

    Mirrors the ``stocked`` fixture of the sale vertical test: a real price
    row and a real ledger receipt, so the sale that follows is rejected only
    if the write path itself is broken.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``product_pk``.
    """
    product = _make_tracked_product()
    ProductPrice.objects.create(
        product=product,
        unit_price=Decimal("25.00"),
        effective_from=now_utc(),
    )
    _receive(product, "40")
    return {"product_pk": product.pk}


def _prepare_sale(client: Client, owner: Any, make_staff: Callable[..., Any]) -> dict[str, Any]:
    """A recorded sale, ready for the void endpoint to reverse.

    Recorded through the API rather than a fixture so the sale's status is
    exactly what a cashier's write leaves behind.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``.
    """
    context = _prepare_stocked_product(client, owner, make_staff)
    recorded = client.post(
        "/api/v1/sales/",
        _sale_body(context["product_pk"]),
        content_type="application/json",
    )
    assert recorded.status_code == 201, recorded.content
    return {"pk": recorded.json()["id"]}


def _prepare_target_user(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A second staff member for the update endpoints to act on.

    Never the Owner: the serializer refuses self role/active changes with a
    400 that would hide the audit assertion behind a validation rule.

    Args:
        client: The Django test client.
        owner: The signed-in Owner (left untouched).
        make_staff: The user factory.

    Returns:
        Context with ``pk``.
    """
    return {"pk": make_staff(Role.Code.BARMAN, suffix="target").pk}


def _prepare_profile(client: Client, owner: Any, make_staff: Callable[..., Any]) -> dict[str, Any]:
    """A register record not yet on payroll, ready for any endpoint to act on.

    Both key spellings are provided: ``pk`` for a path placeholder and
    ``profile_pk`` for the body field ``POST /payroll/employees/`` reads, so one
    prepare serves the register's own detail endpoints and the payroll create.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused - a register entry is not a login).

    Returns:
        Context with ``pk`` and ``profile_pk``.
    """
    profile = EmployeeProfile.objects.create(
        full_name="Rahel Tesfaye",
        position="Barista",
        start_date=date(2026, 2, 2),
    )
    return {"pk": profile.pk, "profile_pk": profile.pk}


def _prepare_archived_profile(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """An archived record, which is the only state ``restore/`` can act on.

    Archived through the public endpoint rather than by setting the column, so
    the archive's own audit row lands before the snapshot and only the restore
    counts - the idempotence rule would otherwise answer a restore of an active
    record with a 200 and no row at all.

    Args:
        client: The Django test client, already signed in as the Owner.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``.
    """
    context = _prepare_profile(client, owner, make_staff)
    archived = client.post(
        f"/api/v1/employees/{context['pk']}/archive/",
        {},
        content_type="application/json",
    )
    assert archived.status_code == 200, archived.content
    return {"pk": context["pk"]}


def _prepare_employee(client: Client, owner: Any, make_staff: Callable[..., Any]) -> dict[str, Any]:
    """A profile with a payroll row, so a run can be generated from it.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``profile_pk``.
    """
    profile = EmployeeProfile.objects.create(
        full_name="Selam Bekele",
        position="Head Cashier",
        phone_number="+251911234567",
        start_date=date(2026, 1, 5),
    )
    Employee.from_profile(profile, monthly_wage=Decimal("18000.00"))
    return {"profile_pk": profile.pk}


def _prepare_payroll(status: str) -> Preparer:
    """Return a prepare that generates a run and leaves it at ``status``.

    Args:
        status: ``"generated"`` for a run awaiting approval, ``"approved"``
            for one awaiting payment. Both are reached through the public
            endpoints, so their audit rows land before the snapshot.

    Returns:
        A :data:`Preparer` returning ``pk``.
    """

    def _prepare(client: Client, owner: Any, make_staff: Callable[..., Any]) -> dict[str, Any]:
        _prepare_employee(client, owner, make_staff)
        generated = client.post(
            "/api/v1/payroll/runs/",
            {"period": "2026-10-09", "notes": "October"},
            content_type="application/json",
        )
        assert generated.status_code == 201, generated.content
        run_pk = generated.json()["id"]
        if status == "approved":
            approved = client.post(
                f"/api/v1/payroll/runs/{run_pk}/approve/",
                {},
                content_type="application/json",
            )
            assert approved.status_code == 200, approved.content
        return {"pk": run_pk}

    return _prepare


def _prepare_deduction(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A generated run's single item, ready for a deduction against it.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``item_pk``.
    """
    _prepare_employee(client, owner, make_staff)
    generated = client.post(
        "/api/v1/payroll/runs/",
        {"period": "2026-10-09", "notes": "October"},
        content_type="application/json",
    )
    assert generated.status_code == 201, generated.content
    return {"item_pk": PayrollItem.objects.get(run_id=generated.json()["id"]).pk}


def _prepare_deduction_record(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A recorded deduction, addressed by a path's ``{pk}`` placeholder.

    Recorded through the API rather than a fixture so the run it belongs to is
    still ``GENERATED`` - which is the state the correction endpoints require,
    and a fixture that wrote the row directly could easily drift into the
    approved state these endpoints must refuse.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``.
    """
    recorded = _run_deduction(client, _prepare_deduction(client, owner, make_staff))
    assert recorded.status_code == 201, recorded.content
    return {"pk": recorded.json()["id"]}


def _prepare_expense_category(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """An expense category for a new expense to point at.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk`` and ``category_pk``.
    """
    created = client.post(
        "/api/v1/finance/categories/",
        {"name": "Utilities", "description": "Power, water, internet"},
        content_type="application/json",
    )
    assert created.status_code == 201, created.content
    category_pk = created.json()["id"]
    return {"pk": category_pk, "category_pk": category_pk}


def _prepare_expense(client: Client, owner: Any, make_staff: Callable[..., Any]) -> dict[str, Any]:
    """A draft expense awaiting approval.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``.
    """
    context = _prepare_expense_category(client, owner, make_staff)
    created = client.post(
        "/api/v1/finance/expenses/",
        {
            "category": context["category_pk"],
            "description": "Electricity",
            "amount": "125.50",
            "currency": "ETB",
            "incurred_on": "2026-10-10",
        },
        content_type="application/json",
    )
    assert created.status_code == 201, created.content
    return {"pk": created.json()["id"]}


def _open_count(client: Client, product: Product) -> dict[str, Any]:
    """Open a count covering ``product`` and return its ids.

    Stock is received first so the flow matches the application's own
    inventory test: expected 12, counted 10, a negative variance for approval
    to act on.

    Args:
        client: The Django test client.
        product: The product being counted.

    Returns:
        Context with ``pk`` and ``item_id``.
    """
    _receive(product, "12")
    opened = client.post(
        "/api/v1/inventory/counts/",
        {"products": [product.pk]},
        content_type="application/json",
    )
    assert opened.status_code == 201, opened.content
    body = opened.json()
    return {"pk": body["id"], "item_id": body["items"][0]["id"]}


def _prepare_open_count(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A count left open, waiting for someone to enter quantities.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk`` and ``item_id``.
    """
    return _open_count(client, _make_tracked_product())


def _prepare_completed_count(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A counted but unapproved stock count.

    Args:
        client: The Django test client.
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``.
    """
    context = _open_count(client, _make_tracked_product())
    completed = client.post(
        f"/api/v1/inventory/counts/{context['pk']}/complete/",
        {"items": [{"item": context["item_id"], "counted_quantity": "10"}]},
        content_type="application/json",
    )
    assert completed.status_code == 200, completed.content
    return {"pk": context["pk"]}


# ----------------------------------------------------------------------- Bono prepare helpers


def _make_bono_catalogue(sku: str = "BONO-AUD-001", name: str = "Audit Bono Beer") -> Product:
    """A priced whole-bottle product a Bono type can pair.

    The pairing rule only accepts active, stock-tracked whole bottles whose
    current selling price equals the Bono's price, so the row deliberately
    sets every one of those flags plus the 25.00 price.

    Args:
        sku: A SKU unique within the test database.
        name: A name unique within the test category.

    Returns:
        The created :class:`Product`.
    """
    category, _created = Category.objects.get_or_create(
        name="Bono Beers", defaults={"display_order": 1}
    )
    product = Product.objects.create(
        category=category,
        name=name,
        sku=sku,
        unit="bottle",
        quantity_mode="WHOLE",
        is_stock_tracked=True,
        is_active=True,
    )
    ProductPrice.objects.create(
        product=product,
        unit_price=Decimal("25.00"),
        currency="ETB",
        effective_from=now_utc() - timedelta(seconds=5),
    )
    return product


def _make_bono_crew(full_name: str = "Abel Tesfaye") -> EmployeeProfile:
    """A staff register row who can be handed Bono custody.

    Args:
        full_name: The register entry's name.

    Returns:
        The created :class:`EmployeeProfile`.
    """
    return EmployeeProfile.objects.create(
        full_name=full_name,
        position="Barman",
        start_date=business_date(now_utc()) - timedelta(days=90),
    )


def _create_audit_bono_type(owner: Any) -> BonoType:
    """Create the active 25.00 Bono type the bono scenarios share.

    Args:
        owner: The acting Owner, stamped onto the record.

    Returns:
        The created :class:`BonoType`.
    """
    return create_bono_type(
        name="Audit Bono",
        color="#0F766E",
        selling_price=Decimal("25.00"),
        currency="ETB",
        actor=owner,
    )


def _prepare_bono_type(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """One active Bono type, addressed by a path's ``{pk}`` placeholder.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``.
    """
    return {"pk": _create_audit_bono_type(owner).pk}


def _prepare_bono_paired_type(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A Bono type with one paired product and one still free.

    ``bono_pk`` addresses the type's own endpoints, ``pairing_pk`` the pairing
    endpoints, ``product_pk`` the bottle already paired and
    ``free_product_pk`` a second bottle a pairing request may still add.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``bono_pk``, ``pairing_pk``, ``product_pk`` and
        ``free_product_pk``.
    """
    bono_type = _create_audit_bono_type(owner)
    product = _make_bono_catalogue()
    add_pairings(bono_type=bono_type, products=[product], actor=owner)
    return {
        "bono_pk": bono_type.pk,
        "pairing_pk": bono_type.pairings.get(product=product).pk,
        "product_pk": product.pk,
        "free_product_pk": _make_bono_catalogue(sku="BONO-AUD-002", name="Audit Bono Lager").pk,
    }


def _prepare_bono_pairing(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """The one pairing of ``_prepare_bono_paired_type``, for ``{pk}`` paths.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk`` naming the pairing.
    """
    return {"pk": _prepare_bono_paired_type(client, owner, make_staff)["pairing_pk"]}


def _prepare_bono_open_review(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A pairing whose product price moved, leaving an Owner review open.

    The price change runs through the pricing service, which is what opens
    the review, so its audit rows land before the snapshot the request is
    counted from.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk`` naming the pairing.
    """
    context = _prepare_bono_paired_type(client, owner, make_staff)
    set_product_price(
        product=Product.objects.get(pk=context["product_pk"]),
        unit_price=Decimal("30.00"),
        currency="ETB",
        actor=owner,
    )
    return {"pk": context["pairing_pk"]}


def _prepare_bono_type_products(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A Bono type with its own ``pk`` untouched by any open day activity.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk`` naming the type and ``free_product_pk``.
    """
    context = _prepare_bono_paired_type(client, owner, make_staff)
    return {"pk": context["bono_pk"], "free_product_pk": context["free_product_pk"]}


def _prepare_bono_day(client: Client, owner: Any, make_staff: Callable[..., Any]) -> dict[str, Any]:
    """An open Bono day with an initial hand-out to one staff member.

    Five tokens leave the counter, so a two-token transfer or a one-token
    loss can never be refused by the custody rule, which would otherwise
    turn the scenario's request into a validation refusal instead of the
    audited write.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``bono_pk``, ``employee_pk``, ``colleague_pk``,
        ``operational_date`` and ``day``.
    """
    bono_type = _create_audit_bono_type(owner)
    add_pairings(bono_type=bono_type, products=[_make_bono_catalogue()], actor=owner)
    employee = _make_bono_crew()
    colleague = _make_bono_crew("Hana Girma")
    operational_date = business_date(now_utc())
    create_issue(
        operational_date=operational_date,
        bono_type=bono_type,
        employee=employee,
        kind="INITIAL",
        quantity=5,
        actor=owner,
    )
    return {
        "bono_pk": bono_type.pk,
        "employee_pk": employee.pk,
        "colleague_pk": colleague.pk,
        "operational_date": operational_date.isoformat(),
        "day": operational_date,
    }


def _record_bono_loss(context: dict[str, Any], owner: Any) -> Any:
    """Record one lost-token incident against the prepared day's holder.

    Args:
        context: The ``_prepare_bono_day`` context whose holder loses one.
        owner: The acting Owner.

    Returns:
        The created pending :class:`BonoIncident`.
    """
    return create_incident(
        operational_date=context["day"],
        kind=BonoIncidentKind.LOST_BONO,
        bono_type=BonoType.objects.get(pk=context["bono_pk"]),
        responsible_employee=EmployeeProfile.objects.get(pk=context["employee_pk"]),
        quantity=1,
        reason="Lost on the floor",
        actor=owner,
    )


def _prepare_bono_pending_incident(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A recorded but unresolved lost-Bono incident, addressed by ``pk``.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``.
    """
    return {"pk": _record_bono_loss(_prepare_bono_day(client, owner, make_staff), owner).pk}


def _prepare_bono_deductible_incident(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A lost token with a payroll line belonging to the same staff member.

    The deduction endpoint refuses a payroll item that names a different
    employee than the incident's responsible staff member, so the run is
    generated from that very profile before the snapshot.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk`` and ``item_pk``.
    """
    context = _prepare_bono_day(client, owner, make_staff)
    incident = _record_bono_loss(context, owner)
    profile = EmployeeProfile.objects.get(pk=context["employee_pk"])
    payroll_employee = Employee.from_profile(profile, monthly_wage=Decimal("18000.00"))
    run = generate_payroll_run(period=context["day"], employee_ids=[payroll_employee.pk])
    return {"pk": incident.pk, "item_pk": run.items.get().pk}


def _fill_bono_report(report: BonoReport, owner: Any) -> None:
    """Enter the counts that let the report reach ``SUBMITTED``.

    Four tokens used and one returned account for all five issued, and a
    physical closing count of zero on the paired product matches the expected
    stock, so no validation holds the submission back.

    Args:
        report: The draft to fill.
        owner: The acting Owner.
    """
    update_report(
        report=report,
        bono_lines=[{"id": report.bono_lines.get().pk, "used_quantity": 4, "returned_quantity": 1}],
        product_lines=[{"id": report.product_lines.get().pk, "physical_closing_quantity": "0.000"}],
        actor=owner,
    )


def _prepare_bono_report_draft(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A draft daily report with its stock and token activity snapshotted.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``, ``bono_line_pk``, ``product_line_pk``, ``day``,
        ``bono_pk`` and ``employee_pk``.
    """
    context = _prepare_bono_day(client, owner, make_staff)
    report = create_report(operational_date=context["day"], actor=owner)
    return {
        **context,
        "pk": report.pk,
        "bono_line_pk": report.bono_lines.get().pk,
        "product_line_pk": report.product_lines.get().pk,
    }


def _prepare_bono_report_edit(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A draft whose token and product line placeholders are both filled.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``, ``bono_line_pk`` and ``product_line_pk``.
    """
    context = _prepare_bono_report_draft(client, owner, make_staff)
    return {key: context[key] for key in ("pk", "bono_line_pk", "product_line_pk")}


def _prepare_bono_stale_report(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A draft whose activity changed after the snapshot, the exact state ``refresh/`` exists for.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``.
    """
    context = _prepare_bono_report_draft(client, owner, make_staff)
    create_issue(
        operational_date=context["day"],
        bono_type=BonoType.objects.get(pk=context["bono_pk"]),
        employee=EmployeeProfile.objects.get(pk=context["employee_pk"]),
        kind="ADDITIONAL",
        quantity=1,
        actor=owner,
    )
    return {"pk": context["pk"]}


def _prepare_bono_filled_report(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A draft whose counts are complete and ready for submission.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``.
    """
    context = _prepare_bono_report_draft(client, owner, make_staff)
    _fill_bono_report(BonoReport.objects.get(pk=context["pk"]), owner)
    return {"pk": context["pk"]}


def _prepare_bono_submitted_report(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """A submitted report awaiting the Owner's decision.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``.
    """
    context = _prepare_bono_filled_report(client, owner, make_staff)
    submit_report(report=BonoReport.objects.get(pk=context["pk"]), actor=owner)
    return {"pk": context["pk"]}


def _prepare_bono_approved_report(
    client: Client, owner: Any, make_staff: Callable[..., Any]
) -> dict[str, Any]:
    """An approved report, the only state ``correct/`` may reopen.

    Args:
        client: The Django test client (unused).
        owner: The signed-in Owner.
        make_staff: The user factory (unused).

    Returns:
        Context with ``pk``.
    """
    context = _prepare_bono_submitted_report(client, owner, make_staff)
    approve_report(report=BonoReport.objects.get(pk=context["pk"]), actor=owner)
    return {"pk": context["pk"]}


# ----------------------------------------------------------------------- request bodies


def _sale_body(product_pk: Any) -> dict[str, Any]:
    """Return a sale body worth 75.00 against the stocked fixture product.

    The total is deliberately spelled out rather than computed: three units
    at the fixture's 25.00 must make exactly this, so a mismatch between the
    price row and the sale's arithmetic is a failing test, not a passing sum.

    Args:
        product_pk: The product being sold.

    Returns:
        A JSON-ready request body.
    """
    return {
        "lines": [{"product": product_pk, "quantity": "3"}],
        "payments": [{"method": "CASH", "amount": "75.00"}],
    }


def _run_login(client: Client, ctx: dict[str, Any]) -> Any:
    """Sign in with the Owner's credentials - the endpoint under test."""
    owner = ctx["owner"]
    return client.post(
        "/api/v1/auth/login/",
        {"username": owner.username, "password": TEST_PASSWORD},
        content_type="application/json",
    )


def _run_create_expense(client: Client, ctx: dict[str, Any]) -> Any:
    """Record an expense against the prepared category."""
    return client.post(
        "/api/v1/finance/expenses/",
        {
            "category": ctx["category_pk"],
            "description": "Electricity",
            "amount": "125.50",
            "currency": "ETB",
            "incurred_on": "2026-10-10",
        },
        content_type="application/json",
    )


def _run_receipt(client: Client, ctx: dict[str, Any]) -> Any:
    """Receive twelve units of the prepared product."""
    return client.post(
        "/api/v1/inventory/receipts/",
        {
            "supplier_name": "Test Supplier",
            "lines": [
                {
                    "product": ctx["product_pk"],
                    "quantity": "12",
                    "unit_cost": "18.00",
                    "currency": "ETB",
                }
            ],
        },
        content_type="application/json",
    )


def _run_grouped_receipt(client: Client, ctx: dict[str, Any]) -> Any:
    """Receive one crate through the grouped endpoint."""
    return client.post(
        "/api/v1/inventory/receipts/grouped/",
        {
            "supplier_name": "Test Supplier",
            "selling_price": "100.00",
            "lines": [
                {
                    "product": ctx["product_pk"],
                    "crates": "1",
                    "crate_cost": "720.00",
                }
            ],
        },
        content_type="application/json",
    )


def _run_breakage(client: Client, ctx: dict[str, Any]) -> Any:
    """Write off two of the received units."""
    return client.post(
        "/api/v1/inventory/breakages/",
        {"reason": "Broken bottle", "lines": [{"product": ctx["product_pk"], "quantity": "2"}]},
        content_type="application/json",
    )


def _run_open_count(client: Client, ctx: dict[str, Any]) -> Any:
    """Open a count covering the prepared product."""
    return client.post(
        "/api/v1/inventory/counts/",
        {"products": [ctx["product_pk"]]},
        content_type="application/json",
    )


def _run_complete_count(client: Client, ctx: dict[str, Any]) -> Any:
    """Enter the counted quantity on the open count."""
    return client.post(
        f"/api/v1/inventory/counts/{ctx['pk']}/complete/",
        {"items": [{"item": ctx["item_id"], "counted_quantity": "10"}]},
        content_type="application/json",
    )


def _run_deduction(client: Client, ctx: dict[str, Any]) -> Any:
    """Deduct an absence from the generated run's item."""
    return client.post(
        "/api/v1/payroll/deductions/",
        {
            "payroll_item": ctx["item_pk"],
            "deduction_type": "ABSENCE",
            "amount": "450.00",
            "reason": "Two days absent in October without leave",
        },
        content_type="application/json",
    )


def _run_create_employee(client: Client, ctx: dict[str, Any]) -> Any:
    """Put the prepared register record onto payroll."""
    return client.post(
        "/api/v1/payroll/employees/",
        {"employee": ctx["profile_pk"], "monthly_wage": "22000.00"},
        content_type="application/json",
    )


def _run_create_product(client: Client, ctx: dict[str, Any]) -> Any:
    """Create a product in the prepared category."""
    return client.post(
        "/api/v1/products/",
        {"category": ctx["category_pk"], "name": "Green Tea", "sku": "BEV-GRN-001"},
        content_type="application/json",
    )


def _run_create_sale(client: Client, ctx: dict[str, Any]) -> Any:
    """Record the three-unit sale priced by the prepared fixture."""
    return client.post(
        "/api/v1/sales/",
        _sale_body(ctx["product_pk"]),
        content_type="application/json",
    )


def _run_bono_open_report(client: Client, ctx: dict[str, Any]) -> Any:
    """Open one draft Bono report for the prepared day."""
    return client.post(
        "/api/v1/bono/reports/",
        {"operational_date": ctx["day"].isoformat(), "notes": "Audit day"},
        content_type="application/json",
    )


def _run_bono_record_issue(client: Client, ctx: dict[str, Any]) -> Any:
    """Record an additional token hand-out on the prepared day."""
    return client.post(
        "/api/v1/bono/issues/",
        {
            "operational_date": ctx["operational_date"],
            "bono_type": ctx["bono_pk"],
            "employee": ctx["employee_pk"],
            "kind": "ADDITIONAL",
            "quantity": 1,
        },
        content_type="application/json",
    )


def _run_bono_record_transfer(client: Client, ctx: dict[str, Any]) -> Any:
    """Move two of the holder's five tokens to the colleague."""
    return client.post(
        "/api/v1/bono/transfers/",
        {
            "operational_date": ctx["operational_date"],
            "bono_type": ctx["bono_pk"],
            "from_employee": ctx["employee_pk"],
            "to_employee": ctx["colleague_pk"],
            "quantity": 2,
            "reason": "Evening shift hand-over",
        },
        content_type="application/json",
    )


def _run_bono_record_loss(client: Client, ctx: dict[str, Any]) -> Any:
    """Record one lost token against the prepared day's holder."""
    return client.post(
        "/api/v1/bono/incidents/",
        {
            "operational_date": ctx["operational_date"],
            "kind": "LOST_BONO",
            "bono_type": ctx["bono_pk"],
            "responsible_employee": ctx["employee_pk"],
            "quantity": 1,
            "reason": "Token lost on the floor",
        },
        content_type="application/json",
    )


def _run_bono_deduct(client: Client, ctx: dict[str, Any]) -> Any:
    """Charge the replacement value of the lost token to the payroll line."""
    return client.post(
        f"/api/v1/bono/incidents/{ctx['pk']}/deduct/",
        {
            "payroll_item": ctx["item_pk"],
            "amount": "25.00",
            "reason": "Replacement value of the lost token",
        },
        content_type="application/json",
    )


def _run_bono_pair_products(client: Client, ctx: dict[str, Any]) -> Any:
    """Pair the free bottle with the prepared Bono type."""
    return client.post(
        "/api/v1/bono/types/{pk}/products/".format(**ctx),
        {"products": [ctx["free_product_pk"]]},
        content_type="application/json",
    )


def _bono_report_edit_body(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return the report body that fills the prepared draft's both lines.

    Args:
        ctx: The ``_prepare_bono_report_edit`` context.

    Returns:
        A JSON-ready request body.
    """
    return {
        "notes": "Counted after the shift",
        "bono_lines": [{"id": ctx["bono_line_pk"], "used_quantity": 4, "returned_quantity": 1}],
        "product_lines": [{"id": ctx["product_line_pk"], "physical_closing_quantity": "0.000"}],
    }


def _run_bono_edit_report_patch(client: Client, ctx: dict[str, Any]) -> Any:
    """PATCH the prepared draft's token and product lines."""
    return client.patch(
        f"/api/v1/bono/reports/{ctx['pk']}/",
        _bono_report_edit_body(ctx),
        content_type="application/json",
    )


def _run_bono_edit_report_put(client: Client, ctx: dict[str, Any]) -> Any:
    """PUT the prepared draft's token and product lines."""
    return client.put(
        f"/api/v1/bono/reports/{ctx['pk']}/",
        _bono_report_edit_body(ctx),
        content_type="application/json",
    )


# ------------------------------------------------------------------------ the scenarios


SCENARIOS: dict[str, Scenario] = {
    "POST /api/v1/auth/login/": Scenario(
        action=AuditLog.Action.LOGIN,
        object_type="accounts.User",
        prepare=_no_prerequisites,
        request=_run_login,
        anonymous=True,
    ),
    "POST /api/v1/auth/logout/": Scenario(
        action=AuditLog.Action.LOGOUT,
        object_type="accounts.User",
        prepare=_no_prerequisites,
        request=_post("/api/v1/auth/logout/", {}),
    ),
    "POST /api/v1/auth/change-password/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="accounts.User",
        prepare=_no_prerequisites,
        request=_post(
            "/api/v1/auth/change-password/",
            {
                "current_password": TEST_PASSWORD,
                "new_password": NEW_PASSWORD,
                "new_password_confirm": NEW_PASSWORD,
            },
        ),
    ),
    "POST /api/v1/bono/incidents/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="bono.BonoIncident",
        prepare=_prepare_bono_day,
        request=_run_bono_record_loss,
    ),
    "POST /api/v1/bono/incidents/{pk}/deduct/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoIncident",
        prepare=_prepare_bono_deductible_incident,
        request=_run_bono_deduct,
    ),
    "POST /api/v1/bono/incidents/{pk}/resolve/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoIncident",
        prepare=_prepare_bono_pending_incident,
        request=_post(
            "/api/v1/bono/incidents/{pk}/resolve/",
            {
                "resolution_status": "RESOLVED",
                "resolution_notes": "Manager confirmed the loss after checking the floor",
            },
        ),
    ),
    "POST /api/v1/bono/issues/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="bono.BonoIssue",
        prepare=_prepare_bono_day,
        request=_run_bono_record_issue,
    ),
    "POST /api/v1/bono/pairings/{pk}/remove/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoType",
        prepare=_prepare_bono_pairing,
        request=_post("/api/v1/bono/pairings/{pk}/remove/", {"reason": "The beer leaves the menu"}),
    ),
    "POST /api/v1/bono/pairings/{pk}/review/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoType",
        prepare=_prepare_bono_open_review,
        request=_post(
            "/api/v1/bono/pairings/{pk}/review/",
            {"resolution": "RETAIN", "reason": "The new menu price is correct"},
        ),
    ),
    "POST /api/v1/bono/reports/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="bono.BonoReport",
        prepare=_prepare_bono_day,
        request=_run_bono_open_report,
    ),
    "PATCH /api/v1/bono/reports/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoReport",
        prepare=_prepare_bono_report_edit,
        request=_run_bono_edit_report_patch,
    ),
    "PUT /api/v1/bono/reports/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoReport",
        prepare=_prepare_bono_report_edit,
        request=_run_bono_edit_report_put,
    ),
    "POST /api/v1/bono/reports/{pk}/approve/": Scenario(
        action=AuditLog.Action.APPROVE,
        object_type="bono.BonoReport",
        prepare=_prepare_bono_submitted_report,
        request=_post("/api/v1/bono/reports/{pk}/approve/", {}),
    ),
    "POST /api/v1/bono/reports/{pk}/correct/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="bono.BonoReport",
        prepare=_prepare_bono_approved_report,
        request=_post(
            "/api/v1/bono/reports/{pk}/correct/",
            {"reason": "The used token count was mis-keyed"},
        ),
    ),
    "POST /api/v1/bono/reports/{pk}/refresh/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoReport",
        prepare=_prepare_bono_stale_report,
        request=_post("/api/v1/bono/reports/{pk}/refresh/", {}),
    ),
    "POST /api/v1/bono/reports/{pk}/reject/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoReport",
        prepare=_prepare_bono_submitted_report,
        request=_post(
            "/api/v1/bono/reports/{pk}/reject/",
            {"reason": "The till total does not match the counted stock"},
        ),
    ),
    "POST /api/v1/bono/reports/{pk}/submit/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoReport",
        prepare=_prepare_bono_filled_report,
        request=_post("/api/v1/bono/reports/{pk}/submit/", {}),
    ),
    "POST /api/v1/bono/transfers/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="bono.BonoTransfer",
        prepare=_prepare_bono_day,
        request=_run_bono_record_transfer,
    ),
    "POST /api/v1/bono/types/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="bono.BonoType",
        prepare=_no_prerequisites,
        request=_post(
            "/api/v1/bono/types/",
            {"name": "Audit Bono", "color": "#0F766E", "selling_price": "25.00"},
        ),
    ),
    "PATCH /api/v1/bono/types/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoType",
        prepare=_prepare_bono_type,
        request=_patch("/api/v1/bono/types/{pk}/", {"name": "Audit Bono Renamed"}),
    ),
    "PUT /api/v1/bono/types/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoType",
        prepare=_prepare_bono_type,
        request=_put(
            "/api/v1/bono/types/{pk}/",
            {
                "name": "Audit Bono Renamed",
                "color": "#0F766E",
                "is_active": True,
                "notes": "Renamed by the audit scenario",
            },
        ),
    ),
    "POST /api/v1/bono/types/{pk}/products/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="bono.BonoType",
        prepare=_prepare_bono_type_products,
        request=_run_bono_pair_products,
    ),
    "POST /api/v1/employees/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="users.EmployeeProfile",
        prepare=_no_prerequisites,
        request=_post(
            "/api/v1/employees/",
            {
                "full_name": "Rahel Tesfaye",
                "position": "Barista",
                "phone_number": "+251911223344",
                "start_date": "2026-02-02",
            },
        ),
    ),
    "PATCH /api/v1/employees/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="users.EmployeeProfile",
        prepare=_prepare_profile,
        request=_patch("/api/v1/employees/{pk}/", {"position": "Senior Barista"}),
    ),
    "PUT /api/v1/employees/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="users.EmployeeProfile",
        prepare=_prepare_profile,
        request=_put("/api/v1/employees/{pk}/", {"phone_number": "+251911556677"}),
    ),
    "POST /api/v1/employees/{pk}/archive/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="users.EmployeeProfile",
        prepare=_prepare_profile,
        request=_post("/api/v1/employees/{pk}/archive/", {}),
    ),
    "POST /api/v1/employees/{pk}/restore/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="users.EmployeeProfile",
        prepare=_prepare_archived_profile,
        request=_post("/api/v1/employees/{pk}/restore/", {}),
    ),
    "POST /api/v1/employees/{pk}/document/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="users.EmployeeProfile",
        prepare=_prepare_profile,
        request=_post_document("/api/v1/employees/{pk}/document/"),
    ),
    "POST /api/v1/finance/categories/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="finance.ExpenseCategory",
        prepare=_no_prerequisites,
        request=_post(
            "/api/v1/finance/categories/",
            {"name": "Maintenance", "description": "Repairs and upkeep"},
        ),
    ),
    "PATCH /api/v1/finance/categories/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="finance.ExpenseCategory",
        prepare=_prepare_expense_category,
        request=_patch("/api/v1/finance/categories/{pk}/", {"name": "Utilities and water"}),
    ),
    "PUT /api/v1/finance/categories/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="finance.ExpenseCategory",
        prepare=_prepare_expense_category,
        request=_put(
            "/api/v1/finance/categories/{pk}/",
            {"name": "Utilities and power", "description": "Power, water, internet"},
        ),
    ),
    "POST /api/v1/finance/categories/{pk}/archive/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="finance.ExpenseCategory",
        prepare=_prepare_expense_category,
        request=_post("/api/v1/finance/categories/{pk}/archive/", {}),
    ),
    "POST /api/v1/finance/expenses/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="finance.Expense",
        prepare=_prepare_expense_category,
        request=_run_create_expense,
    ),
    "POST /api/v1/finance/expenses/{pk}/approve/": Scenario(
        action=AuditLog.Action.APPROVE,
        object_type="finance.Expense",
        prepare=_prepare_expense,
        request=_post("/api/v1/finance/expenses/{pk}/approve/", {}),
    ),
    "POST /api/v1/inventory/receipts/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="inventory.StockReceipt",
        prepare=_prepare_product_body,
        request=_run_receipt,
    ),
    "POST /api/v1/inventory/receipts/grouped/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="inventory.StockReceipt",
        prepare=_prepare_grouped_receipt_product,
        request=_run_grouped_receipt,
    ),
    "POST /api/v1/inventory/breakages/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="inventory.BreakageRecord",
        prepare=_prepare_received_body,
        request=_run_breakage,
    ),
    "POST /api/v1/inventory/counts/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="inventory.StockCount",
        prepare=_prepare_product_body,
        request=_run_open_count,
    ),
    "POST /api/v1/inventory/counts/{pk}/complete/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="inventory.StockCount",
        prepare=_prepare_open_count,
        request=_run_complete_count,
    ),
    "POST /api/v1/inventory/counts/{pk}/approve/": Scenario(
        action=AuditLog.Action.APPROVE,
        object_type="inventory.StockCount",
        prepare=_prepare_completed_count,
        request=_post("/api/v1/inventory/counts/{pk}/approve/", {}),
    ),
    "POST /api/v1/payroll/deductions/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="payroll.PayrollDeduction",
        prepare=_prepare_deduction,
        request=_run_deduction,
    ),
    "PATCH /api/v1/payroll/deductions/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="payroll.PayrollDeduction",
        prepare=_prepare_deduction_record,
        request=_patch("/api/v1/payroll/deductions/{pk}/", {"amount": "500.00"}),
    ),
    "PUT /api/v1/payroll/deductions/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="payroll.PayrollDeduction",
        prepare=_prepare_deduction_record,
        request=_put(
            "/api/v1/payroll/deductions/{pk}/",
            {"reason": "Two days absent; corrected after review", "occurred_on": "2026-10-05"},
        ),
    ),
    "POST /api/v1/payroll/employees/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="payroll.Employee",
        prepare=_prepare_profile,
        request=_run_create_employee,
    ),
    "POST /api/v1/payroll/runs/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="payroll.PayrollRun",
        prepare=_prepare_employee,
        request=_post(
            "/api/v1/payroll/runs/",
            {"period": "2026-10-09", "notes": "October"},
        ),
    ),
    "POST /api/v1/payroll/runs/{pk}/approve/": Scenario(
        action=AuditLog.Action.APPROVE,
        object_type="payroll.PayrollRun",
        prepare=_prepare_payroll("generated"),
        request=_post("/api/v1/payroll/runs/{pk}/approve/", {}),
    ),
    "POST /api/v1/payroll/runs/{pk}/mark-paid/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="payroll.PayrollRun",
        prepare=_prepare_payroll("approved"),
        request=_post("/api/v1/payroll/runs/{pk}/mark-paid/", {}),
    ),
    "POST /api/v1/products/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="products.Product",
        prepare=_prepare_category,
        request=_run_create_product,
    ),
    "POST /api/v1/products/categories/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="products.Category",
        prepare=_no_prerequisites,
        request=_post("/api/v1/products/categories/", {"name": "Drinks"}),
    ),
    "DELETE /api/v1/products/categories/{pk}/": Scenario(
        action=AuditLog.Action.DELETE,
        object_type="products.Category",
        prepare=_prepare_category,
        request=_delete("/api/v1/products/categories/{pk}/"),
    ),
    "PATCH /api/v1/products/categories/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="products.Category",
        prepare=_prepare_category,
        request=_patch("/api/v1/products/categories/{pk}/", {"display_order": 5}),
    ),
    "PUT /api/v1/products/categories/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="products.Category",
        prepare=_prepare_category,
        request=_put("/api/v1/products/categories/{pk}/", {"name": "Dry Goods"}),
    ),
    "DELETE /api/v1/products/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="products.Product",
        prepare=_prepare_product,
        request=_delete("/api/v1/products/{pk}/"),
    ),
    "PATCH /api/v1/products/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="products.Product",
        prepare=_prepare_product,
        request=_patch("/api/v1/products/{pk}/", {"description": "Freshly roasted"}),
    ),
    "PUT /api/v1/products/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="products.Product",
        prepare=_prepare_product,
        request=_put("/api/v1/products/{pk}/", {"name": "Coffee 500g"}),
    ),
    "POST /api/v1/products/{pk}/prices/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="products.ProductPrice",
        prepare=_prepare_product,
        request=_post(
            "/api/v1/products/{pk}/prices/",
            {"unit_price": "12.50", "currency": "ETB"},
        ),
    ),
    "POST /api/v1/sales/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="sales.Sale",
        prepare=_prepare_stocked_product,
        request=_run_create_sale,
    ),
    "POST /api/v1/sales/{pk}/void/": Scenario(
        action=AuditLog.Action.VOID,
        object_type="sales.Sale",
        prepare=_prepare_sale,
        request=_post(
            "/api/v1/sales/{pk}/void/",
            {"reason": "customer changed their mind"},
        ),
    ),
    "PATCH /api/v1/settings/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="accounts.SiteSetting",
        prepare=_no_prerequisites,
        # The shipped default is 0 (never expire), so 47 is a real change;
        # the no-op rule would otherwise skip the row this test exists for.
        request=_patch("/api/v1/settings/", {"password_max_age_days": 47}),
    ),
    "POST /api/v1/users/": Scenario(
        action=AuditLog.Action.CREATE,
        object_type="accounts.User",
        prepare=_no_prerequisites,
        request=_post(
            "/api/v1/users/",
            {"username": "audit-new-staff", "role": "BARMAN", "phone_number": "+251911000000"},
        ),
    ),
    "PATCH /api/v1/users/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="accounts.User",
        prepare=_prepare_target_user,
        request=_patch("/api/v1/users/{pk}/", {"is_active": False}),
    ),
    "PUT /api/v1/users/{pk}/": Scenario(
        action=AuditLog.Action.UPDATE,
        object_type="accounts.User",
        prepare=_prepare_target_user,
        request=_put("/api/v1/users/{pk}/", {"email": "audit-target@example.com"}),
    ),
}


# ------------------------------------------------------------------------------ tests


def test_every_state_changing_endpoint_has_a_scenario() -> None:
    """The scenario table and the live URLconf name the same writable endpoints.

    Checked in both directions, because each drift is a different live gap:
    an endpoint with no scenario would write audit rows nobody verifies, and a
    stale scenario documents a write the API no longer has, quietly lowering
    the coverage the roadmap counts. HEAD and OPTIONS never appear - the DRF
    enumerator already drops them - and an endpoint behind a narrowed
    ``http_method_names`` (sales mutation) is answered 405, so it is not part
    of the writable surface at all.
    """
    discovered = {
        f"{endpoint.method} {endpoint.path}"
        for endpoint in discover_endpoints()
        if endpoint.method not in {"GET", "HEAD", "OPTIONS"}
    }
    declared = set(SCENARIOS)
    missing = sorted(discovered - declared)
    stale = sorted(declared - discovered)
    assert not missing, "state-changing endpoints with no audit scenario: " + ", ".join(missing)
    assert not stale, "scenarios whose endpoint no longer exists: " + ", ".join(stale)


@pytest.mark.parametrize("key", sorted(SCENARIOS))
def test_the_request_writes_exactly_one_matching_audit_row(
    key: str,
    client: Client,
    make_staff_user: Callable[..., Any],
) -> None:
    """One request adds exactly one well-formed audit row for its pair.

    The Owner signs in (unless the endpoint *is* sign-in), prerequisites are
    built, the audit table is snapshotted for this scenario's
    ``(action, object_type)`` pair, and the request runs. The pair must then
    have grown by exactly one: zero means the write went unaudited, two means
    a side effect wrote the same pair and would mask a missing primary record.
    The row itself must name the caller, a target id and a summary - the
    actor/entity/context P06 asks for; the timestamp is the model's own.

    Args:
        key: The ``"METHOD /path/"`` identifying the scenario.
        client: The Django test client.
        make_staff_user: The user factory.
    """
    scenario = SCENARIOS[key]
    owner = make_staff_user(Role.Code.OWNER)
    if not scenario.anonymous:
        client.force_login(owner)
    ctx: dict[str, Any] = {"owner": owner, **scenario.prepare(client, owner, make_staff_user)}

    pair = AuditLog.objects.filter(action=scenario.action, object_type=scenario.object_type)
    before = pair.count()

    response = scenario.request(client, ctx)

    assert 200 <= response.status_code < 300, (
        f"{key} answered {response.status_code}: {response.content[:400]!r}"
    )
    assert pair.count() == before + 1, (
        f"{key} must add exactly one {scenario.action} row for "
        f"{scenario.object_type} (was {before}, now {pair.count()})"
    )
    entry = pair.order_by("-pk").first()
    assert entry is not None
    assert entry.actor_id == owner.pk, (
        f"{key} recorded actor {entry.actor_id}, expected the Owner ({owner.pk})"
    )
    assert entry.object_id, f"{key} wrote a {scenario.action} row with no target id"
    assert entry.summary, f"{key} wrote a {scenario.action} row with no summary"
