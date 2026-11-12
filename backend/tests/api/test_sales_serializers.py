"""Focused serializer checks for sales API response shapes."""

from apps.sales.serializers import SaleListSerializer


def test_sale_list_serializer_includes_payment_status_display_field() -> None:
    """List payloads must expose the readable payment status label."""
    assert "payment_status_display" in SaleListSerializer.Meta.fields
