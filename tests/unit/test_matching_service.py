from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.products.models import Product
from app.modules.purchasing.grn_models import GoodsReceipt, GoodsReceiptLine
from app.modules.purchasing.matching_service import ThreeWayMatchingService
from app.modules.purchasing.models import PurchaseOrder, PurchaseOrderItem
from app.modules.suppliers.models import Supplier


def create_matching_data(db_session):
    supplier = Supplier(
        id=str(uuid4()),
        name="Matching Test Supplier",
        contact_person="Test Contact",
        phone="9876543210",
        email="matching@example.com",
        address="Test Address",
    )
    db_session.add(supplier)
    db_session.flush()

    product = Product(
        id=str(uuid4()),
        sku=f"MATCH-{uuid4().hex[:8]}",
        name="Matching Test Product",
        current_stock=10,
        reorder_point=5,
        reorder_quantity=10,
        primary_supplier_id=supplier.id,
        unit_cost=Decimal("20.00"),
    )
    db_session.add(product)
    db_session.flush()

    order = PurchaseOrder(
        id=str(uuid4()),
        po_number=f"PO-{uuid4().hex[:12].upper()}",
        supplier_id=supplier.id,
        status="PARTIALLY_RECEIVED",
    )
    db_session.add(order)
    db_session.flush()

    item = PurchaseOrderItem(
        id=str(uuid4()),
        purchase_order_id=order.id,
        product_id=product.id,
        quantity=5,
        received_quantity=3,
        unit_price=Decimal("20.00"),
    )
    db_session.add(item)
    db_session.flush()

    receipt = GoodsReceipt(
        id=str(uuid4()),
        grn_number=f"GRN-{uuid4().hex[:12].upper()}",
        purchase_order_id=order.id,
    )
    db_session.add(receipt)
    db_session.flush()

    receipt_line = GoodsReceiptLine(
        id=str(uuid4()),
        goods_receipt_id=receipt.id,
        purchase_order_item_id=item.id,
        quantity_received=3,
        unit_price=Decimal("20.00"),
    )
    db_session.add(receipt_line)
    db_session.commit()

    return order, receipt, item


def invoice_item(item, quantity=3, price="20.00"):
    return {
        "purchase_order_item_id": item.id,
        "invoiced_quantity": quantity,
        "invoiced_unit_price": price,
    }


def test_matching_invoice_without_discrepancies(db_session):
    order, receipt, item = create_matching_data(db_session)

    # All three quantities must match for this test.
    item.quantity = 3
    db_session.commit()

    results = ThreeWayMatchingService(db_session).match_invoice(
        order.id, receipt.id, [invoice_item(item)]
    )

    assert len(results) == 1
    assert results[0]["is_matched"] is True
    assert results[0]["flags"] == []
    assert results[0]["recommended_action"] == "NO_ACTION"


def test_matching_detects_quantity_shortage(db_session):
    order, receipt, item = create_matching_data(db_session)

    results = ThreeWayMatchingService(db_session).match_invoice(
        order.id, receipt.id, [invoice_item(item)]
    )

    assert results[0]["is_matched"] is False
    assert "QUANTITY_SHORTAGE" in results[0]["flags"]
    assert (
        "REQUEST_CREDIT_FOR_SHORTAGE"
        in results[0]["recommended_action"]
    )


def test_matching_detects_price_variance(db_session):
    order, receipt, item = create_matching_data(db_session)

    results = ThreeWayMatchingService(db_session).match_invoice(
        order.id,
        receipt.id,
        [invoice_item(item, quantity=3, price="25.00")],
    )

    assert results[0]["is_matched"] is False
    assert "PRICE_VARIANCE" in results[0]["flags"]
    assert (
        "REQUEST_PRICE_CREDIT_OR_DEBIT"
        in results[0]["recommended_action"]
    )


def test_matching_rejects_receipt_from_another_order(db_session):
    order, receipt, item = create_matching_data(db_session)

    other_order = PurchaseOrder(
        id=str(uuid4()),
        po_number=f"PO-{uuid4().hex[:12].upper()}",
        supplier_id=order.supplier_id,
        status="DISPATCHED",
    )
    db_session.add(other_order)
    db_session.commit()

    with pytest.raises(ValueError, match="does not belong"):
        ThreeWayMatchingService(db_session).match_invoice(
            other_order.id,
            receipt.id,
            [invoice_item(item)],
        )


def test_matching_rejects_empty_invoice(db_session):
    order, receipt, _ = create_matching_data(db_session)

    with pytest.raises(ValueError, match="At least one"):
        ThreeWayMatchingService(db_session).match_invoice(
            order.id, receipt.id, []
        )


def test_matching_rejects_negative_invoice_quantity(db_session):
    order, receipt, item = create_matching_data(db_session)

    with pytest.raises(ValueError, match="non-negative"):
        ThreeWayMatchingService(db_session).match_invoice(
            order.id,
            receipt.id,
            [invoice_item(item, quantity=-1)],
        )