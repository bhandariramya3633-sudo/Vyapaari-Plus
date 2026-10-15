from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.modules.products.models import Product
from app.modules.purchasing.models import PurchaseOrder
from app.modules.purchasing.grn_models import (
    GoodsReceipt,
    GoodsReceiptLine,
)


class GoodsReceiptService:
    """Record goods received against purchase orders."""

    def __init__(self, db: Session):
        self.db = db

    def record_receipt(
        self,
        purchase_order_id: str,
        received_items: list[dict],
        notes: str | None = None,
    ) -> GoodsReceipt:
        if not received_items:
            raise ValueError("At least one received item is required.")

        order = self.db.get(PurchaseOrder, purchase_order_id)

        if order is None:
            raise ValueError("Purchase order not found.")

        if order.status not in {"DISPATCHED", "PARTIALLY_RECEIVED"}:
            raise ValueError(
                "Goods can only be received for a dispatched "
                "or partially received purchase order."
            )

        order_items = {
            item.id: item for item in order.items
        }

        validated_items = []
        for entry in received_items:
            item_id = entry.get("purchase_order_item_id")
            quantity = entry.get("quantity_received")
            unit_price = Decimal(str(entry.get("unit_price", "0")))

            if item_id not in order_items:
                raise ValueError(
                    "Received item does not belong to this purchase order."
                )

            if not isinstance(quantity, int) or isinstance(quantity, bool):
                raise ValueError("Received quantity must be a whole number.")

            if quantity <= 0:
                raise ValueError("Received quantity must be greater than zero.")

            if unit_price < 0:
                raise ValueError("Unit price cannot be negative.")

            order_item = order_items[item_id]

            if order_item.received_quantity + quantity > order_item.quantity:
                raise ValueError(
                    "Received quantity exceeds the outstanding order quantity."
                )

            validated_items.append(
                (order_item, quantity, unit_price)
            )

        receipt = GoodsReceipt(
            id=str(uuid4()),
            grn_number=f"GRN-{uuid4().hex[:12].upper()}",
            purchase_order_id=order.id,
            notes=notes,
        )

        try:
            self.db.add(receipt)
            self.db.flush()

            for order_item, quantity, unit_price in validated_items:
                line = GoodsReceiptLine(
                    id=str(uuid4()),
                    goods_receipt_id=receipt.id,
                    purchase_order_item_id=order_item.id,
                    quantity_received=quantity,
                    unit_price=unit_price,
                )
                self.db.add(line)

                order_item.received_quantity += quantity

                product = self.db.get(Product, order_item.product_id)
                if product is None:
                    raise ValueError(
                        f"Product not found: {order_item.product_id}"
                    )

                product.current_stock += quantity

            all_received = all(
                item.received_quantity >= item.quantity
                for item in order.items
            )

            order.status = (
                "FULFILLED" if all_received else "PARTIALLY_RECEIVED"
            )

            self.db.commit()
            self.db.refresh(receipt)
            return receipt

        except Exception:
            self.db.rollback()
            raise