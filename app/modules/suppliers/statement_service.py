import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.suppliers.models import (
    LedgerEntryType,
    Supplier,
    SupplierCreditLedger,
)


class SupplierStatementService:
    """Export supplier credit ledger statements to CSV and PDF."""

    def __init__(self, db: Session):
        self.db = db

    def _get_statement_data(self, supplier_id: str):
        supplier = self.db.get(Supplier, supplier_id)
        if supplier is None:
            raise ValueError("Supplier not found.")

        entries = self.db.scalars(
            select(SupplierCreditLedger)
            .where(SupplierCreditLedger.supplier_id == supplier_id)
            .order_by(
                SupplierCreditLedger.entry_date,
                SupplierCreditLedger.id,
            )
        ).all()

        rows = []
        running_balance = Decimal("0.00")

        for entry in entries:
            amount = Decimal(str(entry.amount))
            is_payment = entry.entry_type == LedgerEntryType.PAYMENT

            debit = Decimal("0.00") if is_payment else amount
            credit = amount if is_payment else Decimal("0.00")
            running_balance += entry.signed_amount

            rows.append({
                "date": (
                    entry.entry_date.date().isoformat()
                    if entry.entry_date else ""
                ),
                "entry_type": entry.entry_type.value,
                "reference": (
                    entry.invoice.invoice_number
                    if entry.invoice is not None
                    else entry.payment.reference
                    if entry.payment is not None
                    else ""
                ),
                "description": entry.description,
                "debit": f"{debit:.2f}",
                "credit": f"{credit:.2f}",
                "balance": f"{running_balance:.2f}",
            })

        return supplier.name, rows

    def export_csv(
        self, supplier_id: str, output_path: str | Path
    ) -> Path:
        supplier_name, rows = self._get_statement_data(supplier_id)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open(
            "w", newline="", encoding="utf-8-sig"
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "date", "entry_type", "reference",
                    "description", "debit", "credit", "balance",
                ],
            )
            writer.writeheader()
            writer.writerow({
                "date": "Supplier",
                "entry_type": supplier_name,
                "reference": "",
                "description": f"Statement generated {date.today()}",
                "debit": "",
                "credit": "",
                "balance": "",
            })
            writer.writerows(rows)

        return path

    def export_pdf(
        self, supplier_id: str, output_path: str | Path
    ) -> Path:
        supplier_name, rows = self._get_statement_data(supplier_id)

        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.platypus import (
                SimpleDocTemplate,
                Paragraph,
                Spacer,
                Table,
                TableStyle,
            )
            from reportlab.lib.styles import getSampleStyleSheet
        except ImportError as exc:
            raise RuntimeError(
                "PDF export requires ReportLab. Install it with: "
                "python -m pip install reportlab"
            ) from exc

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        document = SimpleDocTemplate(
            str(path), pagesize=landscape(A4)
        )
        styles = getSampleStyleSheet()

        content = [
            Paragraph("Supplier Statement", styles["Title"]),
            Paragraph(f"Supplier: {supplier_name}", styles["Normal"]),
            Paragraph(
                f"Generated: {date.today()}", styles["Normal"]
            ),
            Spacer(1, 12),
        ]

        table_data = [[
            "Date", "Type", "Reference", "Description",
            "Debit", "Credit", "Balance",
        ]]

        for row in rows:
            table_data.append([
                row["date"],
                row["entry_type"],
                row["reference"],
                row["description"][:45],
                row["debit"],
                row["credit"],
                row["balance"],
            ])

        table = Table(
            table_data,
            repeatRows=1,
            colWidths=[65, 65, 90, 190, 65, 65, 65],
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))

        content.append(table)
        document.build(content)
        return path