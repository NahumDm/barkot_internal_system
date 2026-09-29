"""Regression tests for the Phase 0B foundation.

Each test here corresponds to a defect the Phase 0A scaffolding suite could not
catch, because Phase 0A had no models and no database. They assert behaviour the
specification fixes (role grants, ledger directions on void, voided-row
visibility, DRF error envelopes) rather than internal structure, so they stay
meaningful if the implementation moves.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth.models import AnonymousUser, Permission

from apps.accounts.models import Role, User
from apps.core.business_time import business_date, now_utc
from apps.core.enums import MovementDirection, MovementKind, PaymentMethod
from apps.core.exceptions import InsufficientStock, exception_handler
from apps.inventory.models import StockMovement
from apps.inventory.services import (
    ReceiptLineInput,
    current_stock,
    open_stock_count,
    receive_stock,
)
from apps.products.models import Category, Product, ProductPrice
from apps.sales.services import SaleLineInput, complete_sale, void_sale

pytestmark = pytest.mark.django_db


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def category() -> Category:
    return Category.objects.create(name="Beer")


@pytest.fixture
def product(category: Category) -> Product:
    return Product.objects.create(
        category=category,
        name="Beko 330ml",
        sku="BEKO-330",
        is_stock_tracked=True,
    )


@pytest.fixture
def price(product: Product) -> ProductPrice:
    return ProductPrice.objects.create(
        product=product,
        unit_price=Decimal("60.00"),
        effective_from=now_utc(),
    )


@pytest.fixture
def owner() -> User:
    return User.objects.create_user(
        username="owner",
        password="pw",
        role=Role.objects.get(code=Role.Code.OWNER),
    )


def stock_in(product: Product, quantity: str, *, actor: User | None = None) -> None:
    """Put stock on the shelf so a sale can be drawn against it."""
    receive_stock(
        supplier_name="Test Supplier",
        lines=[
            ReceiptLineInput(
                product=product, quantity=Decimal(quantity), unit_cost=Decimal("40.00")
            )
        ],
        actor=actor,
    )


# ── 1. Voided rows are hidden by default, reachable via all_rows ─────────────


def test_objects_hides_voided_rows_all_rows_keeps_them(owner: User, category: Category):
    """`objects` must not surface a voided row, or a voided amount lands in a total.

    Both managers were previously identical, so `objects` returned voided rows too
    despite its own docstring promising otherwise.
    """
    from apps.finance.models import Expense, ExpenseCategory

    expense_category = ExpenseCategory.objects.create(name="Utilities")
    today = business_date(now_utc())
    kept = Expense.objects.create(
        category=expense_category,
        description="Water",
        amount=Decimal("100.00"),
        incurred_on=today,
        created_by=owner,
        updated_by=owner,
    )
    voided = Expense.objects.create(
        category=expense_category,
        description="Mistake",
        amount=Decimal("999.00"),
        incurred_on=today,
        created_by=owner,
        updated_by=owner,
    )
    voided.void(reason="entered twice", actor=owner)
    voided.save()

    assert list(Expense.objects.all()) == [kept]
    assert set(Expense.all_rows.values_list("pk", flat=True)) == {kept.pk, voided.pk}
    assert list(Expense.all_rows.voided()) == [voided]
    assert list(Expense.all_rows.active()) == [kept]

    # `objects.voided()` can never match, so it raises instead of lying.
    with pytest.raises(AttributeError, match="all_rows"):
        Expense.objects.voided()


def test_voided_row_is_not_reachable_from_default_manager(owner: User, category: Category):
    from apps.finance.models import Expense, ExpenseCategory

    expense_category = ExpenseCategory.objects.create(name="Utilities")
    expense = Expense.objects.create(
        category=expense_category,
        description="Water",
        amount=Decimal("100.00"),
        incurred_on=business_date(now_utc()),
        created_by=owner,
        updated_by=owner,
    )
    expense.void(reason="wrong supplier", actor=owner)
    expense.save()

    assert Expense.objects.filter(pk=expense.pk).exists() is False
    assert Expense.all_rows.filter(pk=expense.pk).exists() is True


# ── 2. Voiding a sale returns stock to the ledger ───────────────────────────


def test_void_sale_returns_stock_to_the_ledger(product: Product, price: ProductPrice, owner: User):
    """A void must add stock back, not subtract it a second time.

    The reversal used to be recorded with kind SALE, whose direction is pinned to
    OUT, so voiding a 5-bottle sale left stock at 0 instead of 5.
    """
    stock_in(product, "10.000", actor=owner)
    assert current_stock(product) == Decimal("10.000")

    sale = complete_sale(
        lines=[SaleLineInput(product=product, quantity=Decimal("4.000"))],
        payments=[(PaymentMethod.CASH, Decimal("240.00"))],
        actor=owner,
    )
    assert current_stock(product) == Decimal("6.000")

    void_sale(sale=sale, reason="customer returned the bottles", actor=owner)

    assert current_stock(product) == Decimal("10.000"), "void must restore the drawn stock"

    reversal = StockMovement.objects.get(kind=MovementKind.SALE_VOID)
    assert reversal.direction == MovementDirection.IN
    assert reversal.quantity == Decimal("4.000")


def test_void_sale_keeps_both_legs_in_the_ledger(
    product: Product, price: ProductPrice, owner: User
):
    """The ledger is append-only, so the original draw-down and the return both stay."""
    stock_in(product, "10.000", actor=owner)
    sale = complete_sale(
        lines=[SaleLineInput(product=product, quantity=Decimal("4.000"))],
        payments=[(PaymentMethod.CASH, Decimal("240.00"))],
        actor=owner,
    )
    void_sale(sale=sale, reason="customer returned the bottles", actor=owner)

    kinds = list(
        StockMovement.objects.filter(product=product)
        .exclude(kind=MovementKind.RECEIPT)
        .order_by("id")
        .values_list("kind", "direction")
    )
    assert kinds == [
        (MovementKind.SALE, MovementDirection.OUT),
        (MovementKind.SALE_VOID, MovementDirection.IN),
    ]


def test_sale_direction_is_still_pinned_out(product: Product, price: ProductPrice, owner: User):
    """A sale must never be able to add stock, whatever a caller passes."""
    stock_in(product, "5.000", actor=owner)
    complete_sale(
        lines=[SaleLineInput(product=product, quantity=Decimal("1.000"))],
        payments=[(PaymentMethod.CASH, Decimal("60.00"))],
        actor=owner,
    )
    drawn = StockMovement.objects.get(kind=MovementKind.SALE)
    assert drawn.direction == MovementDirection.OUT


def test_voided_sale_is_excluded_from_totals(product: Product, price: ProductPrice, owner: User):
    from apps.sales.services import sales_totals

    start = now_utc()
    stock_in(product, "10.000", actor=owner)
    sale = complete_sale(
        lines=[SaleLineInput(product=product, quantity=Decimal("2.000"))],
        payments=[(PaymentMethod.CASH, Decimal("120.00"))],
        actor=owner,
    )
    end = now_utc()

    assert sales_totals(start=start, end=end)[PaymentMethod.CASH] == Decimal("120.00")
    assert sales_totals(start=start, end=end)["TOTAL"] == Decimal("120.00")

    void_sale(sale=sale, reason="customer returned the bottles", actor=owner)

    # A voided sale contributes nothing, so the method drops out of the breakdown.
    assert sales_totals(start=start, end=end)["TOTAL"] == Decimal("0.00")
    assert PaymentMethod.CASH not in sales_totals(start=start, end=end)


# ── 3. Role permissions actually reach user.has_perm ───────────────────────


def test_role_permissions_are_granted_through_has_perm(owner: User):
    """`Role.permissions_granted` must be visible to `user.has_perm`.

    ModelBackend only reads user_permissions/groups, so before the role backend
    was added this was False for every seeded permission.
    """
    assert owner.has_perm("sales.create_sale") is True
    assert owner.has_perm("accounts.manage_roles") is True


def test_barman_is_denied_selling_and_is_granted_receiving():
    barman = User.objects.create_user(
        username="barman",
        password="pw",
        role=Role.objects.get(code=Role.Code.BARMAN),
    )
    assert barman.has_perm("inventory.receive_stock") is True
    assert barman.has_perm("sales.create_sale") is False
    assert barman.has_perm("accounts.manage_roles") is False


def test_cashier_cannot_approve_a_stock_count():
    cashier = User.objects.create_user(
        username="cashier",
        password="pw",
        role=Role.objects.get(code=Role.Code.CASHIER),
    )
    assert cashier.has_perm("sales.create_sale") is True
    assert cashier.has_perm("inventory.approve_adjustment") is False


def test_inactive_user_has_no_role_permissions(owner: User):
    owner.is_active = False
    owner.save()
    owner = User.objects.get(pk=owner.pk)
    assert owner.has_perm("sales.create_sale") is False


def test_anonymous_user_has_no_permissions():
    assert AnonymousUser().has_perm("sales.create_sale") is False


def test_direct_user_grant_is_additive_to_role(owner: User):
    """A direct grant widens access without stripping the role's own grants."""
    permission = Permission.objects.get(content_type__app_label="sales", codename="create_sale")
    assert owner.has_perm("sales.create_sale") is True

    barman_role = Role.objects.get(code=Role.Code.BARMAN)
    barman = User.objects.create_user(username="barman2", password="pw", role=barman_role)
    assert barman.has_perm("sales.create_sale") is False
    barman.user_permissions.add(permission)
    barman = User.objects.get(pk=barman.pk)
    assert barman.has_perm("sales.create_sale") is True
    # ...and the role grants survive.
    assert barman.has_perm("inventory.receive_stock") is True


