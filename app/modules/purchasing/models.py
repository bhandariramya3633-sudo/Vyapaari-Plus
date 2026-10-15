from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class PurchaseOrder(Base, TimestampMixin):
    """Purchase order created for a supplier."""

    __tablename__ = "purchase_orders"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    po_number: Mapped[str] = mapped_column(
        String(40), unique=True, nullable=False, index=True
    )
    supplier_id: Mapped[str] = mapped_column(
        ForeignKey("suppliers.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), default="DRAFT", nullable=False
    )
    order_date: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    expected_delivery_date: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
    )
    supplier = relationship("Supplier")

    @property
    def total_amount(self) -> Decimal:
        return sum(
            (
                item.quantity * item.unit_price
                for item in self.items
            ),
            Decimal("0.00"),
        )


class PurchaseOrderItem(Base, TimestampMixin):
    """A product line inside a purchase order."""

    __tablename__ = "purchase_order_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    purchase_order_id: Mapped[str] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.id"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    received_quantity: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )

    purchase_order: Mapped["PurchaseOrder"] = relationship(
        back_populates="items"
    )
    product = relationship("Product")