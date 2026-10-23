"""API tests for the product catalogue's response shapes and filters."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import Role
from apps.products.models import Category, Product

pytestmark = pytest.mark.django_db

PRODUCTS_URL = "/api/v1/products/"
CATEGORIES_URL = "/api/v1/products/categories/"


def test_category_create_returns_the_id_and_count(client: Client, staff_login: Any) -> None:
    """A create response must be addressable without a follow-up list call."""
    staff_login(client, Role.Code.OWNER)

    response = client.post(
        CATEGORIES_URL,
        {"name": "Craft beer", "display_order": 4},
        content_type="application/json",
    )

    assert response.status_code == 201, response.content
    payload = response.json()
    assert payload["id"]
    assert payload["name"] == "Craft beer"
    assert payload["product_count"] == 0
    assert Category.objects.filter(pk=payload["id"]).exists()


def test_category_update_returns_the_new_values_and_count(client: Client, staff_login: Any) -> None:
    """PATCH answers with the stored row, not an echo of only sent fields."""
    staff_login(client, Role.Code.OWNER)
    category = Category.objects.create(name="Spirits")
    Product.objects.create(
        category=category,
        name="Gin",
        sku="SPR-GIN-001",
        is_stock_tracked=False,
    )

    response = client.patch(
        f"{CATEGORIES_URL}{category.pk}/",
        {"name": "Local spirits"},
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    payload = response.json()
    assert payload["name"] == "Local spirits"
    assert payload["product_count"] == 1
    assert payload["id"] == category.pk


def test_product_update_returns_the_full_product(client: Client, staff_login: Any) -> None:
    """The edit screen gets the new name and the fields it did not send."""
    staff_login(client, Role.Code.OWNER)
    category = Category.objects.create(name="Soft drinks")
    product = Product.objects.create(
        category=category,
        name="Soda",
        sku="SOF-SODA-001",
        is_stock_tracked=False,
    )

    response = client.patch(
        f"{PRODUCTS_URL}{product.pk}/",
        {"name": "Soda water"},
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    payload = response.json()
    assert payload["name"] == "Soda water"
    assert payload["id"] == product.pk
    assert payload["category"]["name"] == "Soft drinks"
    assert "current_price" in payload
    assert "current_stock" in payload


def test_product_list_exposes_category_counts(client: Client, staff_login: Any) -> None:
    """The count is a field the category screen actually reads."""
    staff_login(client, Role.Code.CASHIER)
    category = Category.objects.create(name="Water")
    Product.objects.create(
        category=category,
        name="Still water",
        sku="WAT-STILL-001",
        is_stock_tracked=False,
    )

    response = client.get(CATEGORIES_URL)

    assert response.status_code == 200, response.content
    row = response.json()["results"][0]
    assert row["product_count"] == 1


def test_malformed_product_filters_are_400s(client: Client, staff_login: Any) -> None:
    """A non-numeric category id must not become an uncaught ValueError."""
    staff_login(client, Role.Code.CASHIER)

    assert client.get(PRODUCTS_URL, {"category": "not-an-id"}).status_code == 400
    assert client.get(PRODUCTS_URL, {"active": "perhaps"}).status_code == 400
