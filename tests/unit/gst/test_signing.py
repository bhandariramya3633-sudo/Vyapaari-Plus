import hashlib
import io
from datetime import date, datetime

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from PIL import Image

from app.core.exceptions import ValidationError
from app.modules.gst.exceptions import SigningError
from app.modules.gst.models import DocType
from app.modules.gst.signing import (
    ISSUER,
    build_qr_payload,
    compute_demo_irn,
    generate_demo_keypair,
    render_qr_png,
    sign_and_render_qr,
    sign_payload,
    verify,
)

# Fake, format-valid sample GSTINs (checksum is not validated).
SELLER = "24AAACC1206D1ZM"
BUYER = "27AAACB1234F1Z5"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
IRN = "a" * 64
IRN_DATE = datetime(2026, 10, 14, 15, 30, 5)


@pytest.fixture(scope="module")
def keys():
    return generate_demo_keypair()


@pytest.fixture(scope="module")
def other_keys():
    return generate_demo_keypair()


def private_key_object(pem):
    return serialization.load_pem_private_key(pem, password=None)


def make_einvoice():
    return {
        "DocDtls": {"Typ": "INV", "No": "INV-001", "Dt": "14/10/2026"},
        "SellerDtls": {"Gstin": SELLER},
        "BuyerDtls": {"Gstin": BUYER},
        "ItemList": [
            {"HsnCd": "1006", "AssAmt": 100.0},
            {"HsnCd": "8501", "AssAmt": 60000.0},
        ],
        "ValDtls": {"TotInvVal": 70800.0},
    }


def pem_private(key, encryption=None):
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        encryption or serialization.NoEncryption(),
    )


def pem_public(key):
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


# ---------- keys ----------


def test_generated_keys_are_a_2048_bit_rsa_pair(keys):
    private_pem, public_pem = keys
    assert private_pem.startswith(b"-----BEGIN PRIVATE KEY-----")
    assert public_pem.startswith(b"-----BEGIN PUBLIC KEY-----")
    assert private_key_object(private_pem).key_size == 2048


def test_each_generated_pair_is_different(keys, other_keys):
    assert keys[0] != other_keys[0]


# ---------- sign and verify ----------


def test_sign_and_verify_round_trip(keys):
    payload = {"a": 1, "b": [1.5, "x"], "c": {"d": None}}
    token = sign_payload(payload, keys[0])
    assert token.count(".") == 2
    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    assert verify(token, keys[1]) == payload


def test_a_tampered_token_is_rejected(keys):
    token = sign_payload({"amount": 100}, keys[0])
    header, body, signature = token.split(".")
    index = 10
    swapped = "A" if body[index] != "A" else "B"
    tampered = ".".join([header, body[:index] + swapped + body[index + 1:], signature])
    with pytest.raises(SigningError, match="not valid") as exc:
        verify(tampered, keys[1])
    assert exc.value.code == "SIGNING_FAILED"


def test_a_token_signed_by_another_key_is_rejected(keys, other_keys):
    token = sign_payload({"amount": 100}, keys[0])
    with pytest.raises(SigningError, match="not valid"):
        verify(token, other_keys[1])


def test_something_that_is_not_a_token_is_rejected(keys):
    with pytest.raises(SigningError, match="not valid"):
        verify("not-a-token", keys[1])


def test_an_unsigned_token_is_rejected(keys):
    token = jwt.encode({"iss": ISSUER, "data": {"a": 1}}, None, algorithm="none")
    with pytest.raises(SigningError, match="not valid"):
        verify(token, keys[1])


def test_a_token_from_another_issuer_is_rejected(keys):
    token = jwt.encode(
        {"iss": "someone else", "data": {"a": 1}},
        private_key_object(keys[0]),
        algorithm="RS256",
    )
    with pytest.raises(SigningError, match="not valid"):
        verify(token, keys[1])


@pytest.mark.parametrize("claims", [{"iss": ISSUER}, {"iss": ISSUER, "data": "text"}])
def test_a_token_without_a_data_payload_is_rejected(keys, claims):
    token = jwt.encode(claims, private_key_object(keys[0]), algorithm="RS256")
    with pytest.raises(SigningError, match="no data payload"):
        verify(token, keys[1])


