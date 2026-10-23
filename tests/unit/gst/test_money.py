from decimal import Decimal

import pytest

from app.core.exceptions import ValidationError
from app.modules.gst.money import (
    percent_of,
    round_off,
    round_paise,
    round_rupee,
    to_decimal,
)


@pytest.mark.parametrize(
    "value, expected",
    [(5, Decimal("5")), ("12.50", Decimal("12.50")), (Decimal("3.1"), Decimal("3.1"))],
)
def test_to_decimal_accepts_int_str_decimal(value, expected):
    assert to_decimal(value) == expected


@pytest.mark.parametrize("value", [1.5, True, "abc", None, "NaN", "Infinity"])
def test_to_decimal_rejects_bad_values(value):
    with pytest.raises(ValidationError) as exc:
        to_decimal(value, "unit_price")
    assert exc.value.code == "VALIDATION_ERROR"


def test_to_decimal_names_the_field():
    with pytest.raises(ValidationError, match="unit_price"):
        to_decimal(1.5, "unit_price")


@pytest.mark.parametrize(
    "value, expected",
    [
        ("1.005", "1.01"),
        ("1.004", "1.00"),
        ("2.675", "2.68"),  # float rounding gives 2.67, Decimal half-up gives 2.68
        ("-1.005", "-1.01"),
        ("0", "0.00"),
    ],
)
def test_round_paise_is_half_up(value, expected):
    result = round_paise(Decimal(value))
    assert result == Decimal(expected)
    assert result.as_tuple().exponent == -2


@pytest.mark.parametrize(
    "value, expected",
    [("100.50", "101"), ("100.49", "100"), ("100.51", "101"), ("0.49", "0")],
)
def test_round_rupee_is_half_up(value, expected):
    result = round_rupee(Decimal(value))
    assert result == Decimal(expected)
    assert result.as_tuple().exponent == 0


@pytest.mark.parametrize(
    "base, rate, expected",
    [
        ("100.00", "18", "18.00"),
        ("99.99", "18", "18.00"),
        ("0.25", "5", "0.01"),
        ("10.50", "5", "0.53"),
        ("1000", "2.5", "25.00"),
    ],
)
def test_percent_of_rounds_to_paise(base, rate, expected):
    assert percent_of(Decimal(base), Decimal(rate)) == Decimal(expected)


@pytest.mark.parametrize(
    "total, rounded, adjustment",
    [
        ("1180.40", "1180.00", "-0.40"),
        ("1180.50", "1181.00", "0.50"),
        ("1180.60", "1181.00", "0.40"),
        ("1180.00", "1180.00", "0.00"),
    ],
)
def test_round_off_returns_total_and_adjustment(total, rounded, adjustment):
    got_total, got_adjustment = round_off(Decimal(total))
    assert got_total == Decimal(rounded)
    assert got_adjustment == Decimal(adjustment)
    assert got_total.as_tuple().exponent == -2
    assert got_adjustment.as_tuple().exponent == -2
