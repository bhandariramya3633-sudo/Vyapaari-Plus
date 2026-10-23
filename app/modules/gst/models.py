"""Invoice input models and tax output models for the GST engine.

All amounts are Decimal (floats are rejected) and models are immutable.
Invalid input raises the repo's ValidationError, never a raw pydantic error.
"""

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ValidationError
from app.modules.gst.money import to_decimal
from app.modules.gst.place_of_supply import Regime
from app.modules.gst.states import normalize_state_code

GSTIN_RE = re.compile(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]")
DOC_NO_RE = re.compile(r"[A-Za-z1-9][A-Za-z0-9/-]{0,15}")
PINCODE_RE = re.compile(r"[1-9][0-9]{5}")
HSN_RE = re.compile(r"[0-9]{4}|[0-9]{6}|[0-9]{8}")
SERVICE_PREFIX = "99"


def _amount(value, info: ValidationInfo) -> Decimal:
    return to_decimal(value, info.field_name or "value")


def _optional_amount(value, info: ValidationInfo):
    if value is None:
        return None
    return to_decimal(value, info.field_name or "value")


Amount = Annotated[Decimal, BeforeValidator(_amount)]
OptionalAmount = Annotated[Decimal | None, BeforeValidator(_optional_amount)]


def _describe(exc: PydanticValidationError) -> str:
    parts = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"]) or "input"
        parts.append(f"{where}: {err['msg']}")
    return "; ".join(parts)


def check_doc_no(value: str, field: str = "doc_no") -> str:
    if not DOC_NO_RE.fullmatch(value):
        raise ValidationError(
            f"{field} must be 1-16 characters (letters, digits, / or -) "
            f"and cannot start with 0, / or -: {value!r}"
        )
    return value


def check_hsn_sac_code(code, is_service: bool, field: str = "hsn_sac") -> str:
    if not isinstance(code, str) or not HSN_RE.fullmatch(code):
        raise ValidationError(f"{field} must be 4, 6 or 8 digits: {code!r}")
    if code.startswith(SERVICE_PREFIX) != is_service:
        if is_service:
            raise ValidationError(
                f"{field} {code}: services need a SAC code starting with 99"
            )
        raise ValidationError(
            f"{field} {code}: goods need an HSN code (codes starting with 99 are SAC)"
        )
    return code


def _check_percent(value: Decimal, field: str) -> None:
    if not Decimal("0") <= value <= Decimal("100"):
        raise ValidationError(f"{field} must be between 0 and 100")


class DocType(StrEnum):
    INV = "INV"
    CRN = "CRN"
    DBN = "DBN"


class SupplyType(StrEnum):
    B2B = "B2B"
    B2C = "B2C"


class HsnKind(StrEnum):
    HSN = "HSN"
    SAC = "SAC"


