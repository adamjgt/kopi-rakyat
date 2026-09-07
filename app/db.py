"""Koneksi async ke PostgreSQL (asyncpg pool).

Backend ini hanya:
  * READ  — tabel `orders`, `order_items`, `stores` (+ join opsional).
  * WRITE — eksklusif lewat RPC (`place_order`, `advance_order_stage`).

Tidak ada `INSERT`/`UPDATE` manual ke `orders`/`order_items` di mana pun
(PRD Bagian 11, "RPC Consistency").
"""

from __future__ import annotations

import json
import logging
from typing import Any

import asyncpg

from app.config import get_settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Codec agar jsonb otomatis di-encode/decode sebagai objek Python."""
    for typename in ("json", "jsonb"):
        await conn.set_type_codec(
            typename,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


async def connect() -> asyncpg.Pool:
    """Buat pool koneksi (dipanggil sekali saat startup)."""
    global _pool
    if _pool is not None:
        return _pool

    settings = get_settings()
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        init=_init_connection,
        command_timeout=30,
    )
    logger.info("Pool PostgreSQL siap (min=%s max=%s)",
                settings.db_pool_min_size, settings.db_pool_max_size)
    return _pool


async def disconnect() -> None:
    """Tutup pool (dipanggil saat shutdown)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Pool PostgreSQL ditutup")


def get_pool() -> asyncpg.Pool:
    """Pool aktif. Raise bila startup belum jalan (mis. dipanggil dari test
    tanpa lifespan)."""
    if _pool is None:
        raise RuntimeError(
            "Pool database belum diinisialisasi — panggil app.db.connect() dulu."
        )
    return _pool


async def fetch(query: str, *args: Any) -> list[asyncpg.Record]:
    async with get_pool().acquire() as conn:
        return await conn.fetch(query, *args)


async def fetchrow(query: str, *args: Any) -> asyncpg.Record | None:
    async with get_pool().acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetchval(query: str, *args: Any) -> Any:
    async with get_pool().acquire() as conn:
        return await conn.fetchval(query, *args)


async def set_auth_claims(conn: asyncpg.Connection, user_id: Any) -> None:
    """Impersonasi pemilik order untuk transaksi ini.

    RPC asli (`place_order`, `advance_order_stage`) di-scope ke `auth.uid()`.
    Backend tersambung sebagai role database (bukan lewat PostgREST + JWT), jadi
    `auth.uid()` default NULL. Di sini kita set GUC `request.jwt.claims`
    (transaction-local, `is_local = true`) sehingga `auth.uid()` mengembalikan
    `user_id` — persis mekanisme yang dibaca Supabase. RPC-nya tidak diubah.

    HARUS dipanggil di dalam `conn.transaction()` agar `is_local` berlaku dan
    klaim tidak bocor ke koneksi lain di pool.
    """
    await conn.execute(
        "SELECT set_config('request.jwt.claims', $1, true)",
        json.dumps({"sub": str(user_id), "role": "authenticated"}),
    )


async def healthcheck() -> bool:
    """True bila database membalas `SELECT 1`."""
    try:
        return await fetchval("SELECT 1") == 1
    except Exception:  # noqa: BLE001 — health check tidak boleh melempar
        logger.exception("Health check database gagal")
        return False
