from dataclasses import dataclass
from decimal import Decimal


@dataclass
class GRNLine:
    """A line describing goods received against a purchase order."""

    product_id: str
    ordered_quantity: int
    received_quantity: int
    ordered_unit_price: Decimal
    invoiced_unit_price: Decimal

    @property
    def quantity_shortage(self) -> int:
        return max(self.ordered_quantity - self.received_quantity, 0)

    @property
    def quantity_variance(self) -> int:
        return self.received_quantity - self.ordered_quantity

    @property
    def price_variance(self) -> Decimal:
        return self.invoiced_unit_price - self.ordered_unit_price

    @property
    def has_quantity_shortage(self) -> bool:
        return self.received_quantity < self.ordered_quantity

    @property
    def has_price_variance(self) -> bool:
        return self.price_variance != Decimal("0.00")


@dataclass
class ThreeWayMatchResult:
    """Result of comparing a purchase order, goods receipt and invoice."""

    product_id: str
    ordered_quantity: int
    received_quantity: int
    invoiced_quantity: int
    ordered_unit_price: Decimal
    invoiced_unit_price: Decimal
    quantity_shortage: int
    price_variance: Decimal
    flags: list[str]

    @property
    def is_matched(self) -> bool:
        return len(self.flags) == 0


def match_purchase_order_line(
    product_id: str,
    ordered_quantity: int,
    received_quantity: int,
    invoiced_quantity: int,
    ordered_unit_price: Decimal,
    invoiced_unit_price: Decimal,
) -> ThreeWayMatchResult:
    """Compare ordered, received and invoiced quantities and prices."""
    values = (
        ordered_quantity,
        received_quantity,
        invoiced_quantity,
    )

    if any(value < 0 for value in values):
        raise ValueError("Quantities cannot be negative.")

    if ordered_unit_price < 0 or invoiced_unit_price < 0:
        raise ValueError("Prices cannot be negative.")

    quantity_shortage = max(ordered_quantity - received_quantity, 0)
    price_variance = invoiced_unit_price - ordered_unit_price
    flags = []

    if received_quantity < ordered_quantity:
        flags.append("QUANTITY_SHORTAGE")

    if received_quantity > ordered_quantity:
        flags.append("EXCESS_QUANTITY_RECEIVED")

    if invoiced_quantity != received_quantity:
        flags.append("INVOICE_RECEIPT_QUANTITY_MISMATCH")

    if invoiced_unit_price != ordered_unit_price:
        flags.append("PRICE_VARIANCE")

    return ThreeWayMatchResult(
        product_id=product_id,
        ordered_quantity=ordered_quantity,
        received_quantity=received_quantity,
        invoiced_quantity=invoiced_quantity,
        ordered_unit_price=ordered_unit_price,
        invoiced_unit_price=invoiced_unit_price,
        quantity_shortage=quantity_shortage,
        price_variance=price_variance,
        flags=flags,
    )