"""Shared fixtures for the Bono accountability tests.

The fixtures build real catalogue, stock and staff rows instead of mocking
services: the point of the Bono suite is that custody, stock and reports agree
with the ledgers that already exist, which a mock would hide.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.bono.services import add_pairings, create_bono_type
from apps.core.business_time import business_date, business_day_bounds, now_utc
from apps.core.money import CURRENCY
from apps.inventory.services import ReceiptLineInput, receive_stock
from apps.products.models import Category, Product, ProductPrice
from apps.users.models import EmployeeProfile

PRICE = Decimal("25.00")


@pytest.fixture
def today() -> Any:
    """The current business-local date, which every operational test uses."""
    return business_date(now_utc())


@pytest.fixture
def yesterday(today: Any) -> Any:
    return today - timedelta(days=1)


@pytest.fixture
def category() -> Category:
    return Category.objects.create(name="Bono beverages", display_order=1)


@pytest.fixture
def make_product(category: Category) -> Callable[..., Product]:
    """Create a priced bottle product.

    ``price=None`` deliberately leaves the product unpriced, for the validation
    test that a Bono cannot promise a price the catalogue does not have.
    """

    def _make(
        *,
        name: str = "Bono Beer",
        sku: str = "BONO-BEER-001",
        price: Decimal | None = PRICE,
        unit: str = "bottle",
        quantity_mode: str = "WHOLE",
        is_stock_tracked: bool = True,
        is_active: bool = True,
    ) -> Product:
        product = Product.objects.create(
            category=category,
            name=name,
            sku=sku,
            unit=unit,
            quantity_mode=quantity_mode,
            is_stock_tracked=is_stock_tracked,
            is_active=is_active,
        )
        if price is not None:
            ProductPrice.objects.create(
                product=product,
                unit_price=price,
                currency=CURRENCY,
                effective_from=now_utc() - timedelta(seconds=5),
            )
        return product

    return _make


@pytest.fixture
def product(make_product: Callable[..., Product]) -> Product:
    return make_product()


@pytest.fixture
def second_product(make_product: Callable[..., Product]) -> Product:
    return make_product(name="Bono Lager", sku="BONO-LAGER-001")


@pytest.fixture
def receive(make_product: Callable[..., Product]) -> Callable[..., Any]:
    """Receive stock for a product at an arbitrary instant.

    Returning the receipt makes a test able to prove opening stock by receiving
    yesterday and selling today, rather than asserting a formula against itself.
    """

    def _receive(
        product: Product,
        quantity: Decimal = Decimal("40"),
        *,
        at: Any = None,
        unit_cost: Decimal = Decimal("18.00"),
    ) -> Any:
        return receive_stock(
            supplier_name="Bono Test Supplier",
            lines=[
                ReceiptLineInput(
                    product=product,
                    quantity=quantity,
                    unit_cost=unit_cost,
                )
            ],
            received_at=at or now_utc(),
        )

    return _receive


@pytest.fixture
def stocked(product: Product, receive: Callable[..., Any]) -> Product:
    receive(product)
    return product


@pytest.fixture
def make_employee() -> Callable[..., EmployeeProfile]:
    def _make(
        full_name: str = "Abel Tesfaye",
        position: str = "Barman",
        *,
        archived: bool = False,
    ) -> EmployeeProfile:
        profile = EmployeeProfile.objects.create(
            full_name=full_name,
            position=position,
            start_date=business_date(now_utc()) - timedelta(days=90),
        )
        if archived:
            profile.archive()
            profile.save(update_fields=["is_archived", "archived_at"])
        return profile

    return _make


@pytest.fixture
def employee(make_employee: Callable[..., EmployeeProfile]) -> EmployeeProfile:
    return make_employee()


@pytest.fixture
def second_employee(make_employee: Callable[..., EmployeeProfile]) -> EmployeeProfile:
    return make_employee("Hana Girma", "Waitress")


@pytest.fixture
def make_bono_type() -> Callable[..., Any]:
    def _make(
        *,
        name: str = "House Bono",
        price: Decimal = PRICE,
        color: str = "#C2410C",
    ) -> Any:
        return create_bono_type(
            name=name,
            color=color,
            selling_price=price,
            currency=CURRENCY,
        )

    return _make


@pytest.fixture
def bono_type(make_bono_type: Callable[..., Any]) -> Any:
    return make_bono_type()


@pytest.fixture
def paired(bono_type: Any, product: Product) -> Any:
    add_pairings(bono_type=bono_type, products=[product])
    return bono_type


@pytest.fixture
def day_bounds() -> Callable[[Any], tuple[Any, Any]]:
    return business_day_bounds
