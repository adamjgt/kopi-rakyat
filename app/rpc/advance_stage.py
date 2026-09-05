"""Wrapper RPC `advance_order_stage()` (PRD Bagian 8.2 no. 2).

Ini satu-satunya jalur perubahan `stage`/`status` di seluruh backend.
Tidak ada `UPDATE orders SET stage = ...` di mana pun (PRD Bagian 7.2 & 11):
semua efek samping (status, timestamp, loyalty) tetap milik RPC.
"""

from __future__ import annotations

import logging
from uuid import UUID

import asyncpg

from app import db
from app.rpc.errors import RpcError
from app.schemas.orders import Order

logger = logging.getLogger(__name__)

_SQL = "SELECT * FROM advance_order_stage($1::uuid)"


async def advance_order_stage(order_id: UUID) -> Order:
    """Majukan stage satu order; kembalikan baris `orders` terbaru.

    Raise `RpcError` 404 bila order tidak ada, 409 bila order sudah di stage
    final atau dibatalkan.
    """
    try:
        row = await db.fetchrow(_SQL, order_id)
    except asyncpg.PostgresError as exc:
        logger.warning("advance_order_stage(%s) ditolak database: %s", order_id, exc)
        raise RpcError.from_postgres(exc, rpc_name="advance_order_stage") from exc

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
