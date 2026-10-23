import pytest

from app.core.exceptions import ValidationError
from app.modules.gst.states import (
    OTHER_COUNTRY,
    OTHER_TERRITORY,
    STATE_CODES,
    is_utgst_territory,
    normalize_state_code,
    state_name,
)


@pytest.mark.parametrize(
    "raw, expected",
    [("07", "07"), ("7", "07"), (" 27 ", "27"), ("24", "24"), ("97", "97")],
)
def test_normalize_accepts_valid_codes(raw, expected):
    assert normalize_state_code(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "00", "99", "39", "100", 7, None])
def test_normalize_rejects_invalid_codes(raw):
    with pytest.raises(ValidationError):
        normalize_state_code(raw)


def test_normalize_names_the_field():
    with pytest.raises(ValidationError, match="place_of_supply"):
        normalize_state_code("99", "place_of_supply")


def test_all_codes_are_two_digit_strings():
    assert all(len(code) == 2 and code.isdigit() for code in STATE_CODES)


def test_special_codes_exist():
    assert OTHER_COUNTRY in STATE_CODES
    assert OTHER_TERRITORY in STATE_CODES


@pytest.mark.parametrize(
    "code, name", [("24", "Gujarat"), ("27", "Maharashtra"), ("07", "Delhi"), ("7", "Delhi")]
)
def test_state_name(code, name):
    assert state_name(code) == name


@pytest.mark.parametrize("code", ["04", "26", "31", "35", "38", "97"])
def test_utgst_territories(code):
    assert is_utgst_territory(code) is True


@pytest.mark.parametrize("code", ["01", "07", "24", "27", "34"])
def test_states_with_legislature_use_sgst(code):
    assert is_utgst_territory(code) is False
