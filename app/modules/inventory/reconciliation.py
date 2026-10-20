import math
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.modules.inventory.models import (
    ReconciliationApproval,
    ReconciliationLog,
    StockTransfer,
    TransferStatus,
)


RESOLUTION_PENDING = "PENDING"
RESOLUTION_RESOLVED = "RESOLVED"

DECISION_APPROVED = "APPROVED"
DECISION_REJECTED = "REJECTED"

RECONCILABLE_STATUSES = (
    TransferStatus.RECEIVED,
    TransferStatus.DISPUTED,
)


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class MultiBranchReconciliationEngine:
    """Reconcile received, damaged, and missing stock."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def can_reconcile(transfer: StockTransfer) -> bool:
        """Check whether a transfer can be reconciled for the first time."""
        return (
            transfer.status in RECONCILABLE_STATUSES
            and transfer.reconciliation is None
            and bool(transfer.items)
        )

    @staticmethod
    def can_review_dispute(transfer: StockTransfer) -> bool:
        """Check whether a disputed transfer awaits an approval decision."""
        log = transfer.reconciliation

        return (
            transfer.status == TransferStatus.DISPUTED
            and log is not None
            and log.resolution_status == RESOLUTION_PENDING
        )

    def reconcile_transfer(
        self,
        transfer_id: str,
        reconciled_by: str,
        resolution_status: str = None,
        remarks: str = None,
    ) -> ReconciliationLog:
        """Calculate stock variance and create an audit record."""

        try:
            return self._reconcile_transfer(
                transfer_id,
                reconciled_by,
                resolution_status,
                remarks,
            )
        except Exception:
            self.db.rollback()
            raise

    def _reconcile_transfer(
        self,
        transfer_id: str,
        reconciled_by: str,
        resolution_status: str,
        remarks: str,
    ) -> ReconciliationLog:
        if not isinstance(transfer_id, str) or not transfer_id.strip():
            raise ValidationError("Transfer ID is required.")

        if not isinstance(reconciled_by, str) or not reconciled_by.strip():
            raise ValidationError("Reconciled-by is required.")

        if remarks is not None and not isinstance(remarks, str):
            raise ValidationError("Remarks must be text.")

        transfer = (
            self.db.query(StockTransfer)
            .filter(StockTransfer.id == transfer_id)
            .with_for_update()
            .first()
        )

        if transfer is None:
            raise EntityNotFoundError("StockTransfer", transfer_id)

        if transfer.reconciliation is not None:
            raise ValidationError(
                "Transfer has already been reconciled."
            )

        if transfer.status not in RECONCILABLE_STATUSES:
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
            received = item.quantity_received
            damaged = item.quantity_damaged or 0

            for label, quantity in (
                ("dispatched", dispatched),
                ("received", received),
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

            if received + damaged > dispatched:
                raise ValidationError(
                    f"Received and damaged quantities exceed the "
                    f"dispatched quantity for item {item.id}."
                )

            try:
                unit_cost = float(item.unit_cost or 0.0)
            except (TypeError, ValueError, OverflowError):
                raise ValidationError(
                    f"Invalid unit cost for item {item.id}."
                ) from None

            if not math.isfinite(unit_cost) or unit_cost < 0:
                raise ValidationError(
                    f"Invalid unit cost for item {item.id}."
                )

            missing = dispatched - received - damaged

            total_dispatched += dispatched
            total_good_received += received
            total_damaged += damaged
            total_missing += missing

            total_loss_value += (damaged + missing) * unit_cost

        # Variance includes damaged and missing units.
        variance = total_dispatched - total_good_received

        if resolution_status is None:
            resolution_status = (
                RESOLUTION_RESOLVED
                if variance == 0
                else RESOLUTION_PENDING
            )
        else:
            if (
                not isinstance(resolution_status, str)
                or not resolution_status.strip()
            ):
                raise ValidationError(
                    "Resolution status must be PENDING or RESOLVED."
                )

            resolution_status = resolution_status.strip().upper()

            if resolution_status not in {
                RESOLUTION_PENDING,
                RESOLUTION_RESOLVED,
            }:
                raise ValidationError(
                    "Invalid resolution status. "
                    "Allowed values: PENDING, RESOLVED."
                )

        if (
            variance != 0
            and resolution_status == RESOLUTION_RESOLVED
        ):
            raise ValidationError(
                "A transfer with a variance cannot be marked RESOLVED "
                "during reconciliation. Record an approval decision instead."
            )

        summary = (
            f"Good received: {total_good_received}; "
            f"Damaged units: {total_damaged}; "
            f"Missing units: {total_missing}; "
            f"Total variance: {variance}."
        )
        

        clean_remarks = remarks.strip() if remarks else ""
        combined_remarks = (
            f"{clean_remarks}\n{summary}"
            if clean_remarks
            else summary
        )

        log = ReconciliationLog(
            id=str(uuid.uuid4()),
            transfer_id=transfer.id,
            total_dispatched_units=total_dispatched,
            total_received_units=total_good_received,
            variance_units=variance,
            total_transit_loss_value=round(total_loss_value, 2),
            reconciled_by=reconciled_by.strip(),
            reconciled_at=_utc_now(),
            resolution_status=resolution_status,
            remarks=combined_remarks,
        )

        self.db.add(log)

        transfer.status = (
            TransferStatus.RECONCILED
            if variance == 0
            else TransferStatus.DISPUTED
        )

        try:
            self.db.commit()
            self.db.refresh(log)
            return log
        except IntegrityError:
            self.db.rollback()
            raise ValidationError(
                "Transfer has already been reconciled."
            ) from None

    def record_approval(
        self,
        transfer_id: str,
        approver: str,
        decision: str,
        remarks: str = None,
    ) -> ReconciliationApproval:
        """Record an approval or rejection for a disputed transfer."""

        try:
            return self._record_approval(
                transfer_id,
                approver,
                decision,
                remarks,
            )
        except Exception:
            self.db.rollback()
            raise

    def _record_approval(
        self,
        transfer_id: str,
        approver: str,
        decision: str,
        remarks: str,
    ) -> ReconciliationApproval:
        if not isinstance(transfer_id, str) or not transfer_id.strip():
            raise ValidationError("Transfer ID is required.")

        if not isinstance(approver, str) or not approver.strip():
            raise ValidationError("Approver name is required.")

        if not isinstance(decision, str) or not decision.strip():
            raise ValidationError(
                "Decision must be APPROVED or REJECTED."
            )

        decision = decision.strip().upper()

        if decision not in {DECISION_APPROVED, DECISION_REJECTED}:
            raise ValidationError(
                "Invalid decision. Allowed values: APPROVED, REJECTED."
            )

        if remarks is not None and not isinstance(remarks, str):
            raise ValidationError("Remarks must be text.")

        transfer = (
            self.db.query(StockTransfer)
            .filter(StockTransfer.id == transfer_id)
            .with_for_update()
            .first()
        )

        if transfer is None:
            raise EntityNotFoundError("StockTransfer", transfer_id)

        log = transfer.reconciliation

        if log is None:
            raise ValidationError(
                "Transfer has not been reconciled yet."
            )

        if transfer.status != TransferStatus.DISPUTED:
            raise ValidationError(
                "Only DISPUTED transfers can be approved or rejected. "
                f"Current status: {transfer.status.value}"
            )

        if log.resolution_status != RESOLUTION_PENDING:
            raise ValidationError(
                "This reconciliation is already resolved."
            )

        clean_remarks = remarks.strip() if remarks else ""

        if decision == DECISION_REJECTED and not clean_remarks:
            raise ValidationError(
                "Remarks are required when rejecting a reconciliation."
            )

        approval = ReconciliationApproval(
            id=str(uuid.uuid4()),
            transfer_id=transfer.id,
            reconciliation_id=log.id,
            approver=approver.strip(),
            decision=decision,
            remarks=clean_remarks or None,
            decided_at=_utc_now(),
        )

        self.db.add(approval)

        if decision == DECISION_APPROVED:
            log.resolution_status = RESOLUTION_RESOLVED
            transfer.status = TransferStatus.RECONCILED

        self.db.commit()
        self.db.refresh(approval)

        return approval

    def get_approval_history(
        self,
        transfer_id: str,
    ) -> list[ReconciliationApproval]:
        """Return approval decisions for a transfer, oldest first."""

        return (
            self.db.query(ReconciliationApproval)
            .filter(
                ReconciliationApproval.transfer_id == transfer_id
            )
            .order_by(
                ReconciliationApproval.decided_at.asc(),
                ReconciliationApproval.id.asc(),
            )
            .all()
        )

    def build_summary(self, transfer_id: str) -> dict:
        """Return reconciliation figures and approval information."""

        transfer = (
            self.db.query(StockTransfer)
            .filter(StockTransfer.id == transfer_id)
            .first()
        )

        if transfer is None:
            raise EntityNotFoundError("StockTransfer", transfer_id)

        log = transfer.reconciliation

        if log is None:
            raise ValidationError(
                "Transfer has not been reconciled yet."
            )

        damaged = sum(
            item.quantity_damaged or 0
            for item in transfer.items
        )

        missing = sum(
            item.quantity_dispatched
            - item.quantity_received
            - (item.quantity_damaged or 0)
            for item in transfer.items
        )

        approvals = self.get_approval_history(transfer.id)

        if approvals:
            approval_status = approvals[-1].decision
        elif log.variance_units == 0:
            approval_status = "NOT_REQUIRED"
        else:
            approval_status = RESOLUTION_PENDING

        return {
            "transfer_id": transfer.id,
            "transfer_number": transfer.transfer_number,
            "dispatched": log.total_dispatched_units,
            "good_received": log.total_received_units,
            "damaged": damaged,
            "missing": missing,
            "variance": log.variance_units,
            "loss_value": log.total_transit_loss_value,
            "resolution_status": log.resolution_status,
            "final_status": transfer.status.value,
            "reconciled_by": log.reconciled_by,
            "reconciled_at": log.reconciled_at,
            "remarks": log.remarks,
            "approval_status": approval_status,
            "approvals": [
                {
                    "approver": approval.approver,
                    "decision": approval.decision,
                    "remarks": approval.remarks,
                    "decided_at": approval.decided_at,
                }
                for approval in approvals
            ],
        }