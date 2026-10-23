import json
from copy import deepcopy
from datetime import date

import pytest
from jsonschema import Draft7Validator

from app.core.exceptions import ValidationError
from app.modules.gst.einvoice import SCHEMA_PATH, build_einvoice_json, validate_einvoice
from app.modules.gst.exceptions import SchemaValidationError
from app.modules.gst.invoice_calc import calculate_invoice
from app.modules.gst.models import Invoice, LineItem, OriginalInvoiceRef, Party

# Fake, format-valid sample GSTINs (checksum is not validated).
SUPPLIER_GSTIN = "24AAACC1206D1ZM"
BUYER_GSTIN = "27AAACB1234F1Z5"


def make_party(**overrides):
    data = {
        "name": "Sample Traders",
        "state_code": "24",
        "gstin": SUPPLIER_GSTIN,
        "address": "1 Sample Road",
        "city": "Sample City",
        "pincode": "390001",
    }
    data.update(overrides)
    return Party(**data)


def make_buyer(**overrides):
    data = {
        "name": "Sample Buyer",
        "state_code": "27",
        "gstin": BUYER_GSTIN,
        "address": "5 Sample Lane",
        "city": "Mumbai",
        "pincode": "400001",
    }
    data.update(overrides)
    return Party(**data)


def make_item(**overrides):
    data = {
        "description": "Sample rice 5kg",
        "hsn_sac": "1006",
        "quantity": "2",
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
        "place_of_supply": "27",
        "supply_type": "B2B",
        "items": [make_item()],
    }
    data.update(overrides)
    return Invoice(**data)


def build(invoice, **kwargs):
    return build_einvoice_json(invoice, calculate_invoice(invoice), **kwargs)


def valid_payload():
    return build(make_invoice())


# ---------- payload content ----------


def test_inter_state_b2b_payload():
    payload = valid_payload()
    assert payload["Version"] == "1.1"
    assert payload["TranDtls"] == {
        "TaxSch": "GST", "SupTyp": "B2B", "RegRev": "N", "IgstOnIntra": "N",
    }
    assert payload["DocDtls"] == {"Typ": "INV", "No": "INV-001", "Dt": "14/10/2026"}
    assert payload["SellerDtls"] == {
        "Gstin": SUPPLIER_GSTIN, "LglNm": "Sample Traders", "Addr1": "1 Sample Road",
        "Loc": "Sample City", "Pin": 390001, "Stcd": "24",
    }
    assert payload["BuyerDtls"] == {
        "Gstin": BUYER_GSTIN, "LglNm": "Sample Buyer", "Pos": "27", "Addr1": "5 Sample Lane",
        "Loc": "Mumbai", "Pin": 400001, "Stcd": "27",
    }
    assert payload["ItemList"] == [
        {
            "SlNo": "1", "PrdDesc": "Sample rice 5kg", "IsServc": "N", "HsnCd": "1006",
            "Qty": 2.0, "Unit": "NOS", "UnitPrice": 100.0, "TotAmt": 200.0,
            "Discount": 0.0, "AssAmt": 200.0, "GstRt": 18.0, "IgstAmt": 36.0,
            "CgstAmt": 0.0, "SgstAmt": 0.0, "TotItemVal": 236.0,
        }
    ]
    assert payload["ValDtls"] == {
        "AssVal": 200.0, "CgstVal": 0.0, "SgstVal": 0.0, "IgstVal": 36.0,
        "CesVal": 0.0, "RndOffAmt": 0.0, "TotInvVal": 236.0,
    }
    assert "RefDtls" not in payload


def test_intra_state_payload_splits_cgst_and_sgst():
    payload = build(make_invoice(place_of_supply="24"))
    item = payload["ItemList"][0]
    assert (item["CgstAmt"], item["SgstAmt"], item["IgstAmt"]) == (18.0, 18.0, 0.0)
    assert payload["BuyerDtls"]["Pos"] == "24"
    assert payload["TranDtls"]["IgstOnIntra"] == "N"
    assert payload["ValDtls"]["CgstVal"] == 18.0


def test_payload_survives_a_json_round_trip():
    payload = valid_payload()
    assert json.loads(json.dumps(payload)) == payload


def test_valuation_adds_up_with_odd_paise_and_round_off():
    invoice = make_invoice(
        place_of_supply="24",
        items=[
            make_item(unit_price="10.10", quantity="1", gst_rate="5"),
            make_item(unit_price="33.33", quantity="1", gst_rate="12"),
        ],
    )
    payload = build(invoice)
    val = payload["ValDtls"]
    assert val["AssVal"] == 43.43
    assert val["CgstVal"] == 2.25
    assert val["RndOffAmt"] == 0.07
    assert val["TotInvVal"] == 48.0
    gross = val["AssVal"] + val["CgstVal"] + val["SgstVal"] + val["IgstVal"] + val["CesVal"]
    assert gross + val["RndOffAmt"] == pytest.approx(val["TotInvVal"], abs=1e-9)
    items_total = sum(item["TotItemVal"] for item in payload["ItemList"])
    assert items_total + val["RndOffAmt"] == pytest.approx(val["TotInvVal"], abs=1e-9)
    assert [item["SlNo"] for item in payload["ItemList"]] == ["1", "2"]


