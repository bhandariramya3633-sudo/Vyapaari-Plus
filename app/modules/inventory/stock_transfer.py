import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.modules.inventory.models import (
    InTransitLog,
    StockBatch,
    StockTransfer,
    TransferItem,
    TransferStatus,
)


def _utc_now() -> datetime:
    """Return the current UTC time as a timezone-naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class StockTransferService:
    """Manage stock transfers, gate passes, and inventory audit events."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _validate_quantity(value, field_name, allow_zero=False):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(f"{field_name} must be a whole number.")

        minimum = 0 if allow_zero else 1
        if value < minimum:
            raise ValidationError(f"{field_name} must be at least {minimum}.")

        return value

    @staticmethod
    def _validate_unit_cost(value):
        if isinstance(value, bool):
            raise ValidationError(
                "Unit cost must be a finite, non-negative number."
            )

        try:
            cost = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValidationError(
                "Unit cost must be a finite, non-negative number."
            ) from None

        if not math.isfinite(cost) or cost < 0:
            raise ValidationError(
                "Unit cost must be a finite, non-negative number."
            )

        return cost

    def _record_event(
        self,
        transfer_id,
        event_type,
        idempotency_key,
        quantity=0,
        actor=None,
        details=None,
    ):
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValidationError("An idempotency key is required.")

        existing = (
            self.db.query(InTransitLog)
            .filter(InTransitLog.idempotency_key == idempotency_key)
            .first()
        )
        if existing is not None:
            raise ValidationError(
                f"Duplicate idempotency key: {idempotency_key}"
            )

        self.db.add(
            InTransitLog(
                id=str(uuid.uuid4()),
                transfer_id=transfer_id,
                event_type=event_type,
                quantity=quantity,
                actor=actor,
                idempotency_key=idempotency_key,
                details=details,
                occurred_at=_utc_now(),
            )
        )

    def create_transfer_request(
        self,
        source_branch_id,
        destination_branch_id,
        items,
        dispatched_by=None,
        notes=None,
    ):
        if not isinstance(source_branch_id, str) or not source_branch_id.strip():
            raise ValidationError("Source branch ID is required.")

        if (
            not isinstance(destination_branch_id, str)
            or not destination_branch_id.strip()
        ):
            raise ValidationError("Destination branch ID is required.")

        if source_branch_id == destination_branch_id:
            raise ValidationError(
                "Source and destination branch cannot be the same."
            )

        if not isinstance(items, list) or not items:
            raise ValidationError("Transfer must contain at least one item.")

        validated = []
        seen = set()

        for index, data in enumerate(items, 1):
            if not isinstance(data, dict):
                raise ValidationError(f"Item {index} must be an object.")

            product_id = data.get("product_id")
            if not isinstance(product_id, str) or not product_id.strip():
                raise ValidationError(
                    f"Item {index} requires a valid product_id."
                )

            quantity = self._validate_quantity(
                data.get("quantity_dispatched"),
                f"Item {index} quantity_dispatched",
            )
            unit_cost = self._validate_unit_cost(data.get("unit_cost", 0.0))
            batch_number = data.get("batch_number")

            if batch_number is not None and (
                not isinstance(batch_number, str) or not batch_number.strip()
            ):
                raise ValidationError(
                    f"Item {index} has an invalid batch_number."
                )

            key = (product_id, batch_number)
            if key in seen:
                raise ValidationError(
                    "Duplicate product and batch lines are not allowed "
                    "in one transfer."
                )
            seen.add(key)

            product_name = data.get("product_name", "Unknown Product")
            if not isinstance(product_name, str) or not product_name.strip():
                raise ValidationError(
                    f"Item {index} has an invalid product_name."
                )

            validated.append(
                {
                    "product_id": product_id,
                    "product_name": product_name.strip(),
                    "batch_number": batch_number,
                    "quantity_dispatched": quantity,
                    "unit_cost": unit_cost,
                }
            )

        transfer = StockTransfer(
            id=str(uuid.uuid4()),
            transfer_number=(
                f"TRF-{_utc_now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
            ),
            status=TransferStatus.DRAFT,
            source_branch_id=source_branch_id,
            destination_branch_id=destination_branch_id,
            dispatched_by=dispatched_by,
            notes=notes,
        )

        try:
            self.db.add(transfer)
            self.db.flush()

            for data in validated:
                self.db.add(
                    TransferItem(
                        id=str(uuid.uuid4()),
                        transfer_id=transfer.id,
                        product_id=data["product_id"],
                        product_name=data["product_name"],
                        batch_number=data["batch_number"],
                        quantity_dispatched=data["quantity_dispatched"],
                        quantity_received=0,
                        quantity_damaged=0,
                        unit_cost=data["unit_cost"],
                    )
                )

            self.db.commit()
            self.db.refresh(transfer)
            return transfer

        except Exception:
            self.db.rollback()
            raise

    def dispatch_transfer(
        self,
        transfer_id,
        vehicle_number=None,
        driver_contact=None,
    ):
        try:
            transfer = (
                self.db.query(StockTransfer)
                .filter(StockTransfer.id == transfer_id)
                .with_for_update()
                .first()
            )

            if transfer is None:
                raise EntityNotFoundError("StockTransfer", transfer_id)

            if transfer.status != TransferStatus.DRAFT:
                raise ValidationError(
                    "Only a DRAFT transfer can be dispatched. "
                    f"Current status: {transfer.status.value}"
                )

            if not transfer.items:
                raise ValidationError(
                    "Cannot dispatch a transfer without items."
                )

            # Validate every source batch before deducting stock.
            movements = []

            for item in transfer.items:
                query = select(StockBatch).where(
                    StockBatch.branch_id == transfer.source_branch_id,
                    StockBatch.product_id == item.product_id,
                )

                if item.batch_number is not None:
                    query = query.where(
                        StockBatch.batch_number == item.batch_number
                    )

                batch = self.db.execute(
                    query.order_by(StockBatch.expiry_date, StockBatch.id)
                    .with_for_update()
                ).scalars().first()

                if batch is None:
                    raise ValidationError(
                        "No matching source stock found for product "
                        f"{item.product_id}."
                    )

                if batch.quantity < item.quantity_dispatched:
                    raise ValidationError(
                        f"Insufficient stock for product {item.product_id}: "
                        f"available {batch.quantity}, "
                        f"required {item.quantity_dispatched}."
                    )

                movements.append((item, batch))

            for item, batch in movements:
                batch.quantity -= item.quantity_dispatched

            now = _utc_now()
            transfer.status = TransferStatus.IN_TRANSIT
            transfer.dispatched_at = now
            transfer.vehicle_number = vehicle_number
            transfer.driver_contact = driver_contact

            if not transfer.gate_pass_number:
                transfer.gate_pass_number = (
                    f"GP-{now:%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
                )

            self._record_event(
                transfer.id,
                "DISPATCHED",
                f"{transfer.id}:DISPATCHED",
                quantity=sum(
                    item.quantity_dispatched for item in transfer.items
                ),
                actor=transfer.dispatched_by,
                details=(
                    f"Gate pass: {transfer.gate_pass_number}; "
                    f"Vehicle: {vehicle_number or 'Not specified'}"
                ),
            )

            self.db.commit()
            self.db.refresh(transfer)
            return transfer

        except Exception:
            self.db.rollback()
            raise

    def receive_and_record_delivery(
        self,
        transfer_id,
        received_items,
        received_by=None,
    ):
        """Record usable and damaged quantities separately.

        Each item needs item_id and quantity_received.
        quantity_damaged is optional and defaults to zero.
        Only good, accepted quantities are added to destination stock.
        """
        try:
            transfer = (
                self.db.query(StockTransfer)
                .filter(StockTransfer.id == transfer_id)
                .with_for_update()
                .first()
            )

            if transfer is None:
                raise EntityNotFoundError("StockTransfer", transfer_id)

            if transfer.status != TransferStatus.IN_TRANSIT:
                raise ValidationError(
                    "Only an IN_TRANSIT transfer can be received. "
                    f"Current status: {transfer.status.value}"
                )

            if not isinstance(received_items, list):
                raise ValidationError("received_items must be a list.")

            expected = {item.id: item for item in transfer.items}
            received = {}

            for index, data in enumerate(received_items, 1):
                if not isinstance(data, dict):
                    raise ValidationError(
                        f"Received item {index} must be an object."
                    )

                item_id = data.get("item_id")
                if not isinstance(item_id, str) or item_id not in expected:
                    raise ValidationError(
                        f"Received item {index} has an invalid item_id."
                    )

                if item_id in received:
                    raise ValidationError(
                        f"Duplicate receipt entry for item {item_id}."
                    )

                good_quantity = self._validate_quantity(
                    data.get("quantity_received"),
                    f"Item {item_id} quantity_received",
                    allow_zero=True,
                )
                damaged_quantity = self._validate_quantity(
                    data.get("quantity_damaged", 0),
                    f"Item {item_id} quantity_damaged",
                    allow_zero=True,
                )

                dispatched_quantity = expected[item_id].quantity_dispatched

                if good_quantity + damaged_quantity > dispatched_quantity:
                    raise ValidationError(
                        "Good and damaged quantities combined cannot exceed "
                        f"the dispatched quantity for item {item_id}."
                    )

                received[item_id] = {
                    "good": good_quantity,
                    "damaged": damaged_quantity,
                }

            missing = set(expected) - set(received)
            if missing:
                raise ValidationError(
                    "Receipt is missing item IDs: "
                    + ", ".join(sorted(missing))
                )

            source_batches = {}
            destination_batches = {}

            for item_id, item in expected.items():
                source_query = self.db.query(StockBatch).filter(
                    StockBatch.branch_id == transfer.source_branch_id,
                    StockBatch.product_id == item.product_id,
                )

                if item.batch_number is not None:
                    source_query = source_query.filter(
                        StockBatch.batch_number == item.batch_number
                    )

                source_batches[item_id] = (
                    source_query.order_by(StockBatch.id).first()
                )

                destination_batches[item_id] = (
                    self.db.query(StockBatch)
                    .filter(
                        StockBatch.branch_id == transfer.destination_branch_id,
                        StockBatch.product_id == item.product_id,
                        StockBatch.batch_number == (
                            item.batch_number or "TRANSFER"
                        ),
                    )
                    .with_for_update()
                    .first()
                )

            total_good = 0
            total_damaged = 0
            total_dispatched = 0
            event_details = []

            for item_id, item in expected.items():
                good_quantity = received[item_id]["good"]
                damaged_quantity = received[item_id]["damaged"]

                item.quantity_received = good_quantity
                item.quantity_damaged = damaged_quantity

                total_good += good_quantity
                total_damaged += damaged_quantity
                total_dispatched += item.quantity_dispatched

                if good_quantity > 0:
                    batch = destination_batches[item_id]
                    source_batch = source_batches[item_id]

                    if batch is None:
                        batch = StockBatch(
                            id=str(uuid.uuid4()),
                            product_id=item.product_id,
                            branch_id=transfer.destination_branch_id,
                            batch_number=item.batch_number or "TRANSFER",
                            quantity=good_quantity,
                            purchase_price=(
                                source_batch.purchase_price
                                if source_batch is not None
                                else item.unit_cost
                            ),
                            selling_price=(
                                source_batch.selling_price
                                if source_batch is not None
                                else item.unit_cost
                            ),
                            expiry_date=(
                                source_batch.expiry_date
                                if source_batch is not None
                                else None
                            ),
                        )
                        self.db.add(batch)
                    else:
                        batch.quantity += good_quantity

                event_details.append(
                    f"{item.product_name}: good={good_quantity}, "
                    f"damaged={damaged_quantity}"
                )

            transfer.status = TransferStatus.RECEIVED
            transfer.received_at = _utc_now()
            transfer.received_by = received_by

            self._record_event(
                transfer.id,
                "RECEIVED",
                f"{transfer.id}:RECEIVED",
                quantity=total_good + total_damaged,
                actor=received_by,
                details=(
                    f"Dispatched={total_dispatched}; good={total_good}; "
                    f"damaged={total_damaged}. "
                    + "; ".join(event_details)
                ),
            )

            self.db.commit()
            self.db.refresh(transfer)
            return transfer

        except Exception:
            self.db.rollback()
            raise