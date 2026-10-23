from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import ValidationError
from app.modules.gst.invoice_calc import calculate_invoice
from app.modules.gst.models import Invoice, LineItem, Party
from app.modules.gst.place_of_supply import Regime

# Fake, format-valid sample GSTINs (checksum is not validated).
SUPPLIER_GSTIN = "24AAACC1206D1ZM"
BUYER_GSTIN = "27AAACB1234F1Z5"


def make_party(**overrides):
    data = {"name": "Sample Traders", "state_code": "24", "gstin": SUPPLIER_GSTIN}
    data.update(overrides)
    return Party(**data)


def make_buyer(**overrides):
    data = {"name": "Sample Buyer", "state_code": "27", "gstin": BUYER_GSTIN}
    data.update(overrides)
    return Party(**data)


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


def make_invoice(**overrides):
    data = {
        "doc_no": "INV-001",
        "doc_date": date(2026, 10, 14),
        "supplier": make_party(),
        "buyer": make_buyer(),
        "place_of_supply": "24",
        "supply_type": "B2B",
        "items": [make_item(quantity="2")],
    }
    data.update(overrides)
    return Invoice(**data)


def test_intra_state_invoice_splits_into_cgst_and_sgst():
    breakup = calculate_invoice(make_invoice())
    assert breakup.regime is Regime.INTRA
    assert breakup.taxable_total == Decimal("200.00")
    assert breakup.cgst_total == Decimal("18.00")
    assert breakup.sgst_total == Decimal("18.00")
    assert breakup.igst_total == Decimal("0.00")
    assert breakup.cess_total == Decimal("0.00")
    assert breakup.round_off == Decimal("0.00")
    assert breakup.invoice_total == Decimal("236.00")
    assert breakup.payable_to_supplier == Decimal("236.00")
    assert breakup.rcm_applied is False


def test_inter_state_invoice_uses_igst():
    breakup = calculate_invoice(make_invoice(place_of_supply="27"))
    assert breakup.regime is Regime.INTER
    assert breakup.cgst_total == Decimal("0.00")
    assert breakup.sgst_total == Decimal("0.00")
    assert breakup.igst_total == Decimal("36.00")
    assert breakup.invoice_total == Decimal("236.00")


def test_place_of_supply_decides_not_the_buyer_address():
    # Buyer is registered in 27 but the place of supply is 24 (same as supplier).
    breakup = calculate_invoice(make_invoice(place_of_supply="24"))
    assert breakup.regime is Regime.INTRA


def test_sez_or_export_is_igst_even_in_the_same_state():
    breakup = calculate_invoice(make_invoice(is_sez_or_export=True))
    assert breakup.regime is Regime.INTER
    assert breakup.igst_total == Decimal("36.00")
    assert breakup.cgst_total == Decimal("0.00")


def test_multi_line_totals_and_round_up():
    invoice = make_invoice(
        items=[
            make_item(unit_price="10.10", gst_rate="5"),
            make_item(unit_price="33.33", gst_rate="12"),
        ]
    )
    breakup = calculate_invoice(invoice)
    assert len(breakup.lines) == 2
    assert breakup.taxable_total == Decimal("43.43")
    assert breakup.cgst_total == Decimal("2.25")
    assert breakup.sgst_total == Decimal("2.25")
    assert breakup.igst_total == Decimal("0.00")
    assert breakup.round_off == Decimal("0.07")
    assert breakup.invoice_total == Decimal("48.00")


def test_round_off_can_be_negative():
    breakup = calculate_invoice(
        make_invoice(items=[make_item(unit_price="100.40", gst_rate="0")])
    )
    assert breakup.invoice_total == Decimal("100.00")
    assert breakup.round_off == Decimal("-0.40")


def test_cess_is_part_of_the_total():
    breakup = calculate_invoice(
        make_invoice(
            place_of_supply="27",
            items=[make_item(unit_price="1000", gst_rate="28", cess_rate="12")],
        )
    )
    assert breakup.igst_total == Decimal("280.00")
    assert breakup.cess_total == Decimal("120.00")
    assert breakup.invoice_total == Decimal("1400.00")


def test_reverse_charge_shows_tax_but_supplier_is_paid_taxable_value_only():
    invoice = make_invoice(
        place_of_supply="27",
        reverse_charge=True,
        items=[make_item(unit_price="100.40", gst_rate="18")],
    )
    breakup = calculate_invoice(invoice)
    assert breakup.rcm_applied is True
    assert breakup.igst_total == Decimal("18.07")
    assert breakup.round_off == Decimal("-0.47")
    assert breakup.invoice_total == Decimal("118.00")
    assert breakup.payable_to_supplier == Decimal("100.00")


def test_b2c_invoice_uses_the_same_maths():
    b2b = calculate_invoice(make_invoice())
    b2c = calculate_invoice(
        make_invoice(buyer=make_buyer(gstin=None), supply_type="B2C")
    )
    assert b2c.invoice_total == b2b.invoice_total
    assert b2c.cgst_total == b2b.cgst_total


def test_all_totals_have_two_decimals():
    breakup = calculate_invoice(make_invoice())
    for value in (
        breakup.taxable_total,
        breakup.cgst_total,
        breakup.sgst_total,
        breakup.igst_total,
        breakup.cess_total,
        breakup.round_off,
        breakup.invoice_total,
        breakup.payable_to_supplier,
    ):
        assert value.as_tuple().exponent == -2


def test_rate_lookup_fills_in_missing_item_rates():
    seen = []

    def lookup(code):
        seen.append(code)
        return Decimal("18")

    breakup = calculate_invoice(
        make_invoice(items=[make_item(gst_rate=None)]), lookup
    )
    assert seen == ["1006"]
    assert breakup.cgst_total == Decimal("9.00")


def test_rate_lookup_is_not_used_when_the_item_has_a_rate():
    def lookup(code):
        raise AssertionError("lookup should not be called")

    breakup = calculate_invoice(make_invoice(), lookup)
    assert breakup.invoice_total == Decimal("236.00")


def test_missing_rate_without_lookup_is_an_error():
    with pytest.raises(ValidationError, match="gst_rate is missing"):
        calculate_invoice(make_invoice(items=[make_item(gst_rate=None)]))
