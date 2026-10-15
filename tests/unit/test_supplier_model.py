from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.suppliers.models import (
    Supplier,
    PaymentTerms,
    SupplierInvoice,
    SupplierPayment,
)
from app.modules.suppliers.service import SupplierService


def test_supplier_can_be_saved(db_session):
    supplier = Supplier(
        id="supplier-001",
        name="ABC Traders",
        contact_person="Ravi",
        email="ravi@example.com",
        phone="9876543210",
        payment_terms=PaymentTerms.NET_30,
    )

    db_session.add(supplier)
    db_session.commit()

    saved = db_session.get(Supplier, "supplier-001")

    assert saved is not None
    assert saved.name == "ABC Traders"
    assert saved.payment_terms == PaymentTerms.NET_30
    assert saved.is_active is True


def test_supplier_service_creates_supplier(db_session):
    service = SupplierService(db_session)

    supplier = service.create_supplier(
        name="Fresh Foods Ltd",
        contact_person="Ravi",
        email="fresh@example.com",
        payment_terms=PaymentTerms.NET_15,
    )

    assert supplier.id is not None
    assert supplier.name == "Fresh Foods Ltd"
    assert supplier.payment_terms == PaymentTerms.NET_15
    assert supplier.is_active is True


def test_supplier_service_rejects_blank_name(db_session):
    service = SupplierService(db_session)

    with pytest.raises(ValueError, match="Supplier name is required"):
        service.create_supplier(name="   ")


def create_test_invoice(db_session, total="10000.00"):
    supplier = Supplier(
        id=str(uuid4()),
        name="Invoice Test Supplier",
        payment_terms=PaymentTerms.NET_30,
    )
    db_session.add(supplier)
    db_session.flush()

    invoice = SupplierInvoice(
        id=str(uuid4()),
        supplier_id=supplier.id,
        invoice_number=f"INV-{uuid4().hex[:8]}",
        invoice_date=datetime.now(),
        due_date=datetime.now() + timedelta(days=30),
        total_amount=Decimal(total),
        amount_paid=Decimal("0.00"),
    )
    db_session.add(invoice)
    db_session.commit()

    return invoice


def test_supplier_invoice_outstanding_balance(db_session):
    invoice = create_test_invoice(db_session)
    invoice.amount_paid = Decimal("4000.00")
    db_session.commit()

    assert invoice.outstanding_balance == Decimal("6000.00")


def test_supplier_payment_updates_invoice_balance(db_session):
    invoice = create_test_invoice(db_session)
    service = SupplierService(db_session)

    payment = service.record_payment(
        invoice_id=invoice.id,
        amount=Decimal("4000.00"),
        reference="BANK-001",
    )

    db_session.refresh(invoice)

    assert isinstance(payment, SupplierPayment)
    assert payment.amount == Decimal("4000.00")
    assert payment.reference == "BANK-001"
    assert invoice.amount_paid == Decimal("4000.00")
    assert invoice.outstanding_balance == Decimal("6000.00")


def test_supplier_payment_rejects_excess_amount(db_session):
    invoice = create_test_invoice(db_session, total="1000.00")
    service = SupplierService(db_session)

    with pytest.raises(ValueError, match="exceeds outstanding"):
        service.record_payment(
            invoice_id=invoice.id,
            amount=Decimal("1500.00"),
        )

    db_session.refresh(invoice)
    assert invoice.amount_paid == Decimal("0.00")


def test_supplier_payment_rejects_zero_amount(db_session):
    invoice = create_test_invoice(db_session)
    service = SupplierService(db_session)

    with pytest.raises(ValueError, match="must be positive"):
        service.record_payment(
            invoice_id=invoice.id,
            amount=Decimal("0.00"),
        )


def test_supplier_payment_rejects_unknown_invoice(db_session):
    service = SupplierService(db_session)

    with pytest.raises(ValueError, match="invoice not found"):
        service.record_payment(
            invoice_id="missing-invoice",
            amount=Decimal("100.00"),
        )