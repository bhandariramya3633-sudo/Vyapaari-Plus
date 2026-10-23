from decimal import Decimal

import pytest

from app.core.exceptions import ValidationError
from app.modules.gst.engine import calculate_line, taxable_value
from app.modules.gst.models import LineItem
from app.modules.gst.place_of_supply import Regime

FIELDS = ("taxable_value", "cgst", "sgst", "igst", "cess", "line_total")


def make_item(**overrides):
    data = {
        "description": "Sample item",
        "hsn_sac": "1006",
        "quantity": "1",
        "unit_price": "100.00",
        "gst_rate": "18",
    }
    data.update(overrides)
    return LineItem(**data)


CASES = [
    pytest.param(
        {"quantity": "2"}, "INTER",
        ("200.00", "0.00", "0.00", "36.00", "0.00", "236.00"),
        id="inter-18",
    ),
    pytest.param(
        {"quantity": "2"}, "INTRA",
        ("200.00", "18.00", "18.00", "0.00", "0.00", "236.00"),
        id="intra-18",
    ),
    pytest.param(
        {"unit_price": "10.10", "gst_rate": "5"}, "INTRA",
        ("10.10", "0.25", "0.25", "0.00", "0.00", "10.60"),
        id="intra-5-odd-paise",
    ),
    pytest.param(
        {"unit_price": "10.10", "gst_rate": "5"}, "INTER",
        ("10.10", "0.00", "0.00", "0.51", "0.00", "10.61"),
        id="inter-5-odd-paise",
    ),
    pytest.param(
        {"unit_price": "33.33", "gst_rate": "12"}, "INTRA",
        ("33.33", "2.00", "2.00", "0.00", "0.00", "37.33"),
        id="intra-12-rounds-up",
    ),
    pytest.param(
        {"unit_price": "33.33", "gst_rate": "12"}, "INTER",
        ("33.33", "0.00", "0.00", "4.00", "0.00", "37.33"),
        id="inter-12-rounds-up",
    ),
    pytest.param(
        {"quantity": "3", "unit_price": "99.99", "discount": "10"}, "INTER",
        ("289.97", "0.00", "0.00", "52.19", "0.00", "342.16"),
        id="discount",
    ),
    pytest.param(
        {"quantity": "2.5", "unit_price": "99.99", "gst_rate": "0"}, "INTRA",
        ("249.98", "0.00", "0.00", "0.00", "0.00", "249.98"),
        id="fractional-quantity-rounds",
    ),
    pytest.param(
        {"gst_rate": "0"}, "INTER",
        ("100.00", "0.00", "0.00", "0.00", "0.00", "100.00"),
        id="zero-rate",
    ),
    pytest.param(
        {"unit_price": "1000", "gst_rate": "28", "cess_rate": "12"}, "INTER",
        ("1000.00", "0.00", "0.00", "280.00", "120.00", "1400.00"),
        id="cess-ad-valorem",
    ),
    pytest.param(
        {"quantity": "10", "unit_price": "50", "cess_per_unit": "1.5"}, "INTER",
        ("500.00", "0.00", "0.00", "90.00", "15.00", "605.00"),
        id="cess-specific",
    ),
    pytest.param(
        {"unit_price": "1000", "gst_rate": "28", "cess_rate": "5", "cess_per_unit": "2"},
        "INTRA",
        ("1000.00", "140.00", "140.00", "0.00", "52.00", "1332.00"),
        id="cess-both-intra",
    ),
]


@pytest.mark.parametrize("overrides, regime, expected", CASES)
def test_calculate_line(overrides, regime, expected):
    line = calculate_line(make_item(**overrides), regime)
    for name, want in zip(FIELDS, expected):
        assert getattr(line, name) == Decimal(want), name


def test_every_amount_has_two_decimals():
    line = calculate_line(make_item(), "INTRA")
    for name in FIELDS:
        assert getattr(line, name).as_tuple().exponent == -2, name


def test_taxable_value_rounds_to_paise():
    result = taxable_value(make_item(quantity="2.5", unit_price="99.99"))
    assert result == Decimal("249.98")
    assert result.as_tuple().exponent == -2


def test_tax_total_adds_all_taxes():
    line = calculate_line(
        make_item(unit_price="1000", gst_rate="28", cess_rate="5", cess_per_unit="2"),
        "INTRA",
    )
    assert line.tax_total == Decimal("332.00")
    assert line.line_total == line.taxable_value + line.tax_total


def test_regime_enum_and_string_give_the_same_result():
    item = make_item()
    assert calculate_line(item, Regime.INTER) == calculate_line(item, "INTER")


def test_item_rate_wins_over_fallback_rate():
    line = calculate_line(make_item(gst_rate="5"), "INTER", fallback_rate="18")
    assert line.igst == Decimal("5.00")


@pytest.mark.parametrize("fallback", ["18", Decimal("18"), 18])
def test_fallback_rate_is_used_when_item_has_no_rate(fallback):
    line = calculate_line(make_item(gst_rate=None), "INTER", fallback_rate=fallback)
    assert line.igst == Decimal("18.00")


def test_missing_rate_is_an_error():
    with pytest.raises(ValidationError, match="gst_rate is missing"):
        calculate_line(make_item(gst_rate=None), "INTER")


def test_fallback_rate_out_of_range_is_an_error():
    with pytest.raises(ValidationError, match="between 0 and 100"):
        calculate_line(make_item(gst_rate=None), "INTER", fallback_rate="101")


def test_fallback_rate_float_is_rejected():
    with pytest.raises(ValidationError, match="fallback_rate"):
        calculate_line(make_item(gst_rate=None), "INTER", fallback_rate=18.0)


def test_invalid_regime_is_an_error():
    with pytest.raises(ValidationError, match="regime must be INTRA or INTER"):
        calculate_line(make_item(), "BOGUS")