def test_role_permissions_do_not_depend_on_group_membership(owner: User):
    assert owner.groups.count() == 0
    assert owner.has_perm("sales.view_sales") is True


# ── 4. Non-domain exceptions keep their DRF shapes ─────────────────────────


def test_domain_error_keeps_its_error_envelope():
    response = exception_handler(InsufficientStock("only 2 left"), {})
    assert response is not None
    # 409: the request was well-formed, it conflicts with current stock.
    assert response.status_code == 409
    assert response.data == {"error": {"code": "insufficient_stock", "message": "only 2 left"}}


def test_non_domain_exception_keeps_its_status_in_the_envelope():
    """DRF re-raises when a custom handler returns None, so delegation is required.

    Returning None here would turn every ValidationError / PermissionDenied into
    a 500 with a traceback. Delegation keeps DRF's chosen status; only the body
    is replaced, so the frontend sees one shape for every failure.
    """
    from rest_framework.exceptions import PermissionDenied, ValidationError

    denied = exception_handler(PermissionDenied("nope"), {})
    assert denied is not None
    assert denied.status_code == 403
    assert denied.data == {
        "error": {"code": "permission_denied", "message": "You do not have permission to do that."}
    }

    invalid = exception_handler(ValidationError("bad input"), {})
    assert invalid is not None
    assert invalid.status_code == 400
    assert invalid.data["error"]["code"] == "validation_error"
    assert invalid.data["error"]["details"] == {"non_field_errors": ["bad input"]}


