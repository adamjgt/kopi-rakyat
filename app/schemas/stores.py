"""Schema tabel `stores` (read-only bagi backend ini)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Store(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    address: str | None = None
    distance_km: Decimal | None = None
    is_open: bool = True
    hours_note: str | None = None
    map_x: Decimal | None = None
    map_y: Decimal | None = None
    created_at: datetime | None = None
