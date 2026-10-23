"""Runnable demo of the GST flow on SAMPLE data.

Run from the repo root:  python -m app.modules.gst.demo [--out FOLDER]

It builds a sample invoice, calculates the tax, builds the e-invoice and
e-way bill JSON, makes a demo IRN, signs the QR payload with a throw-away RSA
key and checks the signature. Everything is SAMPLE data. The IRN and the
signature are local demo values, not issued by the IRP. The private key stays
in memory and is never written to disk.
"""

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from app.modules.gst.einvoice import build_einvoice_json
from app.modules.gst.eway import Transport, build_eway_bill_json, split_parts
from app.modules.gst.hsn import hsn_rate
from app.modules.gst.invoice_calc import calculate_invoice
from app.modules.gst.models import Invoice, LineItem, Party
from app.modules.gst.signing import (
    build_qr_payload,
    compute_demo_irn,
    generate_demo_keypair,
    sign_and_render_qr,
    verify,
)

DEFAULT_OUT = Path("gst_demo_output")
SAMPLE_SUPPLIER_GSTIN = "24AAACC1206D1ZM"
SAMPLE_BUYER_GSTIN = "27AAACB1234F1Z5"
FILE_NAMES = (
    "tax_breakup.json",
    "einvoice.json",
    "eway_bill.json",
    "eway_bill_part_a.json",
    "eway_bill_part_b.json",
    "qr_payload.json",
    "signed_qr_token.txt",
    "invoice_qr.png",
    "demo_public_key.pem",
    "NOTICE.txt",
)
NOTICE = (
    "SAMPLE DATA - for demonstration only.\n"
    "These files describe a made-up invoice with fake GSTINs.\n"
    "The IRN and the signature are local demo values, not issued by the IRP,\n"
    "and the JSON schemas used are derived, not the official NIC files.\n"
)


def build_demo_invoice() -> Invoice:
    supplier = Party(
        name="SAMPLE Traders (demo)", state_code="24", gstin=SAMPLE_SUPPLIER_GSTIN,
        address="1 Sample Road", city="Sample City", pincode="390001",
    )
    buyer = Party(
        name="SAMPLE Buyer (demo)", state_code="27", gstin=SAMPLE_BUYER_GSTIN,
        address="5 Sample Lane", city="Mumbai", pincode="400001",
    )
    items = [
        LineItem(
            description="Sample desktop computer", hsn_sac="8471",
            quantity="2", unit_price="30000.00",
        ),
        LineItem(
            description="Sample basmati rice 5kg", hsn_sac="1006",
            quantity="100", unit_price="55.50",
        ),
    ]
    return Invoice(
        doc_no="DEMO-001", doc_date=date(2026, 10, 14), supplier=supplier,
        buyer=buyer, place_of_supply="27", supply_type="B2B", items=items,
    )


def build_demo_transport() -> Transport:
    return Transport(mode="ROAD", distance_km=450, vehicle_no="MH12AB1234")


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_demo(out_dir, irn_date: datetime | None = None):
    """Run the flow and write the files. Returns (files, tax breakup, verified)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    invoice = build_demo_invoice()
    breakup = calculate_invoice(invoice, hsn_rate)
    einvoice = build_einvoice_json(invoice, breakup, rate_lookup=hsn_rate)
    eway = build_eway_bill_json(
        invoice, breakup, build_demo_transport(), rate_lookup=hsn_rate
    )
    irn = compute_demo_irn(
        invoice.supplier.gstin, invoice.doc_type, invoice.doc_no, invoice.doc_date
    )
    qr_payload = build_qr_payload(einvoice, irn, irn_date or datetime.now())
    private_pem, public_pem = generate_demo_keypair()
    token, png = sign_and_render_qr(qr_payload, private_pem)
    verified = verify(token, public_pem) == qr_payload
    part_a, part_b = split_parts(eway)

    files = {name: out / name for name in FILE_NAMES}
    _write_json(files["tax_breakup.json"], breakup.model_dump(mode="json"))
    _write_json(files["einvoice.json"], einvoice)
    _write_json(files["eway_bill.json"], eway)
    _write_json(files["eway_bill_part_a.json"], part_a)
    _write_json(files["eway_bill_part_b.json"], part_b)
    _write_json(files["qr_payload.json"], qr_payload)
    files["signed_qr_token.txt"].write_text(token, encoding="ascii")
    files["invoice_qr.png"].write_bytes(png)
    files["demo_public_key.pem"].write_bytes(public_pem)
    files["NOTICE.txt"].write_text(NOTICE, encoding="ascii")
    return files, breakup, verified


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the GST flow on SAMPLE data.")
    parser.add_argument(
        "--out", default=str(DEFAULT_OUT), help="folder for the output files"
    )
    args = parser.parse_args(argv)
    files, breakup, verified = run_demo(Path(args.out))
    print("SAMPLE DATA - demonstration only, not a real invoice")
    print(f"Regime                 : {breakup.regime.value}")
    print(f"Taxable value          : {breakup.taxable_total}")
    print(
        "CGST / SGST / IGST     : "
        f"{breakup.cgst_total} / {breakup.sgst_total} / {breakup.igst_total}"
    )
    print(f"Cess                   : {breakup.cess_total}")
    print(f"Round-off              : {breakup.round_off}")
    print(f"Invoice total          : {breakup.invoice_total}")
    print(f"QR signature verified (demo key): {verified}")
    print("Files written:")
    for path in files.values():
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
