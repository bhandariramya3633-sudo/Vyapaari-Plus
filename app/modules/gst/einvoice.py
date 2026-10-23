"""E-invoice JSON builder (NIC INV-01, version 1.1) with schema validation.

build_einvoice_json turns an Invoice and its TaxBreakup into the payload that
is submitted to the IRP. The IRP, not this module, issues the IRN.

- Amounts are computed as Decimal and turned into JSON numbers only here.
- Supported supply types: B2B, SEZWP, SEZWOP and DEXP. B2C invoices are not
  reported to the IRP, and exports (EXPWP/EXPWOP, buyer "URP") are not supported.
- The payload is checked against a DERIVED schema (not the official NIC file);
  swap schemas/einvoice_v1_1_derived.json for the official one when available.
- Qty and UnitPrice are sent as given; NIC allows up to 3 decimals.
"""

import json
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft7Validator

from app.core.exceptions import ValidationError
from app.modules.gst.exceptions import SchemaValidationError
from app.modules.gst.invoice_calc import RateLookup
from app.modules.gst.models import Invoice, LineItem, LineTax, Party, SupplyType, TaxBreakup
from app.modules.gst.money import percent_of, round_paise, to_decimal
from app.modules.gst.place_of_supply import Regime, resolve_regime

SCHEMA_VERSION = "1.1"
SCHEMA_PATH = Path(__file__).parent / "schemas" / "einvoice_v1_1_derived.json"
SEZ_EXPORT_TYPES = ("SEZWP", "SEZWOP", "DEXP")


@lru_cache(maxsize=1)
def _validator() -> Draft7Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def _where(error) -> str:
    return ".".join(str(part) for part in error.absolute_path) or "payload"


def validate_einvoice(payload: dict) -> None:
    """Raise SchemaValidationError listing every schema violation."""
    errors = sorted(
        _validator().iter_errors(payload),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if errors:
        messages = [f"{_where(error)}: {error.message}" for error in errors]
        raise SchemaValidationError(
            f"e-invoice payload does not match the schema ({len(messages)} error(s))",
            messages,
        )


def _num(value: Decimal) -> float:
    return float(value)


def _format_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _supply_type(invoice: Invoice, sez_export_type: str | None) -> str:
    if invoice.supply_type is SupplyType.B2C:
        raise ValidationError(
            "e-invoice is for B2B, SEZ and deemed export supplies; B2C is not reported to the IRP"
        )
    if invoice.is_sez_or_export:
        if sez_export_type not in SEZ_EXPORT_TYPES:
            raise ValidationError(
                "an SEZ/export invoice needs sez_export_type: SEZWP, SEZWOP or DEXP"
            )
        return sez_export_type
    if sez_export_type is not None:
        raise ValidationError("sez_export_type is only valid when is_sez_or_export is true")
    return "B2B"


def _effective_rate(item: LineItem, rate_lookup: RateLookup | None) -> Decimal:
    if item.gst_rate is not None:
        return item.gst_rate
    if rate_lookup is not None:
        return to_decimal(rate_lookup(item.hsn_sac), "gst_rate")
    raise ValidationError(
        f"gst_rate is missing for HSN/SAC {item.hsn_sac}: set it on the item or pass rate_lookup"
    )


def _party(party: Party, place_of_supply: str | None = None) -> dict:
    block = {"Gstin": party.gstin, "LglNm": party.name}
    if place_of_supply is not None:
        block["Pos"] = place_of_supply
    if party.address is not None:
        block["Addr1"] = party.address
    if party.city is not None:
        block["Loc"] = party.city
    if party.pincode is not None:
        block["Pin"] = int(party.pincode)
    block["Stcd"] = party.state_code
    return block


def _item(index: int, item: LineItem, line: LineTax, rate: Decimal) -> dict:
    block = {
        "SlNo": str(index),
        "PrdDesc": item.description,
        "IsServc": "Y" if item.is_service else "N",
        "HsnCd": item.hsn_sac,
        "Qty": _num(item.quantity),
        "Unit": item.uqc,
        "UnitPrice": _num(item.unit_price),
        "TotAmt": _num(round_paise(item.quantity * item.unit_price)),
        "Discount": _num(item.discount),
        "AssAmt": _num(line.taxable_value),
        "GstRt": _num(rate),
        "IgstAmt": _num(line.igst),
        "CgstAmt": _num(line.cgst),
        "SgstAmt": _num(line.sgst),
    }
    if line.cess > 0:
        # Split the line's cess so the two parts always add up to it.
        ad_valorem = percent_of(line.taxable_value, item.cess_rate)
        block["CesRt"] = _num(item.cess_rate)
        block["CesAmt"] = _num(ad_valorem)
        block["CesNonAdvlAmt"] = _num(line.cess - ad_valorem)
    block["TotItemVal"] = _num(line.line_total)
    return block


def build_einvoice_json(
    invoice: Invoice,
    breakup: TaxBreakup,
    rate_lookup: RateLookup | None = None,
    sez_export_type: str | None = None,
) -> dict:
    """Build and validate the e-invoice payload for an invoice or note."""
    supply_type = _supply_type(invoice, sez_export_type)
    regime = resolve_regime(
        invoice.supplier.state_code, invoice.place_of_supply, invoice.is_sez_or_export
    )
    if (
        len(breakup.lines) != len(invoice.items)
        or breakup.regime is not regime
        or breakup.rcm_applied != invoice.reverse_charge
    ):
        raise ValidationError("the tax breakup does not belong to this invoice")
    if supply_type == "SEZWOP" and breakup.igst_total != 0:
        raise ValidationError("SEZWOP supply carries no tax: set gst_rate to 0 on every item")

    igst_on_intra = (
        regime is Regime.INTER and invoice.supplier.state_code == invoice.place_of_supply
    )
    items = [
        _item(index, item, line, _effective_rate(item, rate_lookup))
        for index, (item, line) in enumerate(zip(invoice.items, breakup.lines), start=1)
    ]
    payload = {
        "Version": SCHEMA_VERSION,
        "TranDtls": {
            "TaxSch": "GST",
            "SupTyp": supply_type,
            "RegRev": "Y" if invoice.reverse_charge else "N",
            "IgstOnIntra": "Y" if igst_on_intra else "N",
        },
        "DocDtls": {
            "Typ": invoice.doc_type.value,
            "No": invoice.doc_no,
            "Dt": _format_date(invoice.doc_date),
        },
        "SellerDtls": _party(invoice.supplier),
        "BuyerDtls": _party(invoice.buyer, invoice.place_of_supply),
        "ItemList": items,
        "ValDtls": {
            "AssVal": _num(breakup.taxable_total),
            "CgstVal": _num(breakup.cgst_total),
            "SgstVal": _num(breakup.sgst_total),
            "IgstVal": _num(breakup.igst_total),
            "CesVal": _num(breakup.cess_total),
            "RndOffAmt": _num(breakup.round_off),
            "TotInvVal": _num(breakup.invoice_total),
        },
    }
    if invoice.original_invoice is not None:
        reference = invoice.original_invoice
        payload["RefDtls"] = {
            "PrecDocDtls": [
                {"InvNo": reference.doc_no, "InvDt": _format_date(reference.doc_date)}
            ]
        }
    validate_einvoice(payload)
    return payload