def test_service_item_is_flagged():
    payload = build(make_invoice(items=[make_item(hsn_sac="998314", is_service=True)]))
    assert payload["ItemList"][0]["IsServc"] == "Y"
    assert payload["ItemList"][0]["HsnCd"] == "998314"


def test_discount_and_gross_amount():
    payload = build(
        make_invoice(items=[make_item(quantity="3", unit_price="99.99", discount="10")])
    )
    item = payload["ItemList"][0]
    assert item["TotAmt"] == 299.97
    assert item["Discount"] == 10.0
    assert item["AssAmt"] == 289.97
    assert item["TotItemVal"] == 342.16


def test_cess_is_split_into_ad_valorem_and_specific_parts():
    item = make_item(
        description="Sample cigarettes", hsn_sac="2402", quantity="10", unit_price="100",
        gst_rate="28", cess_rate="5", cess_per_unit="2",
    )
    payload = build(make_invoice(items=[item]))
    line = payload["ItemList"][0]
    assert line["CesRt"] == 5.0
    assert line["CesAmt"] == 50.0
    assert line["CesNonAdvlAmt"] == 20.0
    assert line["IgstAmt"] == 280.0
    assert line["TotItemVal"] == 1350.0
    assert payload["ValDtls"]["CesVal"] == 70.0
    assert payload["ValDtls"]["TotInvVal"] == 1350.0


def test_cess_keys_are_left_out_when_there_is_no_cess():
    item = valid_payload()["ItemList"][0]
    assert "CesRt" not in item
    assert "CesAmt" not in item
    assert "CesNonAdvlAmt" not in item


def test_reverse_charge_flag():
    payload = build(make_invoice(reverse_charge=True))
    assert payload["TranDtls"]["RegRev"] == "Y"


def test_credit_note_carries_the_original_invoice_reference():
    reference = OriginalInvoiceRef(doc_no="INV-001", doc_date=date(2026, 10, 1))
    payload = build(make_invoice(doc_type="CRN", doc_no="CN-001", original_invoice=reference))
    assert payload["DocDtls"]["Typ"] == "CRN"
    assert payload["RefDtls"] == {"PrecDocDtls": [{"InvNo": "INV-001", "InvDt": "01/10/2026"}]}


def test_debit_note_type():
    reference = OriginalInvoiceRef(doc_no="INV-001", doc_date=date(2026, 10, 1))
    payload = build(make_invoice(doc_type="DBN", doc_no="DN-001", original_invoice=reference))
    assert payload["DocDtls"]["Typ"] == "DBN"


def test_rate_lookup_fills_in_a_missing_item_rate():
    invoice = make_invoice(items=[make_item(gst_rate=None)])
    breakup = calculate_invoice(invoice, lambda code: "18")
    payload = build_einvoice_json(invoice, breakup, rate_lookup=lambda code: "18")
    assert payload["ItemList"][0]["GstRt"] == 18.0


def test_missing_item_rate_without_lookup_is_an_error():
    invoice = make_invoice(items=[make_item(gst_rate=None)])
    breakup = calculate_invoice(invoice, lambda code: "18")
    with pytest.raises(ValidationError, match="gst_rate is missing"):
        build_einvoice_json(invoice, breakup)


# ---------- SEZ and deemed export ----------


@pytest.mark.parametrize("sez_type", ["SEZWP", "DEXP"])
def test_sez_with_payment_of_tax(sez_type):
    invoice = make_invoice(place_of_supply="24", is_sez_or_export=True)
    payload = build(invoice, sez_export_type=sez_type)
    assert payload["TranDtls"]["SupTyp"] == sez_type
    assert payload["TranDtls"]["IgstOnIntra"] == "Y"
    assert payload["ItemList"][0]["IgstAmt"] == 36.0
    assert payload["ItemList"][0]["CgstAmt"] == 0.0


def test_sez_without_payment_of_tax_needs_zero_tax():
    invoice = make_invoice(is_sez_or_export=True, items=[make_item(gst_rate="0")])
    payload = build(invoice, sez_export_type="SEZWOP")
    assert payload["TranDtls"]["SupTyp"] == "SEZWOP"
    assert payload["ValDtls"]["IgstVal"] == 0.0


def test_sez_without_payment_of_tax_rejects_tax():
    invoice = make_invoice(is_sez_or_export=True)
    with pytest.raises(ValidationError, match="SEZWOP"):
        build(invoice, sez_export_type="SEZWOP")


