from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.products.models import Product
from app.modules.purchasing.grn_service import GoodsReceiptService
from app.modules.purchasing.models import PurchaseOrder, PurchaseOrderItem
from app.modules.suppliers.models import Supplier


def create_test_data(db_session, order_status="DISPATCHED"):
    supplier = Supplier(
        id=str(uuid4()),
        name="GRN Test Supplier",
        contact_person="Test Contact",
        phone="9876543210",
        email="grn@example.com",
        address="Test Address",
    )
    db_session.add(supplier)
    db_session.flush()

    product = Product(
        id=str(uuid4()),
        sku=f"GRN-{uuid4().hex[:8]}",
        name="Test Product",
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
        status=order_status,
    )
    db_session.add(order)
    db_session.flush()

    order_item = PurchaseOrderItem(
        id=str(uuid4()),
        purchase_order_id=order.id,
        product_id=product.id,
        quantity=5,
        received_quantity=0,
        unit_price=Decimal("20.00"),
    )
    db_session.add(order_item)
    db_session.commit()

    return product, order, order_item


def test_record_receipt_updates_stock_and_order_status(db_session):
    product, order, item = create_test_data(db_session)

    receipt = GoodsReceiptService(db_session).record_receipt(
        order.id,
        [
            {
                "purchase_order_item_id": item.id,
                "quantity_received": 2,
                "unit_price": "20.00",
            }
        ],
    )

    db_session.refresh(product)
    db_session.refresh(order)
    db_session.refresh(item)

    assert receipt.grn_number.startswith("GRN-")
    assert product.current_stock == 12
    assert item.received_quantity == 2
    assert order.status == "PARTIALLY_RECEIVED"


def test_fully_received_order_becomes_fulfilled(db_session):
    product, order, item = create_test_data(db_session)

    GoodsReceiptService(db_session).record_receipt(
        order.id,
        [
            {
                "purchase_order_item_id": item.id,
                "quantity_received": 5,
                "unit_price": "20.00",
            }
        ],
    )

    db_session.refresh(order)
    db_session.refresh(product)

    assert order.status == "FULFILLED"
    assert product.current_stock == 15


def test_receipt_rejects_quantity_above_ordered_amount(db_session):
    product, order, item = create_test_data(db_session)

    with pytest.raises(ValueError, match="exceeds"):
        GoodsReceiptService(db_session).record_receipt(
            order.id,
            [
                {
                    "purchase_order_item_id": item.id,
                    "quantity_received": 6,
                    "unit_price": "20.00",
                }
            ],
        )

    db_session.refresh(product)
    assert product.current_stock == 10


def test_receipt_rejects_missing_purchase_order(db_session):
    with pytest.raises(ValueError, match="not found"):
        GoodsReceiptService(db_session).record_receipt(
            str(uuid4()),
            [
                {
                    "purchase_order_item_id": str(uuid4()),
                    "quantity_received": 1,
                    "unit_price": "20.00",
                }
            ],
        )


def test_receipt_rejects_empty_items(db_session):
    _, order, _ = create_test_data(db_session)

    with pytest.raises(ValueError, match="At least one"):
        GoodsReceiptService(db_session).record_receipt(order.id, [])