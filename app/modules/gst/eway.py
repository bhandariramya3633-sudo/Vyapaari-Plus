"""E-way bill JSON builder (NIC EWB generation payload) with schema validation.

build_eway_bill_json turns an invoice, its TaxBreakup and the transport details
into one payload; split_parts divides it into Part A (parties, items, values,
transporter, distance) and Part B (mode, vehicle, transport document).

- Only invoices for goods qualify: credit/debit notes and service lines are rejected.
- An e-way bill is built only when the invoice value is above the threshold in
  config.py (or when allow_below_threshold is set).
- A buyer without a GSTIN is sent as "URP".
- hsnCode is a JSON number, so a leading zero is not kept (0401 becomes 401).
- Amounts are Decimal until they are written into the payload as JSON numbers.
- The payload is checked against a DERIVED schema, not the official NIC file.
"""

import json
import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self

from jsonschema import Draft7Validator
from pydantic import field_validator, model_validator

from app.core.exceptions import ValidationError
from app.modules.gst.config import E_WAY_BILL_THRESHOLD, MAX_TRANSPORT_DISTANCE_KM
from app.modules.gst.exceptions import SchemaValidationError
from app.modules.gst.invoice_calc import RateLookup
from app.modules.gst.models import (
    GSTIN_RE,
    DocType,
    GstModel,
    Invoice,
    LineItem,
    LineTax,
    Party,
    TaxBreakup,
)
from app.modules.gst.money import percent_of, to_decimal
from app.modules.gst.place_of_supply import Regime, resolve_regime

SCHEMA_PATH = Path(__file__).parent / "schemas" / "eway_bill_derived.json"
VEHICLE_RE = re.compile(r"[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}")
TRANS_DOC_RE = re.compile(r"[A-Za-z0-9/-]{1,15}")
PART_B_KEYS = ("transMode", "vehicleNo", "vehicleType", "transDocNo", "transDocDate")


class TransportMode(StrEnum):
    ROAD = "ROAD"
    RAIL = "RAIL"
    AIR = "AIR"
    SHIP = "SHIP"


MODE_CODES = {
    TransportMode.ROAD: "1",
    TransportMode.RAIL: "2",
    TransportMode.AIR: "3",
    TransportMode.SHIP: "4",
}


