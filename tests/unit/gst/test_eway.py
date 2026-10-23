import json
from copy import deepcopy
from datetime import date

import pytest
from jsonschema import Draft7Validator
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ValidationError
from app.modules.gst.config import E_WAY_BILL_THRESHOLD, MAX_TRANSPORT_DISTANCE_KM
from app.modules.gst.eway import (
    SCHEMA_PATH,
    Transport,
    build_eway_bill_json,
    split_parts,
    validate_eway_bill,
)
from app.modules.gst.exceptions import SchemaValidationError
from app.modules.gst.invoice_calc import calculate_invoice
from app.modules.gst.models import Invoice, LineItem, OriginalInvoiceRef, Party

# Fake, format-valid sample GSTINs (checksum is not validated).
SUPPLIER_GSTIN = "24AAACC1206D1ZM"
BUYER_GSTIN = "27AAACB1234F1Z5"
TRANSPORTER_GSTIN = "29AAACT1234F1Z7"


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
        "description": "Sample generator",
        "hsn_sac": "8501",
        "quantity": "2",
        "unit_price": "30000.00",
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


def make_transport(**overrides):
    data = {"mode": "ROAD", "distance_km": 450, "vehicle_no": "mh12ab1234"}
    data.update(overrides)
    return Transport(**data)


def build(invoice, transport=None, **kwargs):
    breakup = calculate_invoice(invoice)
    return build_eway_bill_json(invoice, breakup, transport or make_transport(), **kwargs)


def valid_payload():
    return build(make_invoice())


# ---------- payload content ----------


def test_inter_state_payload():
    assert valid_payload() == {
        "supplyType": "O",
        "subSupplyType": 1,
        "docType": "INV",
        "docNo": "INV-001",
        "docDate": "14/10/2026",
        "fromGstin": SUPPLIER_GSTIN,
        "fromTrdName": "Sample Traders",
        "fromAddr1": "1 Sample Road",
        "fromPlace": "Sample City",
        "fromPincode": 390001,
        "actFromStateCode": 24,
        "fromStateCode": 24,
        "toGstin": BUYER_GSTIN,
        "toTrdName": "Sample Buyer",
        "toAddr1": "5 Sample Lane",
        "toPlace": "Mumbai",
        "toPincode": 400001,
        "actToStateCode": 27,
        "toStateCode": 27,
        "transactionType": 1,
        "totalValue": 60000.0,
        "cgstValue": 0.0,
        "sgstValue": 0.0,
        "igstValue": 10800.0,
        "cessValue": 0.0,
        "cessNonAdvolValue": 0.0,
        "otherValue": 0.0,
        "totInvValue": 70800.0,
        "transDistance": 450,
        "transMode": "1",
        "vehicleNo": "MH12AB1234",
        "vehicleType": "R",
        "itemList": [
            {
                "productName": "Sample generator",
                "productDesc": "Sample generator",
                "hsnCode": 8501,
                "quantity": 2.0,
                "qtyUnit": "NOS",
                "taxableAmount": 60000.0,
                "cgstRate": 0.0,
                "sgstRate": 0.0,
                "igstRate": 18.0,
                "cessRate": 0.0,
                "cessNonadvol": 0.0,
            }
        ],
    }


def test_intra_state_payload_splits_cgst_and_sgst():
    payload = build(make_invoice(place_of_supply="24"))
    item = payload["itemList"][0]
    assert (item["cgstRate"], item["sgstRate"], item["igstRate"]) == (9.0, 9.0, 0.0)
    assert payload["cgstValue"] == 5400.0
    assert payload["sgstValue"] == 5400.0
    assert payload["igstValue"] == 0.0
    assert payload["toStateCode"] == 27


def test_payload_survives_a_json_round_trip():
    payload = valid_payload()
    assert json.loads(json.dumps(payload)) == payload


def test_cess_is_split_into_ad_valorem_and_specific_parts():
    item = make_item(
        description="Sample cigarettes", hsn_sac="2402", gst_rate="28",
        cess_rate="5", cess_per_unit="2",
    )
    payload = build(make_invoice(items=[item]))
    line = payload["itemList"][0]
    assert line["igstRate"] == 28.0
    assert line["cessRate"] == 5.0
    assert line["cessNonadvol"] == 4.0
    assert payload["cessValue"] == 3000.0
    assert payload["cessNonAdvolValue"] == 4.0
    assert payload["igstValue"] == 16800.0
    assert payload["totInvValue"] == 79804.0


