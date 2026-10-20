import math
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.modules.inventory.models import (
    ReconciliationLog,
    StockTransfer,
    TransferStatus,
)


def _utc_now() -> datetime:
    """Return UTC time compatible with existing naive DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MultiBranchReconciliationEngine:
    """Reconcile good, damaged, and missing quantities in stock transfers."""

    def __init__(self, db: Session):
        self.db = db

    def reconcile_transfer(
        self,
        transfer_id: str,
        reconciled_by: str,
        resolution_status: str = "RESOLVED",
        remarks: str = None,
    ) -> ReconciliationLog:
        """Calculate stock variance and create or update its audit record."""

        if not isinstance(transfer_id, str) or not transfer_id.strip():
            raise ValidationError("Transfer ID is required.")

        if not isinstance(reconciled_by, str) or not reconciled_by.strip():
            raise ValidationError("Reconciled by is required.")

        if (
            not isinstance(resolution_status, str)
            or not resolution_status.strip()
        ):
            raise ValidationError("Resolution status is required.")

        if remarks is not None and not isinstance(remarks, str):
            raise ValidationError("Remarks must be text.")

        try:
            transfer = (
                self.db.query(StockTransfer)
                .filter(StockTransfer.id == transfer_id)
                .with_for_update()
                .first()
            )

            if transfer is None:
                raise EntityNotFoundError("StockTransfer", transfer_id)

            if transfer.status not in (
                TransferStatus.RECEIVED,
                TransferStatus.DISPUTED,
                TransferStatus.RECONCILED,
            ):
                raise ValidationError(
                    "Cannot reconcile a transfer before delivery. "
                    f"Current status: {transfer.status.value}"
                )

            if not transfer.items:
                raise ValidationError(
                    "Cannot reconcile a transfer without items."
                )

            total_dispatched = 0
            total_good_received = 0
            total_damaged = 0
            total_missing = 0
            total_loss_value = 0.0

            for item in transfer.items:
                dispatched = item.quantity_dispatched
                good = item.quantity_received
                damaged = getattr(item, "quantity_damaged", 0) or 0
                unit_cost = item.unit_cost or 0.0

                for label, quantity in (
                    ("dispatched", dispatched),
                    ("good received", good),
                    ("damaged", damaged),
                ):
                    if (
                        isinstance(quantity, bool)
                        or not isinstance(quantity, int)
                        or quantity < 0
                    ):
                        raise ValidationError(
                            f"Invalid {label} quantity for item {item.id}."
                        )

                if good + damaged > dispatched:
                    raise ValidationError(
                        f"Good and damaged quantities exceed dispatched "
                        f"quantity for item {item.id}."
                    )

                try:
                    unit_cost = float(unit_cost)
                except (TypeError, ValueError, OverflowError):
                    raise ValidationError(
                        f"Invalid unit cost for item {item.id}."
                    ) from None

                if not math.isfinite(unit_cost) or unit_cost < 0:
                    raise ValidationError(
                        f"Invalid unit cost for item {item.id}."
                    )

                missing = dispatched - good - damaged

                total_dispatched += dispatched
                total_good_received += good
                total_damaged += damaged
                total_missing += missing

                # Damaged and missing units both represent a stock variance.
                total_loss_value += (damaged + missing) * unit_cost

            total_variance = total_damaged + total_missing
            now = _utc_now()

            log = transfer.reconciliation

            if log is None:
                log = ReconciliationLog(
                    id=str(uuid.uuid4()),
                    transfer_id=transfer.id,
                )
                self.db.add(log)

            log.total_dispatched_units = total_dispatched
            log.total_received_units = total_good_received
            log.variance_units = total_variance
            log.total_transit_loss_value = round(total_loss_value, 2)
            log.reconciled_by = reconciled_by.strip()
            log.reconciled_at = now
            log.resolution_status = resolution_status.strip().upper()

            variance_summary = (
                f"Good received: {total_good_received}; "
                f"damaged: {total_damaged}; "
                f"missing: {total_missing}; "
                f"total variance: {total_variance}."
            )

            log.remarks = (
                f"{remarks.strip()}\n{variance_summary}"
                if remarks and remarks.strip()
                else variance_summary
            )

            if total_variance == 0:
                transfer.status = TransferStatus.RECONCILED
            else:
                transfer.status = TransferStatus.DISPUTED

            self.db.commit()
            self.db.refresh(log)
            return log

        except Exception:
            self.db.rollback()
            raise