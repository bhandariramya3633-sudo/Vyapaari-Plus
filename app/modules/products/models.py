from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin


class Product(Base, TimestampMixin):
    """Product details and supplier-linked reorder settings."""

    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sku: Mapped[str] = mapped_column(
        String(80), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)

    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    current_stock: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    reorder_point: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    reorder_quantity: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )

    primary_supplier_id: Mapped[str | None] = mapped_column(
        ForeignKey("suppliers.id"), nullable=True, index=True
    )

    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    primary_supplier = relationship("Supplier")

    def __repr__(self) -> str:
        return f"Product(sku={self.sku!r}, name={self.name!r})"