class Transport(GstModel):
    mode: TransportMode
    distance_km: int
    transporter_id: str | None = None
    transporter_name: str | None = None
    vehicle_no: str | None = None
    transport_doc_no: str | None = None
    transport_doc_date: date | None = None

    @field_validator("distance_km", mode="before")
    @classmethod
    def check_distance_type(cls, value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError("distance_km must be a whole number of kilometres")
        return value

    @field_validator("transporter_id")
    @classmethod
    def check_transporter_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip().upper()
        if not GSTIN_RE.fullmatch(value):
            raise ValidationError(f"transporter_id is not in a valid format: {value!r}")
        return value

    @field_validator("transporter_name")
    @classmethod
    def check_transporter_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValidationError("transporter_name must not be blank")
        return value

    @field_validator("vehicle_no")
    @classmethod
    def check_vehicle_no(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.replace(" ", "").replace("-", "").upper()
        if not VEHICLE_RE.fullmatch(cleaned):
            raise ValidationError(f"vehicle_no is not in a valid format: {value!r}")
        return cleaned

    @field_validator("transport_doc_no")
    @classmethod
    def check_transport_doc_no(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not TRANS_DOC_RE.fullmatch(value):
            raise ValidationError(
                f"transport_doc_no must be 1-15 letters, digits, / or -: {value!r}"
            )
        return value

    @model_validator(mode="after")
    def check_transport(self) -> Self:
        if not 0 <= self.distance_km <= MAX_TRANSPORT_DISTANCE_KM:
            raise ValidationError(
                f"distance_km must be between 0 and {MAX_TRANSPORT_DISTANCE_KM}"
            )
        if (self.transport_doc_no is None) != (self.transport_doc_date is None):
            raise ValidationError(
                "transport_doc_no and transport_doc_date go together"
            )
        if self.mode is TransportMode.ROAD:
            if self.vehicle_no is None and self.transporter_id is None:
                raise ValidationError(
                    "a road shipment needs vehicle_no or transporter_id"
                )
        else:
            if self.vehicle_no is not None:
                raise ValidationError("vehicle_no applies to road transport only")
            if self.transport_doc_no is None:
                raise ValidationError(
                    f"{self.mode.value} transport needs transport_doc_no and transport_doc_date"
                )
        return self


@lru_cache(maxsize=1)
def _validator() -> Draft7Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def _where(error) -> str:
    return ".".join(str(part) for part in error.absolute_path) or "payload"


def validate_eway_bill(payload: dict) -> None:
    """Raise SchemaValidationError listing every schema violation."""
    errors = sorted(
        _validator().iter_errors(payload),
        key=lambda error: [str(part) for part in error.absolute_path],
    )
    if errors:
        messages = [f"{_where(error)}: {error.message}" for error in errors]
        raise SchemaValidationError(
            f"e-way bill payload does not match the schema ({len(messages)} error(s))",
            messages,
        )


def split_parts(payload: dict) -> tuple[dict, dict]:
    """Return (Part A, Part B) of an e-way bill payload."""
    part_b = {key: payload[key] for key in PART_B_KEYS if key in payload}
    part_a = {key: value for key, value in payload.items() if key not in PART_B_KEYS}
    return part_a, part_b


def _num(value: Decimal) -> float:
    return float(value)


def _format_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _item_rate(item: LineItem, rate_lookup: RateLookup | None) -> Decimal:
    if item.gst_rate is not None:
        return item.gst_rate
    if rate_lookup is not None:
        return to_decimal(rate_lookup(item.hsn_sac), "gst_rate")
    raise ValidationError(
        f"gst_rate is missing for HSN/SAC {item.hsn_sac}: set it on the item or pass rate_lookup"
    )


def _side(side: str, party: Party) -> dict:
    state = int(party.state_code)
    block = {f"{side}Gstin": party.gstin or "URP", f"{side}TrdName": party.name}
    if party.address is not None:
        block[f"{side}Addr1"] = party.address
    if party.city is not None:
        block[f"{side}Place"] = party.city
    if party.pincode is not None:
        block[f"{side}Pincode"] = int(party.pincode)
    block[f"act{side.capitalize()}StateCode"] = state
    block[f"{side}StateCode"] = state
    return block


def _item(
    item: LineItem, line: LineTax, regime: Regime, rate: Decimal, ad_valorem: Decimal
) -> dict:
    zero = Decimal("0")
    if regime is Regime.INTRA:
        cgst_rate = sgst_rate = rate / 2
        igst_rate = zero
    else:
        cgst_rate = sgst_rate = zero
        igst_rate = rate
    return {
        "productName": item.description,
        "productDesc": item.description,
        "hsnCode": int(item.hsn_sac),
        "quantity": _num(item.quantity),
        "qtyUnit": item.uqc,
        "taxableAmount": _num(line.taxable_value),
        "cgstRate": _num(cgst_rate),
        "sgstRate": _num(sgst_rate),
        "igstRate": _num(igst_rate),
        "cessRate": _num(item.cess_rate),
        "cessNonadvol": _num(line.cess - ad_valorem),
    }


def build_eway_bill_json(
    invoice: Invoice,
    breakup: TaxBreakup,
    transport: Transport,
    rate_lookup: RateLookup | None = None,
    allow_below_threshold: bool = False,
) -> dict:
    """Build and validate the e-way bill payload for a goods invoice."""
    if invoice.doc_type is not DocType.INV:
        raise ValidationError(
            "an e-way bill is generated for invoices only, not credit or debit notes"
        )
    if any(item.is_service for item in invoice.items):
        raise ValidationError(
            "an e-way bill covers goods only: move service lines to a separate invoice"
        )
    regime = resolve_regime(
        invoice.supplier.state_code, invoice.place_of_supply, invoice.is_sez_or_export
    )
    if (
        len(breakup.lines) != len(invoice.items)
        or breakup.regime is not regime
        or breakup.rcm_applied != invoice.reverse_charge
    ):
        raise ValidationError("the tax breakup does not belong to this invoice")
    if not allow_below_threshold and breakup.invoice_total <= E_WAY_BILL_THRESHOLD:
        raise ValidationError(
            f"an e-way bill is not required: invoice value {breakup.invoice_total} "
            f"does not exceed {E_WAY_BILL_THRESHOLD}"
        )
    if (
        transport.transport_doc_date is not None
        and transport.transport_doc_date < invoice.doc_date
    ):
        raise ValidationError("transport_doc_date cannot be before the invoice date")

    items = []
    cess_ad_valorem_total = Decimal("0.00")
    for item, line in zip(invoice.items, breakup.lines):
        rate = _item_rate(item, rate_lookup)
        ad_valorem = percent_of(line.taxable_value, item.cess_rate)
        cess_ad_valorem_total += ad_valorem
        items.append(_item(item, line, regime, rate, ad_valorem))

    payload = {
        "supplyType": "O",
        "subSupplyType": 1,
        "docType": "INV",
        "docNo": invoice.doc_no,
        "docDate": _format_date(invoice.doc_date),
        **_side("from", invoice.supplier),
        **_side("to", invoice.buyer),
        "transactionType": 1,
        "totalValue": _num(breakup.taxable_total),
        "cgstValue": _num(breakup.cgst_total),
        "sgstValue": _num(breakup.sgst_total),
        "igstValue": _num(breakup.igst_total),
        "cessValue": _num(cess_ad_valorem_total),
        "cessNonAdvolValue": _num(breakup.cess_total - cess_ad_valorem_total),
        "otherValue": _num(breakup.round_off),
        "totInvValue": _num(breakup.invoice_total),
        "transDistance": transport.distance_km,
        "transMode": MODE_CODES[transport.mode],
    }
    if transport.transporter_id is not None:
        payload["transporterId"] = transport.transporter_id
    if transport.transporter_name is not None:
        payload["transporterName"] = transport.transporter_name
    if transport.vehicle_no is not None:
        payload["vehicleNo"] = transport.vehicle_no
        payload["vehicleType"] = "R"
    if transport.transport_doc_no is not None:
        payload["transDocNo"] = transport.transport_doc_no
        payload["transDocDate"] = _format_date(transport.transport_doc_date)
    payload["itemList"] = items
    validate_eway_bill(payload)
    return payload
