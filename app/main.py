"""Entry point FastAPI — Backend POS Integration Service.

Peran service ini (PRD Bagian 6): gateway realtime SATU ARAH dari database
online-ordering ke aplikasi POS, plus perantara pemanggilan RPC dari POS.
Database tetap satu-satunya sumber kebenaran; backend ini tidak menyimpan
state order apa pun di memori.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__, db
from app.config import get_settings
from app.realtime.listener import OrderEventListener
from app.realtime.ws_manager import manager
from app.routers import dev_simulate, orders, stores, ws

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)
logger = logging.getLogger("app")

listener = OrderEventListener(ws_manager=manager, settings=settings)

# Dummy POS test interface (PRD Bagian 7.6) — disajikan langsung oleh backend
# agar tidak perlu web server terpisah saat demo.
_POS_CLIENT_DIR = Path(__file__).resolve().parent.parent / "pos_dummy_client"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await db.connect()
    await listener.start()
    logger.info(
        "Backend siap — realtime=%s, dev endpoints=%s",
        settings.realtime_mode, settings.enable_dev_endpoints,
    )
    try:
        yield
    finally:
        await listener.stop()
        await db.disconnect()


app = FastAPI(
    title="Kopi Rakyat — POS Integration Service",
    version=__version__,
    lifespan=lifespan,
    description=(
        "Lapisan integrasi antara database online-ordering (skema milik tim "
        "mobile) dan aplikasi POS barista.\n\n"
        "**Perubahan data hanya lewat RPC** `place_order()` dan "
        "`advance_order_stage()` — backend ini tidak pernah menjalankan "
        "`INSERT`/`UPDATE` manual ke `orders`/`order_items`.\n\n"
        "Asumsi `stage`/`status` yang dipakai lihat README bagian *Asumsi Eksplisit*."
    ),
)

# CORS — dummy POS & simulator berbasis web berjalan di origin berbeda
# (PRD Bagian 11).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,   # "*" + credentials ditolak spesifikasi CORS
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stores.router)
app.include_router(orders.router)
app.include_router(ws.router)

if settings.enable_dev_endpoints:
    app.include_router(dev_simulate.router)
    logger.warning(
        "Endpoint /api/dev/* AKTIF — hanya untuk fase POC. "
        "Set ENABLE_DEV_ENDPOINTS=false sebelum aplikasi mobile asli live."
    )


@app.get("/api/health", tags=["health"], summary="Health check")
async def health() -> dict:
    db_ok = await db.healthcheck()
    return {
        "status": "ok" if db_ok else "degraded",
        "version": __version__,
        "database": "up" if db_ok else "down",
        "realtime_mode": settings.realtime_mode,
        "listener_running": listener.is_running,
        "dev_endpoints_enabled": settings.enable_dev_endpoints,
        "ws_connections": manager.rooms(),
    }


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/pos/" if _POS_CLIENT_DIR.is_dir() else "/docs")


if _POS_CLIENT_DIR.is_dir():
    app.mount("/pos", StaticFiles(directory=_POS_CLIENT_DIR, html=True), name="pos")
