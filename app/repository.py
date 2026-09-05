"""Query baca (read-only) yang dipakai router REST maupun listener realtime.

Sengaja dipisah dari router agar `realtime/listener.py` bisa menyusun payload
broadcast dengan bentuk yang persis sama dengan response REST — POS melihat
struktur data identik lewat kedua jalur.

Semua fungsi di sini murni `SELECT`. Perubahan data hanya lewat `app/rpc/`.
"""

from __future__ import annotations

from uuid import UUID

from app import db
from app.schemas.orders import Order, OrderItem, OrderWithItems
from app.schemas.stores import Store

_ORDER_COLUMNS = """
    o.id, o.order_no, o.user_id, o.store_id, o.address_id, o.fulfilment_mode,
    o.table_number, o.scheduled_for, o.payment_method, o.payment_status,
    o.subtotal, o.discount, o.delivery_fee, o.total, o.voucher_code,
    o.status, o.stage, o.pickup_code, o.created_at, o.updated_at
"""


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------
async def list_stores() -> list[Store]:
    rows = await db.fetch("SELECT * FROM stores ORDER BY name")
    return [Store(**dict(r)) for r in rows]


async def get_store(store_id: UUID) -> Store | None:
    row = await db.fetchrow("SELECT * FROM stores WHERE id = $1", store_id)
    return Store(**dict(row)) if row else None


async def store_exists(store_id: UUID) -> bool:
    return bool(await db.fetchval("SELECT 1 FROM stores WHERE id = $1", store_id))


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
async def _items_by_order(order_ids: list[UUID]) -> dict[UUID, list[OrderItem]]:
    if not order_ids:
        return {}
    rows = await db.fetch(
        "SELECT * FROM order_items WHERE order_id = ANY($1::uuid[]) ORDER BY id",
        order_ids,
    )
    grouped: dict[UUID, list[OrderItem]] = {oid: [] for oid in order_ids}
    for r in rows:
        grouped[r["order_id"]].append(OrderItem(**dict(r)))
    return grouped


async def list_orders(
    store_id: UUID,
    *,
    status: str | None = None,
    stage: int | None = None,
    fulfilment_mode: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[OrderWithItems]:
    """Antrian order satu toko (PRD Bagian 7.3).

    `store_id` selalu wajib dan tidak pernah opsional — inilah yang menegakkan
    Store Isolation di sisi REST (PRD Bagian 11).
    """
    rows = await db.fetch(
        f"""
        SELECT {_ORDER_COLUMNS}, p.full_name AS customer_name, s.name AS store_name
        FROM orders o
        JOIN stores s ON s.id = o.store_id
        LEFT JOIN profiles p ON p.id = o.user_id
        WHERE o.store_id = $1
          AND ($2::text IS NULL OR o.status::text = $2)
          AND ($3::int  IS NULL OR o.stage = $3)
          AND ($4::text IS NULL OR o.fulfilment_mode::text = $4)
        ORDER BY o.created_at DESC
        LIMIT $5 OFFSET $6
        """,
        store_id, status, stage, fulfilment_mode, limit, offset,
    )
    if not rows:
        return []

    items = await _items_by_order([r["id"] for r in rows])
    return [OrderWithItems(**dict(r), items=items.get(r["id"], [])) for r in rows]


async def get_order(order_id: UUID) -> OrderWithItems | None:
    """Detail satu order + `order_items` + info dasar store (PRD Bagian 7.3)."""
    row = await db.fetchrow(
        f"""
        SELECT {_ORDER_COLUMNS}, p.full_name AS customer_name, s.name AS store_name
        FROM orders o
        JOIN stores s ON s.id = o.store_id
        LEFT JOIN profiles p ON p.id = o.user_id
        WHERE o.id = $1
        """,
        order_id,
    )
    if row is None:
        return None

    items = await _items_by_order([row["id"]])
    return OrderWithItems(**dict(row), items=items.get(row["id"], []))


async def get_order_plain(order_id: UUID) -> Order | None:
    """Order tanpa join — dipakai listener saat hanya butuh header."""
    row = await db.fetchrow(f"SELECT {_ORDER_COLUMNS} FROM orders o WHERE o.id = $1", order_id)
    return Order(**dict(row)) if row else None
