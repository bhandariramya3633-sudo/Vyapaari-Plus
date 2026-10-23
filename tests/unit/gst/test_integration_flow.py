"""Integration tests: the whole GST flow with the real HSN cache and real signing.

HSN rates come from the bundled SAMPLE data (8471 -> 18%, 1006 -> 5%, 998314 -> 18%).
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.modules.gst.credit_note import calculate_credit_note
from app.modules.gst.einvoice import build_einvoice_json
from app.modules.gst.eway import Transport, build_eway_bill_json, split_parts
from app.modules.gst.exceptions import SchemaValidationError, SigningError
from app.modules.gst.hsn import hsn_rate
from app.modules.gst.invoice_calc import calculate_invoice
from app.modules.gst.models import Invoice, LineItem, OriginalInvoiceRef, Party
from app.modules.gst.place_of_supply import Regime
from app.modules.gst.signing import (
    build_qr_payload,
    compute_demo_irn,
    generate_demo_keypair,
    sign_and_render_qr,
    verify,
)

# Fake, format-valid sample GSTINs (checksum is not validated).
SUPPLIER_GSTIN = "24AAACC1206D1ZM"
BUYER_GSTIN = "27AAACB1234F1Z5"
IRN_DATE = datetime(2026, 10, 14, 15, 30, 5)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def keys():
    return generate_demo_keypair()


@pytest.fixture(scope="module")
def other_keys():
    return generate_demo_keypair()


def make_supplier():
    return Party(
        name="Sample Traders", state_code="24", gstin=SUPPLIER_GSTIN,
        address="1 Sample Road", city="Sample City", pincode="390001",
    )


def make_buyer(**overrides):
    data = {
        "name": "Sample Buyer", "state_code": "27", "gstin": BUYER_GSTIN,
        "address": "5 Sample Lane", "city": "Mumbai", "pincode": "400001",
    }
    data.update(overrides)
    return Party(**data)


def computer(quantity="2"):
    return LineItem(
        description="Sample desktop computer", hsn_sac="8471",
        quantity=quantity, unit_price="30000.00",
    )


def rice():
    return LineItem(
        description="Sample basmati rice 5kg", hsn_sac="1006",
        quantity="100", unit_price="55.50",
    )


def make_invoice(**overrides):
    data = {
        "doc_no": "INV-001",
        "doc_date": date(2026, 10, 14),
        "supplier": make_supplier(),
        "buyer": make_buyer(),
        "place_of_supply": "27",
        "supply_type": "B2B",
        "items": [computer(), rice()],
    }
    data.update(overrides)
    return Invoice(**data)


def make_transport():
    return Transport(mode="ROAD", distance_km=450, vehicle_no="MH12AB1234")


def make_credit_note(**overrides):
    reference = OriginalInvoiceRef(doc_no="INV-001", doc_date=date(2026, 10, 14))
    data = {
        "doc_type": "CRN",
        "doc_no": "CN-001",
        "doc_date": date(2026, 10, 16),
        "original_invoice": reference,
        "items": [computer("1")],
    }
    data.update(overrides)
    return make_invoice(**data)


def tax(invoice):
    return calculate_invoice(invoice, hsn_rate)


def test_full_goods_invoice_flow(keys):
    invoice = make_invoice()
    breakup = tax(invoice)
    assert breakup.regime is Regime.INTER
    assert breakup.taxable_total == Decimal("65550.00")
    assert breakup.igst_total == Decimal("11077.50")
    assert breakup.cgst_total == Decimal("0.00")
    assert breakup.round_off == Decimal("0.50")
    assert breakup.invoice_total == Decimal("76628.00")

    einvoice = build_einvoice_json(invoice, breakup, rate_lookup=hsn_rate)
    assert [item["GstRt"] for item in einvoice["ItemList"]] == [18.0, 5.0]
    assert einvoice["ValDtls"]["IgstVal"] == 11077.5
    assert einvoice["ValDtls"]["TotInvVal"] == 76628.0
    items_total = sum(item["TotItemVal"] for item in einvoice["ItemList"])
    assert items_total + einvoice["ValDtls"]["RndOffAmt"] == pytest.approx(76628.0, abs=1e-9)

    irn = compute_demo_irn(SUPPLIER_GSTIN, invoice.doc_type, invoice.doc_no, invoice.doc_date)
    qr_payload = build_qr_payload(einvoice, irn, IRN_DATE)
    assert qr_payload["MainHsnCode"] == "8471"
    assert qr_payload["ItemCnt"] == 2
    token, png = sign_and_render_qr(qr_payload, keys[0])
    assert png.startswith(PNG_MAGIC)
    assert verify(token, keys[1]) == qr_payload
    assert verify(token, keys[1])["Irn"] == irn

    eway = build_eway_bill_json(invoice, breakup, make_transport(), rate_lookup=hsn_rate)
    assert eway["docNo"] == einvoice["DocDtls"]["No"]
    assert eway["totInvValue"] == einvoice["ValDtls"]["TotInvVal"]
    assert eway["igstValue"] == einvoice["ValDtls"]["IgstVal"]
    part_a, part_b = split_parts(eway)
    assert part_b == {"transMode": "1", "vehicleNo": "MH12AB1234", "vehicleType": "R"}
    assert part_a["transDistance"] == 450
    assert {**part_a, **part_b} == eway


def test_intra_and_inter_supply_give_the_same_total_with_a_different_split():
    inter = tax(make_invoice())
    intra_invoice = make_invoice(place_of_supply="24")
    intra = tax(intra_invoice)
    assert intra.regime is Regime.INTRA
    assert intra.cgst_total == Decimal("5538.75")
    assert intra.sgst_total == Decimal("5538.75")
    assert intra.igst_total == Decimal("0.00")
    assert intra.invoice_total == inter.invoice_total == Decimal("76628.00")

    einvoice = build_einvoice_json(intra_invoice, intra, rate_lookup=hsn_rate)
    assert einvoice["ValDtls"]["CgstVal"] == 5538.75
    assert einvoice["ValDtls"]["SgstVal"] == 5538.75
    assert einvoice["ValDtls"]["IgstVal"] == 0.0
    eway = build_eway_bill_json(intra_invoice, intra, make_transport(), rate_lookup=hsn_rate)
    assert eway["cgstValue"] == 5538.75
    assert eway["igstValue"] == 0.0


def test_credit_note_flow_references_the_original_invoice():
    original = make_invoice()
    credit = make_credit_note()
    breakup = calculate_credit_note(credit, original=original, rate_lookup=hsn_rate)
    assert breakup.taxable_total == Decimal("30000.00")
    assert breakup.igst_total == Decimal("5400.00")
    assert breakup.invoice_total == Decimal("35400.00")

    einvoice = build_einvoice_json(credit, breakup, rate_lookup=hsn_rate)
    assert einvoice["DocDtls"]["Typ"] == "CRN"
    assert einvoice["RefDtls"] == {
        "PrecDocDtls": [{"InvNo": "INV-001", "InvDt": "14/10/2026"}]
    }
    assert einvoice["ValDtls"]["TotInvVal"] == 35400.0


def test_credit_beyond_the_original_value_is_rejected():
    credit = make_credit_note(items=[computer("3")])
    with pytest.raises(ValidationError, match="exceeds the original invoice"):
        calculate_credit_note(credit, original=make_invoice(), rate_lookup=hsn_rate)


def test_a_credit_note_gets_no_e_way_bill():
    credit = make_credit_note()
    breakup = calculate_credit_note(credit, rate_lookup=hsn_rate)
    with pytest.raises(ValidationError, match="invoices only"):
        build_eway_bill_json(credit, breakup, make_transport(), rate_lookup=hsn_rate)


def test_reverse_charge_flow():
    invoice = make_invoice(reverse_charge=True)
    breakup = tax(invoice)
    assert breakup.rcm_applied is True
    assert breakup.invoice_total == Decimal("76628.00")
    assert breakup.payable_to_supplier == Decimal("65550.00")
    einvoice = build_einvoice_json(invoice, breakup, rate_lookup=hsn_rate)
    assert einvoice["TranDtls"]["RegRev"] == "Y"


def test_sez_supply_in_the_same_state_is_igst():
    invoice = make_invoice(place_of_supply="24", is_sez_or_export=True)
    breakup = tax(invoice)
    assert breakup.regime is Regime.INTER
    einvoice = build_einvoice_json(
        invoice, breakup, rate_lookup=hsn_rate, sez_export_type="SEZWP"
    )
    assert einvoice["TranDtls"]["SupTyp"] == "SEZWP"
    assert einvoice["TranDtls"]["IgstOnIntra"] == "Y"
    assert einvoice["ValDtls"]["IgstVal"] == 11077.5


def test_b2c_invoice_gets_an_e_way_bill_but_no_e_invoice():
    invoice = make_invoice(buyer=make_buyer(gstin=None), supply_type="B2C")
    breakup = tax(invoice)
    assert breakup.invoice_total == Decimal("76628.00")
    with pytest.raises(ValidationError, match="B2C"):
        build_einvoice_json(invoice, breakup, rate_lookup=hsn_rate)
    eway = build_eway_bill_json(invoice, breakup, make_transport(), rate_lookup=hsn_rate)
    assert eway["toGstin"] == "URP"


def test_service_invoice_gets_an_e_invoice_but_no_e_way_bill():
    service = LineItem(
        description="Sample IT service", hsn_sac="998314", is_service=True,
        quantity="1", unit_price="10000",
    )
    invoice = make_invoice(items=[service])
    breakup = tax(invoice)
    assert breakup.igst_total == Decimal("1800.00")
    assert breakup.invoice_total == Decimal("11800.00")
    einvoice = build_einvoice_json(invoice, breakup, rate_lookup=hsn_rate)
    assert einvoice["ItemList"][0]["IsServc"] == "Y"
    with pytest.raises(ValidationError, match="goods only"):
        build_eway_bill_json(invoice, breakup, make_transport(), rate_lookup=hsn_rate)


def test_invoice_below_the_threshold_gets_an_e_invoice_but_no_e_way_bill():
    small = LineItem(
        description="Sample rice", hsn_sac="1006", quantity="10", unit_price="55.50"
    )
    invoice = make_invoice(items=[small])
    breakup = tax(invoice)
    assert breakup.invoice_total == Decimal("583.00")
    assert build_einvoice_json(invoice, breakup, rate_lookup=hsn_rate)["ValDtls"]["TotInvVal"] == 583.0
    with pytest.raises(ValidationError, match="not required"):
        build_eway_bill_json(invoice, breakup, make_transport(), rate_lookup=hsn_rate)


def test_an_8_digit_code_not_in_the_data_uses_its_parent_rate():
    child = LineItem(
        description="Sample computer part", hsn_sac="84719000",
        quantity="1", unit_price="1000",
    )
    breakup = tax(make_invoice(items=[child]))
    assert breakup.igst_total == Decimal("180.00")


def test_an_unknown_hsn_code_stops_the_calculation():
    unknown = LineItem(
        description="Sample unknown item", hsn_sac="5555", quantity="1", unit_price="100"
    )
    with pytest.raises(EntityNotFoundError):
        tax(make_invoice(items=[unknown]))


def test_missing_buyer_address_is_caught_by_both_schemas():
    invoice = make_invoice(buyer=make_buyer(address=None))
    breakup = tax(invoice)
    with pytest.raises(SchemaValidationError):
        build_einvoice_json(invoice, breakup, rate_lookup=hsn_rate)
    with pytest.raises(SchemaValidationError):
        build_eway_bill_json(invoice, breakup, make_transport(), rate_lookup=hsn_rate)


def test_a_qr_signed_with_another_key_fails_verification(keys, other_keys):
    invoice = make_invoice()
    einvoice = build_einvoice_json(invoice, tax(invoice), rate_lookup=hsn_rate)
    irn = compute_demo_irn(SUPPLIER_GSTIN, invoice.doc_type, invoice.doc_no, invoice.doc_date)
    token, _ = sign_and_render_qr(build_qr_payload(einvoice, irn, IRN_DATE), keys[0])
    with pytest.raises(SigningError, match="not valid"):
        verify(token, other_keys[1])
