"""`GET /api/stores` — daftar cabang, dipakai dummy POS untuk memilih store aktif."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app import repository
from app.schemas.stores import Store

router = APIRouter(prefix="/api/stores", tags=["stores"])


@router.get("", response_model=list[Store], summary="Daftar toko/cabang")
async def list_stores() -> list[Store]:
    return await repository.list_stores()


@router.get("/{store_id}", response_model=Store, summary="Detail satu toko")
async def get_store(store_id: UUID) -> Store:
    store = await repository.get_store(store_id)
    if store is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Store {store_id} tidak ditemukan")
    return store
