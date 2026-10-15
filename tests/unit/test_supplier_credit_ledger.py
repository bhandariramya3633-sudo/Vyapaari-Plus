from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.modules.suppliers.models import (
    Supplier,
    SupplierInvoice,
    SupplierCreditLedger,
    LedgerEntryType,
    PaymentTerms,
)
from app.modules.suppliers.service import SupplierService


def test_invoice_creates_credit_ledger_entry(db_session):
    service = SupplierService(db_session)

    supplier = service.create_supplier(
        name="Test Supplier",
        payment_terms=PaymentTerms.NET_30,
    )

    now = datetime.now()
    invoice = service.record_invoice(
        supplier_id=supplier.id,
        invoice_number="INV-001",
        invoice_date=now,
        due_date=now + timedelta(days=30),
        total_amount=Decimal("1000.00"),
    )

    entries = service.get_supplier_ledger(supplier.id)

    assert invoice.outstanding_balance == Decimal("1000.00")
    assert len(entries) == 1
    assert entries[0].entry_type == LedgerEntryType.INVOICE
    assert entries[0].amount == Decimal("1000.00")


def test_payment_creates_ledger_entry_and_reconciles(db_session):
    service = SupplierService(db_session)

    supplier = service.create_supplier(name="Test Supplier")
    now = datetime.now()

    invoice = service.record_invoice(
        supplier.id,
        "INV-002",
        now,
        now + timedelta(days=30),
        Decimal("1000.00"),
    )

    service.record_payment(
        invoice_id=invoice.id,
        amount=Decimal("400.00"),
        reference="PAY-001",
    )

    db_session.refresh(invoice)
    entries = service.get_supplier_ledger(supplier.id)
    result = service.reconcile_supplier_balance(supplier.id)

    assert invoice.outstanding_balance == Decimal("600.00")
    assert len(entries) == 2
    assert entries[1].entry_type == LedgerEntryType.PAYMENT
    assert result["ledger_balance"] == Decimal("600.00")
    assert result["invoice_balance"] == Decimal("600.00")
    assert result["is_reconciled"] is True


def test_aging_report_groups_overdue_invoice(db_session):
    service = SupplierService(db_session)

    supplier = service.create_supplier(name="Test Supplier")
    now = datetime.now()

    invoice = service.record_invoice(
        supplier.id,
        "INV-003",
        now - timedelta(days=40),
        now - timedelta(days=20),
        Decimal("750.00"),
    )

    report = service.get_aging_report(
        supplier_id=supplier.id,
        as_of=now,
    )

    assert report["buckets"]["16_30_days"] == Decimal("750.00")
    assert report["total_outstanding"] == Decimal("750.00")
    assert len(report["invoices"]) == 1


def test_invoice_rejects_nonpositive_amount(db_session):
    service = SupplierService(db_session)
    supplier = service.create_supplier(name="Test Supplier")
    now = datetime.now()

    with pytest.raises(ValueError, match="positive"):
        service.record_invoice(
            supplier.id,
            "INV-004",
            now,
            now + timedelta(days=30),
            Decimal("0.00"),
        )


def test_reconciliation_rejects_unknown_supplier(db_session):
    service = SupplierService(db_session)

    with pytest.raises(ValueError, match="Supplier not found"):
        service.reconcile_supplier_balance("missing-supplier")