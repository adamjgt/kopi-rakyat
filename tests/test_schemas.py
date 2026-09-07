"""Validasi payload place_order & bentuk event WebSocket — tanpa database."""

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
from app.schemas.orders import FulfilmentMode, Order, PlaceOrderRequest

PRODUCT = "cccccccc-0000-0000-0000-000000000001"
STORE = "aaaaaaaa-0000-0000-0000-000000000001"
USER = "11111111-1111-1111-1111-111111111111"


def _item(**overrides) -> dict:
    item = {
        "product_id": PRODUCT,
        "name_snapshot": "Kopi Susu Rakyat",
        "unit_price": 24000,
        "qty": 2,
        "line_total": 48000,
    }
    item.update(overrides)
    return item


def _valid_payload(**overrides) -> dict:
    payload = {
        "user_id": USER,
        "store_id": STORE,
        "fulfilment_mode": "pickup",
        "payment_method": "qris",
        "subtotal": 48000,
        "total": 48000,
        "items": [_item()],
    }
    payload.update(overrides)
    return payload


def test_payload_lengkap_diterima():
    req = PlaceOrderRequest.model_validate(
        _valid_payload(
            items=[
                _item(size="M", milk="oat", ice="less_ice", sugar="50%", note="x")
            ]
        )
    )
    assert req.fulfilment_mode is FulfilmentMode.pickup
    assert req.items[0].qty == 2
    assert req.items[0].milk == "oat"
    assert req.total == 48000


def test_pre_order_mode_dikenali():
    """Skema asli menambah fulfilment_mode 'pre_order'."""
    req = PlaceOrderRequest.model_validate(_valid_payload(fulfilment_mode="pre_order"))
    assert req.fulfilment_mode is FulfilmentMode.pre_order


def test_items_kosong_ditolak():
    with pytest.raises(ValidationError):
        PlaceOrderRequest.model_validate(_valid_payload(items=[]))


def test_qty_nol_ditolak():
    with pytest.raises(ValidationError):
        PlaceOrderRequest.model_validate(_valid_payload(items=[_item(qty=0)]))


def test_name_snapshot_wajib():
    """name_snapshot dikirim klien (server tidak melihat katalog)."""
    bad = _item()
    del bad["name_snapshot"]
    with pytest.raises(ValidationError):
        PlaceOrderRequest.model_validate(_valid_payload(items=[bad]))


def test_fulfilment_mode_tidak_dikenal_ditolak():
    with pytest.raises(ValidationError):
        PlaceOrderRequest.model_validate(_valid_payload(fulfilment_mode="drive_thru"))


def test_items_diserialisasi_sebagai_json_untuk_jsonb():
    req = PlaceOrderRequest.model_validate(_valid_payload())
    dumped = req.items[0].model_dump(mode="json")
    assert dumped["product_id"] == PRODUCT
    assert isinstance(dumped["product_id"], str)


def test_money_adalah_integer():
    req = PlaceOrderRequest.model_validate(_valid_payload())
    assert isinstance(req.total, int)
    assert isinstance(req.items[0].unit_price, int)


def test_bentuk_event_sesuai_kontrak_ws():
    now = datetime.now(timezone.utc)
    order = Order(
        id=uuid4(), order_no="#KR-4471", store_id=STORE,
        fulfilment_mode="pickup", payment_method="qris", payment_status="paid",
        subtotal=48000, discount=0, delivery_fee=0, total=48000,
        status="received", stage=0, pickup_code="A-12", created_at=now,
    )

    created = OrderCreatedEvent(data=OrderCreatedData(order=order, items=[]))
    assert created.model_dump(mode="json")["event"] == "order.created"
    assert set(created.model_dump()["data"]) == {"order", "items"}

    updated = OrderStageUpdatedEvent(
        data=OrderStageUpdatedData(
            order_id=order.id, stage=1, status="preparing", updated_at=now
        )
    )
    body = updated.model_dump(mode="json")
    assert body["event"] == "order.stage_updated"
    assert set(body["data"]) == {"order_id", "stage", "status", "updated_at"}
    assert body["data"]["status"] == "preparing"


def test_status_lama_ditolak():
    """Status skema lama ('paid'/'active') bukan lagi status order valid."""
    with pytest.raises(ValidationError):
        OrderStageUpdatedData(
            order_id=uuid4(), stage=1, status="active",
            updated_at=datetime.now(timezone.utc),
        )
