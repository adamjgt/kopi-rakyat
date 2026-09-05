"""WebSocket endpoint sisi POS: `/ws/pos/{store_id}` (PRD Bagian 7.4 & 9.2).

Event yang dikirim server:
  pos.connected         handshake — konfirmasi store yang di-subscribe
  order.created         order baru dari place_order(), lengkap dengan items
  order.stage_updated   stage/status berubah
  pong                  balasan atas pesan "ping" dari klien

Klien tidak perlu mengirim apa pun; pesan masuk hanya dipakai sebagai keepalive.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter
from starlette.websockets import WebSocket, WebSocketDisconnect

from app import repository
from app.realtime.ws_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

WS_CLOSE_STORE_NOT_FOUND = 4404
WS_CLOSE_BAD_STORE_ID = 4400


@router.websocket("/ws/pos/{store_id}")
async def pos_socket(websocket: WebSocket, store_id: str) -> None:
    # `store_id` diterima sebagai str agar UUID tidak valid bisa ditutup
    # dengan pesan yang jelas, bukan handshake error tanpa keterangan.
    try:
        store_uuid = UUID(store_id)
    except ValueError:
        await websocket.accept()
        await manager.send_to(websocket, {
            "event": "error",
            "data": {"message": f"store_id '{store_id}' bukan UUID yang valid"},
        })
        await websocket.close(code=WS_CLOSE_BAD_STORE_ID)
        return

    store = await repository.get_store(store_uuid)
    if store is None:
        await websocket.accept()
        await manager.send_to(websocket, {
            "event": "error",
            "data": {"message": f"Store {store_id} tidak ditemukan"},
        })
        await websocket.close(code=WS_CLOSE_STORE_NOT_FOUND)
        return

    await manager.connect(websocket, store_uuid)
    try:
        await manager.send_to(websocket, {
            "event": "pos.connected",
            "data": {
                "store_id": str(store.id),
                "store_key": store.key,
                "store_name": store.name,
                "is_open": store.is_open,
                "clients": manager.connection_count(store_uuid),
            },
        })

        while True:
            message = await websocket.receive_text()
            if message.strip().lower() == "ping":
                await manager.send_to(websocket, {"event": "pong", "data": {}})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Koneksi WebSocket store=%s berakhir dengan error", store_id)
    finally:
        await manager.disconnect(websocket, store_uuid)
