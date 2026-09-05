"""Schema tabel `orders` / `order_items` + payload simulator.

CATATAN ASUMSI (PRD Bagian 7.2 — belum resmi dari tim mobile):
  stage 0 = diterima/antre   stage 1 = diracik
  stage 2 = siap diambil/dikirim   stage 3 = selesai
  status  = kategori umum siklus hidup, independen dari progres dapur.
Definisi ini juga dicatat di README dan di `db/functions.sql`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FulfilmentMode(str, Enum):
    pickup = "pickup"
    dine_in = "dine_in"
    delivery = "delivery"


class OrderStatus(str, Enum):
    pending = "pending"
    paid = "paid"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class PaymentStatus(str, Enum):
    unpaid = "unpaid"
    paid = "paid"
    refunded = "refunded"
    failed = "failed"


class PaymentMethod(str, Enum):
    qris = "qris"
    gopay = "gopay"
    ovo = "ovo"
    card = "card"
    cash = "cash"
    balance = "balance"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class OrderItem(BaseModel):
    """Snapshot item — nilai disimpan saat order dibuat, bukan di-join ulang
    dari katalog, sehingga perubahan harga produk tidak mengubah order lama."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    product_id: UUID | None = None
    name_snapshot: str
    size: str | None = None
    milk: str | None = None
    ice: str | None = None
    sugar: str | None = None
    extra_shot: bool = False
    note: str | None = None
    unit_price: Decimal
    qty: int
    line_total: Decimal


class Order(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_no: str
    user_id: UUID | None = None
    store_id: UUID
    address_id: UUID | None = None
    fulfilment_mode: FulfilmentMode
    table_number: str | None = None
    scheduled_for: datetime | None = None
    payment_method: PaymentMethod | None = None
    payment_status: PaymentStatus
    subtotal: Decimal
    discount: Decimal
    delivery_fee: Decimal
    total: Decimal
    voucher_code: str | None = None
    status: OrderStatus
    stage: int = Field(ge=0, le=3)
    pickup_code: str | None = None
    created_at: datetime
    updated_at: datetime


class OrderWithItems(Order):
    """Bentuk yang dikirim ke POS: order + itemnya sekaligus, agar POS tidak
    perlu request kedua (PRD Bagian 7.1)."""

    items: list[OrderItem] = Field(default_factory=list)
    customer_name: str | None = Field(
        default=None, description="Dari `profiles.full_name`, read-only & opsional."
    )
    store_name: str | None = None


# ---------------------------------------------------------------------------
# Request models — hanya untuk endpoint dev/simulator
# ---------------------------------------------------------------------------
class SimulateOrderItem(BaseModel):
    """Satu elemen array `items` (jsonb) yang diteruskan ke `place_order()`."""

    product_id: UUID
    qty: int = Field(default=1, ge=1, le=99)
    size: str | None = Field(default=None, examples=["M"])
    milk: str | None = Field(default=None, examples=["oat"])
    ice: str | None = Field(default=None, examples=["less_ice"])
    sugar: str | None = Field(default=None, examples=["50%"])
    extra_shot: bool = False
    note: str | None = Field(default=None, max_length=280)


class SimulateOrderRequest(BaseModel):
    """Payload `POST /api/dev/simulate-order` (PRD Bagian 9.3)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "store_id": "aaaaaaaa-0000-0000-0000-000000000001",
                "user_id": "11111111-1111-1111-1111-111111111111",
                "fulfilment_mode": "pickup",
                "payment_method": "qris",
                "voucher_code": None,
                "items": [
                    {
                        "product_id": "cccccccc-0000-0000-0000-000000000001",
                        "qty": 2,
                        "size": "M",
                        "milk": "oat",
                        "ice": "less_ice",
                        "sugar": "50%",
                        "extra_shot": False,
                        "note": "less sugar please",
                    }
                ],
            }
        }
    )

    store_id: UUID
    user_id: UUID | None = None
    fulfilment_mode: FulfilmentMode = FulfilmentMode.pickup
    payment_method: PaymentMethod = PaymentMethod.qris
    voucher_code: str | None = None
    table_number: str | None = None
    scheduled_for: datetime | None = None
    address_id: UUID | None = None
    items: list[SimulateOrderItem] = Field(min_length=1, max_length=50)