def test_payload_must_be_a_dict(keys):
    with pytest.raises(ValidationError, match="must be a dict"):
        sign_payload("text", keys[0])


def test_payload_must_be_serializable(keys):
    with pytest.raises(SigningError, match="cannot be signed"):
        sign_payload({"x": object()}, keys[0])


# ---------- bad keys ----------


@pytest.mark.parametrize("pem", [b"nope", "not bytes", None])
def test_private_key_must_be_a_pem(pem):
    with pytest.raises(SigningError, match="valid unencrypted PEM"):
        sign_payload({"a": 1}, pem)


def test_encrypted_private_key_is_rejected():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    encrypted = pem_private(key, serialization.BestAvailableEncryption(b"secret"))
    with pytest.raises(SigningError, match="valid unencrypted PEM"):
        sign_payload({"a": 1}, encrypted)


def test_private_key_must_be_rsa():
    pem = pem_private(ec.generate_private_key(ec.SECP256R1()))
    with pytest.raises(SigningError, match="RSA private key"):
        sign_payload({"a": 1}, pem)


def test_private_key_must_be_at_least_2048_bits():
    pem = pem_private(rsa.generate_private_key(public_exponent=65537, key_size=1024))
    with pytest.raises(SigningError, match="at least 2048"):
        sign_payload({"a": 1}, pem)


@pytest.mark.parametrize("pem", [b"nope", "not bytes", None])
def test_public_key_must_be_a_pem(keys, pem):
    token = sign_payload({"a": 1}, keys[0])
    with pytest.raises(SigningError, match="valid PEM key"):
        verify(token, pem)


def test_a_private_key_is_not_accepted_as_the_public_key(keys):
    token = sign_payload({"a": 1}, keys[0])
    with pytest.raises(SigningError, match="valid PEM key"):
        verify(token, keys[0])


def test_public_key_must_be_rsa(keys):
    token = sign_payload({"a": 1}, keys[0])
    with pytest.raises(SigningError, match="RSA public key"):
        verify(token, pem_public(ec.generate_private_key(ec.SECP256R1())))


# ---------- QR rendering ----------


def test_render_qr_png_returns_a_square_png():
    png = render_qr_png("hello")
    assert png.startswith(PNG_MAGIC)
    width, height = Image.open(io.BytesIO(png)).size
    assert width == height > 0


def test_longer_text_gives_a_bigger_qr_code():
    small = Image.open(io.BytesIO(render_qr_png("a"))).size[0]
    large = Image.open(io.BytesIO(render_qr_png("a" * 500))).size[0]
    assert large > small


@pytest.mark.parametrize("text", ["", None, 123])
def test_qr_text_must_be_a_non_empty_string(text):
    with pytest.raises(ValidationError, match="non-empty string"):
        render_qr_png(text)


def test_text_too_long_for_a_qr_code_is_rejected():
    with pytest.raises(SigningError, match="too long"):
        render_qr_png("x" * 5000)


def test_sign_and_render_qr(keys):
    payload = {"DocNo": "INV-001", "TotInvVal": 70800.0}
    token, png = sign_and_render_qr(payload, keys[0])
    assert png.startswith(PNG_MAGIC)
    assert verify(token, keys[1]) == payload


def test_sign_and_render_qr_rejects_a_payload_too_big_for_a_qr_code(keys):
    with pytest.raises(SigningError, match="too long"):
        sign_and_render_qr({"blob": "x" * 5000}, keys[0])


# ---------- demo IRN ----------


def expected_irn(financial_year, doc_type="INV", doc_no="INV-001"):
    text = f"{SELLER}{financial_year}{doc_type}{doc_no}"
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.parametrize(
    "doc_date, financial_year",
    [
        (date(2026, 10, 14), "2026-27"),
        (date(2026, 4, 1), "2026-27"),
        (date(2026, 3, 31), "2025-26"),
        (date(2027, 1, 15), "2026-27"),
    ],
)
def test_demo_irn_uses_the_financial_year(doc_date, financial_year):
    irn = compute_demo_irn(SELLER, "INV", "INV-001", doc_date)
    assert irn == expected_irn(financial_year)
    assert len(irn) == 64


