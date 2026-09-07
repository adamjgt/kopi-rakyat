"""Schema tabel `stores` (read-only bagi backend ini).

Mengikuti skema ASLI: `address` / `hours_note` / `map_x` / `map_y` NOT NULL,
`distance_km` numeric(4,1), ada `sort_order`, TIDAK ada `created_at`.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Store(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    key: str
    name: str
    address: str
    distance_km: Decimal | None = None
    is_open: bool = True
    hours_note: str
    map_x: Decimal
    map_y: Decimal
    sort_order: int = 0
