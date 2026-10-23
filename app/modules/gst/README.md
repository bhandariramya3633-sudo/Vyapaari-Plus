# GST Invoicing Engine and E-Way Bill Builder

Python package `app/modules/gst` for Vyapaari+. It turns invoice line items into
correct GST amounts and the JSON documents that go with them. It has no UI and
no database; the billing module can call it as a library.

## Read this first: what is real and what is not

| Part | Status |
| --- | --- |
| Tax maths (CGST/SGST/IGST, cess, RCM, round-off, credit notes) | Implemented and tested |
| HSN/SAC data (`data/hsn_sample.csv`) | **SAMPLE data**. Codes and rates are illustrative. Load the official master with `HsnCache(load_records(path))` before real use |
| E-invoice and e-way bill JSON schemas (`schemas/`) | **DERIVED** from the public NIC formats as the author understands them. They are **not** the official NIC files. Swap in the official schemas before real use |
| IRN | `compute_demo_irn` is a **local stand-in**. The real IRN is issued by the IRP |
| QR signature | Signed with **your own RSA key** (RS256 JWT) for demo and verification. The legally valid signed QR comes from the IRP. The signer is a separate module, so an IRP flow can replace it |
| Tax rules that change (`config.py`) | E-way bill threshold and max distance are from the author's knowledge. **Verify on the official portals before a release** |

The package is checked against its own tests only. It has not been validated
against the live IRP or e-way bill portal.

## Flow

## Quick start (Windows PowerShell, from the repo root)

The demo builds a SAMPLE invoice and writes the tax breakup, e-invoice JSON,
e-way bill JSON (whole, Part A, Part B), QR payload, signed token, QR image and
the demo public key to `gst_demo_output/`. The private key stays in memory.

## Using it from code

```python
from app.modules.gst.hsn import hsn_rate
from app.modules.gst.invoice_calc import calculate_invoice
from app.modules.gst.einvoice import build_einvoice_json

breakup = calculate_invoice(invoice, hsn_rate)
einvoice = build_einvoice_json(invoice, breakup, rate_lookup=hsn_rate)
```

| Function | Module | Purpose |
| --- | --- | --- |
| `resolve_hsn`, `search_hsn`, `hsn_rate` | `hsn` | Exact, longest-prefix and search lookups over the in-memory cache |
| `calculate_invoice(invoice, rate_lookup=None)` | `invoice_calc` | Returns a `TaxBreakup` |
| `calculate_credit_note(credit_note, original=None, rate_lookup=None)` | `credit_note` | Same maths with original-invoice checks |
| `build_einvoice_json(invoice, breakup, rate_lookup=None, sez_export_type=None)` | `einvoice` | Validated e-invoice payload |
| `build_eway_bill_json(invoice, breakup, transport, rate_lookup=None, allow_below_threshold=False)` | `eway` | Validated e-way bill payload |
| `split_parts(payload)` | `eway` | `(Part A, Part B)` |
| `compute_demo_irn`, `build_qr_payload`, `sign_and_render_qr`, `verify`, `generate_demo_keypair` | `signing` | Demo IRN, QR payload, RS256 signing, PNG QR, verification |

Bad input raises errors that extend the repo's `VyapaariException`
(`ValidationError`, `EntityNotFoundError`, `SchemaValidationError`, `SigningError`).

## Tax rules implemented

- All money is `Decimal`. Floats are rejected. Rounding is half-up.
- The place of supply, not the buyer's address, decides the regime. Different
  state from the supplier means INTER (IGST). SEZ and export are always INTER.
- Line tax is rounded to paise. For INTRA, CGST and SGST are each half the rate,
  rounded separately, so an odd-paise total can differ by one paisa from the
  IGST figure.
- Cess is ad valorem plus a specific amount per unit, in both regimes.
- The invoice total is rounded to the nearest rupee and the difference is shown
  as the round-off.
- Reverse charge (RCM): tax is shown, but `payable_to_supplier` covers the
  taxable value only.
- Credit notes keep positive amounts. They must reference the original invoice,
  share its parties and place of supply, and not exceed its taxable value.
- In union territories without a legislature the SGST figure is UTGST
  (`states.is_utgst_territory`).

## Known limits

- GSTIN is checked for format and state code, not for the checksum digit.
- E-invoice: B2B, SEZWP, SEZWOP and DEXP only. B2C is not reported. Exports
  (EXPWP, EXPWOP) are not supported. The UQC unit list is not enforced.
- E-way bill: goods invoices only (no credit/debit notes, no service lines).
  `hsnCode` is a JSON number, so a leading zero is dropped (0401 becomes 401).
  The vehicle number check is a simple pattern.
- GST slabs are not hardcoded. Rates come from the item or from HSN/SAC data.
- The state code list should be cross-checked against the official GST list.

## Layout

## Tests and coverage

Every file in `app/modules/gst` is at 100% line coverage. The tests cover
every inter/intra-state, cess, RCM and B2B/B2C combination, odd-paise and
round-off cases, credit notes, schema failures, signing failures, and an
end-to-end flow with the real HSN cache and real signing.

## HSN lookup benchmark




It uses the sample data and a synthetic set of 20,000 codes (labelled
synthetic). The sub-millisecond target applies to exact lookup, longest-prefix
lookup and code-prefix search. Description search scans every description, so
it is reported for information only.

Measured by the author on 2026-10-16 (Windows, Python 3.14.3): about 0.3 us per
exact lookup, 0.7 us for longest-prefix, 6 us for code-prefix search and 112 us
for the description scan. These numbers depend on the machine; run the script
to see your own.
