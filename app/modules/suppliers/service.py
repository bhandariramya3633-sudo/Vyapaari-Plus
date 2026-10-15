from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.modules.suppliers.models import (
    Supplier,
    SupplierInvoice,
    SupplierPayment,
    SupplierCreditLedger,
    LedgerEntryType,
    PaymentTerms,
)


ZERO = Decimal("0.00")


class SupplierService:
    """Business logic for supplier credit accounting."""

    def __init__(self, db: Session):
        self.db = db

    def create_supplier(
        self,
        name: str,
        contact_person: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        address: str | None = None,
        payment_terms: PaymentTerms = PaymentTerms.NET_30,
    ) -> Supplier:
        if not name or not name.strip():
            raise ValueError("Supplier name is required.")

        supplier = Supplier(
            id=str(uuid4()),
            name=name.strip(),
            contact_person=contact_person,
            email=email,
            phone=phone,
            address=address,
            payment_terms=payment_terms,
        )

        try:
            self.db.add(supplier)
            self.db.commit()
            self.db.refresh(supplier)
            return supplier
        except Exception:
            self.db.rollback()
            raise

    def record_invoice(
        self,
        supplier_id: str,
        invoice_number: str,
        invoice_date: datetime,
        due_date: datetime,
        total_amount: Decimal,
    ) -> SupplierInvoice:
        """Create an invoice and its credit-ledger entry."""
        total_amount = Decimal(str(total_amount))

        if total_amount <= ZERO:
            raise ValueError("Invoice amount must be positive.")

        if not invoice_number or not invoice_number.strip():
            raise ValueError("Invoice number is required.")

        if due_date < invoice_date:
            raise ValueError("Due date cannot be before invoice date.")

        supplier = self.db.get(Supplier, supplier_id)
        if supplier is None:
            raise ValueError("Supplier not found.")

        invoice = SupplierInvoice(
            id=str(uuid4()),
            supplier_id=supplier_id,
            invoice_number=invoice_number.strip(),
            invoice_date=invoice_date,
            due_date=due_date,
            total_amount=total_amount,
            amount_paid=ZERO,
        )

        try:
            self.db.add(invoice)
            self.db.flush()

            self.db.add(
                SupplierCreditLedger(
                    id=str(uuid4()),
                    supplier_id=supplier_id,
                    invoice_id=invoice.id,
                    entry_type=LedgerEntryType.INVOICE,
                    amount=total_amount,
                    description=f"Invoice {invoice.invoice_number}",
                    entry_date=datetime.now(),
                )
            )

            self.db.commit()
            self.db.refresh(invoice)
            return invoice
        except Exception:
            self.db.rollback()
            raise

    def record_payment(
        self,
        invoice_id: str,
        amount: Decimal,
        reference: str | None = None,
    ) -> SupplierPayment:
        """Record a payment and its corresponding ledger entry."""
        amount = Decimal(str(amount))

        if amount <= ZERO:
            raise ValueError("Payment amount must be positive.")

        try:
            invoice = (
                self.db.query(SupplierInvoice)
                .filter(SupplierInvoice.id == invoice_id)
                .with_for_update()
                .first()
            )

            if invoice is None:
                raise ValueError("Supplier invoice not found.")

            if amount > invoice.outstanding_balance:
                raise ValueError(
                    "Payment exceeds outstanding invoice balance."
                )

            payment = SupplierPayment(
                id=str(uuid4()),
                invoice_id=invoice.id,
                amount=amount,
                reference=reference,
                payment_date=datetime.now(),
            )

            invoice.amount_paid += amount
            self.db.add(payment)
            self.db.flush()

            self.db.add(
                SupplierCreditLedger(
                    id=str(uuid4()),
                    supplier_id=invoice.supplier_id,
                    invoice_id=invoice.id,
                    payment_id=payment.id,
                    entry_type=LedgerEntryType.PAYMENT,
                    amount=amount,
                    description=(
                        f"Payment for invoice {invoice.invoice_number}"
                    ),
                    entry_date=datetime.now(),
                )
            )

            self.db.commit()
            self.db.refresh(payment)
            return payment
        except Exception:
            self.db.rollback()
            raise

    def get_supplier_ledger(
        self,
        supplier_id: str,
    ) -> list[SupplierCreditLedger]:
        """Return ledger entries in chronological order."""
        if self.db.get(Supplier, supplier_id) is None:
            raise ValueError("Supplier not found.")

        return (
            self.db.query(SupplierCreditLedger)
            .filter(SupplierCreditLedger.supplier_id == supplier_id)
            .order_by(
                SupplierCreditLedger.entry_date,
                SupplierCreditLedger.id,
            )
            .all()
        )

    def reconcile_supplier_balance(self, supplier_id: str) -> dict:
        """Compare ledger balance against unpaid invoice balances."""
        entries = self.get_supplier_ledger(supplier_id)

        ledger_balance = sum(
            (entry.signed_amount for entry in entries),
            ZERO,
        )

        invoices = (
            self.db.query(SupplierInvoice)
            .filter(SupplierInvoice.supplier_id == supplier_id)
            .all()
        )

        invoice_balance = sum(
            (invoice.outstanding_balance for invoice in invoices),
            ZERO,
        )

        return {
            "supplier_id": supplier_id,
            "ledger_balance": ledger_balance,
            "invoice_balance": invoice_balance,
            "difference": ledger_balance - invoice_balance,
            "is_reconciled": ledger_balance == invoice_balance,
        }

    def get_aging_report(
        self,
        supplier_id: str | None = None,
        as_of: datetime | None = None,
    ) -> dict:
        """Group outstanding invoices by overdue age."""
        as_of = as_of or datetime.now()

        buckets = {
            "not_due": ZERO,
            "0_15_days": ZERO,
            "16_30_days": ZERO,
            "31_60_days": ZERO,
            "over_60_days": ZERO,
        }

        query = self.db.query(SupplierInvoice)

        if supplier_id is not None:
            if self.db.get(Supplier, supplier_id) is None:
                raise ValueError("Supplier not found.")

            query = query.filter(
                SupplierInvoice.supplier_id == supplier_id
            )

        details = []

        for invoice in query.all():
            outstanding = invoice.outstanding_balance

            if outstanding <= ZERO:
                continue

            overdue_days = (as_of.date() - invoice.due_date.date()).days

            if overdue_days < 0:
                bucket = "not_due"
            elif overdue_days <= 15:
                bucket = "0_15_days"
            elif overdue_days <= 30:
                bucket = "16_30_days"
            elif overdue_days <= 60:
                bucket = "31_60_days"
            else:
                bucket = "over_60_days"

            buckets[bucket] += outstanding

            details.append(
                {
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "supplier_id": invoice.supplier_id,
                    "due_date": invoice.due_date,
                    "outstanding_balance": outstanding,
                    "overdue_days": max(overdue_days, 0),
                    "aging_bucket": bucket,
                }
            )

        return {
            "as_of": as_of,
            "buckets": buckets,
            "total_outstanding": sum(buckets.values(), ZERO),
            "invoices": details,
        }