import json
import runpy
import sys
from datetime import datetime

import pytest

from app.modules.gst.demo import (
    FILE_NAMES,
    NOTICE,
    build_demo_invoice,
    main,
    run_demo,
)
from app.modules.gst.signing import verify

IRN_DATE = datetime(2026, 10, 14, 15, 30, 5)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_demo_invoice_is_clearly_sample_data():
    invoice = build_demo_invoice()
    assert "SAMPLE" in invoice.supplier.name
    assert "SAMPLE" in invoice.buyer.name
    assert len(invoice.items) == 2


def test_run_demo_writes_every_file(tmp_path):
    files, breakup, verified = run_demo(tmp_path, irn_date=IRN_DATE)
    assert tuple(files) == FILE_NAMES
    for path in files.values():
        assert path.is_file()
        assert path.parent == tmp_path
        assert path.stat().st_size > 0
    assert verified is True
    assert str(breakup.invoice_total) == "76628.00"


def test_run_demo_creates_missing_folders(tmp_path):
    target = tmp_path / "a" / "b"
    files, _, _ = run_demo(target, irn_date=IRN_DATE)
    assert files["einvoice.json"].parent == target


def test_outputs_agree_with_each_other(tmp_path):
    files, _, _ = run_demo(tmp_path, irn_date=IRN_DATE)
    einvoice = load(files["einvoice.json"])
    eway = load(files["eway_bill.json"])
    assert einvoice["ValDtls"]["TotInvVal"] == 76628.0
    assert eway["totInvValue"] == 76628.0
    assert einvoice["ValDtls"]["IgstVal"] == eway["igstValue"] == 11077.5
    part_a = load(files["eway_bill_part_a.json"])
    part_b = load(files["eway_bill_part_b.json"])
    assert {**part_a, **part_b} == eway
    assert part_b["vehicleNo"] == "MH12AB1234"
    assert load(files["tax_breakup.json"])["invoice_total"] == "76628.00"


def test_the_signed_qr_verifies_with_the_written_public_key(tmp_path):
    files, _, _ = run_demo(tmp_path, irn_date=IRN_DATE)
    qr_payload = load(files["qr_payload.json"])
    token = files["signed_qr_token.txt"].read_text(encoding="ascii")
    public_pem = files["demo_public_key.pem"].read_bytes()
    assert verify(token, public_pem) == qr_payload
    assert qr_payload["IrnDt"] == "2026-10-14 15:30:05"
    assert qr_payload["MainHsnCode"] == "8471"
    assert files["invoice_qr.png"].read_bytes().startswith(PNG_MAGIC)


def test_the_private_key_is_never_written(tmp_path):
    files, _, _ = run_demo(tmp_path, irn_date=IRN_DATE)
    for path in files.values():
        assert b"PRIVATE KEY" not in path.read_bytes()


def test_notice_says_the_data_is_sample(tmp_path):
    files, _, _ = run_demo(tmp_path, irn_date=IRN_DATE)
    text = files["NOTICE.txt"].read_text(encoding="ascii")
    assert text == NOTICE
    assert text.startswith("SAMPLE DATA")


def test_main_prints_a_summary(tmp_path, capsys):
    assert main(["--out", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "SAMPLE DATA" in output
    assert "76628.00" in output
    assert "verified (demo key): True" in output
    assert (tmp_path / "einvoice.json").is_file()


def test_main_uses_a_default_output_folder(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main([]) == 0
    capsys.readouterr()
    assert (tmp_path / "gst_demo_output" / "einvoice.json").is_file()


def test_module_runs_as_a_script(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["demo", "--out", str(tmp_path)])
    monkeypatch.delitem(sys.modules, "app.modules.gst.demo", raising=False)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("app.modules.gst.demo", run_name="__main__")
    assert exc.value.code == 0
    assert "SAMPLE DATA" in capsys.readouterr().out
    assert (tmp_path / "invoice_qr.png").is_file()
