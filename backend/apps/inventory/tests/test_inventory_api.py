"""C3 inventory API acceptance tests."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import Role
from apps.inventory.models import StockCount, StockMovement
from apps.inventory.services import current_stock
from apps.products.models import Category, Product

pytestmark = pytest.mark.django_db

RECEIPTS_URL = "/api/v1/inventory/receipts/"
BREAKAGES_URL = "/api/v1/inventory/breakages/"
COUNTS_URL = "/api/v1/inventory/counts/"
MOVEMENTS_URL = "/api/v1/inventory/movements/"


@pytest.fixture
def product() -> Product:
    category = Category.objects.create(name="Beverages", display_order=1)
    return Product.objects.create(
        category=category,
        name="Test Lager",
        sku="INV-LAGER-001",
        is_stock_tracked=True,
    )


def receive_body(product: Product, quantity: str = "12") -> dict[str, Any]:
    return {
        "supplier_name": "Test Supplier",
        "lines": [
            {
                "product": product.pk,
                "quantity": quantity,
                "unit_cost": "18.00",
                "currency": "ETB",
            }
        ],
    }


def test_barman_receives_stock_once_into_the_ledger(
    client: Client, staff_login: Any, product: Product
) -> None:
    staff_login(client, Role.Code.BARMAN)

    response = client.post(RECEIPTS_URL, receive_body(product), content_type="application/json")

    assert response.status_code == 201, response.content
    assert response.json()["status"] == "COMPLETED"
    assert current_stock(product) == Decimal("12.000")
    assert StockMovement.objects.filter(product=product, kind="RECEIPT").count() == 1


def test_cashier_cannot_receive_stock(client: Client, staff_login: Any, product: Product) -> None:
    staff_login(client, Role.Code.CASHIER)

    response = client.post(RECEIPTS_URL, receive_body(product), content_type="application/json")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_barman_records_breakage_and_stock_decreases_once(
    client: Client, staff_login: Any, product: Product
) -> None:
    staff_login(client, Role.Code.BARMAN)
    receive_response = client.post(
        RECEIPTS_URL, receive_body(product), content_type="application/json"
    )
    assert receive_response.status_code == 201

    response = client.post(
        BREAKAGES_URL,
        {
            "reason": "Broken bottle",
            "lines": [{"product": product.pk, "quantity": "2"}],
        },
        content_type="application/json",
    )

    assert response.status_code == 201, response.content
    assert current_stock(product) == Decimal("10.000")
    assert StockMovement.objects.filter(product=product, kind="BREAKAGE").count() == 1


def test_cashier_count_requires_manager_approval_for_variance(
    client: Client, staff_login: Any, make_staff_user: Any, product: Product
) -> None:
    cashier = staff_login(client, Role.Code.CASHIER)
    receive_response = client.post(
        RECEIPTS_URL,
        receive_body(product),
        content_type="application/json",
    )
    assert receive_response.status_code == 403

    # Seed the opening ledger through the service because the Cashier is not a receiver.
    from apps.inventory.services import ReceiptLineInput, receive_stock

    receive_stock(
        supplier_name="Test Supplier",
        lines=[ReceiptLineInput(product=product, quantity=Decimal("12"), unit_cost=Decimal("18"))],
    )

    open_response = client.post(
        COUNTS_URL,
        {"products": [product.pk]},
        content_type="application/json",
    )
    assert open_response.status_code == 201, open_response.content
    count_id = open_response.json()["id"]
    item_id = open_response.json()["items"][0]["id"]

    complete_response = client.post(
        f"{COUNTS_URL}{count_id}/complete/",
        {"items": [{"item": item_id, "counted_quantity": "10"}]},
        content_type="application/json",
    )
    assert complete_response.status_code == 200, complete_response.content
    assert current_stock(product) == Decimal("12.000")

    manager = make_staff_user(Role.Code.MANAGER, suffix="approver")
    client.logout()
    client.login(username=manager.username, password="correct-horse-battery-staple")
    approve_response = client.post(f"{COUNTS_URL}{count_id}/approve/")

    assert approve_response.status_code == 200, approve_response.content
    assert current_stock(product) == Decimal("10.000")
    assert StockMovement.objects.filter(product=product, kind="COUNT_VARIANCE").count() == 1
    assert StockCount.objects.get(pk=count_id).status == "APPROVED"
    assert cashier.role.code == Role.Code.CASHIER


def test_barman_cannot_complete_a_stock_count(
    client: Client, staff_login: Any, product: Product
) -> None:
    staff_login(client, Role.Code.BARMAN)

    response = client.post(
        COUNTS_URL,
        {"products": [product.pk]},
        content_type="application/json",
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


def test_stock_movements_are_visible_to_inventory_roles(
    client: Client, staff_login: Any, product: Product
) -> None:
    staff_login(client, Role.Code.BARMAN)

    response = client.get(MOVEMENTS_URL, {"product": product.pk})

    assert response.status_code == 200, response.content
    assert response.json()["results"] == []
