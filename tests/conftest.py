"""Fixture bersama.

Test dibagi dua kelompok:

  * tanpa DB — validasi schema Pydantic & `ConnectionManager`. Selalu jalan.
  * `@pytest.mark.db` — butuh PostgreSQL berisi MIRROR skema asli
    (auth_local.sql → schema.sql → functions.sql → realtime.sql → seed.sql).
    Otomatis di-SKIP (bukan gagal) bila database tidak terjangkau.

Karena RPC asli di-scope `auth.uid()` dan dipanggil lewat `/api/dev/simulate-order`
(thin wrapper `place_order`), test butuh endpoint dev aktif → di-set di sini.

Pool dibuat ulang per test: asyncpg mengikat pool ke event loop yang aktif.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# HARUS diset sebelum get_settings() pertama kali dipanggil (mis. saat
# app.main diimpor di fixture `client`).
os.environ.setdefault("ENABLE_DEV_ENDPOINTS", "true")

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

# --- UUID dari db/seed.sql -------------------------------------------------
STORE_KEMANG = "aaaaaaaa-0000-0000-0000-000000000001"
STORE_SUDIRMAN = "aaaaaaaa-0000-0000-0000-000000000002"
STORE_TUTUP = "aaaaaaaa-0000-0000-0000-000000000003"      # is_open = false

USER_BUDI = "11111111-1111-1111-1111-111111111111"
ADDRESS_BUDI = "eeeeeeee-0000-0000-0000-000000000001"

PRODUCT_KOPI_SUSU = "cccccccc-0000-0000-0000-000000000001"  # base 18000, drink
PRODUCT_TUMBLER = "cccccccc-0000-0000-0000-000000000005"    # base 85000, merch
PRODUCT_NONAKTIF = "cccccccc-0000-0000-0000-000000000006"   # active = false

_SKIP_REASON = (
    "PostgreSQL (mirror skema asli) tidak terjangkau di {dsn}. Jalankan "
    "`docker compose up -d` atau arahkan DATABASE_URL ke DB uji yang sudah "
    "di-apply db/*.sql."
)


@pytest_asyncio.fixture
async def database():
    settings = get_settings()
    try:
        await db.connect()
        seeded = await db.fetchval("SELECT count(*) FROM stores")
    except Exception as exc:  # noqa: BLE001
        await db.disconnect()
        pytest.skip(_SKIP_REASON.format(dsn=settings.database_url) + f" ({exc})")

    if not seeded:
        await db.disconnect()
        pytest.skip("Database kosong — jalankan db/seed.sql dulu.")

    try:
        yield
    finally:
        await db.disconnect()


@pytest_asyncio.fixture
async def client(database):
    """HTTP client terhadap aplikasi FastAPI (in-process, tanpa server)."""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def default_item(**overrides) -> dict:
    """Satu item drink dengan harga TERHITUNG KLIEN (server tidak menghitung)."""
    item = {
        "product_id": PRODUCT_KOPI_SUSU,
        "name_snapshot": "Kopi Susu Rakyat",
        "size": "M",
        "milk": "oat",
        "ice": "less_ice",
        "sugar": "50%",
        "extra_shot": False,
        "note": "less sugar please",
        "unit_price": 24000,
        "qty": 2,
        "line_total": 48000,
    }
    item.update(overrides)
    return item


def order_payload(
    store_id: str = STORE_KEMANG,
    *,
    items: list[dict] | None = None,
    discount: int = 0,
    delivery_fee: int = 0,
    **overrides,
) -> dict:
    """Payload valid untuk `POST /api/dev/simulate-order` (kontrak place_order asli).

    Harga dihitung di sini (meniru mobile app), bukan oleh server.
    """
    items = items if items is not None else [default_item()]
    subtotal = sum(i["line_total"] for i in items)
    payload = {
        "user_id": USER_BUDI,
        "store_id": store_id,
        "fulfilment_mode": "pickup",
        "payment_method": "qris",
        "payment_provider": "simulated",
        "subtotal": subtotal,
        "discount": discount,
        "delivery_fee": delivery_fee,
        "total": subtotal - discount + delivery_fee,
        "voucher_code": None,
        "items": items,
    }
    payload.update(overrides)
    return payload
