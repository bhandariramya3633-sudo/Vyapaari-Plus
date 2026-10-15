import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    String,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class PaymentTerms(str, enum.Enum):
    NET_15 = "NET_15"
    NET_30 = "NET_30"
    NET_60 = "NET_60"
    COD = "COD"


class LedgerEntryType(str, enum.Enum):
    INVOICE = "INVOICE"
    PAYMENT = "PAYMENT"
    ADJUSTMENT = "ADJUSTMENT"


class Supplier(Base, TimestampMixin):
    """Stores supplier details and payment terms."""

    __tablename__ = "suppliers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(
        String(150), nullable=False, index=True
    )
    contact_person: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    email: Mapped[str | None] = mapped_column(
        String(150), nullable=True
    )
    phone: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    address: Mapped[str | None] = mapped_column(
        String(300), nullable=True
    )
    payment_terms: Mapped[PaymentTerms] = mapped_column(
        Enum(PaymentTerms),
        default=PaymentTerms.NET_30,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )


class SupplierInvoice(Base, TimestampMixin):
    """An invoice received from a supplier."""

    __tablename__ = "supplier_invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False, index=True
    )
    invoice_number: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    invoice_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False
    )
    due_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    supplier: Mapped["Supplier"] = relationship()

    @property
    def outstanding_balance(self) -> Decimal:
        return self.total_amount - self.amount_paid


class SupplierPayment(Base, TimestampMixin):
    """Records a payment made against a supplier invoice."""

    __tablename__ = "supplier_payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey("supplier_invoices.id"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    payment_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    reference: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    invoice: Mapped["SupplierInvoice"] = relationship()


class SupplierCreditLedger(Base, TimestampMixin):
    """Tracks supplier invoices, payments, and adjustments."""

    __tablename__ = "supplier_credit_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False, index=True
    )
    invoice_id: Mapped[str | None] = mapped_column(
        ForeignKey("supplier_invoices.id"),
        nullable=True,
        index=True,
    )
    payment_id: Mapped[str | None] = mapped_column(
        ForeignKey("supplier_payments.id"),
        nullable=True,
        index=True,
    )
    entry_type: Mapped[LedgerEntryType] = mapped_column(
        Enum(LedgerEntryType), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    description: Mapped[str] = mapped_column(
        String(250), nullable=False
    )
    entry_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    supplier: Mapped["Supplier"] = relationship()
    invoice: Mapped["SupplierInvoice"] = relationship()
    payment: Mapped["SupplierPayment"] = relationship()

    @property
    def signed_amount(self) -> Decimal:
        """Invoices increase debt; payments reduce debt."""
        if self.entry_type == LedgerEntryType.PAYMENT:
            return -self.amount
        return self.amount