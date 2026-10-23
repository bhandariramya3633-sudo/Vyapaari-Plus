from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ValidationError
from app.modules.gst.models import (
    DocType,
    HsnKind,
    HsnRecord,
    Invoice,
    LineItem,
    LineTax,
    OriginalInvoiceRef,
    Party,
    SupplyType,
    TaxBreakup,
)
from app.modules.gst.place_of_supply import Regime

# Fake, format-valid sample GSTINs (checksum is not validated).
SAMPLE_SUPPLIER_GSTIN = "24AAACC1206D1ZM"
SAMPLE_BUYER_GSTIN = "27AAACB1234F1Z5"


def make_party(**overrides):
    data = {
        "name": "Sample Traders",
        "state_code": "24",
        "gstin": SAMPLE_SUPPLIER_GSTIN,
        "address": "1 Sample Road",
        "city": "Sample City",
        "pincode": "390001",
    }
    data.update(overrides)
    return Party(**data)


def make_buyer(**overrides):
    data = {"name": "Sample Buyer", "state_code": "27", "gstin": SAMPLE_BUYER_GSTIN}
    data.update(overrides)
    return Party(**data)


def make_item(**overrides):
    data = {
        "description": "Sample rice 5kg",
        "hsn_sac": "1006",
        "quantity": "2",
        "unit_price": "100.00",
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


def make_line_tax(**overrides):
    data = {
        "taxable_value": "200.00",
        "cgst": "0",
        "sgst": "0",
        "igst": "36.00",
        "cess": "0",
        "line_total": "236.00",
    }
    data.update(overrides)
    return LineTax(**data)


def make_breakup(**overrides):
    data = {
        "regime": "INTER",
        "lines": [make_line_tax()],
        "taxable_total": "200.00",
        "cgst_total": "0",
        "sgst_total": "0",
        "igst_total": "36.00",
        "cess_total": "0",
        "round_off": "0.00",
        "invoice_total": "236.00",
        "rcm_applied": False,
        "payable_to_supplier": "236.00",
    }
    data.update(overrides)
    return TaxBreakup(**data)


# ---------- Party ----------


def test_party_trims_name_and_normalizes_gstin():
    party = make_party(name="  Sample Traders  ", gstin=" 24aaacc1206d1zm ")
    assert party.name == "Sample Traders"
    assert party.gstin == SAMPLE_SUPPLIER_GSTIN


def test_party_state_code_is_normalized():
    assert make_party(state_code="7", gstin=None).state_code == "07"


def test_party_optional_fields_can_be_none():
    party = make_party(gstin=None, address=None, city=None, pincode=None)
    assert party.gstin is None
    assert party.pincode is None


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"name": "   "}, "name must not be blank"),
        ({"gstin": "NOTAGSTIN"}, "gstin is not in a valid format"),
        ({"gstin": SAMPLE_BUYER_GSTIN}, "gstin must start with the party's state code"),
        ({"pincode": "012345"}, "pincode"),
        ({"pincode": "12345"}, "pincode"),
        ({"state_code": "99"}, "state_code"),
        ({"state_code": 24}, "state_code"),
    ],
)
def test_party_rejects_invalid_values(overrides, message):
    with pytest.raises(ValidationError, match=message):
        make_party(**overrides)


def test_party_rejects_unknown_fields():
    with pytest.raises(ValidationError, match="Extra inputs"):
        make_party(nickname="x")


def test_party_is_immutable():
    party = make_party()
    with pytest.raises(PydanticValidationError):
        party.name = "Changed"


# ---------- LineItem ----------


def test_line_item_defaults():
    item = make_item()
    assert item.quantity == Decimal("2")
    assert item.unit_price == Decimal("100.00")
    assert item.discount == Decimal("0")
    assert item.cess_rate == Decimal("0")
    assert item.cess_per_unit == Decimal("0")
    assert item.gst_rate is None
    assert item.uqc == "NOS"
    assert item.is_service is False


