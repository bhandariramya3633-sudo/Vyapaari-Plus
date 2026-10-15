from decimal import Decimal

from sqlalchemy.orm import Session

from app.modules.purchasing.models import PurchaseOrder
from app.modules.purchasing.grn_models import GoodsReceipt
from app.modules.purchasing.grn import match_purchase_order_line


class ThreeWayMatchingService:
    """Compare purchase orders, goods receipts, and supplier invoices."""

    def __init__(self, db: Session):
        self.db = db

    def match_invoice(
        self,
        purchase_order_id: str,
        goods_receipt_id: str,
        invoice_items: list[dict],
    ) -> list[dict]:
        if not invoice_items:
            raise ValueError("At least one invoice item is required.")

        order = self.db.get(PurchaseOrder, purchase_order_id)
        if order is None:
            raise ValueError("Purchase order not found.")

        receipt = self.db.get(GoodsReceipt, goods_receipt_id)
        if receipt is None:
            raise ValueError("Goods receipt not found.")

        if receipt.purchase_order_id != order.id:
            raise ValueError(
                "Goods receipt does not belong to this purchase order."
            )

        order_items = {item.id: item for item in order.items}
        receipt_lines = {
            line.purchase_order_item_id: line for line in receipt.lines
        }

        results = []

        for entry in invoice_items:
            item_id = entry.get("purchase_order_item_id")

            if item_id not in order_items:
                raise ValueError(
                    "Invoice item does not belong to this purchase order."
                )

            order_item = order_items[item_id]
            receipt_line = receipt_lines.get(item_id)

            if receipt_line is None:
                raise ValueError(
                    "No goods receipt line exists for this order item."
                )

            invoiced_quantity = entry.get("invoiced_quantity")
            if (
                not isinstance(invoiced_quantity, int)
                or isinstance(invoiced_quantity, bool)
                or invoiced_quantity < 0
            ):
                raise ValueError(
                    "Invoiced quantity must be a non-negative whole number."
                )

            try:
                invoiced_unit_price = Decimal(
                    str(entry.get("invoiced_unit_price"))
                )
            except Exception as exc:
                raise ValueError("Invalid invoiced unit price.") from exc

            if (
                not invoiced_unit_price.is_finite()
                or invoiced_unit_price < 0
            ):
                raise ValueError(
                    "Invoiced unit price must be a finite non-negative amount."
                )

            result = match_purchase_order_line(
                product_id=order_item.product_id,
                ordered_quantity=order_item.quantity,
                received_quantity=receipt_line.quantity_received,
                invoiced_quantity=invoiced_quantity,
                ordered_unit_price=Decimal(str(order_item.unit_price)),
                invoiced_unit_price=invoiced_unit_price,
            )

            results.append(
                {
                    "purchase_order_item_id": item_id,
                    "product_id": order_item.product_id,
                    "ordered_quantity": result.ordered_quantity,
                    "received_quantity": result.received_quantity,
                    "invoiced_quantity": result.invoiced_quantity,
                    "ordered_unit_price": str(result.ordered_unit_price),
                    "invoiced_unit_price": str(result.invoiced_unit_price),
                    "quantity_shortage": result.quantity_shortage,
                    "price_variance": str(result.price_variance),
                    "flags": result.flags,
                    "is_matched": result.is_matched,
                    "recommended_action": self._recommended_action(
                        result.flags
                    ),
                }
            )

        return results

    @staticmethod
    def _recommended_action(flags: list[str]) -> str:
        if not flags:
            return "NO_ACTION"

        actions = []

        if "QUANTITY_SHORTAGE" in flags:
            actions.append("REQUEST_CREDIT_FOR_SHORTAGE")

        if "QUANTITY_EXCESS" in flags:
            actions.append("REVIEW_EXCESS_DELIVERY")

        if "INVOICE_RECEIPT_MISMATCH" in flags:
            actions.append("REQUEST_INVOICE_CORRECTION")

        if "PRICE_VARIANCE" in flags:
            actions.append("REQUEST_PRICE_CREDIT_OR_DEBIT")

        return ", ".join(actions) if actions else "MANUAL_REVIEW"