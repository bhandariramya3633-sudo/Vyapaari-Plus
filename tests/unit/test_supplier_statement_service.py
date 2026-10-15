import csv
from datetime import datetime
from decimal import Decimal

from app.modules.suppliers.models import (
    LedgerEntryType,
    Supplier,
    SupplierCreditLedger,
)
from app.modules.suppliers.statement_service import (
    SupplierStatementService,
)


def create_supplier_with_ledger(db_session):
    supplier = Supplier(
        id="supplier-statement-test",
        name="Test Supplier",
    )
    db_session.add(supplier)
    db_session.flush()

    invoice_entry = SupplierCreditLedger(
        id="ledger-invoice-test",
        supplier_id=supplier.id,
        entry_type=LedgerEntryType.INVOICE,
        amount=Decimal("1000.00"),
        description="Test invoice",
        entry_date=datetime(2026, 10, 1),
    )

    payment_entry = SupplierCreditLedger(
        id="ledger-payment-test",
        supplier_id=supplier.id,
        entry_type=LedgerEntryType.PAYMENT,
        amount=Decimal("300.00"),
        description="Test payment",
        entry_date=datetime(2026, 10, 5),
    )

    db_session.add_all([invoice_entry, payment_entry])
    db_session.commit()
    return supplier


def test_export_csv_creates_statement_with_running_balance(
    db_session, tmp_path
):
    supplier = create_supplier_with_ledger(db_session)
    output_file = tmp_path / "supplier_statement.csv"

    service = SupplierStatementService(db_session)
    result = service.export_csv(supplier.id, output_file)

    assert result.exists()

    with result.open(
        "r", newline="", encoding="utf-8-sig"
    ) as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 3
    assert rows[0]["entry_type"] == supplier.name
    assert rows[1]["debit"] == "1000.00"
    assert rows[1]["balance"] == "1000.00"
    assert rows[2]["credit"] == "300.00"
    assert rows[2]["balance"] == "700.00"


def test_export_pdf_creates_nonempty_file(db_session, tmp_path):
    supplier = create_supplier_with_ledger(db_session)
    output_file = tmp_path / "supplier_statement.pdf"

    service = SupplierStatementService(db_session)
    result = service.export_pdf(supplier.id, output_file)

    assert result.exists()
    assert result.stat().st_size > 0

    with result.open("rb") as file:
        assert file.read(5) == b"%PDF-"


def test_statement_export_rejects_unknown_supplier(
    db_session, tmp_path
):
    service = SupplierStatementService(db_session)

    try:
        service.export_csv("unknown-supplier", tmp_path / "missing.csv")
        assert False, "Expected ValueError for unknown supplier"
    except ValueError as error:
        assert str(error) == "Supplier not found."