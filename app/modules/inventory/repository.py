from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.modules.inventory.models import (
    Branch,
    ReconciliationApproval,
    ReconciliationLog,
    StockBatch,
    StockTransfer,
    TransferItem,
    TransferStatus,
)


class InventoryRepository:
    """Database access methods for branches, batches and transfers."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Transfers
    # ------------------------------------------------------------------
    @staticmethod
    def _transfer_detail_options():
        """Eager-load children in two extra queries instead of N+1."""
        return (
            selectinload(StockTransfer.items),
            selectinload(StockTransfer.reconciliation),
        )

    def get_all_transfers(self) -> list[StockTransfer]:
        return (
            self.db.query(StockTransfer)
            .options(*self._transfer_detail_options())
            .order_by(StockTransfer.created_at.desc())
            .all()
        )

    def get_transfer_by_id(
        self, transfer_id: str
    ) -> StockTransfer:
        transfer = (
            self.db.query(StockTransfer)
            .options(*self._transfer_detail_options())
            .filter(StockTransfer.id == transfer_id)
            .first()
        )

        if transfer is None:
            raise EntityNotFoundError("StockTransfer", transfer_id)

        return transfer

    def get_transfers_by_status(
        self, status: TransferStatus
    ) -> list[StockTransfer]:
        # Served by ix_stock_transfers_status_created.
        return (
            self.db.query(StockTransfer)
            .options(*self._transfer_detail_options())
            .filter(StockTransfer.status == status)
            .order_by(StockTransfer.created_at.desc())
            .all()
        )

    def list_transfers(
        self,
        offset: int = 0,
        limit: int = 50,
    ) -> list[StockTransfer]:
        if offset < 0:
            raise ValidationError("Offset cannot be negative.")

        if limit < 1 or limit > 500:
            raise ValidationError("Limit must be between 1 and 500.")

        return (
            self.db.query(StockTransfer)
            .options(*self._transfer_detail_options())
            .order_by(StockTransfer.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_transfers_by_branch(
        self,
        branch_id: str,
        direction: str = "any",
        status: TransferStatus = None,
    ) -> list[StockTransfer]:
        """Transfers leaving ("source"), entering ("destination") or
        touching ("any") a branch, optionally filtered by status.

        Served by ix_stock_transfers_source_status and
        ix_stock_transfers_destination_status.
        """
        if direction not in ("source", "destination", "any"):
            raise ValidationError(
                "Direction must be source, destination or any."
            )

        query = self.db.query(StockTransfer).options(
            *self._transfer_detail_options()
        )

        if direction == "source":
            query = query.filter(StockTransfer.source_branch_id == branch_id)
        elif direction == "destination":
            query = query.filter(
                StockTransfer.destination_branch_id == branch_id
            )
        else:
            query = query.filter(
                (StockTransfer.source_branch_id == branch_id)
                | (StockTransfer.destination_branch_id == branch_id)
            )

        if status is not None:
            query = query.filter(StockTransfer.status == status)

        return query.order_by(StockTransfer.created_at.desc()).all()

    def count_transfers_by_status(self) -> dict[str, int]:
        """Return {status value: count}; every status is present."""
        counts = {status.value: 0 for status in TransferStatus}

        rows = (
            self.db.query(StockTransfer.status, func.count(StockTransfer.id))
            .group_by(StockTransfer.status)
            .all()
        )

        for status, count in rows:
            counts[status.value] = count

        return counts

    def get_transfer_items(self, transfer_id: str) -> list[TransferItem]:
        return (
            self.db.query(TransferItem)
            .filter(TransferItem.transfer_id == transfer_id)
            .order_by(TransferItem.product_name.asc(), TransferItem.id.asc())
            .all()
        )

    def get_transfer_items_by_product(
        self,
        product_id: str,
        batch_number: str = None,
    ) -> list[TransferItem]:
        """Served by ix_transfer_items_product_batch."""
        query = self.db.query(TransferItem).filter(
            TransferItem.product_id == product_id
        )

        if batch_number is not None:
            query = query.filter(TransferItem.batch_number == batch_number)

        return query.order_by(TransferItem.created_at.desc()).all()

    # ------------------------------------------------------------------
    # Reconciliation and approvals
    # ------------------------------------------------------------------
    def get_reconciliation_by_transfer_id(
        self, transfer_id: str
    ) -> ReconciliationLog | None:
        """Return the single reconciliation log of a transfer, if any."""
        return (
            self.db.query(ReconciliationLog)
            .filter(ReconciliationLog.transfer_id == transfer_id)
            .first()
        )

    def list_reconciliations(
        self,
        resolution_status: str = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[ReconciliationLog]:
        if offset < 0:
            raise ValidationError("Offset cannot be negative.")

        if limit < 1 or limit > 500:
            raise ValidationError("Limit must be between 1 and 500.")

        if resolution_status is not None:
            resolution_status = resolution_status.strip().upper()
            if resolution_status not in ("PENDING", "RESOLVED"):
                raise ValidationError(
                    "Resolution status must be PENDING or RESOLVED."
                )

        query = self.db.query(ReconciliationLog)

        if resolution_status is not None:
            # Served by ix_reconciliation_logs_status_reconciled_at.
            query = query.filter(
                ReconciliationLog.resolution_status == resolution_status
            )

        return (
            query.order_by(ReconciliationLog.reconciled_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def get_disputed_transfers_awaiting_approval(
        self,
    ) -> list[StockTransfer]:
        """DISPUTED transfers whose reconciliation is still PENDING."""
        return (
            self.db.query(StockTransfer)
            .options(*self._transfer_detail_options())
            .join(
                ReconciliationLog,
                ReconciliationLog.transfer_id == StockTransfer.id,
            )
            .filter(
                StockTransfer.status == TransferStatus.DISPUTED,
                ReconciliationLog.resolution_status == "PENDING",
            )
            .order_by(ReconciliationLog.reconciled_at.asc())
            .all()
        )

    def get_approval_history(
        self, transfer_id: str
    ) -> list[ReconciliationApproval]:
        """Approval decisions for a transfer, oldest first."""
        return (
            self.db.query(ReconciliationApproval)
            .filter(ReconciliationApproval.transfer_id == transfer_id)
            .order_by(
                ReconciliationApproval.decided_at.asc(),
                ReconciliationApproval.id.asc(),
            )
            .all()
        )

    # ------------------------------------------------------------------
    # Branches and batches
    # ------------------------------------------------------------------
    def get_branches(self) -> list[Branch]:
        return (
            self.db.query(Branch)
            .order_by(Branch.name.asc())
            .all()
        )

    def get_branch_by_id(self, branch_id: str) -> Branch:
        branch = (
            self.db.query(Branch)
            .filter(Branch.id == branch_id)
            .first()
        )

        if branch is None:
            raise EntityNotFoundError("Branch", branch_id)

        return branch

    def get_stock_batches(
        self,
        branch_id: str = None,
        product_id: str = None,
    ) -> list[StockBatch]:
        query = self.db.query(StockBatch)

        if branch_id is not None:
            query = query.filter(StockBatch.branch_id == branch_id)

        if product_id is not None:
            query = query.filter(StockBatch.product_id == product_id)

        return query.order_by(StockBatch.batch_number.asc()).all()

    def get_batch_by_id(self, batch_id: str) -> StockBatch:
        batch = (
            self.db.query(StockBatch)
            .filter(StockBatch.id == batch_id)
            .first()
        )

        if batch is None:
            raise EntityNotFoundError("StockBatch", batch_id)

        return batch

    def adjust_batch_quantities(
        self,
        adjustments: dict[str, int],
    ) -> list[StockBatch]:
        """Apply quantity adjustments atomically; never allow negative stock.

        adjustments maps batch IDs to signed quantity changes.
        Example: {"batch-id": -2} removes two units.
        """

        if not isinstance(adjustments, dict) or not adjustments:
            raise ValidationError(
                "Provide at least one batch quantity adjustment."
            )

        try:
            updated_batches = []

            for batch_id, delta in adjustments.items():
                if (
                    isinstance(delta, bool)
                    or not isinstance(delta, int)
                ):
                    raise ValidationError(
                        "Batch quantity adjustments must be integers."
                    )

                batch = (
                    self.db.query(StockBatch)
                    .filter(StockBatch.id == batch_id)
                    .with_for_update()
                    .first()
                )

                if batch is None:
                    raise EntityNotFoundError("StockBatch", batch_id)

                new_quantity = batch.quantity + delta

                if new_quantity < 0:
                    raise ValidationError(
                        f"Insufficient stock in batch {batch_id}."
                    )

                batch.quantity = new_quantity
                updated_batches.append(batch)

            self.db.commit()

            for batch in updated_batches:
                self.db.refresh(batch)

            return updated_batches

        except Exception:
            self.db.rollback()
            raise