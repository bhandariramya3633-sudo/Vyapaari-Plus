from collections import defaultdict
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.modules.purchasing.models import PurchaseOrder, PurchaseOrderItem
from app.modules.purchasing.repository import PurchaseOrderRepository


class PurchaseOrderService:
    """Generate and manage draft purchase orders."""

    VALID_STATUSES = {
        "DRAFT",
        "PENDING_APPROVAL",
        "DISPATCHED",
        "PARTIALLY_RECEIVED",
        "FULFILLED",
        "CANCELLED",
    }

    def __init__(self, db: Session):
        self.db = db
        self.repository = PurchaseOrderRepository(db)

    def generate_draft_orders(self) -> list[PurchaseOrder]:
        """Create one draft order per supplier for low-stock products."""
        products = self.repository.get_low_stock_products()

        products_by_supplier = defaultdict(list)
        for product in products:
            if product.primary_supplier_id:
                products_by_supplier[product.primary_supplier_id].append(
                    product
                )

        created_orders = []

        try:
            for supplier_id, supplier_products in products_by_supplier.items():
                po_number = self._generate_po_number()

                order = PurchaseOrder(
                    id=str(uuid4()),
                    po_number=po_number,
                    supplier_id=supplier_id,
                    status="DRAFT",
                )
                self.repository.add_order(order)

                for product in supplier_products:
                    quantity = max(
                        product.reorder_quantity - product.current_stock,
                        1,
                    )

                    item = PurchaseOrderItem(
                        id=str(uuid4()),
                        purchase_order_id=order.id,
                        product_id=product.id,
                        quantity=quantity,
                        received_quantity=0,
                        unit_price=Decimal(str(product.unit_cost)),
                    )
                    self.repository.add_order_item(item)

                created_orders.append(order)

            self.repository.save()
            return created_orders

        except Exception:
            self.repository.rollback()
            raise

    def get_order(self, purchase_order_id: str) -> PurchaseOrder:
        order = self.repository.get_by_id(purchase_order_id)
        if order is None:
            raise ValueError("Purchase order not found.")
        return order

    def update_status(
        self, purchase_order_id: str, new_status: str
    ) -> PurchaseOrder:
        if new_status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid purchase order status: {new_status}")

        order = self.get_order(purchase_order_id)

        allowed_transitions = {
            "DRAFT": {"PENDING_APPROVAL", "CANCELLED"},
            "PENDING_APPROVAL": {"DISPATCHED", "CANCELLED"},
            "DISPATCHED": {"PARTIALLY_RECEIVED", "FULFILLED", "CANCELLED"},
            "PARTIALLY_RECEIVED": {"FULFILLED", "CANCELLED"},
            "FULFILLED": set(),
            "CANCELLED": set(),
        }

        if new_status not in allowed_transitions[order.status]:
            raise ValueError(
                f"Cannot change purchase order from {order.status} "
                f"to {new_status}."
            )

        try:
            order.status = new_status
            self.repository.save()
            self.db.refresh(order)
            return order
        except Exception:
            self.repository.rollback()
            raise

    @staticmethod
    def _generate_po_number() -> str:
        return f"PO-{uuid4().hex[:12].upper()}"