def test_genuinely_unhandled_exception_is_returned_as_none():
    """A real bug must still surface as a 500, not be dressed up as a 4xx."""
    assert exception_handler(TypeError("a real bug"), {}) is None


# ── 5. A count can be opened and approved ───────────────────────────────────


def test_open_stock_count_writes_the_variance_placeholder(product: Product, owner: User):
    """`variance` is NOT NULL, so opening a count must supply it."""
    stock_in(product, "10.000", actor=owner)
    count = open_stock_count(lines=[product], actor=owner)

    item = count.items.get()
    assert item.expected_quantity == Decimal("10.000")
    assert item.variance == Decimal("0.000")
    assert item.counted_quantity == Decimal("0.000")


def test_approved_count_variance_adjusts_the_ledger(product: Product, owner: User):
    from apps.inventory.services import approve_stock_count, complete_stock_count

    stock_in(product, "10.000", actor=owner)
    count = open_stock_count(lines=[product], actor=owner)
    complete_stock_count(
        stock_count=count,
        counted_quantities={count.items.get().pk: Decimal("8.000")},
        actor=owner,
    )
    assert current_stock(product) == Decimal("10.000"), "completing a count must not move stock"

    approve_stock_count(stock_count=count, actor=owner)
    assert current_stock(product) == Decimal("8.000")
    variance_movement = StockMovement.objects.get(kind=MovementKind.COUNT_VARIANCE)
    assert variance_movement.direction == MovementDirection.OUT


def test_sale_beyond_stock_is_rejected(product: Product, price: ProductPrice, owner: User):
    stock_in(product, "1.000", actor=owner)
    with pytest.raises(InsufficientStock):
        complete_sale(
            lines=[SaleLineInput(product=product, quantity=Decimal("5.000"))],
            payments=[(PaymentMethod.CASH, Decimal("300.00"))],
            actor=owner,
        )
