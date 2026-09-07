"""Wrapper RPC `place_order()`.

Dipakai HANYA oleh endpoint dev opsional `POST /api/dev/simulate-order` dan
oleh test. Saat aplikasi mobile asli live, mobile app memanggil `place_order()`
langsung ke Supabase (lewat PostgREST, dengan JWT user), sehingga modul ini
beserta routernya bisa dihapus tanpa menyentuh sisa backend.

KONTRAK ASLI (13 parameter, TANPA p_user_id — user diambil dari auth.uid()):

    place_order(p_store_id uuid, p_fulfilment_mode text, p_table_number text,
                p_address_id uuid, p_scheduled_for timestamptz,
                p_payment_method text, p_payment_provider text,
                p_subtotal int, p_discount int, p_delivery_fee int, p_total int,
                p_voucher_code text, p_items jsonb) RETURNS orders

Harga TIDAK dihitung server: subtotal/discount/total/unit_price/line_total/
name_snapshot semuanya berasal dari payload. Backend meng-impersonasi
`payload.user_id` agar auth.uid() di dalam RPC terisi (lihat db.set_auth_claims).
"""

from __future__ import annotations

import logging

import asyncpg

from app import db
from app.rpc.errors import RpcError
from app.schemas.orders import Order, PlaceOrderRequest

logger = logging.getLogger(__name__)

# Urutan argumen wajib sama persis dengan definisi RPC asli.
_SQL = """
SELECT * FROM place_order(
    $1::uuid,        -- p_store_id
    $2::text,        -- p_fulfilment_mode
    $3::text,        -- p_table_number
    $4::uuid,        -- p_address_id
    $5::timestamptz, -- p_scheduled_for
    $6::text,        -- p_payment_method
    $7::text,        -- p_payment_provider
    $8::int,         -- p_subtotal
    $9::int,         -- p_discount
    $10::int,        -- p_delivery_fee
    $11::int,        -- p_total
    $12::text,       -- p_voucher_code
    $13::jsonb       -- p_items
)
"""


async def place_order(payload: PlaceOrderRequest) -> Order:
    """Panggil `place_order()` (impersonasi `payload.user_id`) dan kembalikan
    baris `orders` hasilnya. Raise `RpcError` bila RPC menolak."""
    # mode="json" -> UUID menjadi str agar codec jsonb bisa men-serialisasi.
    items = [item.model_dump(mode="json") for item in payload.items]

    pool = db.get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await db.set_auth_claims(conn, payload.user_id)
                row = await conn.fetchrow(
                    _SQL,
                    payload.store_id,
                    payload.fulfilment_mode.value,
                    payload.table_number,
                    payload.address_id,
                    payload.scheduled_for,
                    payload.payment_method,
                    payload.payment_provider,
                    payload.subtotal,
                    payload.discount,
                    payload.delivery_fee,
                    payload.total,
                    payload.voucher_code,
                    items,
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
