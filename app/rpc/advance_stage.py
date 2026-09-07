"""Wrapper RPC `advance_order_stage()` — satu-satunya jalur perubahan
`stage`/`status` di seluruh backend (tidak ada `UPDATE orders` manual).

KONTRAK ASLI: `advance_order_stage(p_order_id uuid) RETURNS orders`, di-scope ke
pemilik order (`WHERE id = p_order_id AND user_id = auth.uid()`). Karena backend
POS tersambung sebagai role database (auth.uid() default NULL), wrapper ini:

  1. membaca `user_id` order yang dituju (query baca biasa, bypass RLS sbagai
     role service);
  2. meng-impersonasi user itu lewat `request.jwt.claims` (transaction-local);
  3. memanggil RPC di transaksi yang sama.

Dengan begitu RPC milik tim mobile dipakai APA ADANYA — tidak ada perubahan di
sisi database. Perubahan yang ditulis RPC memicu trigger NOTIFY, dan
`realtime/listener.py` yang menyiarkannya ke POS.
"""

from __future__ import annotations

import logging
from uuid import UUID

import asyncpg

from app import db
from app.rpc.errors import RpcError
from app.schemas.orders import Order

logger = logging.getLogger(__name__)


async def advance_order_stage(order_id: UUID) -> Order:
    """Majukan stage satu order; kembalikan baris `orders` terbaru.

    Raise `RpcError` 404 bila order tidak ada, 409 bila order tak punya pemilik
    (guest/anonim) sehingga tak bisa di-advance lewat RPC yang di-scope pemilik.
    """
    pool = db.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            owner = await conn.fetchval(
                "SELECT user_id FROM orders WHERE id = $1", order_id
            )
            if owner is None:
                exists = await conn.fetchval(
                    "SELECT 1 FROM orders WHERE id = $1", order_id
                )
                if not exists:
                    raise RpcError(
                        f"order {order_id} tidak ditemukan", status_code=404
                    )
                raise RpcError(
                    "order tidak memiliki user_id (guest/anonim); "
                    "advance_order_stage() di-scope ke pemilik order",
                    status_code=409,
                )

            await db.set_auth_claims(conn, owner)
            try:
                row = await conn.fetchrow(
                    "SELECT * FROM advance_order_stage($1::uuid)", order_id
                )
            except asyncpg.PostgresError as exc:
                logger.warning(
                    "advance_order_stage(%s) ditolak database: %s", order_id, exc
                )
                raise RpcError.from_postgres(
                    exc, rpc_name="advance_order_stage"
                ) from exc

    if row is None:
        raise RpcError(
            "advance_order_stage() tidak mengembalikan baris orders",
            status_code=500,
        )

    order = Order(**dict(row))
    logger.info(
        "advance_order_stage() OK — order_no=%s stage=%s status=%s",
        order.order_no, order.stage, order.status.value,
    )
    return order
