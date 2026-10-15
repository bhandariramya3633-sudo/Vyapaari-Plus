from sqlalchemy.orm import Session

from app.modules.products.models import Product
from app.modules.purchasing.models import PurchaseOrder, PurchaseOrderItem


class PurchaseOrderRepository:
    """Database operations for purchase orders."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, purchase_order_id: str) -> PurchaseOrder | None:
        return self.db.get(PurchaseOrder, purchase_order_id)

    def get_by_number(self, po_number: str) -> PurchaseOrder | None:
        return (
            self.db.query(PurchaseOrder)
            .filter(PurchaseOrder.po_number == po_number)
            .first()
        )

    def get_by_supplier(
        self, supplier_id: str
    ) -> list[PurchaseOrder]:
        return (
            self.db.query(PurchaseOrder)
            .filter(PurchaseOrder.supplier_id == supplier_id)
            .order_by(PurchaseOrder.order_date.desc())
            .all()
        )

    def get_by_status(self, status: str) -> list[PurchaseOrder]:
        return (
            self.db.query(PurchaseOrder)
            .filter(PurchaseOrder.status == status)
            .order_by(PurchaseOrder.order_date.desc())
            .all()
        )

    def get_low_stock_products(self) -> list[Product]:
        """Find active products at or below their reorder point."""
        return (
            self.db.query(Product)
            .filter(
                Product.is_active.is_(True),
                Product.primary_supplier_id.is_not(None),
                Product.current_stock <= Product.reorder_point,
            )
            .order_by(Product.primary_supplier_id, Product.name)
            .all()
        )

    def add_order(self, order: PurchaseOrder) -> PurchaseOrder:
        self.db.add(order)
        self.db.flush()
        return order

    def add_order_item(
        self, item: PurchaseOrderItem
    ) -> PurchaseOrderItem:
        self.db.add(item)
        self.db.flush()
        return item

    def save(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()