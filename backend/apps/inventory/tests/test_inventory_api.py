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


# ---------------------------------------------------------------------------
# Grouped receiving and grouped stock count tests
# ---------------------------------------------------------------------------


def test_grouped_receiving_matching_selling_price_converts_crates_to_bottles(
    client: Client, staff_login: Any
) -> None:
    staff_login(client, Role.Code.BARMAN)

    category = Category.objects.create(name="Beers", display_order=1)
    heineken = Product.objects.create(
        category=category,
        name="Heineken",
        sku="BEER-HEIN-001",
        unit="bottle",
        bottles_per_crate=24,
        is_stock_tracked=True,
    )
    from apps.core.business_time import now_utc
    from apps.products.models import ProductPrice

    ProductPrice.objects.create(
        product=heineken, unit_price=Decimal("100.00"), currency="ETB", effective_from=now_utc()
    )

    bedele = Product.objects.create(
        category=category,
        name="Bedele",
        sku="BEER-BEDE-001",
        unit="bottle",
        bottles_per_crate=20,
        is_stock_tracked=True,
    )
    ProductPrice.objects.create(
        product=bedele, unit_price=Decimal("100.00"), currency="ETB", effective_from=now_utc()
    )

    payload = {
        "supplier_name": "BGI Ethiopia",
        "selling_price": "100.00",
        "reference": "DEL-GRP-001",
        "lines": [
            {
                "product": heineken.pk,
                "crates": "3",
                "crate_cost": "720.00",
                # Deliberately spoofed conversion/quantity fields. The backend
                # must ignore them and use Product.bottles_per_crate.
                "bottles_per_crate": 100,
                "quantity": 9999,
            },
            {
                "product": bedele.pk,
                "crates": "2",
                "crate_cost": "500.00",
            },
        ],
    }

    response = client.post(
        f"{RECEIPTS_URL}grouped/",
        payload,
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    data = response.json()
    assert data["status"] == "COMPLETED"
    assert len(data["items"]) == 2

    # Heineken: 3 crates * 24 = 72 bottles; 720 / 24 = 30.00 unit_cost
    assert current_stock(heineken) == Decimal("72.000")
    heineken_item = next(it for it in data["items"] if it["product"] == heineken.pk)
    assert Decimal(heineken_item["quantity"]) == Decimal("72.000")
    assert Decimal(heineken_item["unit_cost"]) == Decimal("30.00")

    # Bedele: 2 crates * 20 = 40 bottles; 500 / 20 = 25.00 unit_cost.
    # Each line keeps its own purchase cost.
    assert current_stock(bedele) == Decimal("40.000")
    bedele_item = next(it for it in data["items"] if it["product"] == bedele.pk)
    assert Decimal(bedele_item["quantity"]) == Decimal("40.000")
    assert Decimal(bedele_item["unit_cost"]) == Decimal("25.00")

    # Combined total is 112 bottles
    assert current_stock(heineken) + current_stock(bedele) == Decimal("112.000")

    # Stock movements are separate
    assert StockMovement.objects.filter(product=heineken, kind="RECEIPT").count() == 1
    assert StockMovement.objects.filter(product=bedele, kind="RECEIPT").count() == 1


def test_grouped_receiving_rejects_mismatched_selling_price(
    client: Client, staff_login: Any
) -> None:
    staff_login(client, Role.Code.BARMAN)

    category = Category.objects.create(name="Beers2", display_order=2)
    heineken = Product.objects.create(
        category=category,
        name="Heineken Premium",
        sku="BEER-HEIN-002",
        bottles_per_crate=24,
        is_stock_tracked=True,
    )
    from apps.core.business_time import now_utc
    from apps.products.models import ProductPrice

    ProductPrice.objects.create(
        product=heineken, unit_price=Decimal("100.00"), currency="ETB", effective_from=now_utc()
    )

    cheaper_beer = Product.objects.create(
        category=category,
        name="Cheap Beer",
        sku="BEER-CHEAP-001",
        bottles_per_crate=24,
        is_stock_tracked=True,
    )
    ProductPrice.objects.create(
        product=cheaper_beer, unit_price=Decimal("60.00"), currency="ETB", effective_from=now_utc()
    )

    payload = {
        "supplier_name": "Distributor",
        "selling_price": "100.00",
        "lines": [
            {"product": heineken.pk, "crates": "1", "crate_cost": "700.00"},
            {"product": cheaper_beer.pk, "crates": "1", "crate_cost": "400.00"},
        ],
    }

    response = client.post(f"{RECEIPTS_URL}grouped/", payload, content_type="application/json")
    assert response.status_code == 400
    assert "does not match the selected price group" in response.content.decode()
    # Transaction atomicity: neither was received
    assert current_stock(heineken) == Decimal("0.000")
    assert current_stock(cheaper_beer) == Decimal("0.000")


def test_grouped_receiving_rolls_back_atomically_if_one_line_fails(
    client: Client, staff_login: Any
) -> None:
    staff_login(client, Role.Code.BARMAN)

    category = Category.objects.create(name="Beers3", display_order=3)
    heineken = Product.objects.create(
        category=category,
        name="Heineken Silver",
        sku="BEER-HEIN-003",
        bottles_per_crate=24,
        is_stock_tracked=True,
    )
    from apps.core.business_time import now_utc
    from apps.products.models import ProductPrice

    ProductPrice.objects.create(
        product=heineken, unit_price=Decimal("100.00"), currency="ETB", effective_from=now_utc()
    )

    inactive_beer = Product.objects.create(
        category=category,
        name="Discontinued Beer",
        sku="BEER-DISC-001",
        bottles_per_crate=24,
        is_stock_tracked=True,
        is_active=False,
    )
    ProductPrice.objects.create(
        product=inactive_beer,
        unit_price=Decimal("100.00"),
        currency="ETB",
        effective_from=now_utc(),
    )

    payload = {
        "supplier_name": "Distributor",
        "selling_price": "100.00",
        "lines": [
            {"product": heineken.pk, "crates": "2", "crate_cost": "1400.00"},
            {"product": inactive_beer.pk, "crates": "1", "crate_cost": "700.00"},
        ],
    }

    response = client.post(f"{RECEIPTS_URL}grouped/", payload, content_type="application/json")
    assert response.status_code == 400
    # Nothing was committed
    assert current_stock(heineken) == Decimal("0.000")


def test_grouped_receiving_duplicate_submission_protection(
    client: Client, staff_login: Any
) -> None:
    staff_login(client, Role.Code.BARMAN)

    category = Category.objects.create(name="Beers4", display_order=4)
    heineken = Product.objects.create(
        category=category,
        name="Heineken Gold",
        sku="BEER-HEIN-004",
        bottles_per_crate=24,
        is_stock_tracked=True,
    )
    from apps.core.business_time import now_utc
    from apps.products.models import ProductPrice

    ProductPrice.objects.create(
        product=heineken, unit_price=Decimal("100.00"), currency="ETB", effective_from=now_utc()
    )

    payload = {
        "supplier_name": "Distributor",
        "selling_price": "100.00",
        "idempotency_key": "grp-idemp-001",
        "lines": [
            {"product": heineken.pk, "crates": "1", "crate_cost": "720.00"},
        ],
    }

    first = client.post(f"{RECEIPTS_URL}grouped/", payload, content_type="application/json")
    assert first.status_code == 201
    receipt_id = first.json()["id"]

    # Replay identical request with same idempotency key
    second = client.post(f"{RECEIPTS_URL}grouped/", payload, content_type="application/json")
    assert second.status_code == 201
    assert second.json()["id"] == receipt_id

    # Stock is only added once (24 bottles, not 48)
    assert current_stock(heineken) == Decimal("24.000")


def test_grouped_receiving_rejects_products_without_crate_conversion(
    client: Client, staff_login: Any
) -> None:
    staff_login(client, Role.Code.BARMAN)

    category = Category.objects.create(name="BeersNoCrate", display_order=6)
    from apps.core.business_time import now_utc
    from apps.products.models import ProductPrice

    loose_bottle = Product.objects.create(
        category=category,
        name="Loose Bottle",
        sku="BEER-LOOSE-001",
        unit="bottle",
        bottles_per_crate=None,
        is_stock_tracked=True,
    )
    ProductPrice.objects.create(
        product=loose_bottle,
        unit_price=Decimal("100.00"),
        currency="ETB",
        effective_from=now_utc(),
    )

    response = client.post(
        f"{RECEIPTS_URL}grouped/",
        {
            "supplier_name": "Distributor",
            "selling_price": "100.00",
            "lines": [{"product": loose_bottle.pk, "crates": "1", "crate_cost": "100.00"}],
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "bottles-per-crate" in response.content.decode()
    assert current_stock(loose_bottle) == Decimal("0.000")


def test_grouped_receiving_rejects_non_positive_crate_quantity(
    client: Client, staff_login: Any
) -> None:
    staff_login(client, Role.Code.BARMAN)

    category = Category.objects.create(name="BeersQty", display_order=7)
    from apps.core.business_time import now_utc
    from apps.products.models import ProductPrice

    beer = Product.objects.create(
        category=category,
        name="Quantity Beer",
        sku="BEER-QTY-001",
        bottles_per_crate=24,
        is_stock_tracked=True,
    )
    ProductPrice.objects.create(
        product=beer, unit_price=Decimal("100.00"), currency="ETB", effective_from=now_utc()
    )

    for invalid in ("0", "-2"):
        response = client.post(
            f"{RECEIPTS_URL}grouped/",
            {
                "supplier_name": "Distributor",
                "selling_price": "100.00",
                "lines": [{"product": beer.pk, "crates": invalid, "crate_cost": "720.00"}],
            },
            content_type="application/json",
        )
        assert response.status_code == 400, response.content
        assert "greater than zero" in response.content.decode()

    assert current_stock(beer) == Decimal("0.000")


def test_grouped_stock_count_does_not_treat_missing_count_as_zero(
    client: Client, staff_login: Any
) -> None:
    staff_login(client, Role.Code.CASHIER)

    category = Category.objects.create(name="CountIncomplete", display_order=8)
    from apps.core.business_time import now_utc
    from apps.products.models import ProductPrice

    products = []
    for index, sku in enumerate(("COUNT-INC-1", "COUNT-INC-2"), start=1):
        product = Product.objects.create(
            category=category,
            name=f"Incomplete Count {index}",
            sku=sku,
            bottles_per_crate=24,
            is_stock_tracked=True,
        )
        ProductPrice.objects.create(
            product=product,
            unit_price=Decimal("100.00"),
            currency="ETB",
            effective_from=now_utc(),
        )
        products.append(product)

    open_res = client.post(
        COUNTS_URL,
        {"products": [product.pk for product in products]},
        content_type="application/json",
    )
    assert open_res.status_code == 201, open_res.content
    count_data = open_res.json()
    first_item = count_data["items"][0]

    # Submitting only one of two lines must be refused; the count stays DRAFT
    # so an unentered physical quantity is never interpreted as zero.
    complete_res = client.post(
        f"{COUNTS_URL}{count_data['id']}/complete/",
        {"items": [{"item": first_item["id"], "counted_quantity": "10"}]},
        content_type="application/json",
    )
    assert complete_res.status_code == 409, complete_res.content

    refreshed = client.get(f"{COUNTS_URL}{count_data['id']}/")
    assert refreshed.status_code == 200
    refreshed_data = refreshed.json()
    assert refreshed_data["status"] == "DRAFT"
    assert all(item["counted_quantity"] == "0.000" for item in refreshed_data["items"])
    assert refreshed_data["total_counted"] == "0.000"


def test_grouped_stock_count_calculates_individual_and_combined_variances(
    client: Client, staff_login: Any, make_staff_user: Any
) -> None:
    category = Category.objects.create(name="CountBeers", display_order=5)
    from apps.core.business_time import now_utc
    from apps.products.models import ProductPrice

    heineken = Product.objects.create(
        category=category,
        name="Count Heineken",
        sku="COUNT-HEIN",
        bottles_per_crate=24,
        is_stock_tracked=True,
    )
    ProductPrice.objects.create(
        product=heineken, unit_price=Decimal("100.00"), currency="ETB", effective_from=now_utc()
    )

    bedele = Product.objects.create(
        category=category,
        name="Count Bedele",
        sku="COUNT-BEDE",
        bottles_per_crate=20,
        is_stock_tracked=True,
    )
    ProductPrice.objects.create(
        product=bedele, unit_price=Decimal("100.00"), currency="ETB", effective_from=now_utc()
    )

    # Seed initial stock via receive_grouped_stock
    from apps.inventory.services import GroupedReceiptLineInput, receive_grouped_stock

    receive_grouped_stock(
        supplier_name="Distributor",
        selling_price=Decimal("100.00"),
        lines=[
            GroupedReceiptLineInput(
                product=heineken, crates=Decimal("3"), crate_cost=Decimal("720.00")
            ),
            GroupedReceiptLineInput(
                product=bedele, crates=Decimal("2"), crate_cost=Decimal("600.00")
            ),
        ],
    )
    assert current_stock(heineken) == Decimal("72.000")
    assert current_stock(bedele) == Decimal("40.000")

    # Cashier opens a stock count covering both products
    staff_login(client, Role.Code.CASHIER)
    open_res = client.post(
        COUNTS_URL,
        {"products": [heineken.pk, bedele.pk]},
        content_type="application/json",
    )
    assert open_res.status_code == 201, open_res.content
    count_data = open_res.json()
    count_id = count_data["id"]
    items = count_data["items"]
    assert len(items) == 2

    heineken_item = next(it for it in items if it["product"] == heineken.pk)
    bedele_item = next(it for it in items if it["product"] == bedele.pk)

    assert Decimal(heineken_item["expected_quantity"]) == Decimal("72.000")
    assert Decimal(bedele_item["expected_quantity"]) == Decimal("40.000")
    assert Decimal(count_data["total_expected"]) == Decimal("112.000")

    # Complete count: Heineken physical = 70 (variance -2); Bedele physical = 41 (variance +1)
    complete_res = client.post(
        f"{COUNTS_URL}{count_id}/complete/",
        {
            "items": [
                {"item": heineken_item["id"], "counted_quantity": "70"},
                {"item": bedele_item["id"], "counted_quantity": "41"},
            ]
        },
        content_type="application/json",
    )
    assert complete_res.status_code == 200, complete_res.content
    completed_data = complete_res.json()
    assert completed_data["status"] == "COMPLETED"

    h_completed = next(it for it in completed_data["items"] if it["product"] == heineken.pk)
    b_completed = next(it for it in completed_data["items"] if it["product"] == bedele.pk)

    assert Decimal(h_completed["counted_quantity"]) == Decimal("70.000")
    assert Decimal(h_completed["variance"]) == Decimal("-2.000")

    assert Decimal(b_completed["counted_quantity"]) == Decimal("41.000")
    assert Decimal(b_completed["variance"]) == Decimal("1.000")

    # Combined summary
    assert Decimal(completed_data["total_expected"]) == Decimal("112.000")
    assert Decimal(completed_data["total_counted"]) == Decimal("111.000")
    assert Decimal(completed_data["total_variance"]) == Decimal("-1.000")

    # Stock has NOT changed yet
    assert current_stock(heineken) == Decimal("72.000")
    assert current_stock(bedele) == Decimal("40.000")

    # Manager approves
    manager = make_staff_user(Role.Code.MANAGER, suffix="mgr_app")
    client.logout()
    client.login(username=manager.username, password="correct-horse-battery-staple")
    approve_res = client.post(f"{COUNTS_URL}{count_id}/approve/")
    assert approve_res.status_code == 200

    # Stock movements posted
    assert current_stock(heineken) == Decimal("70.000")
    assert current_stock(bedele) == Decimal("41.000")
    assert StockCount.objects.get(pk=count_id).status == "APPROVED"
