"""Konsumen perubahan tabel `orders` -> broadcast ke klien POS.

Dua mode (PRD Bagian 7.1 & 10), dipilih lewat `REALTIME_MODE`:

  notify  PostgreSQL LISTEN/NOTIFY pada channel `pos_order_events`, diisi oleh
          trigger `notify_order_event()` di `db/schema.sql`. Mode default —
          latensi mendekati nol dan tanpa beban query berulang.

  poll    Fallback tanpa trigger: bandingkan snapshot `(stage, status)` order
          aktif tiap `POLL_INTERVAL_SECONDS`. Dipakai bila trigger NOTIFY tidak
          boleh dipasang pada database tim mobile. (Tabel `orders` asli tidak
          punya `updated_at`, jadi tidak ada watermark waktu.)

Kedua mode menghasilkan bentuk event yang identik, sehingga sisa aplikasi
(dan klien POS) tidak perlu tahu mode mana yang aktif.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import asyncpg

from app import db, repository
from app.config import Settings, get_settings
from app.realtime.ws_manager import ConnectionManager, manager as default_manager
from app.schemas.events import (
    EVENT_ORDER_CREATED,
    EVENT_ORDER_STAGE_UPDATED,
    OrderCreatedData,
    OrderCreatedEvent,
    OrderStageUpdatedData,
    OrderStageUpdatedEvent,
)

logger = logging.getLogger(__name__)

_RECONNECT_DELAY_SECONDS = 3.0
_KEEPALIVE_SECONDS = 30.0


@dataclass(frozen=True)
class OrderEvent:
    """Bentuk internal yang seragam antara mode notify dan mode poll."""

    event: str
    order_id: UUID
    store_id: UUID
    stage: int
    status: str
    updated_at: datetime


class OrderEventListener:
    """Task latar yang mengubah perubahan `orders` menjadi event WebSocket."""

    def __init__(
        self,
        ws_manager: ConnectionManager | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._manager = ws_manager or default_manager
        self._settings = settings or get_settings()
        self._queue: asyncio.Queue[OrderEvent] = asyncio.Queue(maxsize=1000)
        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()

    # -- lifecycle ----------------------------------------------------
    async def start(self) -> None:
        if self._tasks:
            return
        self._stopping.clear()
        source = self._run_notify if self._settings.realtime_mode == "notify" else self._run_poll
        self._tasks = [
            asyncio.create_task(source(), name="pos-realtime-source"),
            asyncio.create_task(self._run_dispatcher(), name="pos-realtime-dispatcher"),
        ]
        logger.info("Listener realtime dimulai (mode=%s)", self._settings.realtime_mode)

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        logger.info("Listener realtime dihentikan")

    # -- sumber event: LISTEN/NOTIFY ----------------------------------
    def _on_notify(self, _conn, _pid, _channel: str, payload: str) -> None:
        """Callback asyncpg (sinkron) — kerjakan seminimal mungkin di sini."""
        try:
            data = json.loads(payload)
            event = OrderEvent(
                event=data["event"],
                order_id=UUID(data["order_id"]),
                store_id=UUID(data["store_id"]),
                stage=int(data["stage"]),
                status=str(data["status"]),
                updated_at=datetime.fromisoformat(data["updated_at"]),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Payload NOTIFY tidak bisa diurai: %r", payload)
            return

        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.error("Antrean event penuh, event %s dibuang", event.order_id)

    async def _run_notify(self) -> None:
        channel = self._settings.realtime_channel
        while not self._stopping.is_set():
            conn: asyncpg.Connection | None = None
            try:
                # Koneksi khusus di luar pool: LISTEN harus menempel pada satu
                # session dan tidak boleh dikembalikan ke pool.
                conn = await asyncpg.connect(dsn=self._settings.database_url)
                await conn.add_listener(channel, self._on_notify)
                logger.info("LISTEN aktif pada channel '%s'", channel)

                while not self._stopping.is_set():
                    await asyncio.sleep(_KEEPALIVE_SECONDS)
                    await conn.execute("SELECT 1")  # deteksi koneksi mati
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Koneksi LISTEN terputus, mencoba ulang dalam %.0f detik",
                    _RECONNECT_DELAY_SECONDS,
                )
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=_RECONNECT_DELAY_SECONDS
                    )
            finally:
                if conn is not None:
                    with contextlib.suppress(Exception):
                        await conn.remove_listener(channel, self._on_notify)
                    with contextlib.suppress(Exception):
                        await conn.close()

    # -- sumber event: polling ----------------------------------------
    async def _run_poll(self) -> None:
        """Fallback tanpa trigger — dipakai bila NOTIFY tak boleh dipasang.

        Tabel `orders` ASLI TIDAK punya kolom `updated_at`, jadi kita tidak bisa
        memakai watermark waktu. Sebagai gantinya kita simpan snapshot
        `(stage, status)` per order aktif di memori, lalu tiap siklus mem-poll
        order yang masih aktif (`stage < 3`) atau baru dibuat, dan membandingkan:

          * id baru        -> order.created
          * (stage,status) berubah -> order.stage_updated

        Cakupan dibatasi ke order aktif + order 1 hari terakhir agar query ringan.
        Siklus pertama hanya membangun baseline (tidak memancarkan event) supaya
        order lama tidak diputar ulang saat backend baru start.
        """
        interval = self._settings.poll_interval_seconds
        seen: dict[UUID, tuple[int, str]] = {}
        baseline_done = False

        while not self._stopping.is_set():
            try:
                rows = await db.fetch(
                    """
                    SELECT id, store_id, stage, status
                    FROM orders
                    WHERE stage < 3 OR created_at > now() - interval '1 day'
                    ORDER BY created_at ASC
                    LIMIT 500
                    """
                )
                now = datetime.now(timezone.utc)

                if not baseline_done:
                    for row in rows:
                        seen[row["id"]] = (row["stage"], row["status"])
                    baseline_done = True
                    logger.info(
                        "Polling aktif (interval=%.1fs, %d order dasar diabaikan)",
                        interval, len(seen),
                    )
                else:
                    for row in rows:
                        oid = row["id"]
                        cur = (row["stage"], row["status"])
                        prev = seen.get(oid)
                        if prev is None:
                            event = EVENT_ORDER_CREATED
                        elif prev != cur:
                            event = EVENT_ORDER_STAGE_UPDATED
                        else:
                            continue
                        seen[oid] = cur
                        self._queue.put_nowait(
                            OrderEvent(
                                event=event,
                                order_id=oid,
                                store_id=row["store_id"],
                                stage=row["stage"],
                                status=row["status"],
                                updated_at=now,
                            )
                        )
            except asyncio.CancelledError:
                raise
            except asyncio.QueueFull:
                logger.error("Antrean event penuh saat polling")
            except Exception:  # noqa: BLE001
                logger.exception("Siklus polling gagal, dicoba lagi pada interval berikutnya")

            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)

    # -- dispatcher ---------------------------------------------------
    async def _run_dispatcher(self) -> None:
        while not self._stopping.is_set():
            event = await self._queue.get()
            try:
                await self._dispatch(event)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("Gagal mem-broadcast event %s untuk order %s",
                                 event.event, event.order_id)
            finally:
                self._queue.task_done()

    async def _dispatch(self, event: OrderEvent) -> None:
        # Tidak ada POS yang mendengarkan toko ini -> tak perlu query apa pun.
        if self._manager.connection_count(event.store_id) == 0:
            logger.debug("Event %s untuk store=%s dilewati (tidak ada klien POS)",
                         event.event, event.store_id)
            return

        if event.event == EVENT_ORDER_CREATED:
            # Payload wajib lengkap dengan order_items agar POS tidak perlu
            # request tambahan (PRD Bagian 7.1).
            order = await repository.get_order(event.order_id)
            if order is None:
                logger.warning("Order %s hilang sebelum sempat di-broadcast", event.order_id)
                return
            message = OrderCreatedEvent(
                data=OrderCreatedData(order=order, items=order.items)
            )
            logger.info("order.created -> store=%s order_no=%s items=%d",
                        order.store_id, order.order_no, len(order.items))
        else:
            message = OrderStageUpdatedEvent(
                data=OrderStageUpdatedData(
                    order_id=event.order_id,
                    stage=event.stage,
                    status=event.status,
                    updated_at=event.updated_at,
                )
            )
            logger.info("order.stage_updated -> store=%s order=%s stage=%s status=%s",
                        event.store_id, event.order_id, event.stage, event.status)

        delivered = await self._manager.broadcast(event.store_id, message)
        logger.debug("Event %s terkirim ke %d klien POS", event.event, delivered)

    # -- dipakai test & health ----------------------------------------
    @property
    def is_running(self) -> bool:
        return bool(self._tasks) and not all(t.done() for t in self._tasks)