class GstModel(BaseModel):
    """Immutable base model that reports errors as the repo's ValidationError."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def __init__(self, **data):
        try:
            super().__init__(**data)
        except PydanticValidationError as exc:
            raise ValidationError(_describe(exc)) from None


class Party(GstModel):
    name: str
    state_code: str
    gstin: str | None = None
    address: str | None = None
    city: str | None = None
    pincode: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValidationError("name must not be blank")
        return value

    @field_validator("state_code", mode="before")
    @classmethod
    def validate_state_code(cls, value):
        return normalize_state_code(value)

    @field_validator("gstin")
    @classmethod
    def validate_gstin(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip().upper()
        if not GSTIN_RE.fullmatch(value):
            raise ValidationError(f"gstin is not in a valid format: {value!r}")
        return value

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, value: str | None) -> str | None:
        if value is not None and not PINCODE_RE.fullmatch(value):
            raise ValidationError(f"pincode must be a 6-digit PIN code: {value!r}")
        return value

    @model_validator(mode="after")
    def check_gstin_matches_state(self) -> Self:
        if self.gstin is not None and self.gstin[:2] != self.state_code:
            raise ValidationError("gstin must start with the party's state code")
        return self


class LineItem(GstModel):
    description: str
    hsn_sac: str
    quantity: Amount
    unit_price: Amount
    is_service: bool = False
    uqc: str = "NOS"
    discount: Amount = Decimal("0")
    gst_rate: OptionalAmount = None
    cess_rate: Amount = Decimal("0")
    cess_per_unit: Amount = Decimal("0")

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValidationError("description must not be blank")
        return value

    @field_validator("uqc")
    @classmethod
    def validate_uqc(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValidationError("uqc must not be blank")
        return value

    @model_validator(mode="after")
    def check_item(self) -> Self:
        check_hsn_sac_code(self.hsn_sac, self.is_service)
        if self.quantity <= 0:
            raise ValidationError("quantity must be greater than zero")
        if self.unit_price < 0:
            raise ValidationError("unit_price must not be negative")
        if self.discount < 0:
            raise ValidationError("discount must not be negative")
        if self.discount > self.quantity * self.unit_price:
            raise ValidationError("discount cannot exceed quantity x unit_price")
        if self.gst_rate is not None:
            _check_percent(self.gst_rate, "gst_rate")
        _check_percent(self.cess_rate, "cess_rate")
        if self.cess_per_unit < 0:
            raise ValidationError("cess_per_unit must not be negative")
        return self


class OriginalInvoiceRef(GstModel):
    """Points a credit or debit note back at the invoice it adjusts."""

    doc_no: str
    doc_date: date

    @field_validator("doc_no")
    @classmethod
    def validate_doc_no(cls, value: str) -> str:
        return check_doc_no(value)


class Invoice(GstModel):
    doc_no: str
    doc_date: date
    supplier: Party
    buyer: Party
    place_of_supply: str
    supply_type: SupplyType
    items: tuple[LineItem, ...]
    doc_type: DocType = DocType.INV
    reverse_charge: bool = False
    is_sez_or_export: bool = False
    original_invoice: OriginalInvoiceRef | None = None

    @field_validator("doc_no")
    @classmethod
    def validate_doc_no(cls, value: str) -> str:
        return check_doc_no(value)

    @field_validator("place_of_supply", mode="before")
    @classmethod
    def validate_place_of_supply(cls, value):
        return normalize_state_code(value, "place_of_supply")

    @field_validator("items")
    @classmethod
    def validate_items(cls, value: tuple[LineItem, ...]) -> tuple[LineItem, ...]:
        if not value:
            raise ValidationError("items must not be empty")
        return value

    @model_validator(mode="after")
    def check_invoice(self) -> Self:
        if self.supplier.gstin is None:
            raise ValidationError("supplier must have a gstin")
        if self.supply_type is SupplyType.B2B and self.buyer.gstin is None:
            raise ValidationError("a B2B invoice needs the buyer's gstin")
        if self.doc_type is DocType.INV:
            if self.original_invoice is not None:
                raise ValidationError("an invoice cannot reference an original invoice")
        else:
            if self.original_invoice is None:
                raise ValidationError(f"{self.doc_type} needs original_invoice")
            if self.original_invoice.doc_date > self.doc_date:
                raise ValidationError("original invoice date cannot be after the note date")
        return self


class LineTax(GstModel):
    taxable_value: Amount
    cgst: Amount
    sgst: Amount
    igst: Amount
    cess: Amount
    line_total: Amount

    @property
    def tax_total(self) -> Decimal:
        return self.cgst + self.sgst + self.igst + self.cess


class TaxBreakup(GstModel):
    regime: Regime
    lines: tuple[LineTax, ...]
    taxable_total: Amount
    cgst_total: Amount
    sgst_total: Amount
    igst_total: Amount
    cess_total: Amount
    round_off: Amount
    invoice_total: Amount
    rcm_applied: bool
    payable_to_supplier: Amount


class HsnRecord(GstModel):
    code: str
    description: str
    kind: HsnKind
    gst_rate: Amount
    cess_rate: Amount = Decimal("0")

    @model_validator(mode="after")
    def check_record(self) -> Self:
        check_hsn_sac_code(self.code, self.kind is HsnKind.SAC, "code")
        _check_percent(self.gst_rate, "gst_rate")
        _check_percent(self.cess_rate, "cess_rate")
        return self
