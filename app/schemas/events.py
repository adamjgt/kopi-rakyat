"""Payload event WebSocket ke klien POS (PRD Bagian 9.5 & 9.6)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.orders import Order, OrderItem, OrderStatus

EVENT_ORDER_CREATED = "order.created"
EVENT_ORDER_STAGE_UPDATED = "order.stage_updated"


class WSEvent(BaseModel):
    """Amplop umum semua event: `{"event": ..., "data": {...}}`."""

    event: str
    data: dict


class OrderCreatedData(BaseModel):
    order: Order
    items: list[OrderItem] = Field(default_factory=list)


class OrderCreatedEvent(BaseModel):
    event: Literal["order.created"] = "order.created"
    data: OrderCreatedData


class OrderStageUpdatedData(BaseModel):
    order_id: UUID
    stage: int = Field(ge=0)
    status: OrderStatus
    updated_at: datetime


class OrderStageUpdatedEvent(BaseModel):
    event: Literal["order.stage_updated"] = "order.stage_updated"
    data: OrderStageUpdatedData
