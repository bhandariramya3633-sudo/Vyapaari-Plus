"""QR payload, RS256 signing and QR rendering for e-invoices.

The legally valid signed QR comes from the IRP (NIC). This module is the local
demo/verification path: it signs with your own RSA key, and the IRN here is
computed locally (compute_demo_irn), not registered. Never present either as
a government-issued value.

- sign_payload / verify use an RS256 JWT with issuer ISSUER; unsigned tokens,
  other algorithms, other issuers and tampered tokens are rejected.
- Keys are RSA, at least 2048 bits. generate_demo_keypair keeps keys in memory
  only. Never commit a private key.
- render_qr_png draws the token as a PNG QR code; data that is too long for a
  QR code raises SigningError.
"""

import hashlib
import io
import re
from datetime import date, datetime

import jwt
import qrcode
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from qrcode.constants import ERROR_CORRECT_M
from qrcode.exceptions import DataOverflowError

from app.core.exceptions import ValidationError
from app.modules.gst.exceptions import SigningError
from app.modules.gst.models import GSTIN_RE, DocType, check_doc_no

ISSUER = "Vyapaari+ demo signer"
ALGORITHM = "RS256"
MIN_KEY_BITS = 2048
IRN_RE = re.compile(r"[0-9a-f]{64}")
DOC_TYPES = frozenset(doc_type.value for doc_type in DocType)


def generate_demo_keypair() -> tuple[bytes, bytes]:
    """Return (private PEM, public PEM) for a new 2048-bit RSA key, in memory only."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=MIN_KEY_BITS)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _load_private_key(pem):
    try:
        key = serialization.load_pem_private_key(pem, password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise SigningError("private key is not a valid unencrypted PEM key") from None
    if not isinstance(key, rsa.RSAPrivateKey):
        raise SigningError("an RSA private key is required")
    if key.key_size < MIN_KEY_BITS:
        raise SigningError(f"the RSA key must be at least {MIN_KEY_BITS} bits")
    return key


def _load_public_key(pem):
    try:
        key = serialization.load_pem_public_key(pem)
    except (ValueError, TypeError, UnsupportedAlgorithm):
        raise SigningError("public key is not a valid PEM key") from None
    if not isinstance(key, rsa.RSAPublicKey):
        raise SigningError("an RSA public key is required")
    return key


def sign_payload(payload: dict, private_key_pem: bytes) -> str:
    """Sign a JSON-serializable dict as an RS256 JWT."""
    if not isinstance(payload, dict):
        raise ValidationError("payload must be a dict")
    key = _load_private_key(private_key_pem)
    try:
        return jwt.encode({"iss": ISSUER, "data": payload}, key, algorithm=ALGORITHM)
    except (TypeError, ValueError) as exc:
        raise SigningError(f"payload cannot be signed: {exc}") from None


def verify(token: str, public_key_pem: bytes) -> dict:
    """Check the signature, algorithm and issuer; return the signed payload."""
    key = _load_public_key(public_key_pem)
    try:
        claims = jwt.decode(token, key, algorithms=[ALGORITHM], issuer=ISSUER)
    except jwt.PyJWTError as exc:
        raise SigningError(f"token is not valid: {exc}") from None
    data = claims.get("data")
    if not isinstance(data, dict):
        raise SigningError("token has no data payload")
    return data


def render_qr_png(text: str) -> bytes:
    """Draw text as a PNG QR code."""
    if not isinstance(text, str) or not text:
        raise ValidationError("QR text must be a non-empty string")
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=4, border=2)
    qr.add_data(text)
    try:
        qr.make(fit=True)
    except (DataOverflowError, ValueError):
        raise SigningError("data is too long for a QR code") from None
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def sign_and_render_qr(payload: dict, private_key_pem: bytes) -> tuple[str, bytes]:
    """Sign a payload and draw the signed token as a QR code: (token, PNG bytes)."""
    token = sign_payload(payload, private_key_pem)
    return token, render_qr_png(token)


def financial_year(doc_date: date) -> str:
    """Indian financial year (April to March) as '2026-27'."""
    start = doc_date.year if doc_date.month >= 4 else doc_date.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def compute_demo_irn(supplier_gstin, doc_type, doc_no, doc_date) -> str:
    """Locally computed stand-in for the IRN. The real IRN is issued by the IRP.

    SHA-256 of supplier GSTIN + financial year + document type + document number.
    """
    if not isinstance(supplier_gstin, str) or not GSTIN_RE.fullmatch(supplier_gstin):
        raise ValidationError(f"supplier_gstin is not in a valid format: {supplier_gstin!r}")
    if str(doc_type) not in DOC_TYPES:
        raise ValidationError(f"doc_type must be one of INV, CRN, DBN: {doc_type!r}")
    if not isinstance(doc_no, str):
        raise ValidationError("doc_no must be a string")
    check_doc_no(doc_no)
    if not isinstance(doc_date, date):
        raise ValidationError("doc_date must be a date")
    text = f"{supplier_gstin}{financial_year(doc_date)}{doc_type}{doc_no}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_qr_payload(einvoice: dict, irn: str, irn_date: datetime) -> dict:
    """Fields that go into the invoice QR code, taken from a built e-invoice payload."""
    if not isinstance(irn, str) or not IRN_RE.fullmatch(irn):
        raise ValidationError("irn must be 64 lowercase hex characters")
    if not isinstance(irn_date, datetime):
        raise ValidationError("irn_date must be a datetime")
    try:
        items = einvoice["ItemList"]
        main_item = max(items, key=lambda item: item["AssAmt"])
        return {
            "SellerGstin": einvoice["SellerDtls"]["Gstin"],
            "BuyerGstin": einvoice["BuyerDtls"]["Gstin"],
            "DocNo": einvoice["DocDtls"]["No"],
            "DocTyp": einvoice["DocDtls"]["Typ"],
            "DocDt": einvoice["DocDtls"]["Dt"],
            "TotInvVal": einvoice["ValDtls"]["TotInvVal"],
            "ItemCnt": len(items),
            "MainHsnCode": main_item["HsnCd"],
            "Irn": irn,
            "IrnDt": irn_date.strftime("%Y-%m-%d %H:%M:%S"),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError(f"e-invoice payload is incomplete or malformed: {exc!r}") from None
