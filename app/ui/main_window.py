from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from pathlib import Path
from PySide6.QtGui import QPixmap, QColor, QBrush
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QSpinBox,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QInputDialog,
    QScrollArea,
    QButtonGroup,
    QAbstractItemView,
)

from app.db.session import SessionLocal
from app.modules.inventory.models import (
    Branch,
    StockBatch,
    StockTransfer,
    TransferStatus,
)
from app.modules.inventory.reconciliation import (
    DECISION_APPROVED,
    DECISION_REJECTED,
    MultiBranchReconciliationEngine,
)
from app.modules.inventory.stock_transfer import StockTransferService
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGO_PATH = PROJECT_ROOT / "assets" / "logo1.png"

# (text colour, background colour) for status badges
STATUS_COLORS = {
    "PENDING": ("#92400E", "#FEF3C7"),
    "DISPATCHED": ("#1D4ED8", "#DBEAFE"),
    "IN_TRANSIT": ("#6D28D9", "#EDE9FE"),
    "RECEIVED": ("#166534", "#DCFCE7"),
    "COMPLETED": ("#166534", "#DCFCE7"),
    "PARTIALLY_RECEIVED": ("#9A3412", "#FFEDD5"),
    "CANCELLED": ("#991B1B", "#FEE2E2"),
    "RECONCILED": ("#065F46", "#D1FAE5"),
    "DISPUTED": ("#9F1239", "#FFE4E6"),
}
DEFAULT_STATUS_COLOR = ("#334155", "#E2E8F0")

# Statuses that mean a transfer is finished (not "pending" on dashboard)
FINISHED_STATUSES = {
    "RECEIVED", "COMPLETED", "CANCELLED", "RECONCILED", "PARTIALLY_RECEIVED",
}

NAV_ITEMS = [
    ("🏠", "Dashboard"),
    ("📦", "Products"),
    ("🏬", "Inventory"),
    ("🔁", "Stock Transfers"),
    ("🧾", "Billing / POS"),
    ("👥", "Customers"),
    ("🚚", "Suppliers"),
    ("📊", "Reports"),
    ("⚙️", "Settings"),
]


def status_colors(status_text):
    key = str(status_text).upper()
    if key in STATUS_COLORS:
        return STATUS_COLORS[key]
    return DEFAULT_STATUS_COLOR


