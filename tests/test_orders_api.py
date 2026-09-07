"""Endpoint pembacaan order & Store Isolation di sisi REST (Deliverable 6).

Butuh PostgreSQL; otomatis di-skip bila tidak terjangkau.
"""

from __future__ import annotations

import pytest

from tests.conftest import (
    ADDRESS_BUDI,
    STORE_KEMANG,
    STORE_SUDIRMAN,
    order_payload,
)

pytestmark = pytest.mark.db


async def _create(client, store_id: str = STORE_KEMANG, **overrides) -> dict:
    resp = await client.post(
        "/api/dev/simulate-order", json=order_payload(store_id, **overrides)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Store isolation
# ---------------------------------------------------------------------------
async def test_order_store_lain_tidak_pernah_muncul(client):
    """PRD Acceptance: POS satu store tidak menerima order store lain."""
    kemang = await _create(client, STORE_KEMANG)
    sudirman = await _create(client, STORE_SUDIRMAN)

    ids_kemang = {o["id"] for o in (await client.get(
        "/api/orders", params={"store_id": STORE_KEMANG})).json()}
    ids_sudirman = {o["id"] for o in (await client.get(
        "/api/orders", params={"store_id": STORE_SUDIRMAN})).json()}

    assert kemang["id"] in ids_kemang
    assert kemang["id"] not in ids_sudirman
    assert sudirman["id"] in ids_sudirman
    assert sudirman["id"] not in ids_kemang


async def test_store_id_wajib(client):
    """Tanpa store_id endpoint harus menolak, bukan mengembalikan semua order."""
    resp = await client.get("/api/orders")
    assert resp.status_code == 422


async def test_store_tidak_dikenal_404(client):
    resp = await client.get(
        "/api/orders", params={"store_id": "00000000-0000-0000-0000-0000000000ff"}
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------
async def test_filter_stage(client):
    baru = await _create(client)
    diproses = await _create(client)
    await client.patch(f"/api/orders/{diproses['id']}/advance")

    stage0 = (await client.get(
        "/api/orders", params={"store_id": STORE_KEMANG, "stage": 0})).json()
    stage1 = (await client.get(
        "/api/orders", params={"store_id": STORE_KEMANG, "stage": 1})).json()

    assert all(o["stage"] == 0 for o in stage0)
    assert baru["id"] in {o["id"] for o in stage0}
    assert diproses["id"] in {o["id"] for o in stage1}
    assert diproses["id"] not in {o["id"] for o in stage0}


async def test_filter_status(client):
    order = await _create(client)

    received = (await client.get(
        "/api/orders", params={"store_id": STORE_KEMANG, "status": "received"})).json()
    completed = (await client.get(
        "/api/orders", params={"store_id": STORE_KEMANG, "status": "completed"})).json()

    assert order["id"] in {o["id"] for o in received}
    assert order["id"] not in {o["id"] for o in completed}
    assert all(o["status"] == "received" for o in received)


async def test_filter_fulfilment_mode(client):
    pickup = await _create(client, fulfilment_mode="pickup")
    dine_in = await _create(client, fulfilment_mode="dine_in", table_number="3")

    hasil = (await client.get(
        "/api/orders",
        params={"store_id": STORE_KEMANG, "fulfilment_mode": "dine_in"},
    )).json()

    ids = {o["id"] for o in hasil}
    assert dine_in["id"] in ids
    assert pickup["id"] not in ids
    assert all(o["fulfilment_mode"] == "dine_in" for o in hasil)


async def test_filter_gabungan(client):
    order = await _create(client, fulfilment_mode="delivery", address_id=ADDRESS_BUDI)

    hasil = (await client.get(
        "/api/orders",
        params={
            "store_id": STORE_KEMANG,
            "stage": 0,
            "status": "received",
            "fulfilment_mode": "delivery",
        },
    )).json()

    assert order["id"] in {o["id"] for o in hasil}


async def test_stage_di_luar_rentang_ditolak(client):
    resp = await client.get("/api/orders", params={"store_id": STORE_KEMANG, "stage": 9})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Bentuk payload
# ---------------------------------------------------------------------------
async def test_antrian_menyertakan_order_items_tanpa_request_tambahan(client):
    """PRD 7.1: POS tidak perlu request kedua untuk melihat item."""
    order = await _create(client)

    hasil = (await client.get("/api/orders", params={"store_id": STORE_KEMANG})).json()
    ditemukan = next(o for o in hasil if o["id"] == order["id"])

    assert ditemukan["items"], "order_items harus ikut di-join"
    assert ditemukan["items"][0]["name_snapshot"] == "Kopi Susu Rakyat"
    assert ditemukan["store_name"] == "Kopi Rakyat Kemang"


async def test_detail_order_menyertakan_items_dan_info_store(client):
    order = await _create(client)

    detail = (await client.get(f"/api/orders/{order['id']}")).json()

    assert detail["id"] == order["id"]
    assert detail["store_name"] == "Kopi Rakyat Kemang"
    assert detail["customer_name"] == "Budi Santoso"
    assert len(detail["items"]) == 1


async def test_detail_order_tidak_dikenal_404(client):
    resp = await client.get("/api/orders/00000000-0000-0000-0000-0000000000ff")
    assert resp.status_code == 404


async def test_antrian_terurut_terbaru_dulu(client):
    lama = await _create(client)
    baru = await _create(client)

    hasil = (await client.get(
        "/api/orders", params={"store_id": STORE_KEMANG, "limit": 50})).json()
    ids = [o["id"] for o in hasil]

    assert ids.index(baru["id"]) < ids.index(lama["id"])


async def test_limit_dihormati(client):
    for _ in range(3):
        await _create(client)

    hasil = (await client.get(
        "/api/orders", params={"store_id": STORE_KEMANG, "limit": 2})).json()

    assert len(hasil) == 2


# ---------------------------------------------------------------------------
# Endpoint lain
# ---------------------------------------------------------------------------
async def test_health_melaporkan_database_up(client):
    body = (await client.get("/api/health")).json()

    assert body["status"] == "ok"
    assert body["database"] == "up"
    assert body["realtime_mode"] in ("notify", "poll")


async def test_daftar_store_berisi_seed(client):
    stores = (await client.get("/api/stores")).json()
    keys = {s["key"] for s in stores}
    assert {"kemang", "sudirman"} <= keys


async def test_detail_store(client):
    store = (await client.get(f"/api/stores/{STORE_KEMANG}")).json()
    assert store["key"] == "kemang"
    assert store["is_open"] is True
