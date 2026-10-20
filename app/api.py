from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.modules.inventory.service import InventoryService
from app.core.exceptions import (
    EntityNotFoundError,
    ValidationError,
    InsufficientStockError,
)

app = FastAPI(
    title="Vyapaari+ Inventory Transfer API",
    version="1.0.0",
    description="API for inter-store stock transfers and reconciliation.",
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class TransferItemInput(BaseModel):
    product_id: str = Field(min_length=1)
    product_name: str = Field(default="Unknown Product", min_length=1)
    quantity_dispatched: int = Field(gt=0)
    unit_cost: float = Field(default=0.0, ge=0)
    batch_number: str | None = None


class CreateTransferInput(BaseModel):
    source_branch_id: str = Field(min_length=1)
    destination_branch_id: str = Field(min_length=1)
    items: list[TransferItemInput] = Field(min_length=1)
    dispatched_by: str | None = None
    notes: str | None = None


class DispatchInput(BaseModel):
    vehicle_number: str | None = None
    driver_contact: str | None = None


class ReceivedItemInput(BaseModel):
    item_id: str = Field(min_length=1)
    quantity_received: int = Field(ge=0)
    quantity_damaged: int = Field(default=0, ge=0)


class ReceiveInput(BaseModel):
    items: list[ReceivedItemInput]
    received_by: str | None = None


def to_dict(transfer):
    return {
        "id": transfer.id,
        "transfer_number": transfer.transfer_number,
        "gate_pass_number": transfer.gate_pass_number,
        "source_branch_id": transfer.source_branch_id,
        "destination_branch_id": transfer.destination_branch_id,
        "status": transfer.status.value,
        "items": [
            {
                "item_id": item.id,
                "product_id": item.product_id,
                "product_name": item.product_name,
                "quantity_dispatched": item.quantity_dispatched,
                "quantity_received": item.quantity_received,
                "quantity_damaged": item.quantity_damaged,
                "unit_cost": item.unit_cost,
            }
            for item in transfer.items
        ],
    }


def service_error(exc):
    if isinstance(exc, EntityNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValidationError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(exc, InsufficientStockError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/transfers", status_code=201)
def create_transfer(payload: CreateTransferInput, db: Session = Depends(get_db)):
    service = InventoryService(db)
    try:
        transfer = service.transfers.create_transfer_request(
            source_branch_id=payload.source_branch_id,
            destination_branch_id=payload.destination_branch_id,
            items=[item.model_dump() for item in payload.items],
            dispatched_by=payload.dispatched_by,
            notes=payload.notes,
        )
        return to_dict(transfer)
    except (EntityNotFoundError, ValidationError, InsufficientStockError) as exc:
        service_error(exc)


@app.post("/transfers/{transfer_id}/dispatch")
def dispatch_transfer(
    transfer_id: str,
    payload: DispatchInput,
    db: Session = Depends(get_db),
):
    service = InventoryService(db)
    try:
        transfer = service.transfers.dispatch_transfer(
            transfer_id,
            vehicle_number=payload.vehicle_number,
            driver_contact=payload.driver_contact,
        )
        return to_dict(transfer)
    except (EntityNotFoundError, ValidationError, InsufficientStockError) as exc:
        service_error(exc)


@app.post("/transfers/{transfer_id}/receive")
def receive_transfer(
    transfer_id: str,
    payload: ReceiveInput,
    db: Session = Depends(get_db),
):
    service = InventoryService(db)
    try:
        transfer = service.transfers.receive_and_record_delivery(
            transfer_id,
            received_items=[item.model_dump() for item in payload.items],
            received_by=payload.received_by,
        )
        return to_dict(transfer)
    except (EntityNotFoundError, ValidationError, InsufficientStockError) as exc:
        service_error(exc)


@app.post("/transfers/{transfer_id}/reconcile")
def reconcile_transfer(
    transfer_id: str,
    reconciled_by: str = "api",
    resolution_status: str = "RESOLVED",
    remarks: str | None = None,
    db: Session = Depends(get_db),
):
    service = InventoryService(db)
    try:
        log = service.reconciliation.reconcile_transfer(
            transfer_id=transfer_id,
            reconciled_by=reconciled_by,
            resolution_status=resolution_status,
            remarks=remarks,
        )
        return {
            "transfer_id": log.transfer_id,
            "total_dispatched_units": log.total_dispatched_units,
            "total_received_units": log.total_received_units,
            "variance_units": log.variance_units,
            "total_transit_loss_value": log.total_transit_loss_value,
            "resolution_status": log.resolution_status,
            "remarks": log.remarks,
        }
    except (EntityNotFoundError, ValidationError, InsufficientStockError) as exc:
        service_error(exc)