@pytest.mark.parametrize("sez_type", [None, "EXPWP", "B2B"])
def test_sez_invoice_needs_a_supported_sez_export_type(sez_type):
    with pytest.raises(ValidationError, match="sez_export_type"):
        build(make_invoice(is_sez_or_export=True), sez_export_type=sez_type)


def test_sez_export_type_is_only_valid_for_sez_invoices():
    with pytest.raises(ValidationError, match="only valid"):
        build(make_invoice(), sez_export_type="SEZWP")


# ---------- rejected inputs ----------


def test_b2c_invoice_is_not_reported():
    invoice = make_invoice(buyer=make_buyer(gstin=None), supply_type="B2C")
    with pytest.raises(ValidationError, match="B2C"):
        build(invoice)


def test_breakup_with_a_different_number_of_lines_is_rejected():
    two_lines = make_invoice(items=[make_item(), make_item(description="Other item")])
    with pytest.raises(ValidationError, match="does not belong"):
        build_einvoice_json(make_invoice(), calculate_invoice(two_lines))


def test_breakup_with_a_different_regime_is_rejected():
    intra_breakup = calculate_invoice(make_invoice(place_of_supply="24"))
    with pytest.raises(ValidationError, match="does not belong"):
        build_einvoice_json(make_invoice(place_of_supply="27"), intra_breakup)


def test_breakup_with_a_different_reverse_charge_flag_is_rejected():
    plain_breakup = calculate_invoice(make_invoice())
    with pytest.raises(ValidationError, match="does not belong"):
        build_einvoice_json(make_invoice(reverse_charge=True), plain_breakup)


def test_missing_seller_address_fails_schema_validation():
    with pytest.raises(SchemaValidationError) as exc:
        build(make_invoice(supplier=make_party(address=None)))
    assert exc.value.code == "SCHEMA_INVALID"
    assert any("SellerDtls" in m and "Addr1" in m for m in exc.value.errors)


def test_short_legal_name_fails_schema_validation():
    with pytest.raises(SchemaValidationError) as exc:
        build(make_invoice(supplier=make_party(name="AB")))
    assert any(m.startswith("SellerDtls.LglNm") for m in exc.value.errors)


def test_overlong_address_fails_schema_validation():
    with pytest.raises(SchemaValidationError) as exc:
        build(make_invoice(supplier=make_party(address="A" * 101)))
    assert any(m.startswith("SellerDtls.Addr1") for m in exc.value.errors)


# ---------- schema validation of a payload ----------

MUTATIONS = {
    "missing-buyer-location": (lambda p: p["BuyerDtls"].pop("Loc"), ("BuyerDtls", "Loc")),
    "bad-supply-type": (lambda p: p["TranDtls"].update(SupTyp="XYZ"), ("TranDtls.SupTyp",)),
    "overlong-address": (lambda p: p["SellerDtls"].update(Addr1="A" * 101), ("SellerDtls.Addr1",)),
    "bad-pin": (lambda p: p["BuyerDtls"].update(Pin=12), ("BuyerDtls.Pin",)),
    "bad-date": (lambda p: p["DocDtls"].update(Dt="2026-10-14"), ("DocDtls.Dt",)),
    "unknown-field": (lambda p: p.update(Extra=1), ("Extra",)),
    "no-items": (lambda p: p.update(ItemList=[]), ("ItemList",)),
    "bad-service-flag": (lambda p: p["ItemList"][0].update(IsServc="X"), ("ItemList.0.IsServc",)),
    "bad-gstin": (lambda p: p["SellerDtls"].update(Gstin="BADGSTIN"), ("SellerDtls.Gstin",)),
}


@pytest.mark.parametrize("mutate, needles", list(MUTATIONS.values()), ids=list(MUTATIONS))
def test_schema_rejects_invalid_payloads(mutate, needles):
    payload = deepcopy(valid_payload())
    mutate(payload)
    with pytest.raises(SchemaValidationError) as exc:
        validate_einvoice(payload)
    assert any(all(needle in message for needle in needles) for message in exc.value.errors)


def test_a_valid_payload_passes_validation():
    assert validate_einvoice(valid_payload()) is None


def test_empty_payload_reports_missing_top_level_fields():
    with pytest.raises(SchemaValidationError) as exc:
        validate_einvoice({})
    assert any(m.startswith("payload:") and "Version" in m for m in exc.value.errors)


def test_every_violation_is_reported():
    payload = deepcopy(valid_payload())
    payload["DocDtls"]["Dt"] = "bad"
    payload["BuyerDtls"]["Pin"] = 12
    with pytest.raises(SchemaValidationError, match=r"\(2 error\(s\)\)") as exc:
        validate_einvoice(payload)
    assert len(exc.value.errors) == 2


# ---------- the schema file ----------


def test_schema_file_is_valid_json_schema_and_labelled_derived():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    assert schema["description"].startswith("DERIVED")
    assert "not official" in schema["title"]
