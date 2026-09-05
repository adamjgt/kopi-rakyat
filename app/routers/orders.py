"""Endpoint order untuk sisi POS (PRD Bagian 7.2, 7.3, 9.1)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query, status

from app import repository
from app.rpc import RpcError, advance_order_stage
from app.schemas.orders import (
    FulfilmentMode,
    Order,
    OrderStatus,
    OrderWithItems,
)

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get(
    "",
    response_model=list[OrderWithItems],
    summary="Antrian order satu store (join order_items)",
)
async def list_orders(
    store_id: UUID = Query(
        ...,
        description=(
            "WAJIB. Menegakkan Store Isolation: POS satu cabang tidak pernah "
            "bisa membaca order cabang lain."
        ),
    ),
    status_filter: OrderStatus | None = Query(default=None, alias="status"),
    stage: int | None = Query(default=None, ge=0, le=3),
    fulfilment_mode: FulfilmentMode | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[OrderWithItems]:
    if not await repository.store_exists(store_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Store {store_id} tidak ditemukan")

    return await repository.list_orders(
        store_id,
        status=status_filter.value if status_filter else None,
        stage=stage,
        fulfilment_mode=fulfilment_mode.value if fulfilment_mode else None,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{order_id}",
    response_model=OrderWithItems,
    summary="Detail satu order lengkap",
)
async def get_order(order_id: UUID) -> OrderWithItems:
    order = await repository.get_order(order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Order {order_id} tidak ditemukan")
    return order


@router.patch(
    "/{order_id}/advance",
    response_model=Order,
    summary="Majukan stage order (memanggil advance_order_stage())",
    responses={
        404: {"description": "Order tidak ditemukan"},
        409: {"description": "Order sudah di stage final (3) atau dibatalkan"},
        501: {"description": "RPC advance_order_stage() belum ada di database"},
    },
)
async def advance_stage(
    order_id: UUID = Path(..., description="ID order yang akan dimajukan"),
) -> Order:
    """Tidak butuh request body — `order_id` sudah ada di path (PRD Bagian 9.4).

    Broadcast `order.stage_updated` TIDAK dikirim dari sini. Perubahan yang
    ditulis RPC memicu trigger Postgres, dan `realtime/listener.py` yang
    menyiarkannya ke semua POS pada store tersebut. Satu jalur broadcast saja
    berarti tidak ada event ganda, dan perubahan stage dari sumber lain
    (mis. langsung lewat SQL saat debugging) tetap sampai ke POS.
    """
    try:
        return await advance_order_stage(order_id)
    except RpcError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
