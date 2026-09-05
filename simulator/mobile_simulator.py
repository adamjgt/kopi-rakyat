#!/usr/bin/env python3
"""Dummy mobile simulator (PRD Bagian 7.5).

Berperan sebagai aplikasi mobile online-ordering yang belum selesai dibangun:
membuat order lewat `place_order()` (via endpoint tipis
`POST /api/dev/simulate-order`), lalu — dengan `--watch` — memantau perubahan
stage order tersebut untuk memverifikasi bahwa update dari POS benar-benar
tersimpan di database.

Katalog produk di bawah mengacu pada `db/seed.sql`. Backend sengaja tidak
menyediakan endpoint katalog (PRD Bagian 4: manajemen katalog di luar scope),
jadi simulator memakai id dari seed. Pakai `--product <uuid>` untuk id lain.

Contoh:
    python simulator/mobile_simulator.py                       # 1 order acak
    python simulator/mobile_simulator.py --count 5 --interval 2
    python simulator/mobile_simulator.py --store sudirman --mode dine_in
    python simulator/mobile_simulator.py --watch               # ikuti sampai selesai
    python simulator/mobile_simulator.py --list-stores
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from typing import Any

import httpx

DEFAULT_API = "http://localhost:8000"

# --- Katalog dari db/seed.sql -------------------------------------------
CATALOG: list[dict[str, Any]] = [
    {"id": "cccccccc-0000-0000-0000-000000000001", "name": "Kopi Susu Rakyat", "drink": True},
    {"id": "cccccccc-0000-0000-0000-000000000002", "name": "Americano",        "drink": True},
    {"id": "cccccccc-0000-0000-0000-000000000003", "name": "Caffe Latte",      "drink": True},
    {"id": "cccccccc-0000-0000-0000-000000000004", "name": "Matcha Latte",     "drink": True},
    {"id": "cccccccc-0000-0000-0000-000000000005", "name": "Butter Croissant", "drink": False},
]

DUMMY_USERS = [
    "11111111-1111-1111-1111-111111111111",  # Budi Santoso
    "22222222-2222-2222-2222-222222222222",  # Sarah Amelia
]
DELIVERY_ADDRESS_ID = "eeeeeeee-0000-0000-0000-000000000001"  # milik Budi

SIZES = ["S", "M", "L"]
MILKS = ["fresh", "oat", "almond", "none"]
ICES = ["no_ice", "less_ice", "normal"]
SUGARS = ["0%", "50%", "100%"]
NOTES = [None, "less sugar please", "tolong dipisah esnya", "buat dibawa pulang", None]
PAYMENTS = ["qris", "gopay", "ovo", "card", "cash"]

STAGE_LABEL = {0: "diterima", 1: "diracik", 2: "siap", 3: "selesai"}


# ---------------------------------------------------------------------------
# Penyusun payload
# ---------------------------------------------------------------------------
def random_items(max_items: int = 3) -> list[dict[str, Any]]:
    """Kombinasi item yang merepresentasikan payload `items` (jsonb)."""
    items = []
    for product in random.sample(CATALOG, k=random.randint(1, min(max_items, len(CATALOG)))):
        item: dict[str, Any] = {
            "product_id": product["id"],
            "qty": random.randint(1, 3),
            "note": random.choice(NOTES),
        }
        if product["drink"]:
            item |= {
                "size": random.choice(SIZES),
                "milk": random.choice(MILKS),
                "ice": random.choice(ICES),
                "sugar": random.choice(SUGARS),
                "extra_shot": random.random() < 0.3,
            }
        items.append(item)
    return items


def build_payload(store_id: str, mode: str) -> dict[str, Any]:
    user_id = random.choice(DUMMY_USERS)
    payload: dict[str, Any] = {
        "store_id": store_id,
        "user_id": user_id,
        "fulfilment_mode": mode,
        "payment_method": random.choice(PAYMENTS),
        "voucher_code": None,
        "items": random_items(),
    }
    if mode == "dine_in":
        payload["table_number"] = str(random.randint(1, 20))
    elif mode == "delivery":
        # Alamat dummy di seed hanya milik user pertama.
        payload["user_id"] = DUMMY_USERS[0]
        payload["address_id"] = DELIVERY_ADDRESS_ID
    return payload


# ---------------------------------------------------------------------------
# Pemanggilan API
# ---------------------------------------------------------------------------
async def fetch_stores(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    resp = await client.get("/api/stores")
    resp.raise_for_status()
    return resp.json()


async def resolve_store(client: httpx.AsyncClient, wanted: str | None) -> dict[str, Any]:
    """Terima `key` (mis. 'kemang') maupun UUID penuh."""
    stores = await fetch_stores(client)
    if not stores:
        raise SystemExit("Tidak ada store di database. Jalankan db/seed.sql dulu.")

    if wanted:
        for store in stores:
            if wanted in (store["key"], store["id"]):
                return store
        keys = ", ".join(s["key"] for s in stores)
        raise SystemExit(f"Store '{wanted}' tidak ditemukan. Pilihan: {keys}")

    for store in stores:
        if store["is_open"]:
            return store
    raise SystemExit("Semua store sedang tutup — place_order() akan ditolak RPC.")


async def place(client: httpx.AsyncClient, payload: dict[str, Any]) -> dict[str, Any] | None:
    resp = await client.post("/api/dev/simulate-order", json=payload)
    if resp.status_code >= 400:
        detail = resp.json().get("detail", resp.text) if resp.text else resp.reason_phrase
        print(f"  ✗ ditolak ({resp.status_code}): {detail}")
        return None

    order = resp.json()
    pickup = f" pickup_code={order['pickup_code']}" if order.get("pickup_code") else ""
    print(
        f"  ✓ {order['order_no']}  {order['fulfilment_mode']:<8} "
        f"total=Rp {float(order['total']):,.0f}  stage={order['stage']}{pickup}"
    )
    for item in payload["items"]:
        opts = " / ".join(
            str(item[k]) for k in ("size", "milk", "ice", "sugar") if item.get(k)
        )
        extra = " +shot" if item.get("extra_shot") else ""
        note = f"  «{item['note']}»" if item.get("note") else ""
        name = next(p["name"] for p in CATALOG if p["id"] == item["product_id"])
        print(f"      {item['qty']}x {name:<18} {opts}{extra}{note}")
    return order


async def watch_order(client: httpx.AsyncClient, order_id: str, timeout: float = 300.0) -> None:
    """Polling detail order sampai stage 3 — verifikasi update POS tersimpan.

    Sengaja memakai endpoint REST biasa (bukan koneksi database) supaya
    simulator bisa dijalankan dari mesin mana pun.
    """
    print(f"  … memantau perubahan stage (timeout {timeout:.0f}s, Ctrl+C untuk berhenti)")
    last_stage = -1
    waited = 0.0
    while waited < timeout:
        resp = await client.get(f"/api/orders/{order_id}")
        if resp.status_code != 200:
            print(f"  ✗ gagal membaca order: {resp.status_code}")
            return
        order = resp.json()
        if order["stage"] != last_stage:
            last_stage = order["stage"]
            label = STAGE_LABEL.get(last_stage, "?")
            print(f"     stage {last_stage} ({label})   status={order['status']}")
            if last_stage >= 3:
                print("  ✓ order selesai")
                return
        await asyncio.sleep(1.0)
        waited += 1.0
    print("  ! timeout — order belum mencapai stage 3")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run(args: argparse.Namespace) -> int:
    async with httpx.AsyncClient(base_url=args.api, timeout=15.0) as client:
        try:
            await client.get("/api/health")
        except httpx.ConnectError:
            print(f"Tidak bisa terhubung ke backend di {args.api}.")
            print("Jalankan dulu: uvicorn app.main:app --reload")
            return 1

        if args.list_stores:
            for store in await fetch_stores(client):
                flag = "buka " if store["is_open"] else "TUTUP"
                print(f"{flag}  {store['key']:<10} {store['id']}  {store['name']}")
            return 0

        store = await resolve_store(client, args.store)
        print(f"Store: {store['name']} ({store['key']})  id={store['id']}")
        print(f"Backend: {args.api}\n")

        created: list[dict[str, Any]] = []
        for n in range(1, args.count + 1):
            mode = args.mode or random.choice(["pickup", "pickup", "dine_in", "delivery"])
            print(f"[{n}/{args.count}] place_order() mode={mode}")
            order = await place(client, build_payload(store["id"], mode))
            if order:
                created.append(order)
            if n < args.count:
                await asyncio.sleep(args.interval)

        if args.watch and created:
            print()
            await watch_order(client, created[-1]["id"])

        print(f"\nSelesai — {len(created)}/{args.count} order berhasil dibuat.")
        return 0 if len(created) == args.count else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dummy mobile simulator — memanggil place_order() lewat backend POS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--api", default=DEFAULT_API, help=f"Base URL backend (default: {DEFAULT_API})")
    parser.add_argument("--store", help="Store key (mis. 'kemang') atau UUID. Default: store buka pertama.")
    parser.add_argument("--count", type=int, default=1, help="Jumlah order yang dibuat (default: 1)")
    parser.add_argument("--interval", type=float, default=1.5, help="Jeda antar order dalam detik")
    parser.add_argument(
        "--mode",
        choices=["pickup", "dine_in", "delivery"],
        help="Fulfilment mode. Default: acak.",
    )
    parser.add_argument("--watch", action="store_true", help="Pantau stage order terakhir sampai selesai")
    parser.add_argument("--list-stores", action="store_true", help="Tampilkan daftar store lalu keluar")
    parser.add_argument("--seed", type=int, help="Seed RNG agar hasil dapat direproduksi")

    args = parser.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nDihentikan.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
