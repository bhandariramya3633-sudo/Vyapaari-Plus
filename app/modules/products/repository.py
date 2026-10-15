from sqlalchemy.orm import Session

from app.modules.products.models import Product


class ProductRepository:
    """Database operations for products."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, product_id: str) -> Product | None:
        return self.db.get(Product, product_id)

    def get_by_sku(self, sku: str) -> Product | None:
        return (
            self.db.query(Product)
            .filter(Product.sku == sku)
            .first()
        )

    def get_all_active(self) -> list[Product]:
        return (
            self.db.query(Product)
            .filter(Product.is_active.is_(True))
            .order_by(Product.name)
            .all()
        )

    def get_low_stock(self) -> list[Product]:
        """Return active products at or below their reorder point."""
        return (
            self.db.query(Product)
            .filter(
                Product.is_active.is_(True),
                Product.current_stock <= Product.reorder_point,
            )
            .order_by(Product.name)
            .all()
        )

    def get_by_supplier(self, supplier_id: str) -> list[Product]:
        return (
            self.db.query(Product)
            .filter(
                Product.primary_supplier_id == supplier_id,
                Product.is_active.is_(True),
            )
            .order_by(Product.name)
            .all()
        )