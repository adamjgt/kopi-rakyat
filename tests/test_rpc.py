"""Pemanggilan RPC `place_order()` & `advance_order_stage()` (Deliverable 6).

Butuh PostgreSQL yang sudah di-apply schema + functions + seed.
Otomatis di-skip bila database tidak terjangkau (lihat tests/conftest.py).
"""

from __future__ import annotations

import re

import pytest

from tests.conftest import (
    ADDRESS_BUDI,
    PRODUCT_CROISSANT,
    PRODUCT_KOPI_SUSU,
    PRODUCT_NONAKTIF,
    STORE_KEMANG,
    STORE_TUTUP,
    order_payload,
)

pytestmark = pytest.mark.db


# ---------------------------------------------------------------------------
# place_order()
# ---------------------------------------------------------------------------
async def test_place_order_membuat_order_dengan_stage_0_dan_status_paid(client):
    resp = await client.post("/api/dev/simulate-order", json=order_payload())

    assert resp.status_code == 201, resp.text
    order = resp.json()
    assert order["stage"] == 0
    assert order["status"] == "paid"
    assert order["payment_status"] == "paid"
    assert order["store_id"] == STORE_KEMANG
    assert re.fullmatch(r"ORD-\d{8}-\d{4}", order["order_no"]), order["order_no"]


async def test_place_order_menghitung_harga_dari_base_price_plus_option_delta(client):
    """Kopi Susu 18.000 + size M (0) + oat (+5.000) = 23.000 ×2 = 46.000.

    Backend tidak menghitung apa pun di sini — angka ini murni hasil RPC.
    """
    resp = await client.post("/api/dev/simulate-order", json=order_payload())
    order = resp.json()

    assert float(order["subtotal"]) == 46000
    assert float(order["discount"]) == 0
    assert float(order["delivery_fee"]) == 0
    assert float(order["total"]) == 46000

    detail = (await client.get(f"/api/orders/{order['id']}")).json()
    item = detail["items"][0]
    assert float(item["unit_price"]) == 23000
    assert float(item["line_total"]) == 46000


async def test_place_order_menyimpan_snapshot_opsi_item(client):
    """PRD Acceptance: order_items yang tampil di POS = snapshot tersimpan."""
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
    assert resp.json()["pickup_code"], "mode pickup wajib punya pickup_code"


async def test_place_order_dine_in_tanpa_pickup_code_tapi_ada_nomor_meja(client):
    payload = order_payload(fulfilment_mode="dine_in", table_number="7")
    order = (await client.post("/api/dev/simulate-order", json=payload)).json()

    assert order["pickup_code"] is None
    assert order["table_number"] == "7"


async def test_place_order_delivery_menambahkan_delivery_fee(client):
    payload = order_payload(fulfilment_mode="delivery", address_id=ADDRESS_BUDI)
    order = (await client.post("/api/dev/simulate-order", json=payload)).json()

    assert float(order["delivery_fee"]) > 0
    assert float(order["total"]) == float(order["subtotal"]) + float(order["delivery_fee"])


async def test_place_order_extra_shot_menaikkan_unit_price(client):
    tanpa = order_payload()
    tanpa["items"][0]["extra_shot"] = False
    dengan = order_payload()
    dengan["items"][0]["extra_shot"] = True

    a = (await client.post("/api/dev/simulate-order", json=tanpa)).json()
    b = (await client.post("/api/dev/simulate-order", json=dengan)).json()

    assert float(b["subtotal"]) > float(a["subtotal"])


async def test_place_order_voucher_fixed_mengurangi_total(client):
    order = (await client.post(
        "/api/dev/simulate-order", json=order_payload(voucher_code="HEMAT5K")
    )).json()

    assert float(order["discount"]) == 5000
    assert float(order["total"]) == float(order["subtotal"]) - 5000


