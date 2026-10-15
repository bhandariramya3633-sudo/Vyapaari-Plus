from decimal import Decimal

import pytest

from app.modules.products.models import Product
from app.modules.products.service import ProductService


def test_create_product_success(db_session):
    service = ProductService(db_session)

    product = service.create_product(
        sku="TEST-001",
        name="Test Product",
        current_stock=10,
        reorder_point=5,
        reorder_quantity=20,
        unit_cost=Decimal("100.00"),
    )

    assert product.id is not None
    assert product.sku == "TEST-001"
    assert product.name == "Test Product"
    assert product.current_stock == 10
    assert product.reorder_point == 5
    assert product.reorder_quantity == 20


def test_create_product_rejects_empty_sku(db_session):
    service = ProductService(db_session)

    with pytest.raises(ValueError, match="SKU is required"):
        service.create_product(
            sku="",
            name="Test Product",
        )


def test_create_product_rejects_negative_stock(db_session):
    service = ProductService(db_session)

    with pytest.raises(ValueError, match="negative"):
        service.create_product(
            sku="TEST-002",
            name="Test Product",
            current_stock=-1,
        )


def test_create_product_rejects_duplicate_sku(db_session):
    service = ProductService(db_session)

    service.create_product(
        sku="TEST-003",
        name="First Product",
    )

    with pytest.raises(ValueError, match="already exists"):
        service.create_product(
            sku="TEST-003",
            name="Second Product",
        )


def test_get_low_stock_products(db_session):
    service = ProductService(db_session)

    service.create_product(
        sku="LOW-001",
        name="Low Stock Product",
        current_stock=2,
        reorder_point=5,
    )

    service.create_product(
        sku="OK-001",
        name="Available Product",
        current_stock=20,
        reorder_point=5,
    )

    low_stock_products = service.get_low_stock_products()

    assert len(low_stock_products) == 1
    assert low_stock_products[0].sku == "LOW-001"


def test_update_stock(db_session):
    service = ProductService(db_session)

    product = service.create_product(
        sku="TEST-004",
        name="Stock Update Product",
        current_stock=10,
    )

    updated_product = service.update_stock(product.id, 25)

    assert updated_product.current_stock == 25


def test_update_stock_rejects_negative_quantity(db_session):
    service = ProductService(db_session)

    product = service.create_product(
        sku="TEST-005",
        name="Stock Validation Product",
        current_stock=10,
    )

    with pytest.raises(ValueError, match="negative"):
        service.update_stock(product.id, -5)