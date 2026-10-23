"""GST calculation engine: per-line CGST/SGST/IGST and cess.

Rules (all amounts Decimal, rounded to paise, half-up):
- taxable = quantity x unit_price - discount
- INTRA: CGST and SGST are each rate/2 of taxable, rounded separately, so an
  odd-paise total can differ by one paisa from the INTER (IGST) figure.
- INTER (also SEZ and export): IGST = rate of taxable.
- Cess = taxable x cess_rate% + cess_per_unit x quantity, in both regimes.
- In union territories without a legislature the SGST figure is UTGST.
"""

from decimal import Decimal

from app.core.exceptions import ValidationError
from app.modules.gst.models import LineItem, LineTax
from app.modules.gst.money import HUNDRED, percent_of, round_paise, to_decimal
from app.modules.gst.place_of_supply import Regime

ZERO = Decimal("0.00")
TWO = Decimal("2")


def taxable_value(item: LineItem) -> Decimal:
    """Value on which GST is charged, after discount, in paise."""
    return round_paise(item.quantity * item.unit_price - item.discount)


def _resolve_rate(item: LineItem, fallback_rate) -> Decimal:
    if item.gst_rate is not None:
        rate = item.gst_rate
    elif fallback_rate is not None:
        rate = to_decimal(fallback_rate, "fallback_rate")
    else:
        raise ValidationError(
            "gst_rate is missing: set it on the item or resolve it from HSN/SAC"
        )
    if not Decimal("0") <= rate <= HUNDRED:
        raise ValidationError("gst_rate must be between 0 and 100")
    return rate


def calculate_line(item: LineItem, regime, fallback_rate=None) -> LineTax:
    """Tax for one line. The item's own gst_rate wins over fallback_rate."""
    try:
        regime = Regime(regime)
    except ValueError:
        raise ValidationError(f"regime must be INTRA or INTER: {regime!r}") from None
    rate = _resolve_rate(item, fallback_rate)
    taxable = taxable_value(item)

    cgst = sgst = igst = ZERO
    if regime is Regime.INTRA:
        cgst = sgst = percent_of(taxable, rate / TWO)
    else:
        igst = percent_of(taxable, rate)

    cess = round_paise(
        taxable * item.cess_rate / HUNDRED + item.cess_per_unit * item.quantity
    )
    return LineTax(
        taxable_value=taxable,
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        cess=cess,
        line_total=taxable + cgst + sgst + igst + cess,
    )
