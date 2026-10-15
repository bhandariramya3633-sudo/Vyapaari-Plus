from decimal import Decimal

import pytest

from app.modules.purchasing.grn import (
    GRNLine,
    match_purchase_order_line,
)


def test_grn_detects_quantity_shortage():
    line = GRNLine(
        product_id="PRODUCT-1",
        ordered_quantity=10,
        received_quantity=8,
        ordered_unit_price=Decimal("50.00"),
        invoiced_unit_price=Decimal("50.00"),
    )

    assert line.quantity_shortage == 2
    assert line.has_quantity_shortage is True


def test_grn_detects_price_variance():
    line = GRNLine(
        product_id="PRODUCT-1",
        ordered_quantity=10,
        received_quantity=10,
        ordered_unit_price=Decimal("50.00"),
        invoiced_unit_price=Decimal("55.00"),
    )

    assert line.price_variance == Decimal("5.00")
    assert line.has_price_variance is True


def test_three_way_match_success():
    result = match_purchase_order_line(
        product_id="PRODUCT-1",
        ordered_quantity=10,
        received_quantity=10,
        invoiced_quantity=10,
        ordered_unit_price=Decimal("50.00"),
        invoiced_unit_price=Decimal("50.00"),
    )

    assert result.is_matched is True
    assert result.flags == []


def test_three_way_match_flags_shortage():
    result = match_purchase_order_line(
        product_id="PRODUCT-1",
        ordered_quantity=10,
        received_quantity=8,
        invoiced_quantity=8,
        ordered_unit_price=Decimal("50.00"),
        invoiced_unit_price=Decimal("50.00"),
    )

    assert result.is_matched is False
    assert "QUANTITY_SHORTAGE" in result.flags
    assert result.quantity_shortage == 2


def test_three_way_match_flags_price_difference():
    result = match_purchase_order_line(
        product_id="PRODUCT-1",
        ordered_quantity=10,
        received_quantity=10,
        invoiced_quantity=10,
        ordered_unit_price=Decimal("50.00"),
        invoiced_unit_price=Decimal("55.00"),
    )

    assert result.is_matched is False
    assert "PRICE_VARIANCE" in result.flags
    assert result.price_variance == Decimal("5.00")


def test_three_way_match_rejects_negative_quantity():
    with pytest.raises(ValueError, match="Quantities cannot be negative"):
        match_purchase_order_line(
            product_id="PRODUCT-1",
            ordered_quantity=10,
            received_quantity=-1,
            invoiced_quantity=10,
            ordered_unit_price=Decimal("50.00"),
            invoiced_unit_price=Decimal("50.00"),
        )