def test_values_add_up_with_round_off():
    payload = build(make_invoice(items=[make_item(unit_price="25000.40")]))
    assert payload["totalValue"] == 50000.8
    assert payload["igstValue"] == 9000.14
    assert payload["otherValue"] == 0.06
    assert payload["totInvValue"] == 59001.0
    parts = (
        payload["totalValue"], payload["cgstValue"], payload["sgstValue"],
        payload["igstValue"], payload["cessValue"], payload["cessNonAdvolValue"],
        payload["otherValue"],
    )
    assert sum(parts) == pytest.approx(payload["totInvValue"], abs=1e-9)


def test_hsn_code_is_a_number_so_a_leading_zero_is_dropped():
    item = make_item(description="Sample milk", hsn_sac="0401", gst_rate="0", quantity="1",
                     unit_price="60000")
    assert build(make_invoice(items=[item]))["itemList"][0]["hsnCode"] == 401


def test_buyer_without_gstin_is_sent_as_urp():
    invoice = make_invoice(buyer=make_buyer(gstin=None), supply_type="B2C")
    assert build(invoice)["toGstin"] == "URP"


def test_rate_lookup_fills_in_a_missing_item_rate():
    invoice = make_invoice(items=[make_item(gst_rate=None)])
    breakup = calculate_invoice(invoice, lambda code: "18")
    payload = build_eway_bill_json(
        invoice, breakup, make_transport(), rate_lookup=lambda code: "18"
    )
    assert payload["itemList"][0]["igstRate"] == 18.0


def test_missing_item_rate_without_lookup_is_an_error():
    invoice = make_invoice(items=[make_item(gst_rate=None)])
    breakup = calculate_invoice(invoice, lambda code: "18")
    with pytest.raises(ValidationError, match="gst_rate is missing"):
        build_eway_bill_json(invoice, breakup, make_transport())


# ---------- threshold ----------


def test_threshold_value_comes_from_config():
    assert E_WAY_BILL_THRESHOLD == 50000


def test_invoice_value_at_the_threshold_does_not_need_an_e_way_bill():
    invoice = make_invoice(
        items=[make_item(quantity="1", unit_price="50000", gst_rate="0")]
    )
    with pytest.raises(ValidationError, match="not required"):
        build(invoice)


def test_invoice_value_above_the_threshold_gets_an_e_way_bill():
    invoice = make_invoice(
        items=[make_item(quantity="1", unit_price="50001", gst_rate="0")]
    )
    assert build(invoice)["totInvValue"] == 50001.0


def test_below_threshold_is_allowed_when_asked_for():
    invoice = make_invoice(
        items=[make_item(quantity="1", unit_price="50000", gst_rate="0")]
    )
    assert build(invoice, allow_below_threshold=True)["totInvValue"] == 50000.0


# ---------- rejected invoices ----------


@pytest.mark.parametrize("doc_type", ["CRN", "DBN"])
def test_credit_and_debit_notes_are_rejected(doc_type):
    reference = OriginalInvoiceRef(doc_no="INV-000", doc_date=date(2026, 10, 1))
    invoice = make_invoice(doc_type=doc_type, doc_no="N-001", original_invoice=reference)
    with pytest.raises(ValidationError, match="invoices only"):
        build(invoice)


def test_service_lines_are_rejected():
    item = make_item(hsn_sac="998314", is_service=True)
    with pytest.raises(ValidationError, match="goods only"):
        build(make_invoice(items=[item]))


def test_breakup_with_a_different_number_of_lines_is_rejected():
    two_lines = make_invoice(items=[make_item(), make_item(description="Other item")])
    with pytest.raises(ValidationError, match="does not belong"):
        build_eway_bill_json(make_invoice(), calculate_invoice(two_lines), make_transport())


def test_breakup_with_a_different_regime_is_rejected():
    intra_breakup = calculate_invoice(make_invoice(place_of_supply="24"))
    with pytest.raises(ValidationError, match="does not belong"):
        build_eway_bill_json(make_invoice(place_of_supply="27"), intra_breakup, make_transport())