async def test_place_order_multi_item(client):
    payload = order_payload()
    payload["items"].append({"product_id": PRODUCT_CROISSANT, "qty": 1})

    order = (await client.post("/api/dev/simulate-order", json=payload)).json()
    detail = (await client.get(f"/api/orders/{order['id']}")).json()

    assert len(detail["items"]) == 2
    assert float(order["subtotal"]) == 46000 + 20000


# --- error path: constraint milik RPC, bukan milik backend -----------------
async def test_place_order_ditolak_bila_produk_nonaktif(client):
    payload = order_payload()
    payload["items"][0]["product_id"] = PRODUCT_NONAKTIF

    resp = await client.post("/api/dev/simulate-order", json=payload)

    assert resp.status_code == 409
    assert "not active" in resp.json()["detail"]


async def test_place_order_ditolak_bila_toko_tutup(client):
    resp = await client.post("/api/dev/simulate-order", json=order_payload(STORE_TUTUP))

    assert resp.status_code == 409
    assert "closed" in resp.json()["detail"]


async def test_place_order_404_bila_store_tidak_ada(client):
    payload = order_payload("00000000-0000-0000-0000-0000000000ff")
    resp = await client.post("/api/dev/simulate-order", json=payload)
    assert resp.status_code == 404


async def test_place_order_404_bila_produk_tidak_ada(client):
    payload = order_payload()
    payload["items"][0]["product_id"] = "00000000-0000-0000-0000-0000000000ff"
    resp = await client.post("/api/dev/simulate-order", json=payload)
    assert resp.status_code == 404


async def test_place_order_ditolak_bila_delivery_tanpa_alamat(client):
    resp = await client.post(
        "/api/dev/simulate-order", json=order_payload(fulfilment_mode="delivery")
    )
    assert resp.status_code == 409


async def test_place_order_422_bila_items_kosong(client):
    """Ditolak Pydantic sebelum menyentuh database."""
    resp = await client.post("/api/dev/simulate-order", json=order_payload(items=[]))
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# advance_order_stage()
# ---------------------------------------------------------------------------
async def _new_order(client) -> dict:
    resp = await client.post("/api/dev/simulate-order", json=order_payload())
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_advance_menaikkan_stage_satu_per_satu(client):
    order = await _new_order(client)

    for expected in (1, 2, 3):
        resp = await client.patch(f"/api/orders/{order['id']}/advance")
        assert resp.status_code == 200, resp.text
        assert resp.json()["stage"] == expected


async def test_advance_mengubah_status_sesuai_stage(client):
    """ASUMSI PRD 7.2: stage 1–2 -> 'active', stage 3 -> 'completed'."""
    order = await _new_order(client)

    s1 = (await client.patch(f"/api/orders/{order['id']}/advance")).json()
    s2 = (await client.patch(f"/api/orders/{order['id']}/advance")).json()
    s3 = (await client.patch(f"/api/orders/{order['id']}/advance")).json()

    assert s1["status"] == "active"
    assert s2["status"] == "active"
    assert s3["status"] == "completed"


async def test_advance_menyentuh_updated_at(client):
    order = await _new_order(client)
    after = (await client.patch(f"/api/orders/{order['id']}/advance")).json()
    assert after["updated_at"] >= order["updated_at"]


async def test_advance_di_stage_final_ditolak_409(client):
    order = await _new_order(client)
    for _ in range(3):
        await client.patch(f"/api/orders/{order['id']}/advance")

    resp = await client.patch(f"/api/orders/{order['id']}/advance")

    assert resp.status_code == 409
    assert "final stage" in resp.json()["detail"]


async def test_advance_order_tidak_dikenal_404(client):
    resp = await client.patch("/api/orders/00000000-0000-0000-0000-0000000000ff/advance")
    assert resp.status_code == 404


async def test_advance_tersimpan_permanen_di_database(client):
    """PRD Acceptance: data konsisten karena RPC menulis ke Postgres."""
    order = await _new_order(client)
    await client.patch(f"/api/orders/{order['id']}/advance")

    from app import repository
    from uuid import UUID

    persisted = await repository.get_order(UUID(order["id"]))
    assert persisted is not None
    assert persisted.stage == 1
