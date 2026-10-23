"""Whole-invoice tax: line taxes, totals, round-off and reverse charge (RCM).

- Regime comes from the place of supply (SEZ and export are always INTER).
- Line tax comes from calculate_line. A missing item rate is filled from
  rate_lookup (for example the HSN/SAC service) when one is given.
- invoice_total is the tax-inclusive total rounded to the nearest rupee, and
  round_off is the adjustment that was added.
- Under RCM the tax is shown but not collected by the supplier, so
  payable_to_supplier covers the taxable value only (rounded the same way).
"""

from collections.abc import Callable
from decimal import Decimal

from app.modules.gst.engine import calculate_line
from app.modules.gst.models import Invoice, TaxBreakup
from app.modules.gst.money import round_off
from app.modules.gst.place_of_supply import resolve_regime

ZERO = Decimal("0.00")

RateLookup = Callable[[str], Decimal]


def calculate_invoice(
    invoice: Invoice, rate_lookup: RateLookup | None = None
) -> TaxBreakup:
    regime = resolve_regime(
        invoice.supplier.state_code,
        invoice.place_of_supply,
        invoice.is_sez_or_export,
    )
    lines = []
    for item in invoice.items:
        fallback = None
        if item.gst_rate is None and rate_lookup is not None:
            fallback = rate_lookup(item.hsn_sac)
        lines.append(calculate_line(item, regime, fallback))

    taxable_total = sum((line.taxable_value for line in lines), ZERO)
    cgst_total = sum((line.cgst for line in lines), ZERO)
    sgst_total = sum((line.sgst for line in lines), ZERO)
    igst_total = sum((line.igst for line in lines), ZERO)
    cess_total = sum((line.cess for line in lines), ZERO)

    gross = taxable_total + cgst_total + sgst_total + igst_total + cess_total
    invoice_total, adjustment = round_off(gross)
    if invoice.reverse_charge:
        payable_to_supplier = round_off(taxable_total)[0]
    else:
        payable_to_supplier = invoice_total

    return TaxBreakup(
        regime=regime,
        lines=tuple(lines),
        taxable_total=taxable_total,
        cgst_total=cgst_total,
        sgst_total=sgst_total,
        igst_total=igst_total,
        cess_total=cess_total,
        round_off=adjustment,
        invoice_total=invoice_total,
        rcm_applied=invoice.reverse_charge,
        payable_to_supplier=payable_to_supplier,
    )
