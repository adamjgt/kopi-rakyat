"""RPC asli `place_order()` & `advance_order_stage()` lewat backend.

Butuh PostgreSQL berisi MIRROR skema asli. Otomatis di-skip bila tidak
terjangkau (lihat tests/conftest.py).

Catatan kontrak ASLI yang diuji di sini:
  * place_order() TIDAK menghitung harga — subtotal/total/unit_price/line_total
    dikirim klien dan disimpan apa adanya.
  * Order baru: status 'received', payment_status 'paid', stage 0,
    order_no '#KR-####', +1 stamp & poin.
  * advance_order_stage(): stage 0→1→2→3, status preparing → ready/on_the_way
    → completed; di-scope ke pemilik order (backend impersonasi via JWT claims).
"""

from __future__ import annotations

import re
from uuid import UUID

import pytest

from tests.conftest import (
    ADDRESS_BUDI,
    PRODUCT_TUMBLER,
    USER_BUDI,
    default_item,
    order_payload,
)

pytestmark = pytest.mark.db


# ---------------------------------------------------------------------------
# place_order()
# ---------------------------------------------------------------------------
async def test_place_order_stage_0_status_received_payment_paid(client):
    resp = await client.post("/api/dev/simulate-order", json=order_payload())

    assert resp.status_code == 201, resp.text
    order = resp.json()
    assert order["stage"] == 0
    assert order["status"] == "received"
    assert order["payment_status"] == "paid"
    assert order["payment_provider"] == "simulated"
    assert re.fullmatch(r"#KR-\d+", order["order_no"]), order["order_no"]


async def test_place_order_menyimpan_harga_dari_klien(client):
    """Server tidak menghitung — angka yang disimpan = yang dikirim."""
    payload = order_payload()
    resp = await client.post("/api/dev/simulate-order", json=payload)
    order = resp.json()

    assert order["subtotal"] == payload["subtotal"] == 48000
    assert order["total"] == payload["total"] == 48000
    assert isinstance(order["total"], int)

    detail = (await client.get(f"/api/orders/{order['id']}")).json()
    item = detail["items"][0]
    assert item["unit_price"] == 24000
    assert item["line_total"] == 48000


async def test_place_order_menyimpan_snapshot_opsi_item(client):
    resp = await client.post("/api/dev/simulate-order", json=order_payload())
    detail = (await client.get(f"/api/orders/{resp.json()['id']}")).json()

    item = detail["items"][0]
    assert item["name_snapshot"] == "Kopi Susu Rakyat"
    assert item["size"] == "M"
    assert item["milk"] == "oat"
    assert item["ice"] == "less_ice"
    assert item["sugar"] == "50%"
    assert item["extra_shot"] is False
    assert item["note"] == "less sugar please"
    assert item["qty"] == 2


async def test_place_order_pickup_menghasilkan_pickup_code(client):
    resp = await client.post("/api/dev/simulate-order", json=order_payload())
    assert resp.json()["pickup_code"], "place_order asli selalu men-generate pickup_code"


async def test_place_order_dine_in_menyimpan_nomor_meja(client):
    payload = order_payload(fulfilment_mode="dine_in", table_number="7")
    order = (await client.post("/api/dev/simulate-order", json=payload)).json()
    assert order["table_number"] == "7"


async def test_place_order_delivery_total_termasuk_ongkir(client):
    payload = order_payload(
        fulfilment_mode="delivery", address_id=ADDRESS_BUDI, delivery_fee=10000
    )
    order = (await client.post("/api/dev/simulate-order", json=payload)).json()

    assert order["delivery_fee"] == 10000
    assert order["total"] == order["subtotal"] - order["discount"] + 10000


async def test_place_order_multi_item(client):
    tumbler = default_item(
        product_id=PRODUCT_TUMBLER, name_snapshot="Tumbler Kopi Rakyat",
        size=None, milk=None, ice=None, sugar=None, note=None,
        unit_price=85000, qty=1, line_total=85000,
    )
    payload = order_payload(items=[default_item(), tumbler])

    order = (await client.post("/api/dev/simulate-order", json=payload)).json()
    detail = (await client.get(f"/api/orders/{order['id']}")).json()

    assert len(detail["items"]) == 2
    assert order["subtotal"] == 48000 + 85000


async def test_place_order_menambah_stamp_dan_poin(client):
    """Efek samping loyalty: +1 stamp, +total/1000 poin, 1 baris ledger."""
    from app import db

    payload = order_payload()  # total 48000 -> 48 poin
    order = (await client.post("/api/dev/simulate-order", json=payload)).json()

    row = await db.fetchrow(
        "SELECT delta_stamps, delta_points FROM loyalty_ledger WHERE order_id = $1",
        UUID(order["id"]),
    )
    assert row is not None
    assert row["delta_stamps"] == 1
    assert row["delta_points"] == 48


async def test_place_order_422_bila_items_kosong(client):
    resp = await client.post("/api/dev/simulate-order", json=order_payload(items=[]))
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# advance_order_stage()
# ---------------------------------------------------------------------------
async def _new_order(client, **overrides) -> dict:
    resp = await client.post("/api/dev/simulate-order", json=order_payload(**overrides))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_advance_menaikkan_stage_satu_per_satu(client):
    order = await _new_order(client)
    for expected in (1, 2, 3):
        resp = await client.patch(f"/api/orders/{order['id']}/advance")
        assert resp.status_code == 200, resp.text
        assert resp.json()["stage"] == expected


async def test_advance_status_pickup(client):
    order = await _new_order(client)  # pickup
    s1 = (await client.patch(f"/api/orders/{order['id']}/advance")).json()
    s2 = (await client.patch(f"/api/orders/{order['id']}/advance")).json()
    s3 = (await client.patch(f"/api/orders/{order['id']}/advance")).json()

    assert s1["status"] == "preparing"
    assert s2["status"] == "ready"
    assert s3["status"] == "completed"


async def test_advance_status_delivery_on_the_way(client):
    order = await _new_order(
        client, fulfilment_mode="delivery", address_id=ADDRESS_BUDI, delivery_fee=10000
    )
    await client.patch(f"/api/orders/{order['id']}/advance")           # stage 1
    s2 = (await client.patch(f"/api/orders/{order['id']}/advance")).json()  # stage 2

    assert s2["stage"] == 2
    assert s2["status"] == "on_the_way"


async def test_advance_di_stage_final_idempotent(client):
    """advance_order_stage asli meng-clamp di 3 (least(3, stage+1)), tidak error."""
    order = await _new_order(client)
    for _ in range(3):
        await client.patch(f"/api/orders/{order['id']}/advance")

    resp = await client.patch(f"/api/orders/{order['id']}/advance")
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage"] == 3
    assert resp.json()["status"] == "completed"


async def test_advance_order_tidak_dikenal_404(client):
    resp = await client.patch("/api/orders/00000000-0000-0000-0000-0000000000ff/advance")
    assert resp.status_code == 404


async def test_advance_tersimpan_permanen_di_database(client):
    order = await _new_order(client)
    await client.patch(f"/api/orders/{order['id']}/advance")

    from app import repository

    persisted = await repository.get_order(UUID(order["id"]))
    assert persisted is not None
    assert persisted.stage == 1
    assert persisted.status.value == "preparing"
