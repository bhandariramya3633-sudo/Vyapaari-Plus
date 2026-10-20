import enum
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Integer,
    Float,
    DateTime,
    Enum,
    ForeignKey,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


def utc_now() -> datetime:
    """Return UTC time compatible with existing naive DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TransferStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"


class Branch(Base, TimestampMixin):
    __tablename__ = "branches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    is_warehouse: Mapped[bool] = mapped_column(default=False, nullable=False)


class StoreLocations(Base, TimestampMixin):
    """Physical store or warehouse location associated with a branch."""

    __tablename__ = "store_locations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    branch_id: Mapped[str] = mapped_column(
        ForeignKey("branches.id"),
        unique=True,
        nullable=False,
        index=True,
    )
    location_code: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False
    )
    location_name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class StockBatch(Base, TimestampMixin):
    __tablename__ = "stock_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    product_id: Mapped[str] = mapped_column(
        String(36), index=True, nullable=False
    )
    branch_id: Mapped[str] = mapped_column(
        ForeignKey("branches.id"), nullable=False, index=True
    )
    batch_number: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    purchase_price: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )
    selling_price: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )
    expiry_date: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )


class StockTransfer(Base, TimestampMixin):
    """Model for inter-store and branch stock transfers."""

    __tablename__ = "stock_transfers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transfer_number: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    gate_pass_number: Mapped[str | None] = mapped_column(
        String(50), unique=True, nullable=True
    )
    source_branch_id: Mapped[str] = mapped_column(
        ForeignKey("branches.id"), nullable=False
    )
    destination_branch_id: Mapped[str] = mapped_column(
        ForeignKey("branches.id"), nullable=False
    )
    status: Mapped[TransferStatus] = mapped_column(
        Enum(TransferStatus), default=TransferStatus.DRAFT, nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    dispatched_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    received_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    vehicle_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    driver_contact: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    items: Mapped[list["TransferItem"]] = relationship(
        "TransferItem",
        back_populates="transfer",
        cascade="all, delete-orphan",
    )
    reconciliation: Mapped["ReconciliationLog | None"] = relationship(
        "ReconciliationLog",
        back_populates="transfer",
        uselist=False,
    )


class TransferItem(Base, TimestampMixin):
    """Items included in a stock transfer."""

    __tablename__ = "transfer_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transfer_id: Mapped[str] = mapped_column(
        ForeignKey("stock_transfers.id"), nullable=False
    )
    product_id: Mapped[str] = mapped_column(String(36), nullable=False)
    product_name: Mapped[str] = mapped_column(String(150), nullable=False)
    batch_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    quantity_dispatched: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    quantity_received: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    quantity_damaged: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    unit_cost: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )

    transfer: Mapped["StockTransfer"] = relationship(
        "StockTransfer", back_populates="items"
    )


class ReconciliationLog(Base, TimestampMixin):
    """Reconciliation record for inter-branch inventory transfers."""

    __tablename__ = "reconciliation_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transfer_id: Mapped[str] = mapped_column(
        ForeignKey("stock_transfers.id"), unique=True, nullable=False
    )
    total_dispatched_units: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    total_received_units: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    variance_units: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    total_transit_loss_value: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )
    reconciled_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    resolution_status: Mapped[str] = mapped_column(
        String(50), default="PENDING", nullable=False
    )
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    transfer: Mapped["StockTransfer"] = relationship(
        "StockTransfer", back_populates="reconciliation"
    )


class InTransitLog(Base, TimestampMixin):
    """Auditable record of stock-transfer events."""

    __tablename__ = "in_transit_logs"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_in_transit_logs_idempotency_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transfer_id: Mapped[str] = mapped_column(
        ForeignKey("stock_transfers.id"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False
    )