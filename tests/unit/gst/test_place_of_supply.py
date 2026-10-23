import pytest

from app.core.exceptions import ValidationError
from app.modules.gst.place_of_supply import Regime, resolve_regime


def test_same_state_is_intra():
    assert resolve_regime("24", "24") is Regime.INTRA


def test_different_state_is_inter():
    assert resolve_regime("24", "27") is Regime.INTER


def test_code_format_does_not_matter():
    assert resolve_regime("7", "07") is Regime.INTRA


@pytest.mark.parametrize("flag_state", ["24", "27"])
def test_sez_or_export_is_always_inter(flag_state):
    assert resolve_regime("24", flag_state, is_sez_or_export=True) is Regime.INTER


def test_other_country_is_inter():
    assert resolve_regime("24", "96") is Regime.INTER


def test_invalid_supplier_state_names_the_field():
    with pytest.raises(ValidationError, match="supplier_state_code"):
        resolve_regime("99", "24")


def test_invalid_place_of_supply_names_the_field():
    with pytest.raises(ValidationError, match="place_of_supply"):
        resolve_regime("24", "99")


def test_regime_values_are_plain_strings():
    assert Regime.INTRA == "INTRA"
    assert Regime.INTER == "INTER"