def test_line_item_accepts_int_str_and_decimal_numbers():
    item = make_item(
        quantity=3,
        unit_price="99.50",
        gst_rate="18",
        cess_rate=Decimal("12"),
        cess_per_unit=1,
    )
    assert item.quantity == Decimal("3")
    assert item.gst_rate == Decimal("18")
    assert item.cess_rate == Decimal("12")
    assert item.cess_per_unit == Decimal("1")


def test_line_item_gst_rate_can_be_explicit_none():
    assert make_item(gst_rate=None).gst_rate is None


def test_line_item_normalizes_uqc():
    assert make_item(uqc=" kgs ").uqc == "KGS"


def test_line_item_service_with_sac_is_valid():
    item = make_item(hsn_sac="998314", is_service=True)
    assert item.is_service is True


def test_line_item_boundaries_are_valid():
    item = make_item(discount="200", gst_rate="0", cess_rate="100")
    assert item.discount == Decimal("200")
    assert make_item(gst_rate="100").gst_rate == Decimal("100")


@pytest.mark.parametrize(
    "field",
    ["quantity", "unit_price", "discount", "gst_rate", "cess_rate", "cess_per_unit"],
)
def test_line_item_rejects_float_amounts(field):
    with pytest.raises(ValidationError, match=field):
        make_item(**{field: 1.5})


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"description": " "}, "description must not be blank"),
        ({"uqc": "  "}, "uqc must not be blank"),
        ({"hsn_sac": "12"}, "hsn_sac must be 4, 6 or 8 digits"),
        ({"hsn_sac": "abcd"}, "hsn_sac must be 4, 6 or 8 digits"),
        ({"hsn_sac": "123456789"}, "hsn_sac must be 4, 6 or 8 digits"),
        ({"hsn_sac": "1006", "is_service": True}, "services need a SAC"),
        ({"hsn_sac": "996511"}, "goods need an HSN"),
        ({"quantity": "0"}, "quantity must be greater than zero"),
        ({"unit_price": "-1"}, "unit_price must not be negative"),
        ({"discount": "-1"}, "discount must not be negative"),
        ({"discount": "200.01"}, "discount cannot exceed"),
        ({"gst_rate": "101"}, "gst_rate must be between 0 and 100"),
        ({"gst_rate": "-1"}, "gst_rate must be between 0 and 100"),
        ({"cess_rate": "101"}, "cess_rate must be between 0 and 100"),
        ({"cess_per_unit": "-1"}, "cess_per_unit must not be negative"),
    ],
)
def test_line_item_rejects_invalid_values(overrides, message):
    with pytest.raises(ValidationError, match=message):
        make_item(**overrides)


# ---------- OriginalInvoiceRef ----------


def test_original_invoice_ref_is_valid():
    ref = OriginalInvoiceRef(doc_no="INV-001", doc_date=date(2026, 10, 1))
    assert ref.doc_no == "INV-001"


def test_original_invoice_ref_rejects_bad_doc_no():
    with pytest.raises(ValidationError, match="doc_no"):
        OriginalInvoiceRef(doc_no="0123", doc_date=date(2026, 10, 1))


# ---------- Invoice ----------


def test_invoice_defaults_and_tuple_items():
    invoice = make_invoice()
    assert invoice.doc_type is DocType.INV
    assert invoice.supply_type is SupplyType.B2B
    assert invoice.reverse_charge is False
    assert invoice.is_sez_or_export is False
    assert invoice.original_invoice is None
    assert isinstance(invoice.items, tuple)
    assert len(invoice.items) == 1


def test_invoice_accepts_iso_date_string():
    assert make_invoice(doc_date="2026-10-14").doc_date == date(2026, 10, 14)


def test_invoice_normalizes_place_of_supply():
    assert make_invoice(place_of_supply="7").place_of_supply == "07"


@pytest.mark.parametrize(
    "doc_no", ["INV-001", "A/2026/17", "1", "a", "AB12345678901234"]
)
def test_invoice_accepts_valid_doc_numbers(doc_no):
    assert make_invoice(doc_no=doc_no).doc_no == doc_no


@pytest.mark.parametrize("doc_no", ["", "0123", "-AB", "A" * 17, "AB 12", "AB#1"])
def test_invoice_rejects_invalid_doc_numbers(doc_no):
    with pytest.raises(ValidationError, match="doc_no"):
        make_invoice(doc_no=doc_no)