def test_breakup_with_a_different_reverse_charge_flag_is_rejected():
    plain_breakup = calculate_invoice(make_invoice())
    with pytest.raises(ValidationError, match="does not belong"):
        build_eway_bill_json(
            make_invoice(reverse_charge=True), plain_breakup, make_transport()
        )


def test_transport_document_cannot_be_older_than_the_invoice():
    transport = make_transport(
        mode="RAIL", vehicle_no=None, transport_doc_no="RR1234",
        transport_doc_date=date(2026, 10, 13),
    )
    with pytest.raises(ValidationError, match="before the invoice date"):
        build(make_invoice(), transport)


# ---------- transport modes and Part A / Part B ----------


def test_road_shipment_with_transporter_id_and_no_vehicle_yet():
    transport = make_transport(
        vehicle_no=None, transporter_id="29aaact1234f1z7", transporter_name="Sample Carriers"
    )
    payload = build(make_invoice(), transport)
    assert payload["transporterId"] == TRANSPORTER_GSTIN
    assert payload["transporterName"] == "Sample Carriers"
    assert payload["transMode"] == "1"
    assert "vehicleNo" not in payload
    assert "vehicleType" not in payload


@pytest.mark.parametrize("mode, code", [("RAIL", "2"), ("AIR", "3"), ("SHIP", "4")])
def test_non_road_modes_carry_the_transport_document(mode, code):
    transport = Transport(
        mode=mode, distance_km=800, transport_doc_no="RR1234",
        transport_doc_date=date(2026, 10, 15),
    )
    payload = build(make_invoice(), transport)
    assert payload["transMode"] == code
    assert payload["transDocNo"] == "RR1234"
    assert payload["transDocDate"] == "15/10/2026"
    assert "vehicleNo" not in payload


def test_split_parts_divides_the_payload():
    payload = valid_payload()
    part_a, part_b = split_parts(payload)
    assert part_b == {"transMode": "1", "vehicleNo": "MH12AB1234", "vehicleType": "R"}
    assert "transMode" not in part_a
    assert part_a["docNo"] == "INV-001"
    assert part_a["transDistance"] == 450
    assert {**part_a, **part_b} == payload


def test_split_parts_puts_the_transport_document_in_part_b():
    transport = Transport(
        mode="AIR", distance_km=900, transport_doc_no="AW1234",
        transport_doc_date=date(2026, 10, 15),
    )
    part_a, part_b = split_parts(build(make_invoice(), transport))
    assert part_b == {"transMode": "3", "transDocNo": "AW1234", "transDocDate": "15/10/2026"}
    assert "transDocNo" not in part_a


# ---------- Transport model ----------


def test_transport_normalizes_vehicle_and_transporter_id():
    transport = make_transport(vehicle_no=" mh-12 ab 1234 ", transporter_id="29aaact1234f1z7")
    assert transport.vehicle_no == "MH12AB1234"
    assert transport.transporter_id == TRANSPORTER_GSTIN


def test_transport_accepts_a_distance_of_zero_and_the_maximum():
    assert make_transport(distance_km=0).distance_km == 0
    assert (
        make_transport(distance_km=MAX_TRANSPORT_DISTANCE_KM).distance_km
        == MAX_TRANSPORT_DISTANCE_KM
    )


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"distance_km": True}, "distance_km"),
        ({"distance_km": 1.5}, "distance_km"),
        ({"distance_km": "100"}, "distance_km"),
        ({"distance_km": -1}, "between 0 and"),
        ({"distance_km": MAX_TRANSPORT_DISTANCE_KM + 1}, "between 0 and"),
        ({"vehicle_no": "12AB"}, "vehicle_no"),
        ({"transporter_id": "BAD"}, "transporter_id"),
        ({"transporter_name": "  "}, "transporter_name"),
        ({"transport_doc_no": "A B"}, "transport_doc_no"),
        ({"mode": "BOAT"}, "mode"),
        ({"vehicle_no": None}, "vehicle_no or transporter_id"),
        ({"transport_doc_no": "RR1"}, "go together"),
        ({"transport_doc_date": date(2026, 10, 15)}, "go together"),
    ],
)
def test_transport_rejects_invalid_values(overrides, message):
    with pytest.raises(ValidationError, match=message):
        make_transport(**overrides)


