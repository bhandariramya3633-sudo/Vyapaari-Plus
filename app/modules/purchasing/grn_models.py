from datetime import datetime
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


class GoodsReceipt(Base, TimestampMixin):
    """Goods Receipt Note recorded against a purchase order."""

    __tablename__ = "goods_receipts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    grn_number: Mapped[str] = mapped_column(
        String(40), unique=True, nullable=False, index=True
    )
    purchase_order_id: Mapped[str] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=False, index=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    purchase_order = relationship("PurchaseOrder")
    lines: Mapped[list["GoodsReceiptLine"]] = relationship(
        back_populates="goods_receipt",
        cascade="all, delete-orphan",
    )


class GoodsReceiptLine(Base, TimestampMixin):
    """Quantity received for a purchase order item."""

    __tablename__ = "goods_receipt_lines"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    goods_receipt_id: Mapped[str] = mapped_column(
        ForeignKey("goods_receipts.id"), nullable=False, index=True
    )
    purchase_order_item_id: Mapped[str] = mapped_column(
        ForeignKey("purchase_order_items.id"), nullable=False, index=True
    )
    quantity_received: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    unit_price: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    goods_receipt = relationship(
        "GoodsReceipt",
        back_populates="lines",
    )
    purchase_order_item = relationship("PurchaseOrderItem")