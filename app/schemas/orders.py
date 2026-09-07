"""Schema tabel `orders` / `order_items` + payload place_order.

Mengikuti skema ASLI tim mobile (supabase/migrations/...), BUKAN asumsi lama:

  * Kolom uang (`subtotal`, `total`, `unit_price`, ...) bertipe **integer**
    (rupiah bulat) — bukan numeric. Diserialisasi sebagai angka JSON biasa.
  * `status`  : received | preparing | on_the_way | ready | completed.
  * `stage`   : integer 0..3 (0 diterima, 1 diracik/preparing,
                2 ready/on_the_way, 3 completed). Dipetakan dari status oleh
                RPC advance_order_stage().
  * `fulfilment_mode` : delivery | pickup | dine_in | pre_order.
  * `payment_status`  : pending | paid | failed.
  * `payment_method`  : teks bebas (qris, gopay, ovo, card, cash, balance, ...);
                        di DB asli kolomnya `text`, jadi tidak dibatasi enum.
  * Kolom `payment_provider` (default 'simulated') dan `paid_at` ADA di DB asli.
    Kolom `updated_at` TIDAK ada di `orders` asli.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FulfilmentMode(str, Enum):
    delivery = "delivery"
    pickup = "pickup"
    dine_in = "dine_in"
    pre_order = "pre_order"


class OrderStatus(str, Enum):
    received = "received"
    preparing = "preparing"
    on_the_way = "on_the_way"
    ready = "ready"
    completed = "completed"


class PaymentStatus(str, Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"


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
    unit_price: int
    qty: int
    line_total: int


class Order(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_no: str
    user_id: UUID | None = None
    store_id: UUID | None = None
    fulfilment_mode: FulfilmentMode
    table_number: str | None = None
    address_id: UUID | None = None
    scheduled_for: datetime | None = None
    payment_method: str
    payment_provider: str = "simulated"
    payment_status: PaymentStatus
    subtotal: int
    discount: int = 0
    delivery_fee: int = 0
    total: int
    voucher_code: str | None = None
    status: OrderStatus
    stage: int = Field(ge=0)
    pickup_code: str | None = None
    created_at: datetime
    paid_at: datetime | None = None


class OrderWithItems(Order):
    """Bentuk yang dikirim ke POS: order + itemnya sekaligus, agar POS tidak
    perlu request kedua."""

    items: list[OrderItem] = Field(default_factory=list)
    customer_name: str | None = Field(
        default=None, description="Dari `profiles.full_name`, read-only & opsional."
    )
    store_name: str | None = None


# ---------------------------------------------------------------------------
# Request models — untuk endpoint dev opsional & test.
#
# place_order() ASLI menghitung harga DI KLIEN, bukan di server: subtotal,
# discount, total, unit_price, line_total, dan name_snapshot semuanya dikirim
# oleh pemanggil. Payload di bawah mencerminkan itu persis (thin pass-through).
# `user_id` dipakai backend untuk meng-impersonasi auth.uid() (lihat app/rpc/).
# ---------------------------------------------------------------------------
class PlaceOrderItem(BaseModel):
    """Satu elemen array `items` (jsonb) untuk `place_order()`."""

    product_id: UUID | None = None
    name_snapshot: str = Field(min_length=1, examples=["Kopi Susu Rakyat"])
    size: str | None = Field(default=None, examples=["M"])
    milk: str | None = Field(default=None, examples=["oat"])
    ice: str | None = Field(default=None, examples=["less_ice"])
    sugar: str | None = Field(default=None, examples=["50%"])
    extra_shot: bool = False
    note: str | None = Field(default=None, max_length=280)
    unit_price: int = Field(ge=0)
    qty: int = Field(default=1, ge=1, le=99)
    line_total: int = Field(ge=0)


class PlaceOrderRequest(BaseModel):
    """Payload thin-wrapper untuk `place_order()` (dev/test).

    Cermin persis parameter RPC asli — server tidak menghitung harga apa pun.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "11111111-1111-1111-1111-111111111111",
                "store_id": "aaaaaaaa-0000-0000-0000-000000000001",
                "fulfilment_mode": "pickup",
                "payment_method": "qris",
                "payment_provider": "simulated",
                "subtotal": 48000,
                "discount": 0,
                "delivery_fee": 0,
                "total": 48000,
                "voucher_code": None,
                "items": [
                    {
                        "product_id": "cccccccc-0000-0000-0000-000000000001",
                        "name_snapshot": "Kopi Susu Rakyat",
                        "size": "M",
                        "milk": "oat",
                        "ice": "less_ice",
                        "sugar": "50%",
                        "extra_shot": False,
                        "note": "less sugar please",
                        "unit_price": 24000,
                        "qty": 2,
                        "line_total": 48000,
                    }
                ],
            }
        }
    )

    user_id: UUID
    store_id: UUID
    fulfilment_mode: FulfilmentMode = FulfilmentMode.pickup
    table_number: str | None = None
    address_id: UUID | None = None
    scheduled_for: datetime | None = None
    payment_method: str = "qris"
    payment_provider: str = "simulated"
    subtotal: int = Field(ge=0)
    discount: int = Field(default=0, ge=0)
    delivery_fee: int = Field(default=0, ge=0)
    total: int = Field(ge=0)
    voucher_code: str | None = None
    items: list[PlaceOrderItem] = Field(min_length=1, max_length=50)
