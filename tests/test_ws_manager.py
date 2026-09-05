"""Store Isolation di lapisan WebSocket (PRD Bagian 11) — tanpa database."""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketState

from app.realtime.ws_manager import ConnectionManager

STORE_A = "aaaaaaaa-0000-0000-0000-000000000001"
STORE_B = "aaaaaaaa-0000-0000-0000-000000000002"


class FakeWebSocket:
    """Stand-in WebSocket: mencatat pesan, bisa dibuat 'mati' untuk uji cleanup."""

    def __init__(self, broken: bool = False) -> None:
        self.sent: list[str] = []
        self.accepted = False
        self.broken = broken
        self.client_state = WebSocketState.CONNECTED

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        if self.broken:
            raise ConnectionResetError("klien sudah pergi")
        self.sent.append(text)


async def test_broadcast_hanya_ke_store_yang_sama():
    manager = ConnectionManager()
    pos_a1, pos_a2, pos_b = FakeWebSocket(), FakeWebSocket(), FakeWebSocket()

    await manager.connect(pos_a1, STORE_A)
    await manager.connect(pos_a2, STORE_A)
    await manager.connect(pos_b, STORE_B)

    delivered = await manager.broadcast(STORE_A, {"event": "order.created", "data": {}})

    assert delivered == 2
    assert len(pos_a1.sent) == 1 and len(pos_a2.sent) == 1
    assert pos_b.sent == []          # POS store lain TIDAK menerima apa pun


async def test_connect_menerima_koneksi_dan_menghitung_klien():
    manager = ConnectionManager()
    ws = FakeWebSocket()

    await manager.connect(ws, STORE_A)

    assert ws.accepted is True
    assert manager.connection_count(STORE_A) == 1
    assert manager.connection_count(STORE_B) == 0
    assert manager.connection_count() == 1


async def test_disconnect_membersihkan_room_kosong():
    manager = ConnectionManager()
    ws = FakeWebSocket()

    await manager.connect(ws, STORE_A)
    await manager.disconnect(ws, STORE_A)

    assert manager.connection_count(STORE_A) == 0
    assert manager.rooms() == {}


async def test_klien_mati_dibuang_dan_tidak_menjatuhkan_broadcast():
    manager = ConnectionManager()
    sehat, mati = FakeWebSocket(), FakeWebSocket(broken=True)

    await manager.connect(sehat, STORE_A)
    await manager.connect(mati, STORE_A)

    delivered = await manager.broadcast(STORE_A, {"event": "ping"})

    assert delivered == 1
    assert len(sehat.sent) == 1
    assert manager.connection_count(STORE_A) == 1   # yang mati sudah dibuang


async def test_broadcast_ke_store_tanpa_klien_aman():
    manager = ConnectionManager()
    assert await manager.broadcast(STORE_A, {"event": "order.created"}) == 0


async def test_koneksi_yang_sudah_disconnect_tidak_dikirimi():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    await manager.connect(ws, STORE_A)
    ws.client_state = WebSocketState.DISCONNECTED

    delivered = await manager.broadcast(STORE_A, {"event": "x"})

    assert delivered == 0
    assert ws.sent == []


@pytest.mark.parametrize("store_id", [STORE_A, "not-a-uuid", 12345])
async def test_room_key_selalu_string(store_id):
    """`store_id` boleh UUID atau str — kuncinya dinormalisasi ke str."""
    manager = ConnectionManager()
    ws = FakeWebSocket()
    await manager.connect(ws, store_id)
    assert manager.connection_count(str(store_id)) == 1
