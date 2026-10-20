import pytest

from app.core.exceptions import ValidationError
from app.modules.inventory.models import (
    Branch,
    StockBatch,
    TransferStatus,
    InTransitLog,
)
from app.modules.inventory.stock_transfer import StockTransferService
from app.modules.inventory.reconciliation import MultiBranchReconciliationEngine


def create_branches(db_session):
    """Create the source and destination branches."""
    source = Branch(
        id="b1",
        name="Main Warehouse",
        code="WH-01",
        is_warehouse=True,
    )
    destination = Branch(
        id="b2",
        name="Downtown Store",
        code="STR-02",
        is_warehouse=False,
    )
    db_session.add_all([source, destination])
    db_session.commit()


def add_source_stock(db_session, quantity=100):
    """Add a stock batch to the source warehouse."""
    stock = StockBatch(
        id="batch-source-1",
        product_id="p1",
        branch_id="b1",
        batch_number="BATCH-001",
        quantity=quantity,
        purchase_price=450.0,
        selling_price=500.0,
    )
    db_session.add(stock)
    db_session.commit()
    return stock


def create_transfer(service, quantity=20):
    return service.create_transfer_request(
        "b1",
        "b2",
        [
            {
                "product_id": "p1",
                "product_name": "Premium Basmati Rice 5kg",
                "batch_number": "BATCH-001",
                "quantity_dispatched": quantity,
                "unit_cost": 450.0,
            }
        ],
        dispatched_by="Ramesh Manager",
    )


def test_stock_transfer_lifecycle(db_session):
    """Test creating, dispatching, receiving, and reconciling."""
    create_branches(db_session)
    source_stock = add_source_stock(db_session)

    service = StockTransferService(db_session)
    reconciler = MultiBranchReconciliationEngine(db_session)
    transfer = create_transfer(service, quantity=20)

    assert transfer.status == TransferStatus.DRAFT
    assert len(transfer.items) == 1
    assert transfer.items[0].quantity_dispatched == 20
    assert transfer.items[0].quantity_received == 0
    assert source_stock.quantity == 100

    dispatched = service.dispatch_transfer(
        transfer.id,
        vehicle_number="DL-01-AB-1234",
    )

    assert dispatched.status == TransferStatus.IN_TRANSIT
    assert dispatched.vehicle_number == "DL-01-AB-1234"

    db_session.refresh(source_stock)
    assert source_stock.quantity == 80

    logs = (
        db_session.query(InTransitLog)
        .filter(InTransitLog.transfer_id == transfer.id)
        .all()
    )
    assert any(log.event_type == "DISPATCHED" for log in logs)

    received = service.receive_and_record_delivery(
        transfer.id,
        [
            {
                "item_id": transfer.items[0].id,
                "quantity_received": 19,
            }
        ],
        received_by="Suresh Store",
    )

    assert received.status == TransferStatus.RECEIVED
    assert received.items[0].quantity_received == 19

    destination_stock = (
        db_session.query(StockBatch)
        .filter(
            StockBatch.branch_id == "b2",
            StockBatch.product_id == "p1",
            StockBatch.batch_number == "BATCH-001",
        )
        .first()
    )
    assert destination_stock is not None
    assert destination_stock.quantity == 19

    rec_log = reconciler.reconcile_transfer(
        transfer.id,
        reconciled_by="Auditor Sharma",
        remarks="1 unit damaged in transit",
    )

    assert rec_log.variance_units == 1
    assert rec_log.total_transit_loss_value == 450.0
    db_session.refresh(transfer)
    assert transfer.status == TransferStatus.DISPUTED


def test_create_transfer_rejects_same_branch(db_session):
    service = StockTransferService(db_session)

    with pytest.raises(ValidationError):
        service.create_transfer_request(
            "b1",
            "b1",
            [{"product_id": "p1", "quantity_dispatched": 5}],
        )


def test_create_transfer_rejects_negative_quantity(db_session):
    service = StockTransferService(db_session)

    with pytest.raises(ValidationError):
        service.create_transfer_request(
            "b1",
            "b2",
            [{"product_id": "p1", "quantity_dispatched": -5}],
        )


def test_receive_rejects_quantity_above_dispatched(db_session):
    create_branches(db_session)
    add_source_stock(db_session, quantity=20)

    service = StockTransferService(db_session)
    transfer = create_transfer(service, quantity=5)
    service.dispatch_transfer(transfer.id)

    with pytest.raises(ValidationError):
        service.receive_and_record_delivery(
            transfer.id,
            [
                {
                    "item_id": transfer.items[0].id,
                    "quantity_received": 6,
                }
            ],
        )

    db_session.refresh(transfer)
    assert transfer.status == TransferStatus.IN_TRANSIT


def test_dispatch_rejects_insufficient_stock(db_session):
    create_branches(db_session)
    add_source_stock(db_session, quantity=3)

    service = StockTransferService(db_session)
    transfer = create_transfer(service, quantity=5)

    with pytest.raises(ValidationError):
        service.dispatch_transfer(transfer.id)

    db_session.refresh(transfer)
    assert transfer.status == TransferStatus.DRAFT

    stock = (
        db_session.query(StockBatch)
        .filter(StockBatch.branch_id == "b1")
        .one()
    )
    assert stock.quantity == 3


def test_dispatch_creates_only_one_audit_event(db_session):
    create_branches(db_session)
    add_source_stock(db_session, quantity=20)

    service = StockTransferService(db_session)
    transfer = create_transfer(service, quantity=5)
    service.dispatch_transfer(transfer.id)

    with pytest.raises(ValidationError):
        service.dispatch_transfer(transfer.id)

    events = (
        db_session.query(InTransitLog)
        .filter(
            InTransitLog.transfer_id == transfer.id,
            InTransitLog.event_type == "DISPATCHED",
        )
        .all()
    )
    assert len(events) == 1