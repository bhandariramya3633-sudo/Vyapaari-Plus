from decimal import Decimal
from uuid import uuid4

import pytest

from app.modules.products.service import ProductService
from app.modules.purchasing.service import PurchaseOrderService
from app.modules.suppliers.models import Supplier


def create_supplier(db_session):
    """Create a supplier for purchase-order tests."""
    supplier = Supplier(
        id=str(uuid4()),
        name="Test Supplier",
        contact_person="Test Contact",
        phone="9876543210",
        email="supplier@example.com",
        address="Test Address",
    )

    db_session.add(supplier)
    db_session.commit()
    db_session.refresh(supplier)

    return supplier


def test_generate_draft_order_for_low_stock(db_session):
    supplier = create_supplier(db_session)

    product_service = ProductService(db_session)
    product_service.create_product(
        sku="LOW-PO-001",
        name="Low Stock Product",
        current_stock=2,
        reorder_point=5,
        reorder_quantity=10,
        primary_supplier_id=supplier.id,
        unit_cost=Decimal("25.00"),
    )

    po_service = PurchaseOrderService(db_session)
    orders = po_service.generate_draft_orders()

    assert len(orders) == 1
    assert orders[0].supplier_id == supplier.id
    assert orders[0].status == "DRAFT"
    assert len(orders[0].items) == 1
    assert orders[0].items[0].quantity == 8


def test_low_stock_products_grouped_by_supplier(db_session):
    supplier = create_supplier(db_session)
    product_service = ProductService(db_session)

    product_service.create_product(
        sku="GROUP-001",
        name="Product One",
        current_stock=1,
        reorder_point=5,
        reorder_quantity=10,
        primary_supplier_id=supplier.id,
        unit_cost=Decimal("10.00"),
    )

    product_service.create_product(
        sku="GROUP-002",
        name="Product Two",
        current_stock=1,
        reorder_point=5,
        reorder_quantity=10,
        primary_supplier_id=supplier.id,
        unit_cost=Decimal("15.00"),
    )

    orders = PurchaseOrderService(
        db_session
    ).generate_draft_orders()

    assert len(orders) == 1
    assert orders[0].supplier_id == supplier.id
    assert len(orders[0].items) == 2


def test_update_order_status(db_session):
    supplier = create_supplier(db_session)
    product_service = ProductService(db_session)

    product_service.create_product(
        sku="STATUS-001",
        name="Status Product",
        current_stock=0,
        reorder_point=5,
        reorder_quantity=5,
        primary_supplier_id=supplier.id,
        unit_cost=Decimal("10.00"),
    )

    service = PurchaseOrderService(db_session)
    orders = service.generate_draft_orders()

    assert len(orders) == 1

    updated = service.update_status(
        orders[0].id,
        "PENDING_APPROVAL",
    )

    assert updated.status == "PENDING_APPROVAL"


def test_invalid_order_status_transition(db_session):
    supplier = create_supplier(db_session)
    product_service = ProductService(db_session)

    product_service.create_product(
        sku="INVALID-001",
        name="Invalid Transition Product",
        current_stock=0,
        reorder_point=5,
        reorder_quantity=5,
        primary_supplier_id=supplier.id,
        unit_cost=Decimal("10.00"),
    )

    service = PurchaseOrderService(db_session)
    orders = service.generate_draft_orders()

    assert len(orders) == 1

    with pytest.raises(ValueError, match="Cannot change"):
        service.update_status(
            orders[0].id,
            "FULFILLED",
        )