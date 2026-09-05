"""Wrapper tipis di atas RPC yang sudah didefinisikan tim mobile.

Aturan PRD Bagian 11 ("RPC Consistency"): backend TIDAK menduplikasi business
logic. Modul-modul di sini hanya menerjemahkan payload HTTP -> pemanggilan
`SELECT * FROM <fungsi>(...)` dan menerjemahkan error Postgres -> HTTP status.
"""

from app.rpc.advance_stage import advance_order_stage
from app.rpc.errors import RpcError
from app.rpc.place_order import place_order

__all__ = ["RpcError", "advance_order_stage", "place_order"]
