"""Connection manager WebSocket, satu "room" per `store_id`.

Store Isolation (PRD Bagian 11) ditegakkan secara struktural di sini: sebuah
koneksi hanya pernah terdaftar pada satu room, dan `broadcast()` hanya bisa
menyasar satu room. Tidak ada jalur kode yang bisa mengirim order milik toko A
ke koneksi yang terdaftar di toko B.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    # -- lifecycle ----------------------------------------------------
    async def connect(self, websocket: WebSocket, store_id: UUID | str) -> None:
        """Terima koneksi dan daftarkan ke room `store_id`."""
        await websocket.accept()
        room = str(store_id)
        async with self._lock:
            self._rooms.setdefault(room, set()).add(websocket)
        logger.info("POS terkoneksi ke store=%s (total %d klien)",
                    room, len(self._rooms[room]))

    async def disconnect(self, websocket: WebSocket, store_id: UUID | str) -> None:
        room = str(store_id)
        async with self._lock:
            peers = self._rooms.get(room)
            if peers is None:
                return
            peers.discard(websocket)
            remaining = len(peers)
            if not peers:
                del self._rooms[room]
        logger.info("POS terputus dari store=%s (sisa %d klien)", room, remaining)

    # -- pengiriman ---------------------------------------------------
    async def broadcast(self, store_id: UUID | str, message: Any) -> int:
        """Kirim `message` ke semua klien POS pada satu store.

        Mengembalikan jumlah klien yang berhasil menerima. Koneksi yang mati
        dibuang otomatis agar room tidak bocor.
        """
        room = str(store_id)
        async with self._lock:
            peers = list(self._rooms.get(room, ()))

        if not peers:
            return 0

        # Serialisasi sekali saja, bukan per koneksi.
        text = json.dumps(jsonable_encoder(message), ensure_ascii=False)

        results = await asyncio.gather(
            *(self._send(ws, text) for ws in peers), return_exceptions=False
        )
        dead = [ws for ws, ok in zip(peers, results) if not ok]
        if dead:
            async with self._lock:
                current = self._rooms.get(room)
                if current is not None:
                    for ws in dead:
                        current.discard(ws)
                    if not current:
                        del self._rooms[room]

        delivered = len(peers) - len(dead)
        logger.debug("Broadcast ke store=%s: %d/%d terkirim", room, delivered, len(peers))
        return delivered

    async def send_to(self, websocket: WebSocket, message: Any) -> bool:
        """Kirim ke satu koneksi saja (mis. snapshot awal setelah connect)."""
        return await self._send(websocket, json.dumps(jsonable_encoder(message), ensure_ascii=False))

    @staticmethod
    async def _send(websocket: WebSocket, text: str) -> bool:
        if websocket.client_state is not WebSocketState.CONNECTED:
            return False
        try:
            await websocket.send_text(text)
            return True
        except Exception:  # noqa: BLE001 — satu klien mati tak boleh menjatuhkan broadcast
            logger.debug("Gagal mengirim ke klien WebSocket, koneksi dibuang", exc_info=True)
            return False

    # -- introspeksi (dipakai /api/health & test) ----------------------
    def connection_count(self, store_id: UUID | str | None = None) -> int:
        if store_id is None:
            return sum(len(p) for p in self._rooms.values())
        return len(self._rooms.get(str(store_id), ()))

    def rooms(self) -> dict[str, int]:
        return {room: len(peers) for room, peers in self._rooms.items()}


# Instance tunggal dipakai seluruh aplikasi.
manager = ConnectionManager()
