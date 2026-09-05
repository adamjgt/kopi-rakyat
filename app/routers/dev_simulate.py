"""Endpoint KHUSUS FASE POC (PRD Bagian 9.1).

`POST /api/dev/simulate-order` adalah lapisan tipis di atas `place_order()`
supaya dummy mobile simulator tidak perlu kredensial database.

⚠️  HAPUS / MATIKAN SAAT APLIKASI MOBILE ASLI LIVE.
    Saat itu mobile app memanggil `place_order()` langsung ke Supabase, bukan
    lewat backend ini. Matikan dengan `ENABLE_DEV_ENDPOINTS=false` — router ini
    tidak akan didaftarkan sama sekali (lihat app/main.py).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app.rpc import RpcError, place_order
from app.schemas.orders import Order, SimulateOrderRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dev", tags=["dev (POC only)"])


@router.post(
    "/simulate-order",
    response_model=Order,
    status_code=status.HTTP_201_CREATED,
    summary="[POC] Buat order dummy lewat place_order()",
    responses={
        404: {"description": "Store / produk tidak ditemukan"},
        409: {"description": "Ditolak aturan bisnis RPC (toko tutup, produk nonaktif, voucher invalid)"},
        501: {"description": "RPC place_order() belum ada di database"},
    },
)
async def simulate_order(payload: SimulateOrderRequest) -> Order:
    """Meneruskan payload apa adanya ke `place_order()`.

    Backend tidak menghitung harga, tidak membuat `order_no`, dan tidak
    menyentuh loyalty — semuanya milik RPC (PRD Bagian 11).
    """
    logger.info(
        "simulate-order: store=%s mode=%s items=%d",
        payload.store_id, payload.fulfilment_mode.value, len(payload.items),
    )
    try:
        return await place_order(payload)
    except RpcError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
