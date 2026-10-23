"""Place-of-supply rule: decides intra-state (CGST+SGST) vs inter-state (IGST).

Pass the *place of supply*, not the buyer's address. They can differ.
"""

from enum import StrEnum

from app.modules.gst.states import normalize_state_code


class Regime(StrEnum):
    INTRA = "INTRA"
    INTER = "INTER"


def resolve_regime(
    supplier_state_code: str,
    place_of_supply: str,
    is_sez_or_export: bool = False,
) -> Regime:
    """INTER for SEZ/export or when states differ, otherwise INTRA."""
    supplier = normalize_state_code(supplier_state_code, "supplier_state_code")
    supply = normalize_state_code(place_of_supply, "place_of_supply")
    if is_sez_or_export:
        return Regime.INTER
    return Regime.INTRA if supplier == supply else Regime.INTER
