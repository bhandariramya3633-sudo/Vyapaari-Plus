import sys
from app.config import settings
from app.core.logging import setup_logging

def main():
    logger = setup_logging()
    logger.info(f"Starting {settings.app_name} v{settings.app_version}...")

    # Check dependencies
    try:
        from app.modules.inventory import models as inventory_models
        from app.db.session import init_db
        init_db()
        logger.info("Database schema initialized successfully.")
    except ImportError as e:
        logger.warning(f"Optional or required dependency missing: {e}")
        logger.info("To install full production dependencies: pip install -r requirements.txt")

    # In GUI mode, initialize PySide6 QApplication
    try:
        from PySide6.QtWidgets import QApplication
        from app.ui.main_window import MainWindow
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        return app.exec()
    except ImportError:
        logger.info("PySide6 not present or running in headless mode. Headless BOS service ready.")
        return 0

if __name__ == "__main__":
    sys.exit(main())