def test_demo_irn_accepts_the_doc_type_enum():
    irn = compute_demo_irn(SELLER, DocType.CRN, "CN-7", date(2026, 10, 14))
    assert irn == expected_irn("2026-27", "CRN", "CN-7")


def test_demo_irn_differs_per_document():
    first = compute_demo_irn(SELLER, "INV", "INV-001", date(2026, 10, 14))
    second = compute_demo_irn(SELLER, "INV", "INV-002", date(2026, 10, 14))
    assert first != second


@pytest.mark.parametrize(
    "args, message",
    [
        (("BADGSTIN", "INV", "INV-001", date(2026, 10, 14)), "supplier_gstin"),
        ((None, "INV", "INV-001", date(2026, 10, 14)), "supplier_gstin"),
        ((SELLER, "XYZ", "INV-001", date(2026, 10, 14)), "doc_type"),
        ((SELLER, "INV", 1, date(2026, 10, 14)), "doc_no must be a string"),
        ((SELLER, "INV", "0123", date(2026, 10, 14)), "doc_no"),
        ((SELLER, "INV", "INV-001", "2026-10-14"), "doc_date"),
    ],
)
def test_demo_irn_rejects_invalid_input(args, message):
    with pytest.raises(ValidationError, match=message):
        compute_demo_irn(*args)


# ---------- QR payload ----------


def test_build_qr_payload():
    assert build_qr_payload(make_einvoice(), IRN, IRN_DATE) == {
        "SellerGstin": SELLER,
        "BuyerGstin": BUYER,
        "DocNo": "INV-001",
        "DocTyp": "INV",
        "DocDt": "14/10/2026",
        "TotInvVal": 70800.0,
        "ItemCnt": 2,
        "MainHsnCode": "8501",
        "Irn": IRN,
        "IrnDt": "2026-10-14 15:30:05",
    }


def test_main_hsn_code_is_the_first_of_equally_valued_items():
    einvoice = make_einvoice()
    einvoice["ItemList"] = [
        {"HsnCd": "1006", "AssAmt": 500.0},
        {"HsnCd": "8501", "AssAmt": 500.0},
    ]
    assert build_qr_payload(einvoice, IRN, IRN_DATE)["MainHsnCode"] == "1006"


@pytest.mark.parametrize("irn", ["short", "A" * 64, "a" * 63, 123, None])
def test_irn_must_be_64_lowercase_hex_characters(irn):
    with pytest.raises(ValidationError, match="irn must be"):
        build_qr_payload(make_einvoice(), irn, IRN_DATE)


@pytest.mark.parametrize("irn_date", ["2026-10-14", date(2026, 10, 14), None])
def test_irn_date_must_be_a_datetime(irn_date):
    with pytest.raises(ValidationError, match="irn_date must be"):
        build_qr_payload(make_einvoice(), IRN, irn_date)


def remove_seller(einvoice):
    del einvoice["SellerDtls"]["Gstin"]


def remove_total(einvoice):
    del einvoice["ValDtls"]


def remove_items(einvoice):
    einvoice["ItemList"] = []


def remove_hsn(einvoice):
    del einvoice["ItemList"][1]["HsnCd"]


@pytest.mark.parametrize("breaker", [remove_seller, remove_total, remove_items, remove_hsn])
def test_incomplete_einvoice_payloads_are_rejected(breaker):
    einvoice = make_einvoice()
    breaker(einvoice)
    with pytest.raises(ValidationError, match="incomplete or malformed"):
        build_qr_payload(einvoice, IRN, IRN_DATE)


@pytest.mark.parametrize("einvoice", [None, "text", {}])
def test_non_einvoice_input_is_rejected(einvoice):
    with pytest.raises(ValidationError, match="incomplete or malformed"):
        build_qr_payload(einvoice, IRN, IRN_DATE)


def test_full_flow_from_einvoice_to_a_verified_qr(keys):
    irn = compute_demo_irn(SELLER, "INV", "INV-001", date(2026, 10, 14))
    qr_payload = build_qr_payload(make_einvoice(), irn, IRN_DATE)
    token, png = sign_and_render_qr(qr_payload, keys[0])
    assert png.startswith(PNG_MAGIC)
    assert verify(token, keys[1]) == qr_payload
