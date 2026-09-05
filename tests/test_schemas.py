"""Validasi payload simulator & bentuk event WebSocket — tanpa database."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.events import (
    OrderCreatedData,
    OrderCreatedEvent,
    OrderStageUpdatedData,
    OrderStageUpdatedEvent,
)
from app.schemas.orders import FulfilmentMode, Order, SimulateOrderRequest

PRODUCT = "cccccccc-0000-0000-0000-000000000001"
STORE = "aaaaaaaa-0000-0000-0000-000000000001"


def _valid_payload(**overrides) -> dict:
    payload = {
        "store_id": STORE,
        "fulfilment_mode": "pickup",
        "payment_method": "qris",
        "items": [{"product_id": PRODUCT, "qty": 1}],
    }
    payload.update(overrides)
    return payload


def test_payload_contoh_prd_93_diterima():
    """Payload persis dari PRD Bagian 9.3 harus lolos validasi."""
    req = SimulateOrderRequest.model_validate(
        {
            "store_id": STORE,
            "user_id": "11111111-1111-1111-1111-111111111111",
            "fulfilment_mode": "pickup",
            "payment_method": "qris",
            "voucher_code": None,
            "items": [
                {
                    "product_id": PRODUCT,
                    "qty": 2,
                    "size": "M",
                    "milk": "oat",
                    "ice": "less_ice",
                    "sugar": "50%",
                    "extra_shot": False,
                    "note": "less sugar please",
                }
            ],
        }
    )
    assert req.fulfilment_mode is FulfilmentMode.pickup
    assert req.items[0].qty == 2
    assert req.items[0].milk == "oat"


def test_items_kosong_ditolak():
    with pytest.raises(ValidationError):
        SimulateOrderRequest.model_validate(_valid_payload(items=[]))


def test_qty_nol_ditolak():
    with pytest.raises(ValidationError):
        SimulateOrderRequest.model_validate(
            _valid_payload(items=[{"product_id": PRODUCT, "qty": 0}])
        )


def test_fulfilment_mode_tidak_dikenal_ditolak():
    with pytest.raises(ValidationError):
        SimulateOrderRequest.model_validate(_valid_payload(fulfilment_mode="drive_thru"))


def test_default_item_aman():
    req = SimulateOrderRequest.model_validate(_valid_payload())
    item = req.items[0]
    assert item.qty == 1
    assert item.extra_shot is False
    assert item.size is None


def test_items_diserialisasi_sebagai_json_untuk_jsonb():
    """`place_order()` menerima jsonb — UUID harus jadi str saat di-dump."""
    req = SimulateOrderRequest.model_validate(_valid_payload())
    dumped = req.items[0].model_dump(mode="json")
    assert dumped["product_id"] == PRODUCT
    assert isinstance(dumped["product_id"], str)


def test_stage_di_luar_0_3_ditolak():
    with pytest.raises(ValidationError):
        OrderStageUpdatedData(
            order_id=uuid4(), stage=4, status="active", updated_at=datetime.now(timezone.utc)
        )


def test_bentuk_event_sesuai_prd_95_dan_96():
    now = datetime.now(timezone.utc)
    order = Order(
        id=uuid4(), order_no="ORD-20260905-0001", store_id=STORE,
        fulfilment_mode="pickup", payment_status="paid", subtotal=44000,
        discount=0, delivery_fee=0, total=44000, status="paid", stage=0,
        pickup_code="A102", created_at=now, updated_at=now,
    )

    created = OrderCreatedEvent(data=OrderCreatedData(order=order, items=[]))
    assert created.model_dump(mode="json")["event"] == "order.created"
    assert set(created.model_dump()["data"]) == {"order", "items"}

    updated = OrderStageUpdatedEvent(
        data=OrderStageUpdatedData(order_id=order.id, stage=1, status="active", updated_at=now)
    )
    body = updated.model_dump(mode="json")
    assert body["event"] == "order.stage_updated"
    assert set(body["data"]) == {"order_id", "stage", "status", "updated_at"}
