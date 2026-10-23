from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import ValidationError
from app.modules.gst.credit_note import calculate_credit_note
from app.modules.gst.models import Invoice, LineItem, OriginalInvoiceRef, Party
from app.modules.gst.place_of_supply import Regime

# Fake, format-valid sample GSTINs (checksum is not validated).
SUPPLIER_GSTIN = "24AAACC1206D1ZM"
BUYER_GSTIN = "27AAACB1234F1Z5"
OTHER_SUPPLIER_GSTIN = "24AAACC1206D2ZL"
OTHER_BUYER_GSTIN = "27AAACB1234F2Z4"


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


def make_ref():
    return OriginalInvoiceRef(doc_no="INV-001", doc_date=date(2026, 10, 1))


def make_invoice(**overrides):
    data = {
        "doc_no": "INV-001",
        "doc_date": date(2026, 10, 1),
        "supplier": make_party(),
        "buyer": make_buyer(),
        "place_of_supply": "27",
        "supply_type": "B2B",
        "items": [make_item(quantity="5")],
    }
    data.update(overrides)
    return Invoice(**data)


def make_credit(**overrides):
    data = {
        "doc_type": "CRN",
        "doc_no": "CN-001",
        "doc_date": date(2026, 10, 14),
        "original_invoice": make_ref(),
        "items": [make_item(quantity="2")],
    }
    data.update(overrides)
    return make_invoice(**data)


def test_credit_note_uses_the_invoice_maths_with_positive_amounts():
    breakup = calculate_credit_note(make_credit())
    assert breakup.regime is Regime.INTER
    assert breakup.taxable_total == Decimal("200.00")
    assert breakup.igst_total == Decimal("36.00")
    assert breakup.invoice_total == Decimal("236.00")


def test_credit_note_matching_the_original_is_valid():
    breakup = calculate_credit_note(make_credit(), original=make_invoice())
    assert breakup.invoice_total == Decimal("236.00")


def test_a_full_credit_of_the_original_value_is_allowed():
    credit = make_credit(items=[make_item(quantity="5")])
    breakup = calculate_credit_note(credit, original=make_invoice())
    assert breakup.taxable_total == Decimal("500.00")


def test_credit_cannot_exceed_the_original_value():
    credit = make_credit(items=[make_item(quantity="6")])
    with pytest.raises(ValidationError, match="exceeds the original invoice"):
        calculate_credit_note(credit, original=make_invoice())


def test_invoice_is_not_a_credit_note():
    with pytest.raises(ValidationError, match="needs a credit note"):
        calculate_credit_note(make_invoice())


def test_debit_note_is_not_a_credit_note():
    debit = make_invoice(doc_type="DBN", doc_no="DN-001", original_invoice=make_ref())
    with pytest.raises(ValidationError, match="needs a credit note"):
        calculate_credit_note(debit)


def test_original_must_be_an_invoice():
    not_an_invoice = make_credit(doc_no="CN-000")
    with pytest.raises(ValidationError, match="must be an invoice"):
        calculate_credit_note(make_credit(), original=not_an_invoice)


@pytest.mark.parametrize(
    "ref",
    [
        OriginalInvoiceRef(doc_no="INV-999", doc_date=date(2026, 10, 1)),
        OriginalInvoiceRef(doc_no="INV-001", doc_date=date(2026, 10, 2)),
    ],
)
def test_reference_must_match_the_original(ref):
    credit = make_credit(original_invoice=ref)
    with pytest.raises(ValidationError, match="does not match"):
        calculate_credit_note(credit, original=make_invoice())


@pytest.mark.parametrize(
    "overrides",
    [
        {"supplier": make_party(gstin=OTHER_SUPPLIER_GSTIN)},
        {"buyer": make_buyer(gstin=OTHER_BUYER_GSTIN)},
        {"place_of_supply": "24"},
    ],
    ids=["supplier", "buyer", "place-of-supply"],
)
def test_parties_and_place_of_supply_must_match_the_original(overrides):
    with pytest.raises(ValidationError, match="must match the original"):
        calculate_credit_note(make_credit(**overrides), original=make_invoice())


def test_rate_lookup_is_used_for_the_note_and_the_original():
    def lookup(code):
        return Decimal("18")

    credit = make_credit(items=[make_item(quantity="2", gst_rate=None)])
    original = make_invoice(items=[make_item(quantity="5", gst_rate=None)])
    breakup = calculate_credit_note(credit, original=original, rate_lookup=lookup)
    assert breakup.igst_total == Decimal("36.00")
