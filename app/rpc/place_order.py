"""Wrapper RPC `place_order()` (PRD Bagian 8.2 no. 1).

Dipakai HANYA oleh endpoint dev `POST /api/dev/simulate-order`. Saat aplikasi
mobile asli live, mobile app memanggil `place_order()` langsung ke Supabase
dan modul ini (beserta routernya) bisa dihapus tanpa menyentuh sisa backend.
"""

from __future__ import annotations

import logging

import asyncpg

from app import db
from app.rpc.errors import RpcError
from app.schemas.orders import Order, SimulateOrderRequest

logger = logging.getLogger(__name__)

# Urutan argumen wajib sama dengan definisi di db/functions.sql:
#   place_order(p_user_id, p_store_id, p_fulfilment_mode, p_payment_method,
#               p_items, p_voucher_code, p_table_number, p_scheduled_for,
#               p_address_id)
_SQL = """
SELECT * FROM place_order(
    $1::uuid,
    $2::uuid,
    $3::fulfilment_mode,
    $4::payment_method,
    $5::jsonb,
    $6::text,
    $7::text,
    $8::timestamptz,
    $9::uuid
)
"""


async def place_order(payload: SimulateOrderRequest) -> Order:
    """Panggil `place_order()` dan kembalikan baris `orders` hasilnya.

    Raise `RpcError` bila RPC menolak (toko tutup, produk tidak aktif, voucher
    kedaluwarsa, dsb) — pesan asli dari Postgres diteruskan apa adanya.
    """
    # mode="json" -> UUID menjadi str sehingga codec jsonb bisa men-serialisasi.
    items = [item.model_dump(mode="json") for item in payload.items]

    try:
        row = await db.fetchrow(
            _SQL,
            payload.user_id,
            payload.store_id,
            payload.fulfilment_mode.value,
            payload.payment_method.value,
            items,
            payload.voucher_code,
            payload.table_number,
            payload.scheduled_for,
            payload.address_id,
        )
    except asyncpg.PostgresError as exc:
        logger.warning("place_order() ditolak database: %s", exc)
        raise RpcError.from_postgres(exc, rpc_name="place_order") from exc

    if row is None:
        raise RpcError("place_order() tidak mengembalikan baris orders", status_code=500)

    order = Order(**dict(row))
    logger.info(
        "place_order() OK — order_no=%s store_id=%s total=%s",
        order.order_no, order.store_id, order.total,
    )
    return order
