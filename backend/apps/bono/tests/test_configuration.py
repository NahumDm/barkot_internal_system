"""Configuration, equal-price pairing and price-review rules for Bono."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.audit.models import AuditLog
from apps.bono.models import BonoIncidentKind, BonoIssueKind, BonoProductPairing, BonoType
from apps.bono.services import (
    add_pairings,
    config_history,
    create_incident,
    create_issue,
    create_report,
    remove_pairing,
    resolve_pairing_review,
    update_bono_type,
)
from apps.core.business_time import now_utc
from apps.core.exceptions import (
    BonoActivityInProgress,
    BonoPriceMismatch,
    BonoReviewPending,
    BonoTypeConflict,
)
from apps.core.money import CURRENCY
from apps.products.services import set_product_price

pytestmark = pytest.mark.django_db


def test_a_bono_type_keeps_a_stable_code_when_its_label_and_colour_change(
    bono_type: Any,
) -> None:
    """The UUID is identity; name and colour are presentation."""
    code = bono_type.code

    updated = update_bono_type(
        bono_type=bono_type,
        changes={"name": "Premium Bono", "color": "#2563EB"},
        change_reason="New bar menu",
    )

    assert updated.pk == bono_type.pk
    assert updated.code == code
    assert updated.name == "Premium Bono"
    assert updated.color == "#2563EB"
    assert AuditLog.objects.filter(
        object_type="bono.BonoType", object_id=str(bono_type.pk)
    ).exists()


def test_duplicate_bono_names_are_refused_case_insensitively(
    make_bono_type: Any,
) -> None:
    make_bono_type(name="House Bono")

    with pytest.raises(BonoTypeConflict):
        make_bono_type(name="house bono")


@pytest.mark.parametrize("colour", ["red", "#12345", "#GGGGGG", "#1234567"])
def test_a_bono_colour_must_be_a_six_digit_hex_value(make_bono_type: Any, colour: str) -> None:
    with pytest.raises(BonoTypeConflict):
        make_bono_type(color=colour)


def test_equally_priced_bottle_products_can_share_one_bono_type(
    bono_type: Any,
    product: Any,
    second_product: Any,
) -> None:
    pairings = add_pairings(bono_type=bono_type, products=[product, second_product])

    assert len(pairings) == 2
    assert all(pairing.is_active for pairing in pairings)
    assert all(pairing.price_at_pairing == Decimal("25.00") for pairing in pairings)
    assert all(pairing.currency == CURRENCY for pairing in pairings)
    assert BonoProductPairing.objects.filter(bono_type=bono_type, is_active=True).count() == 2


def test_a_product_with_a_different_selling_price_cannot_join_the_bono_type(
    bono_type: Any,
    make_product: Any,
) -> None:
    expensive = make_product(name="Premium Beer", sku="BONO-PREM-001", price=Decimal("30.00"))

    with pytest.raises(BonoPriceMismatch):
        add_pairings(bono_type=bono_type, products=[expensive])

    assert not BonoProductPairing.objects.filter(product=expensive).exists()


def test_unpriced_untracked_non_bottle_and_inactive_products_are_refused(
    bono_type: Any,
    make_product: Any,
) -> None:
    unpriced = make_product(name="Unpriced", sku="BONO-NOPRICE", price=None)
    untracked = make_product(name="Untracked", sku="BONO-UNTRACKED", is_stock_tracked=False)
    crate = make_product(name="Crate", sku="BONO-CRATE", unit="crate")
    inactive = make_product(name="Inactive", sku="BONO-INACTIVE", is_active=False)

    with pytest.raises(BonoPriceMismatch):
        add_pairings(bono_type=bono_type, products=[unpriced])
    with pytest.raises(BonoTypeConflict):
        add_pairings(bono_type=bono_type, products=[untracked])
    with pytest.raises(BonoTypeConflict):
        add_pairings(bono_type=bono_type, products=[crate])
    with pytest.raises(BonoTypeConflict):
        add_pairings(bono_type=bono_type, products=[inactive])


def test_a_product_can_only_be_paired_with_one_active_bono_type(
    paired: Any,
    product: Any,
    make_bono_type: Any,
) -> None:
    other_type = make_bono_type(name="Other Bono")

    with pytest.raises(BonoTypeConflict):
        add_pairings(bono_type=other_type, products=[product])


def test_retiring_a_pairing_keeps_the_row_and_its_history(
    paired: Any,
    product: Any,
) -> None:
    pairing = paired.pairings.get(product=product)

    retired = remove_pairing(pairing=pairing, reason="Product left the menu")

    assert retired.is_active is False
    assert retired.unpaired_at is not None
    assert retired.reviewed_at is not None
    assert BonoProductPairing.objects.filter(pk=pairing.pk).exists()
    with pytest.raises(BonoTypeConflict):
        remove_pairing(pairing=retired, reason="Again")


def test_retiring_a_type_retires_its_active_pairings_without_deleting_them(
    paired: Any,
    product: Any,
) -> None:
    retired_type = update_bono_type(
        bono_type=paired,
        changes={"is_active": False},
        change_reason="Bono withdrawn",
    )

    pairing = BonoProductPairing.objects.get(product=product)
    assert retired_type.is_active is False
    assert pairing.is_active is False
    assert pairing.unpaired_at is not None
    with pytest.raises(BonoTypeConflict):
        add_pairings(bono_type=retired_type, products=[product])


def test_a_price_change_opens_an_owner_review_and_blocks_new_issues(
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
) -> None:
    pairing = paired.pairings.get(product=product)

    set_product_price(
        product=product,
        unit_price=Decimal("30.00"),
        currency=CURRENCY,
    )

    pairing.refresh_from_db()
    assert pairing.review_required is True
    assert pairing.previous_price == Decimal("25.00")
    assert pairing.new_price == Decimal("30.00")
    assert pairing.flagged_at is not None

    with pytest.raises(BonoReviewPending):
        create_issue(
            operational_date=today,
            bono_type=paired,
            employee=employee,
            kind=BonoIssueKind.INITIAL,
            quantity=1,
        )

    retained = resolve_pairing_review(
        pairing=pairing,
        resolution="RETAIN",
        reason="The new menu price applies to both products",
    )
    assert isinstance(retained, BonoType)

    pairing.refresh_from_db()
    assert retained.selling_price == Decimal("30.00")
    assert pairing.review_required is False
    assert pairing.price_at_pairing == Decimal("30.00")
    issue = create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind=BonoIssueKind.INITIAL,
        quantity=1,
    )
    assert issue.bono_price_snapshot == Decimal("30.00")


def test_a_future_price_cannot_be_signed_off_early(
    paired: Any,
    product: Any,
    employee: Any,
    today: Any,
) -> None:
    pairing = paired.pairings.get(product=product)
    set_product_price(
        product=product,
        unit_price=Decimal("30.00"),
        currency=CURRENCY,
        effective_from=now_utc() + timedelta(days=1),
    )

    with pytest.raises(BonoReviewPending):
        resolve_pairing_review(
            pairing=pairing,
            resolution="RETAIN",
            reason="Too early",
        )

    # The old price is still the selling price, so a token issued today is not
    # yet blocked by a revision that has not taken effect.
    issue = create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind=BonoIssueKind.INITIAL,
        quantity=1,
    )
    assert issue.bono_price_snapshot == Decimal("25.00")


def test_configuration_edits_need_confirmation_while_a_day_is_open(
    paired: Any,
    employee: Any,
    today: Any,
) -> None:
    issue = create_issue(
        operational_date=today,
        bono_type=paired,
        employee=employee,
        kind=BonoIssueKind.INITIAL,
        quantity=2,
    )

    with pytest.raises(BonoActivityInProgress):
        update_bono_type(
            bono_type=paired,
            changes={"color": "#2563EB"},
        )
    with pytest.raises(BonoActivityInProgress):
        update_bono_type(
            bono_type=paired,
            changes={"color": "#2563EB"},
            confirm_in_progress=True,
        )

    updated = update_bono_type(
        bono_type=paired,
        changes={"color": "#2563EB"},
        confirm_in_progress=True,
        change_reason="Owner approved the new menu colour",
    )

    issue.refresh_from_db()
    assert updated.color == "#2563EB"
    # The already-issued row keeps the colour it was issued under.
    assert issue.bono_color_snapshot == "#C2410C"

    report = create_report(operational_date=today)
    line = report.bono_lines.get()
    assert line.bono_color_snapshot == "#C2410C"


def test_the_configuration_history_is_owner_readable_and_ordered(
    bono_type: Any,
) -> None:
    update_bono_type(
        bono_type=bono_type,
        changes={"name": "Renamed Bono"},
        change_reason="Menu update",
    )

    history = config_history(bono_type)

    assert history
    assert history[0].object_type == "bono.BonoType"
    assert history[0].object_id == str(bono_type.pk)
    assert any("Renamed Bono" in row.summary for row in history)


def test_a_broken_bottle_cannot_be_recorded_for_an_unpaired_product(
    bono_type: Any,
    make_product: Any,
    today: Any,
) -> None:
    unpaired = make_product(name="Unpaired", sku="BONO-UNPAIRED")

    with pytest.raises(BonoTypeConflict):
        create_incident(
            operational_date=today,
            kind=BonoIncidentKind.BROKEN_BOTTLE,
            product=unpaired,
            quantity=1,
            reason="Dropped",
        )
