import sys

import app.modules.purchasing.models
import app.modules.purchasing.grn_models

from app.config import settings
from app.core.logging import setup_logging


def main():
    logger = setup_logging()
    logger.info(
        f"Starting {settings.app_name} v{settings.app_version}..."
    )

    try:
        # Register database models before initializing the schema.
        import app.modules.auth.models
        import app.modules.billing.models
        import app.modules.business.models
        import app.modules.customers.models
        import app.modules.employees.models
        import app.modules.finance.models
        import app.modules.inventory.models
        import app.modules.products.models
        import app.modules.reports.models
        import app.modules.suppliers.models

        from app.db.session import init_db

        init_db()
        logger.info("Database schema initialized successfully.")

    except ImportError as exc:
        logger.warning(
            f"Application dependency or model import missing: {exc}"
        )
        logger.info(
            "Check installed dependencies and module imports."
        )

    try:
        from PySide6.QtWidgets import QApplication
        from app.ui.main_window import MainWindow

        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        return app.exec()

    except ImportError:
        logger.info(
            "PySide6 not present or running in headless mode. "
            "Headless BOS service ready."
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())