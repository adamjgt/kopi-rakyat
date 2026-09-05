"""Fixture bersama.

Test dibagi dua kelompok:

  * tanpa DB — validasi schema Pydantic & `ConnectionManager`. Selalu jalan.
  * `@pytest.mark.db` — butuh PostgreSQL berisi schema + functions + seed.
    Otomatis di-SKIP (bukan gagal) bila database tidak terjangkau, sehingga
    `pytest` tetap hijau di mesin yang belum menjalankan docker compose.

Pool dibuat ulang per test: asyncpg mengikat pool ke event loop yang aktif,
sementara pytest-asyncio memberi loop baru untuk setiap test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402

# --- UUID dari db/seed.sql -------------------------------------------------
STORE_KEMANG = "aaaaaaaa-0000-0000-0000-000000000001"
STORE_SUDIRMAN = "aaaaaaaa-0000-0000-0000-000000000002"
STORE_TUTUP = "aaaaaaaa-0000-0000-0000-000000000003"      # is_open = false

USER_BUDI = "11111111-1111-1111-1111-111111111111"
ADDRESS_BUDI = "eeeeeeee-0000-0000-0000-000000000001"

PRODUCT_KOPI_SUSU = "cccccccc-0000-0000-0000-000000000001"  # base 18000, drink
PRODUCT_CROISSANT = "cccccccc-0000-0000-0000-000000000005"  # base 20000, food
PRODUCT_NONAKTIF = "cccccccc-0000-0000-0000-000000000006"   # active = false

_SKIP_REASON = (
    "PostgreSQL tidak terjangkau di {dsn}. Jalankan `docker compose up -d` "
    "dan pastikan schema.sql/functions.sql/seed.sql sudah di-apply."
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
    """HTTP client terhadap aplikasi FastAPI (in-process, tanpa server).

    Lifespan sengaja tidak dijalankan: pool sudah disiapkan fixture `database`,
    dan listener realtime tidak diperlukan untuk test REST.
    """
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def order_payload(store_id: str = STORE_KEMANG, **overrides) -> dict:
    """Payload minimal yang valid untuk `POST /api/dev/simulate-order`."""
    payload = {
        "store_id": store_id,
        "user_id": USER_BUDI,
        "fulfilment_mode": "pickup",
        "payment_method": "qris",
        "items": [
            {
                "product_id": PRODUCT_KOPI_SUSU,
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
    payload.update(overrides)
    return payload
