from decimal import Decimal
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.products.models import Product
from app.modules.products.repository import ProductRepository
from app.modules.suppliers.models import Supplier


class ProductService:
    """Business logic for product creation and stock management."""

    def __init__(self, db: Session):
        self.db = db
        self.repository = ProductRepository(db)

    def create_product(
        self,
        sku: str,
        name: str,
        current_stock: int = 0,
        reorder_point: int = 0,
        reorder_quantity: int = 1,
        primary_supplier_id: str | None = None,
        unit_cost: Decimal = Decimal("0.00"),
        description: str | None = None,
    ) -> Product:
        sku = sku.strip() if sku else ""
        name = name.strip() if name else ""
        unit_cost = Decimal(str(unit_cost))

        if not sku:
            raise ValueError("Product SKU is required.")
        if not name:
            raise ValueError("Product name is required.")
        if current_stock < 0:
            raise ValueError("Current stock cannot be negative.")
        if reorder_point < 0:
            raise ValueError("Reorder point cannot be negative.")
        if reorder_quantity < 1:
            raise ValueError("Reorder quantity must be at least 1.")
        if unit_cost < 0:
            raise ValueError("Unit cost cannot be negative.")

        if self.repository.get_by_sku(sku):
            raise ValueError(f"Product SKU already exists: {sku}")

        if primary_supplier_id is not None:
            supplier = self.db.get(Supplier, primary_supplier_id)
            if supplier is None:
                raise ValueError("Primary supplier not found.")

        product = Product(
            id=str(uuid4()),
            sku=sku,
            name=name,
            current_stock=current_stock,
            reorder_point=reorder_point,
            reorder_quantity=reorder_quantity,
            primary_supplier_id=primary_supplier_id,
            unit_cost=unit_cost,
            description=description,
        )

        try:
            self.db.add(product)
            self.db.commit()
            self.db.refresh(product)
            return product
        except IntegrityError as exc:
            self.db.rollback()
            raise ValueError(
                "Could not create product. Check that its SKU is unique "
                "and its supplier exists."
            ) from exc
        except Exception:
            self.db.rollback()
            raise

    def get_product(self, product_id: str) -> Product:
        product = self.repository.get_by_id(product_id)
        if product is None:
            raise ValueError("Product not found.")
        return product

    def get_low_stock_products(self) -> list[Product]:
        return self.repository.get_low_stock()

    def update_stock(self, product_id: str, quantity: int) -> Product:
        if quantity < 0:
            raise ValueError("Stock quantity cannot be negative.")

        product = self.get_product(product_id)
        product.current_stock = quantity

        try:
            self.db.commit()
            self.db.refresh(product)
            return product
        except Exception:
            self.db.rollback()
            raise