"""Credit note tax: same maths as an invoice, plus checks against the original.

Amounts stay positive; the document type (CRN) says it reduces the original.
When the original invoice is given, the note must reference it, share its
parties and place of supply, and not credit more than the original's value.
"""

from app.core.exceptions import ValidationError
from app.modules.gst.invoice_calc import RateLookup, calculate_invoice
from app.modules.gst.models import DocType, Invoice, TaxBreakup


def calculate_credit_note(
    credit_note: Invoice,
    original: Invoice | None = None,
    rate_lookup: RateLookup | None = None,
) -> TaxBreakup:
    if credit_note.doc_type is not DocType.CRN:
        raise ValidationError("calculate_credit_note needs a credit note (doc_type CRN)")
    breakup = calculate_invoice(credit_note, rate_lookup)
    if original is not None:
        _check_against_original(credit_note, original, breakup, rate_lookup)
    return breakup


def _check_against_original(
    credit_note: Invoice,
    original: Invoice,
    breakup: TaxBreakup,
    rate_lookup: RateLookup | None,
) -> None:
    if original.doc_type is not DocType.INV:
        raise ValidationError("the original document must be an invoice (doc_type INV)")
    ref = credit_note.original_invoice
    if (ref.doc_no, ref.doc_date) != (original.doc_no, original.doc_date):
        raise ValidationError(
            "credit note original_invoice does not match the original invoice"
        )
    if (
        credit_note.supplier.gstin != original.supplier.gstin
        or credit_note.buyer.gstin != original.buyer.gstin
        or credit_note.place_of_supply != original.place_of_supply
    ):
        raise ValidationError(
            "credit note parties and place of supply must match the original invoice"
        )
    original_breakup = calculate_invoice(original, rate_lookup)
    if breakup.taxable_total > original_breakup.taxable_total:
        raise ValidationError("credit note taxable value exceeds the original invoice")