def format_reconciliation_summary(summary):
    """Return the text shown after a reconciliation is completed."""
    lines = [
        f"Transfer: {summary['transfer_number']}",
        "",
        f"Dispatched units:     {summary['dispatched']}",
        f"Good received units:  {summary['good_received']}",
        f"Damaged units:        {summary['damaged']}",
        f"Missing units:        {summary['missing']}",
        f"Variance:             {summary['variance']}",
        f"Loss value:           ₹ {summary['loss_value']:,.2f}",
        "",
        f"Resolution status:    {summary['resolution_status']}",
        f"Approval status:      "
        f"{summary['approval_status'].replace('_', ' ')}",
        f"Final transfer status: {summary['final_status']}",
    ]
    return "\n".join(lines)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(
            "Vyapaari+ - Windows Desktop Business Operating System"
        )
        self.resize(1360, 840)
        self.setMinimumSize(1050, 680)

        self.nav_buttons = {}
        self.all_transfer_rows = []

        self.apply_styles()
        self.build_layout()
        self.show_section("Dashboard")

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------
    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #F3F6FB;
                color: #172033;
                font-family: "Segoe UI";
                font-size: 14px;
            }

            QScrollArea { border: none; background: transparent; }

            /* ---------- Sidebar ---------- */
            QFrame#Sidebar { background-color: #14213D; border: none; }
            QFrame#Sidebar QWidget { background-color: transparent; }

            QLabel#Brand {
                color: #FFFFFF;
                font-size: 23px;
                font-weight: 800;
                padding: 4px 2px;
            }

            QLabel#Tagline {
                color: #93C5FD;
                font-size: 10px;
                letter-spacing: 1px;
                padding: 0 8px 14px 8px;
            }

            QLabel#SidebarFooter { color: #94A3B8; padding: 8px; }

            QPushButton#NavButton {
                background-color: transparent;
                color: #DCE6F7;
                text-align: left;
                padding: 12px 14px;
                border: 1px solid transparent;
                border-left: 4px solid transparent;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 500;
            }

            QPushButton#NavButton:hover {
                background-color: #263858;
                color: #FFFFFF;
                border: 1px solid #354968;
                border-left: 4px solid transparent;
            }

            QPushButton#NavButton:checked {
                background-color: #2563EB;
                color: #FFFFFF;
                border: 1px solid #2563EB;
                border-left: 4px solid #5EEAD4;
                font-weight: 700;
            }

            /* ---------- Typography ---------- */
            QLabel { background: transparent; }

            QLabel#PageTitle {
                font-size: 27px;
                font-weight: 750;
                color: #172033;
            }

            QLabel#Subtitle { color: #5B677B; font-size: 14px; }

            QLabel#SectionTitle {
                color: #172033;
                font-size: 17px;
                font-weight: 700;
            }

            QLabel#FieldLabel {
                color: #475569;
                font-size: 12px;
                font-weight: 700;
            }

            QLabel#Hint {
                color: #475569;
                background-color: #EFF6FF;
                border: 1px solid #DBEAFE;
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 13px;
            }

            QLabel#EmptyState {
                color: #94A3B8;
                font-size: 14px;
                padding: 28px;
            }

            /* ---------- Cards ---------- */
            QFrame#MetricCard, QFrame#ContentCard {
                background-color: #FFFFFF;
                border: 1px solid #DFE6F0;
                border-radius: 12px;
            }

            QFrame#MetricCard QLabel, QFrame#ContentCard QLabel {
                background: transparent;
            }

            QLabel#MetricIcon {
                background-color: #EAF1FF;
                border-radius: 12px;
                font-size: 20px;
                qproperty-alignment: AlignCenter;
            }

            QLabel#MetricLabel {
                color: #64748B;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 1px;
            }

            QLabel#MetricValue {
                color: #172033;
                font-size: 28px;
                font-weight: 750;
            }

            QLabel#MetricNote { color: #64748B; font-size: 12px; }

            /* ---------- Buttons ---------- */
            QPushButton {
                background-color: #E8EEF8;
                color: #1E3A5F;
                border: 1px solid #D4DEED;
                border-radius: 7px;
                padding: 10px 15px;
                font-weight: 600;
            }

            QPushButton:hover {
                background-color: #D9E6F8;
                border-color: #AFC5E7;
            }

            QPushButton:pressed { background-color: #C8D9F1; }

            QPushButton:disabled {
                background-color: #F1F5F9;
                color: #94A3B8;
                border-color: #E2E8F0;
            }

            QPushButton#ActionButton {
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 7px;
                padding: 11px 20px;
                font-weight: 700;
            }

            QPushButton#ActionButton:hover { background-color: #1D4ED8; }
            QPushButton#ActionButton:pressed { background-color: #1E40AF; }

            QPushButton#SuccessButton {
                background-color: #16A34A;
                color: #FFFFFF;
                border: none;
                font-weight: 700;
            }
            QPushButton#SuccessButton:hover { background-color: #15803D; }

            QPushButton#SwapButton {
                padding: 8px 10px;
                font-size: 16px;
                border-radius: 16px;
            }

            /* ---------- Inputs ---------- */
            QLineEdit, QComboBox, QSpinBox {
                background-color: #FFFFFF;
                color: #172033;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px 10px;
                min-height: 20px;
                selection-background-color: #2563EB;
                selection-color: #FFFFFF;
            }

            QLineEdit:hover, QComboBox:hover, QSpinBox:hover {
                border: 1px solid #94A3B8;
            }

            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 2px solid #3B82F6;
            }

            QComboBox::drop-down { border: none; width: 26px; }

            QComboBox QAbstractItemView {
                background-color: #FFFFFF;
                color: #172033;
                selection-background-color: #DBEAFE;
                selection-color: #1D4ED8;
                border: 1px solid #CBD5E1;
                outline: none;
            }

            /* ---------- Table ---------- */
            QTableWidget {
                background-color: #FFFFFF;
                alternate-background-color: #F8FAFC;
                color: #172033;
                gridline-color: #E2E8F0;
                border: 1px solid #E2E8F0;
                border-radius: 7px;
                selection-background-color: #DBEAFE;
                selection-color: #1D4ED8;
                outline: none;
            }

            QTableWidget::item { padding: 6px; border: none; }

            QHeaderView::section {
                background-color: #EAF0F8;
                color: #243650;
                padding: 10px 7px;
                border: none;
                border-bottom: 1px solid #D5DFEC;
                font-weight: 700;
            }

            QTableWidget QTableCornerButton::section {
                background-color: #EAF0F8;
                border: none;
            }

            /* ---------- Header status pill ---------- */
            QLabel#Status {
                color: #166534;
                background-color: #DCFCE7;
                padding: 7px 12px;
                border-radius: 8px;
                font-weight: 600;
            }

            QLabel#StatusError {
                color: #991B1B;
                background-color: #FEE2E2;
                padding: 7px 12px;
                border-radius: 8px;
                font-weight: 600;
            }

            /* ---------- Scrollbars ---------- */
            QScrollBar:vertical {
                background-color: transparent;
                width: 10px;
                margin: 0;
            }

            QScrollBar::handle:vertical {
                background-color: #CBD5E1;
                border-radius: 5px;
                min-height: 25px;
            }

            QScrollBar::handle:vertical:hover { background-color: #94A3B8; }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }

            QScrollBar:horizontal {
                background-color: transparent;
                height: 10px;
            }
            QScrollBar::handle:horizontal {
                background-color: #CBD5E1;
                border-radius: 5px;
                min-width: 25px;
            }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal { width: 0; }

            /* ---------- Status bar & tooltip ---------- */
            QStatusBar {
                background-color: #FFFFFF;
                color: #475569;
                border-top: 1px solid #DFE6F0;
            }

            QToolTip {
                background-color: #14213D;
                color: #FFFFFF;
                border: 1px solid #334155;
                padding: 5px;
            }
        """)

    # ------------------------------------------------------------------
    # Main layout
    # ------------------------------------------------------------------
    
    # ------------------------------------------------------------------
    # Main layout
    # ------------------------------------------------------------------
    def build_layout(self):
        """Build the main application window and sidebar."""

        # ---------- Root widget ----------
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ---------- Sidebar ----------
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(255)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 24, 18, 18)
        sidebar_layout.setSpacing(8)

        # ---------- Brand logo and name ----------
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.setSpacing(10)

        brand_mark = QLabel()
        brand_mark.setFixedSize(46, 46)
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if LOGO_PATH.is_file():
            logo_pixmap = QPixmap(str(LOGO_PATH))

            if not logo_pixmap.isNull():
                brand_mark.setPixmap(
                    logo_pixmap.scaled(
                        42,
                        42,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                brand_mark.setStyleSheet("background: transparent;")
            else:
                brand_mark.setText("V+")
                brand_mark.setStyleSheet("""
                    QLabel {
                        background-color: #14B8A6;
                        color: #FFFFFF;
                        font-size: 19px;
                        font-weight: 800;
                        border-radius: 10px;
                    }
                """)
        else:
            brand_mark.setText("V+")
            brand_mark.setStyleSheet("""
                QLabel {
                    background-color: #14B8A6;
                    color: #FFFFFF;
                    font-size: 19px;
                    font-weight: 800;
                    border-radius: 10px;
                }
            """)

        brand = QLabel("Vyapaari+")
        brand.setObjectName("Brand")

        brand_row.addWidget(brand_mark)
        brand_row.addWidget(brand)
        brand_row.addStretch()

        sidebar_layout.addLayout(brand_row)

        # ---------- Tagline ----------
        tagline = QLabel("BUSINESS OPERATING SYSTEM")
        tagline.setObjectName("Tagline")
        tagline.setWordWrap(True)
        sidebar_layout.addWidget(tagline)

        # ---------- Navigation ----------
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        for icon_text, item_name in NAV_ITEMS:
            button = QPushButton(
                f"  {icon_text}   {item_name}"
            )
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(
                Qt.CursorShape.PointingHandCursor
            )

            button.clicked.connect(
                lambda checked=False, name=item_name:
                    self.show_section(name)
            )

            self.nav_group.addButton(button)
            self.nav_buttons[item_name] = button
            sidebar_layout.addWidget(button)

        sidebar_layout.addStretch()

        # ---------- Sidebar footer ----------
        version = QLabel("Desktop Edition  •  v1.0")
        version.setObjectName("SidebarFooter")
        version.setWordWrap(True)
        sidebar_layout.addWidget(version)

        # ---------- Main content ----------
        self.content = QWidget()

        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(
            32, 28, 32, 28
        )
        self.content_layout.setSpacing(20)

        # ---------- Scroll area ----------
        self.scroll = QScrollArea()
        self.scroll.setObjectName("MainScrollArea")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(
            QFrame.Shape.NoFrame
        )
        self.scroll.setWidget(self.content)

        # ---------- Assemble the window ----------
        root_layout.addWidget(sidebar)
        root_layout.addWidget(self.scroll, 1)

        self.setCentralWidget(root)
        self.statusBar().showMessage("Ready")


    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def notify(self, message, timeout=6000):
        """Non-blocking message shown in the bottom status bar."""
        self.statusBar().showMessage(message, timeout)

    def _clear_layout(self, layout):
        """Recursively remove every widget and nested layout."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)
                child_layout.deleteLater()

    def clear_content(self):
        self._clear_layout(self.content_layout)

    def make_card(self, margins=(22, 20, 22, 20), spacing=12):
        card = QFrame()
        card.setObjectName("ContentCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(*margins)
        layout.setSpacing(spacing)
        return card, layout

    def make_field(self, label_text, widget):
        """A label stacked above an input widget."""
        box = QVBoxLayout()
        box.setSpacing(5)
        label = QLabel(label_text.upper())
        label.setObjectName("FieldLabel")
        box.addWidget(label)
        box.addWidget(widget)
        return box

    def make_metric_card(self, icon, label, value, note):
        card = QFrame()
        card.setObjectName("MetricCard")
        outer = QHBoxLayout(card)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)

        title = QLabel(label)
        title.setObjectName("MetricLabel")

        metric = QLabel(value)
        metric.setObjectName("MetricValue")

        description = QLabel(note)
        description.setObjectName("MetricNote")
        description.setWordWrap(True)

        text_col.addWidget(title)
        text_col.addWidget(metric)
        text_col.addWidget(description)

        icon_label = QLabel(icon)
        icon_label.setObjectName("MetricIcon")
        icon_label.setFixedSize(52, 52)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        outer.addLayout(text_col, 1)
        outer.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignTop)
        return card

    def make_status_item(self, status_text):
        fg, bg = status_colors(status_text)
        item = QTableWidgetItem(str(status_text).replace("_", " "))
        item.setForeground(QBrush(QColor(fg)))
        item.setBackground(QBrush(QColor(bg)))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        return item

    @staticmethod
    def format_datetime(value):
        try:
            return value.strftime("%d %b %Y, %I:%M %p")
        except Exception:
            return "" if value is None else str(value)

    def style_table(self, table):
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(40)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        table.horizontalHeader().setHighlightSections(False)

    # ------------------------------------------------------------------
    # Dashboard data
    # ------------------------------------------------------------------
    def load_dashboard_data(self):
        """Return live figures for the dashboard (or None on failure)."""
        db = SessionLocal()
        try:
            batches = db.query(
                StockBatch.product_id,
                StockBatch.quantity,
                StockBatch.purchase_price,
            ).all()

            product_ids = {row[0] for row in batches}
            inventory_value = sum(
                (row[1] or 0) * float(row[2] or 0) for row in batches
            )

            transfers = (
                db.query(StockTransfer)
                .order_by(StockTransfer.created_at.desc())
                .all()
            )
            pending = [
                t for t in transfers
                if t.status.value.upper() not in FINISHED_STATUSES
            ]
            disputed = [
                t for t in transfers
                if t.status == TransferStatus.DISPUTED
            ]

            branches = {b.id: b.name for b in db.query(Branch).all()}

            recent = [
                (
                    t.transfer_number,
                    branches.get(t.source_branch_id, t.source_branch_id),
                    branches.get(
                        t.destination_branch_id, t.destination_branch_id
                    ),
                    t.status.value,
                )
                for t in transfers[:6]
            ]

            return {
                "products": len(product_ids),
                "value": inventory_value,
                "pending": len(pending),
                "disputed": len(disputed),
                "total_transfers": len(transfers),
                "branches": len(branches),
                "recent": recent,
            }
        except Exception as exc:
            self.notify(f"Could not load dashboard data: {exc}", 10000)
            return None
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Stock transfer screen
    # ------------------------------------------------------------------
    def build_stock_transfer_ui(self):
        """Build the database-connected stock transfer screen."""

        # ---------- Create transfer card ----------
        card, layout = self.make_card()

        heading = QLabel("Create Stock Transfer")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        self.transfer_source = QComboBox()
        self.transfer_destination = QComboBox()
        self.transfer_product = QComboBox()
        self.transfer_quantity = QSpinBox()
        self.transfer_quantity.setRange(1, 1000000)
        self.transfer_quantity.setValue(1)
        self.transfer_notes = QLineEdit()
        self.transfer_notes.setPlaceholderText("Transfer notes (optional)")
        self.transfer_notes.setClearButtonEnabled(True)

        swap_button = QPushButton("⇄")
        swap_button.setObjectName("SwapButton")
        swap_button.setToolTip("Swap source and destination")
        swap_button.setCursor(Qt.CursorShape.PointingHandCursor)
        swap_button.setFixedSize(36, 36)
        swap_button.clicked.connect(self.swap_branches)

        branch_row = QHBoxLayout()
        branch_row.setSpacing(12)
        branch_row.addLayout(
            self.make_field("Source branch", self.transfer_source), 1
        )
        branch_row.addWidget(
            swap_button, alignment=Qt.AlignmentFlag.AlignBottom
        )
        branch_row.addLayout(
            self.make_field("Destination branch", self.transfer_destination),
            1,
        )
        layout.addLayout(branch_row)

        stock_row = QHBoxLayout()
        stock_row.setSpacing(12)
        stock_row.addLayout(
            self.make_field("Available stock", self.transfer_product), 3
        )
        stock_row.addLayout(
            self.make_field("Quantity", self.transfer_quantity), 1
        )
        layout.addLayout(stock_row)

        self.stock_hint = QLabel("Select a source branch to see its stock.")
        self.stock_hint.setObjectName("Hint")
        layout.addWidget(self.stock_hint)

        layout.addLayout(self.make_field("Notes", self.transfer_notes))

        create_button = QPushButton("Create Transfer")
        create_button.setObjectName("ActionButton")
        create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_button.clicked.connect(self.create_stock_transfer)
        layout.addWidget(create_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.content_layout.addWidget(card)

        # ---------- Transfer history card ----------
        actions_card, actions_layout = self.make_card(
            margins=(22, 18, 22, 18), spacing=12
        )

        history_header = QHBoxLayout()
        history_title = QLabel("Transfer History")
        history_title.setObjectName("SectionTitle")
        history_header.addWidget(history_title)
        history_header.addStretch()

        self.transfer_search = QLineEdit()
        self.transfer_search.setPlaceholderText("🔍  Search transfers…")
        self.transfer_search.setClearButtonEnabled(True)
        self.transfer_search.setFixedWidth(250)
        self.transfer_search.textChanged.connect(self.apply_transfer_filter)

        self.transfer_status_filter = QComboBox()
        self.transfer_status_filter.addItem("All statuses", "")
        self.transfer_status_filter.setFixedWidth(170)
        self.transfer_status_filter.currentIndexChanged.connect(
            self.apply_transfer_filter
        )

        history_header.addWidget(self.transfer_search)
        history_header.addWidget(self.transfer_status_filter)
        actions_layout.addLayout(history_header)

        self.transfer_table = QTableWidget(0, 7)
        self.transfer_table.setHorizontalHeaderLabels([
            "Transfer Number",
            "Source",
            "Destination",
            "Status",
            "Items",
            "Created",
            "Transfer ID",
        ])
        self.transfer_table.setColumnHidden(6, True)
        self.style_table(self.transfer_table)
        self.transfer_table.setMinimumHeight(280)
        self.transfer_table.itemSelectionChanged.connect(
            self.update_action_buttons
        )
        actions_layout.addWidget(self.transfer_table)

        self.transfer_empty = QLabel("No transfers found.")
        self.transfer_empty.setObjectName("EmptyState")
        self.transfer_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.transfer_empty.setVisible(False)
        actions_layout.addWidget(self.transfer_empty)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)

        self.dispatch_button = QPushButton("📤  Dispatch Selected")
        self.transit_button = QPushButton("🚚  Start Transit")
        self.receive_button = QPushButton("📥  Receive Delivery")
        self.receive_button.setObjectName("SuccessButton")
        self.reconcile_button = QPushButton("🧮  Reconcile")
        self.review_button = QPushButton("✅  Review Dispute")
        refresh_button = QPushButton("🔄  Refresh")

        self.dispatch_button.clicked.connect(self.dispatch_selected_transfer)
        self.transit_button.clicked.connect(self.start_selected_transit)
        self.receive_button.clicked.connect(self.receive_selected_transfer)
        self.reconcile_button.clicked.connect(
            self.reconcile_selected_transfer
        )
        self.review_button.clicked.connect(self.review_selected_dispute)
        refresh_button.clicked.connect(self.refresh_stock_transfers)

        for button in (
            self.dispatch_button,
            self.transit_button,
            self.receive_button,
            self.reconcile_button,
            self.review_button,
            refresh_button,
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            buttons.addWidget(button)
        buttons.addStretch()

        actions_layout.addLayout(buttons)
        self.content_layout.addWidget(actions_card)

        self.transfer_source.currentIndexChanged.connect(
            self.load_transfer_products
        )
        self.transfer_product.currentIndexChanged.connect(
            self.on_product_changed
        )

        self.update_action_buttons()
        self.refresh_stock_transfers()

    def swap_branches(self):
        source_index = self.transfer_source.currentIndex()
        destination_index = self.transfer_destination.currentIndex()
        if source_index < 0 or destination_index < 0:
            return
        self.transfer_destination.setCurrentIndex(source_index)
        self.transfer_source.setCurrentIndex(destination_index)

    def on_product_changed(self):
        """Limit the quantity spinner to the selected batch's stock."""
        product = self.transfer_product.currentData()
        if product:
            maximum = max(int(product["quantity"]), 1)
            self.transfer_quantity.setMaximum(maximum)
            self.stock_hint.setText(
                f"Batch {product['batch_number']} has "
                f"{product['quantity']} unit(s) available "
                f"(cost {product['unit_cost']} per unit)."
            )
        else:
            self.transfer_quantity.setMaximum(1000000)
            self.stock_hint.setText(
                "No available stock batches for this source branch."
            )

    def current_transfer_row(self):
        """Return the row info for the selected transfer, or None."""
        row = self.transfer_table.currentRow()
        if row < 0 or row >= len(self.all_transfer_rows):
            return None
        item = self.transfer_table.item(row, 6)
        info = self.all_transfer_rows[row]
        if item is None or item.text() != info.get("id"):
            return None
        return info

    def update_action_buttons(self):
        has_selection = self.transfer_table.currentRow() >= 0
        for button in (
            self.dispatch_button,
            self.transit_button,
            self.receive_button,
        ):
            button.setEnabled(has_selection)

        info = self.current_transfer_row()
        self.reconcile_button.setEnabled(
            bool(info and info.get("reconcilable"))
        )
        self.review_button.setEnabled(
            bool(info and info.get("reviewable"))
        )

    def apply_transfer_filter(self):
        text = self.transfer_search.text().strip().lower()
        status_filter = self.transfer_status_filter.currentData() or ""

        visible_count = 0
        for row in range(self.transfer_table.rowCount()):
            row_text = " ".join(
                self.transfer_table.item(row, col).text().lower()
                for col in range(5)
                if self.transfer_table.item(row, col)
            )
            row_status = self.all_transfer_rows[row]["status"]

            matches_text = not text or text in row_text
            matches_status = not status_filter or row_status == status_filter
            hide = not (matches_text and matches_status)
            self.transfer_table.setRowHidden(row, hide)
            if not hide:
                visible_count += 1

        self.transfer_empty.setVisible(visible_count == 0)
        self.transfer_table.setVisible(visible_count > 0)

    def load_transfer_products(self):
        """Load available batches for the selected source branch."""
        self.transfer_product.clear()
        branch_id = self.transfer_source.currentData()

        if not branch_id:
            self.on_product_changed()
            return

        db = SessionLocal()
        try:
            batches = (
                db.query(StockBatch)
                .filter(
                    StockBatch.branch_id == branch_id,
                    StockBatch.quantity > 0,
                )
                .order_by(StockBatch.product_id, StockBatch.batch_number)
                .all()
            )

            for batch in batches:
                label = (
                    f"Product {batch.product_id}  |  "
                    f"Batch {batch.batch_number}  |  "
                    f"Available: {batch.quantity}"
                )
                self.transfer_product.addItem(
                    label,
                    {
                        "product_id": batch.product_id,
                        "batch_number": batch.batch_number,
                        "quantity": batch.quantity,
                        "unit_cost": batch.purchase_price,
                    },
                )
        except Exception as exc:
            QMessageBox.critical(self, "Database Error", str(exc))
        finally:
            db.close()

        self.on_product_changed()

    def refresh_stock_transfers(self):
        """Refresh branch choices and transfer history from SQLite."""
        db = SessionLocal()
        try:
            branches = db.query(Branch).order_by(Branch.name).all()
            transfers = (
                db.query(StockTransfer)
                .order_by(StockTransfer.created_at.desc())
                .all()
            )

            branch_names = {
                branch.id: f"{branch.name} ({branch.code})"
                for branch in branches
            }

            source_current = self.transfer_source.currentData()
            destination_current = self.transfer_destination.currentData()

            self.transfer_source.blockSignals(True)
            self.transfer_destination.blockSignals(True)

            self.transfer_source.clear()
            self.transfer_destination.clear()

            for branch in branches:
                self.transfer_source.addItem(
                    branch_names[branch.id], branch.id
                )
                self.transfer_destination.addItem(
                    branch_names[branch.id], branch.id
                )

            for combo, previous_id in (
                (self.transfer_source, source_current),
                (self.transfer_destination, destination_current),
            ):
                index = combo.findData(previous_id)
                if index >= 0:
                    combo.setCurrentIndex(index)

            # Default destination to a different branch than the source
            if (
                self.transfer_destination.count() > 1
                and self.transfer_source.currentData()
                == self.transfer_destination.currentData()
            ):
                self.transfer_destination.setCurrentIndex(
                    (self.transfer_source.currentIndex() + 1)
                    % self.transfer_destination.count()
                )

            self.transfer_source.blockSignals(False)
            self.transfer_destination.blockSignals(False)

            # Rebuild status filter, keeping the current choice
            previous_filter = self.transfer_status_filter.currentData() or ""
            statuses = sorted({t.status.value for t in transfers})
            self.transfer_status_filter.blockSignals(True)
            self.transfer_status_filter.clear()
            self.transfer_status_filter.addItem("All statuses", "")
            for status_value in statuses:
                self.transfer_status_filter.addItem(
                    status_value.replace("_", " ").title(), status_value
                )
            index = self.transfer_status_filter.findData(previous_filter)
            self.transfer_status_filter.setCurrentIndex(max(index, 0))
            self.transfer_status_filter.blockSignals(False)

            # Fill the table
            self.transfer_table.setRowCount(0)
            self.all_transfer_rows = []

            for transfer in transfers:
                row = self.transfer_table.rowCount()
                self.transfer_table.insertRow(row)

                status_value = transfer.status.value
                self.all_transfer_rows.append({
                    "id": str(transfer.id),
                    "status": status_value,
                    "reconcilable": (
                        MultiBranchReconciliationEngine.can_reconcile(
                            transfer
                        )
                    ),
                    "reviewable": (
                        MultiBranchReconciliationEngine.can_review_dispute(
                            transfer
                        )
                    ),
                })

                values = [
                    transfer.transfer_number,
                    branch_names.get(
                        transfer.source_branch_id,
                        transfer.source_branch_id,
                    ),
                    branch_names.get(
                        transfer.destination_branch_id,
                        transfer.destination_branch_id,
                    ),
                ]
                for column, value in enumerate(values):
                    self.transfer_table.setItem(
                        row, column, QTableWidgetItem(str(value))
                    )

                self.transfer_table.setItem(
                    row, 3, self.make_status_item(status_value)
                )

                items_item = QTableWidgetItem(str(len(transfer.items)))
                items_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.transfer_table.setItem(row, 4, items_item)

                self.transfer_table.setItem(
                    row,
                    5,
                    QTableWidgetItem(
                        self.format_datetime(
                            getattr(transfer, "created_at", None)
                        )
                    ),
                )
                self.transfer_table.setItem(
                    row, 6, QTableWidgetItem(str(transfer.id))
                )

            self.apply_transfer_filter()
            self.load_transfer_products()
            self.update_action_buttons()
            self.notify(f"{len(transfers)} transfer(s) loaded.")

        except Exception as exc:
            QMessageBox.critical(self, "Database Error", str(exc))
        finally:
            db.close()

    def create_stock_transfer(self):
        source_id = self.transfer_source.currentData()
        destination_id = self.transfer_destination.currentData()
        product = self.transfer_product.currentData()
        quantity = self.transfer_quantity.value()
        notes = self.transfer_notes.text().strip()

        if not source_id or not destination_id:
            QMessageBox.warning(
                self, "Missing Branch", "Select source and destination."
            )
            return

        if source_id == destination_id:
            QMessageBox.warning(
                self, "Invalid Branches",
                "Source and destination must be different."
            )
            return

        if not product:
            QMessageBox.warning(
                self, "No Stock",
                "The selected source branch has no available stock batches."
            )
            return

        if quantity > product["quantity"]:
            QMessageBox.warning(
                self, "Insufficient Stock",
                f"Available quantity is {product['quantity']}."
            )
            return

        db = SessionLocal()
        try:
            service = StockTransferService(db)
            transfer = service.create_transfer_request(
                source_branch_id=source_id,
                destination_branch_id=destination_id,
                items=[{
                    "product_id": product["product_id"],
                    "product_name": f"Product {product['product_id']}",
                    "batch_number": product["batch_number"],
                    "quantity_dispatched": quantity,
                    "unit_cost": product["unit_cost"],
                }],
                dispatched_by="Desktop User",
                notes=notes or None,
            )

            number = transfer.transfer_number
            self.transfer_notes.clear()
            self.refresh_stock_transfers()
            self.notify(f"✔ Transfer {number} created successfully.")
            QMessageBox.information(
                self,
                "Transfer Created",
                f"Transfer {number} created successfully.",
            )

        except Exception as exc:
            db.rollback()
            QMessageBox.critical(self, "Create Failed", str(exc))
        finally:
            db.close()

    def selected_transfer_id(self):
        row = self.transfer_table.currentRow()
        if row < 0:
            QMessageBox.warning(
                self, "Select Transfer",
                "Select a transfer from the history table first."
            )
            return None

        item = self.transfer_table.item(row, 6)
        return item.text() if item else None

    def dispatch_selected_transfer(self):
        transfer_id = self.selected_transfer_id()
        if not transfer_id:
            return

        vehicle, accepted = QInputDialog.getText(
            self, "Dispatch Transfer", "Vehicle number (optional):"
        )
        if not accepted:
            return

        db = SessionLocal()
        try:
            transfer = StockTransferService(db).dispatch_transfer(
                transfer_id,
                vehicle_number=vehicle.strip() or None,
            )
            message = (
                f"{transfer.transfer_number} dispatched.\n"
                f"Challan: {transfer.delivery_challan_number}\n"
                f"Gate pass: {transfer.gate_pass_number}"
            )
            number = transfer.transfer_number
            self.refresh_stock_transfers()
            self.notify(f"✔ {number} dispatched.")
            QMessageBox.information(self, "Dispatched", message)
        except Exception as exc:
            db.rollback()
            QMessageBox.critical(self, "Dispatch Failed", str(exc))
        finally:
            db.close()

    def start_selected_transit(self):
        transfer_id = self.selected_transfer_id()
        if not transfer_id:
            return

        db = SessionLocal()
        try:
            transfer = StockTransferService(db).start_transit(transfer_id)
            number = transfer.transfer_number
            self.refresh_stock_transfers()
            self.notify(f"✔ {number} is now IN_TRANSIT.")
        except Exception as exc:
            db.rollback()
            QMessageBox.critical(self, "Transit Failed", str(exc))
        finally:
            db.close()

    def receive_selected_transfer(self):
        transfer_id = self.selected_transfer_id()
        if not transfer_id:
            return

        db = SessionLocal()
        try:
            service = StockTransferService(db)
            transfer = (
                db.query(StockTransfer)
                .filter(StockTransfer.id == transfer_id)
                .first()
            )

            if transfer is None:
                QMessageBox.warning(
                    self, "Not Found", "Transfer was not found."
                )
                return

            if transfer.status != TransferStatus.IN_TRANSIT:
                QMessageBox.warning(
                    self, "Invalid Status",
                    "Only IN_TRANSIT transfers can be received."
                )
                return

            if len(transfer.items) != 1:
                QMessageBox.warning(
                    self, "Unsupported Transfer",
                    "This screen's receipt form currently supports "
                    "transfers with one product line."
                )
                return

            transfer_item = transfer.items[0]
            dispatched = transfer_item.quantity_dispatched

            good, accepted = QInputDialog.getInt(
                self, "Receive Delivery",
                f"Good units received (dispatched: {dispatched}):",
                dispatched, 0, dispatched,
            )
            if not accepted:
                return

            damaged, accepted = QInputDialog.getInt(
                self, "Damaged Quantity",
                "Damaged units:",
                0, 0, dispatched - good,
            )
            if not accepted:
                return

            receiver, accepted = QInputDialog.getText(
                self, "Received By", "Receiver name:"
            )
            if not accepted:
                return

            service.receive_and_record_delivery(
                transfer_id=transfer_id,
                received_items=[{
                    "item_id": transfer_item.id,
                    "quantity_received": good,
                    "quantity_damaged": damaged,
                }],
                received_by=receiver.strip() or "Desktop User",
            )

            self.refresh_stock_transfers()
            self.notify("✔ Delivery recorded successfully.")
            QMessageBox.information(
                self, "Delivery Recorded",
                "Delivery saved successfully.\n"
                f"Good: {good}\nDamaged: {damaged}\n"
                f"Missing: {dispatched - good - damaged}",
            )

        except Exception as exc:
            db.rollback()
            QMessageBox.critical(self, "Receipt Failed", str(exc))
        finally:
            db.close()

    def reconcile_selected_transfer(self):
        info = self.current_transfer_row()
        if info is None or not info.get("reconcilable"):
            QMessageBox.warning(
                self, "Reconcile Transfer",
                "Select a RECEIVED transfer that has not been "
                "reconciled yet."
            )
            return

        transfer_id = info["id"]

        reconciler, accepted = QInputDialog.getText(
            self, "Reconcile Transfer", "Reconciler name:"
        )
        if not accepted:
            return
        if not reconciler.strip():
            QMessageBox.warning(
                self, "Reconcile Transfer",
                "Reconciler name is required."
            )
            return

        remarks, accepted = QInputDialog.getMultiLineText(
            self, "Reconcile Transfer", "Remarks (optional):"
        )
        if not accepted:
            return

        db = SessionLocal()
        try:
            engine = MultiBranchReconciliationEngine(db)
            engine.reconcile_transfer(
                transfer_id,
                reconciled_by=reconciler.strip(),
                remarks=remarks.strip() or None,
            )
            summary = engine.build_summary(transfer_id)
            self.refresh_stock_transfers()
            self.notify(
                f"✔ {summary['transfer_number']} reconciled: "
                f"{summary['final_status']}."
            )
            QMessageBox.information(
                self, "Reconciliation Complete",
                format_reconciliation_summary(summary),
            )
        except Exception as exc:
            db.rollback()
            QMessageBox.critical(self, "Reconciliation Failed", str(exc))
            self.refresh_stock_transfers()
        finally:
            db.close()

    def review_selected_dispute(self):
        info = self.current_transfer_row()
        if info is None or not info.get("reviewable"):
            QMessageBox.warning(
                self, "Review Dispute",
                "Select a DISPUTED transfer awaiting approval."
            )
            return

        transfer_id = info["id"]

        approver, accepted = QInputDialog.getText(
            self, "Review Dispute", "Approver name:"
        )
        if not accepted:
            return
        if not approver.strip():
            QMessageBox.warning(
                self, "Review Dispute", "Approver name is required."
            )
            return

        labels = ["Approve", "Reject"]
        choice, accepted = QInputDialog.getItem(
            self, "Review Dispute", "Decision:", labels, 0, False
        )
        if not accepted:
            return
        decision = (
            DECISION_APPROVED if choice == "Approve" else DECISION_REJECTED
        )

        remarks, accepted = QInputDialog.getMultiLineText(
            self, "Review Dispute",
            "Remarks (required when rejecting):"
        )
        if not accepted:
            return

        db = SessionLocal()
        try:
            engine = MultiBranchReconciliationEngine(db)
            engine.record_approval(
                transfer_id,
                approver=approver.strip(),
                decision=decision,
                remarks=remarks.strip() or None,
            )
            summary = engine.build_summary(transfer_id)
            self.refresh_stock_transfers()
            self.notify(
                f"✔ Decision {decision} recorded for "
                f"{summary['transfer_number']}."
            )
            QMessageBox.information(
                self, "Decision Recorded",
                format_reconciliation_summary(summary),
            )
        except Exception as exc:
            db.rollback()
            QMessageBox.critical(self, "Review Failed", str(exc))
            self.refresh_stock_transfers()
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Section router
    # ------------------------------------------------------------------
    def build_page_header(self, section_name):
        header = QHBoxLayout()
        heading_layout = QVBoxLayout()
        heading_layout.setSpacing(4)

        title = QLabel(
            "Overview" if section_name == "Dashboard" else section_name
        )
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Manage your business from one place."
            if section_name == "Dashboard"
            else f"Welcome to the {section_name} section."
        )
        subtitle.setObjectName("Subtitle")

        heading_layout.addWidget(title)
        heading_layout.addWidget(subtitle)
        header.addLayout(heading_layout)
        header.addStretch()

        # Real database connectivity check
        try:
            db = SessionLocal()
            try:
                db.query(Branch).count()
            finally:
                db.close()
            status = QLabel("●  Database Connected")
            status.setObjectName("Status")
        except Exception:
            status = QLabel("●  Database Unavailable")
            status.setObjectName("StatusError")

        header.addWidget(status, alignment=Qt.AlignmentFlag.AlignTop)
        self.content_layout.addLayout(header)

    def show_section(self, section_name):
        # Keep sidebar highlight in sync
        button = self.nav_buttons.get(section_name)
        if button is not None:
            button.setChecked(True)

        self.clear_content()
        self.build_page_header(section_name)

        if section_name == "Dashboard":
            self.build_dashboard()
        elif section_name == "Stock Transfers":
            self.build_stock_transfer_ui()
            self.content_layout.addStretch()
        else:
            self.build_placeholder(section_name)

        self.scroll.verticalScrollBar().setValue(0)

    def build_dashboard(self):
        data = self.load_dashboard_data()

        if data:
            products = f"{data['products']:,}"
            value = f"₹ {data['value']:,.2f}"
            pending = str(data["pending"])
            disputed = str(data["disputed"])
            product_note = f"Across {data['branches']} branch(es)"
            value_note = "Quantity × purchase price"
            pending_note = (
                f"{data['total_transfers']} transfer(s) in total; "
                f"includes {data['disputed']} disputed"
            )
            disputed_note = "Awaiting reconciliation approval"
        else:
            products = value = pending = disputed = "—"
            product_note = value_note = pending_note = "Data unavailable"
            disputed_note = "Data unavailable"

        cards = QHBoxLayout()
        cards.setSpacing(16)
        cards.addWidget(
            self.make_metric_card(
                "📦", "TOTAL PRODUCTS", products, product_note
            )
        )
        cards.addWidget(
            self.make_metric_card(
                "💰", "INVENTORY VALUE", value, value_note
            )
        )
        cards.addWidget(
            self.make_metric_card(
                "🔁", "PENDING TRANSFERS", pending, pending_note
            )
        )
        cards.addWidget(
            self.make_metric_card(
                "⚠️", "DISPUTED TRANSFERS", disputed, disputed_note
            )
        )
        self.content_layout.addLayout(cards)

        # Quick actions
        actions, actions_layout = self.make_card(
            margins=(24, 22, 24, 22), spacing=14
        )

        title = QLabel("Quick Actions")
        title.setObjectName("SectionTitle")
        actions_layout.addWidget(title)

        description = QLabel(
            "Jump straight into your most common tasks, or choose a "
            "module from the left navigation."
        )
        description.setWordWrap(True)
        description.setObjectName("Subtitle")
        actions_layout.addWidget(description)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        transfer_button = QPushButton("🔁  Open Stock Transfers")
        transfer_button.setObjectName("ActionButton")
        transfer_button.setCursor(Qt.CursorShape.PointingHandCursor)
        transfer_button.clicked.connect(
            lambda: self.show_section("Stock Transfers")
        )
        action_row.addWidget(transfer_button)

        inventory_button = QPushButton("🏬  View Inventory")
        inventory_button.setCursor(Qt.CursorShape.PointingHandCursor)
        inventory_button.clicked.connect(
            lambda: self.show_section("Inventory")
        )
        action_row.addWidget(inventory_button)
        action_row.addStretch()

        actions_layout.addLayout(action_row)
        self.content_layout.addWidget(actions)

        # Recent transfers
        recent_card, recent_layout = self.make_card(
            margins=(24, 22, 24, 22), spacing=12
        )
        recent_title = QLabel("Recent Transfers")
        recent_title.setObjectName("SectionTitle")
        recent_layout.addWidget(recent_title)

        recent = data["recent"] if data else []
        if recent:
            table = QTableWidget(len(recent), 4)
            table.setHorizontalHeaderLabels(
                ["Transfer Number", "Source", "Destination", "Status"]
            )
            self.style_table(table)
            table.setSelectionMode(
                QAbstractItemView.SelectionMode.NoSelection
            )
            table.setFixedHeight(46 + 40 * len(recent))

            for row, (number, source, dest, status_value) in enumerate(recent):
                table.setItem(row, 0, QTableWidgetItem(str(number)))
                table.setItem(row, 1, QTableWidgetItem(str(source)))
                table.setItem(row, 2, QTableWidgetItem(str(dest)))
                table.setItem(row, 3, self.make_status_item(status_value))
            recent_layout.addWidget(table)
        else:
            empty = QLabel("No transfers yet. Create your first transfer!")
            empty.setObjectName("EmptyState")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            recent_layout.addWidget(empty)

        self.content_layout.addWidget(recent_card)
        self.content_layout.addStretch()

    def build_placeholder(self, section_name):
        card, layout = self.make_card(margins=(24, 22, 24, 22), spacing=10)

        title = QLabel("Coming soon")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        message = QLabel(
            f"The {section_name} screen is a placeholder. "
            "Business logic and database integration are not connected yet."
        )
        message.setWordWrap(True)
        message.setObjectName("Subtitle")
        layout.addWidget(message)

        self.content_layout.addWidget(card)
        self.content_layout.addStretch()


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())