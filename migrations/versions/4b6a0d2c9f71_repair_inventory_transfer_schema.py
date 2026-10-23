"""Repair inventory transfer schema.

Revision ID: 4b6a0d2c9f71
Revises: 692fa2e1bbdd
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "4b6a0d2c9f71"
down_revision: Union[str, Sequence[str], None] = "692fa2e1bbdd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add optional delivery-tracking fields without losing existing transfers.
    op.add_column(
        "stock_transfers",
        sa.Column("delivery_challan_number", sa.String(50), nullable=True),
    )
    op.create_index(
        "uq_stock_transfers_delivery_challan_number",
        "stock_transfers",
        ["delivery_challan_number"],
        unique=True,
    )
    op.add_column(
        "stock_transfers",
        sa.Column("carrier_name", sa.String(100), nullable=True),
    )
    op.add_column(
        "stock_transfers",
        sa.Column("estimated_delivery_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "stock_transfers",
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Replace the accidental unique index with a normal index.
    op.drop_index("ix_store_locations_branch_id", table_name="store_locations")
    op.create_index(
        "ix_store_locations_branch_id",
        "store_locations",
        ["branch_id"],
        unique=False,
    )

    # Carrier movement and delivery events.
    op.create_table(
        "carrier_logs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("transfer_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("logged_by", sa.String(100), nullable=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["transfer_id"],
            ["stock_transfers.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_carrier_logs_transfer_logged",
        "carrier_logs",
        ["transfer_id", "logged_at"],
        unique=False,
    )

    # Append-only reconciliation approval history.
    op.create_table(
        "reconciliation_approvals",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("transfer_id", sa.String(36), nullable=False),
        sa.Column("reconciliation_id", sa.String(36), nullable=False),
        sa.Column("approver", sa.String(100), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('APPROVED', 'REJECTED')",
            name="ck_reconciliation_approvals_decision",
        ),
        sa.ForeignKeyConstraint(
            ["transfer_id"],
            ["stock_transfers.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reconciliation_id"],
            ["reconciliation_logs.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reconciliation_approvals_transfer",
        "reconciliation_approvals",
        ["transfer_id", "decided_at"],
        unique=False,
    )
    op.create_index(
        "ix_reconciliation_approvals_reconciliation",
        "reconciliation_approvals",
        ["reconciliation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reconciliation_approvals_reconciliation",
        table_name="reconciliation_approvals",
    )
    op.drop_index(
        "ix_reconciliation_approvals_transfer",
        table_name="reconciliation_approvals",
    )
    op.drop_table("reconciliation_approvals")

    op.drop_index(
        "ix_carrier_logs_transfer_logged",
        table_name="carrier_logs",
    )
    op.drop_table("carrier_logs")



    op.drop_index(
        "uq_stock_transfers_delivery_challan_number",
        table_name="stock_transfers",
    )
    with op.batch_alter_table("stock_transfers") as batch_op:
        batch_op.drop_column("delivered_at")
        batch_op.drop_column("estimated_delivery_at")
        batch_op.drop_column("carrier_name")
        batch_op.drop_column("delivery_challan_number")