def test_invoice_rejects_invalid_place_of_supply():
    with pytest.raises(ValidationError, match="place_of_supply"):
        make_invoice(place_of_supply="99")


def test_invoice_rejects_empty_items():
    with pytest.raises(ValidationError, match="items must not be empty"):
        make_invoice(items=[])


def test_invoice_requires_supplier_gstin():
    with pytest.raises(ValidationError, match="supplier must have a gstin"):
        make_invoice(supplier=make_party(gstin=None))


def test_b2b_invoice_requires_buyer_gstin():
    with pytest.raises(ValidationError, match="B2B invoice needs the buyer"):
        make_invoice(buyer=make_buyer(gstin=None))


def test_b2c_invoice_does_not_need_buyer_gstin():
    invoice = make_invoice(buyer=make_buyer(gstin=None), supply_type="B2C")
    assert invoice.buyer.gstin is None


def test_invoice_cannot_reference_original_invoice():
    ref = OriginalInvoiceRef(doc_no="INV-000", doc_date=date(2026, 10, 1))
    with pytest.raises(ValidationError, match="cannot reference an original invoice"):
        make_invoice(original_invoice=ref)


@pytest.mark.parametrize("doc_type", ["CRN", "DBN"])
def test_notes_require_original_invoice(doc_type):
    with pytest.raises(ValidationError, match="needs original_invoice"):
        make_invoice(doc_type=doc_type)


@pytest.mark.parametrize("doc_type", ["CRN", "DBN"])
def test_notes_with_original_invoice_are_valid(doc_type):
    ref = OriginalInvoiceRef(doc_no="INV-000", doc_date=date(2026, 10, 1))
    invoice = make_invoice(doc_type=doc_type, original_invoice=ref)
    assert invoice.doc_type == doc_type
    assert invoice.original_invoice == ref


def test_note_cannot_be_dated_before_original_invoice():
    ref = OriginalInvoiceRef(doc_no="INV-000", doc_date=date(2026, 10, 20))
    with pytest.raises(ValidationError, match="cannot be after the note date"):
        make_invoice(doc_type="CRN", original_invoice=ref)


def test_invoice_reports_missing_fields_as_validation_error():
    with pytest.raises(ValidationError, match="Field required"):
        Invoice(doc_no="INV-001")


# ---------- LineTax, TaxBreakup, HsnRecord ----------


def test_line_tax_total():
    assert make_line_tax().tax_total == Decimal("36.00")
    assert make_line_tax(cgst="9", sgst="9", igst="0", cess="2").tax_total == Decimal("20")


def test_tax_breakup_holds_regime_and_lines():
    breakup = make_breakup()
    assert breakup.regime is Regime.INTER
    assert isinstance(breakup.lines, tuple)
    assert breakup.invoice_total == Decimal("236.00")
    assert breakup.rcm_applied is False


def test_tax_breakup_rejects_float_amounts():
    with pytest.raises(ValidationError, match="invoice_total"):
        make_breakup(invoice_total=236.0)


def test_hsn_record_for_goods_and_services():
    goods = HsnRecord(code="1006", description="Sample rice", kind="HSN", gst_rate="5")
    service = HsnRecord(
        code="998314", description="Sample IT service", kind="SAC", gst_rate="18"
    )
    assert goods.kind is HsnKind.HSN
    assert goods.cess_rate == Decimal("0")
    assert service.kind is HsnKind.SAC


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"code": "12"}, "code must be 4, 6 or 8 digits"),
        ({"kind": "SAC"}, "services need a SAC"),
        ({"code": "998314"}, "goods need an HSN"),
        ({"gst_rate": "101"}, "gst_rate must be between 0 and 100"),
        ({"cess_rate": "-1"}, "cess_rate must be between 0 and 100"),
        ({"gst_rate": 5.0}, "gst_rate"),
    ],
)
def test_hsn_record_rejects_invalid_values(overrides, message):
    data = {"code": "1006", "description": "Sample", "kind": "HSN", "gst_rate": "5"}
    data.update(overrides)
    with pytest.raises(ValidationError, match=message):
        HsnRecord(**data)