def test_rail_shipment_needs_a_transport_document():
    with pytest.raises(ValidationError, match="RAIL transport needs"):
        Transport(mode="RAIL", distance_km=800)


def test_vehicle_number_is_for_road_transport_only():
    with pytest.raises(ValidationError, match="road transport only"):
        Transport(
            mode="RAIL", distance_km=800, vehicle_no="MH12AB1234",
            transport_doc_no="RR1", transport_doc_date=date(2026, 10, 15),
        )


def test_transport_is_immutable():
    transport = make_transport()
    with pytest.raises(PydanticValidationError):
        transport.distance_km = 10


# ---------- schema validation ----------


@pytest.mark.parametrize(
    "field, key",
    [("address", "fromAddr1"), ("city", "fromPlace"), ("pincode", "fromPincode")],
)
def test_missing_supplier_details_fail_schema_validation(field, key):
    invoice = make_invoice(supplier=make_party(**{field: None}))
    with pytest.raises(SchemaValidationError) as exc:
        build(invoice)
    assert exc.value.code == "SCHEMA_INVALID"
    assert any(key in message for message in exc.value.errors)


def test_overlong_address_fails_schema_validation():
    with pytest.raises(SchemaValidationError) as exc:
        build(make_invoice(supplier=make_party(address="A" * 121)))
    assert any("fromAddr1" in message for message in exc.value.errors)


def test_overlong_product_name_fails_schema_validation():
    with pytest.raises(SchemaValidationError) as exc:
        build(make_invoice(items=[make_item(description="P" * 101)]))
    assert any("itemList.0.productName" in message for message in exc.value.errors)


MUTATIONS = {
    "bad-supply-type": (lambda p: p.update(supplyType="X"), "supplyType"),
    "bad-doc-type": (lambda p: p.update(docType="XYZ"), "docType"),
    "bad-date": (lambda p: p.update(docDate="2026-10-14"), "docDate"),
    "bad-pin": (lambda p: p.update(fromPincode=12), "fromPincode"),
    "bad-gstin": (lambda p: p.update(fromGstin="BAD"), "fromGstin"),
    "no-items": (lambda p: p.update(itemList=[]), "itemList"),
    "unknown-field": (lambda p: p.update(Extra=1), "Extra"),
    "bad-mode": (lambda p: p.update(transMode="9"), "transMode"),
    "bad-distance": (lambda p: p.update(transDistance=4001), "transDistance"),
    "missing-place": (lambda p: p.pop("fromPlace"), "fromPlace"),
    "bad-hsn": (lambda p: p["itemList"][0].update(hsnCode=0), "itemList.0.hsnCode"),
    "negative-value": (lambda p: p.update(totalValue=-1), "totalValue"),
}


@pytest.mark.parametrize("mutate, needle", list(MUTATIONS.values()), ids=list(MUTATIONS))
def test_schema_rejects_invalid_payloads(mutate, needle):
    payload = deepcopy(valid_payload())
    mutate(payload)
    with pytest.raises(SchemaValidationError) as exc:
        validate_eway_bill(payload)
    assert any(needle in message for message in exc.value.errors)


def test_a_valid_payload_passes_validation():
    assert validate_eway_bill(valid_payload()) is None


def test_every_violation_is_reported():
    payload = deepcopy(valid_payload())
    payload["docDate"] = "bad"
    payload["fromPincode"] = 12
    with pytest.raises(SchemaValidationError, match=r"\(2 error\(s\)\)") as exc:
        validate_eway_bill(payload)
    assert len(exc.value.errors) == 2


def test_schema_file_is_valid_json_schema_and_labelled_derived():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    assert schema["description"].startswith("DERIVED")
    assert "not official" in schema["title"]


def test_optional_transport_fields_accept_an_explicit_none():
    transport = make_transport(
        transporter_id=None, transporter_name=None, transport_doc_no=None
    )
    assert transport.transporter_id is None
    assert transport.transporter_name is None
    assert transport.transport_doc_no is None
