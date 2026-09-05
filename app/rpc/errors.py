"""Terjemahan error RPC/Postgres menjadi error HTTP yang wajar.

RPC bisa gagal karena constraint yang ditulis tim mobile (produk tidak aktif,
toko tutup, order sudah stage final, dsb — PRD Bagian 11 "Error Handling").
Backend tidak menebak-nebak isi constraint tersebut; ia hanya memetakan
SQLSTATE ke status code dan meneruskan pesan aslinya ke klien POS.
"""

from __future__ import annotations

import asyncpg

# SQLSTATE -> HTTP status
_SQLSTATE_TO_HTTP: dict[str, int] = {
    "P0002": 404,  # no_data_found        -> order/store/product tidak ditemukan
    "02000": 404,  # no_data
    "23514": 409,  # check_violation      -> aturan bisnis dilanggar
    "23505": 409,  # unique_violation
    "23503": 400,  # foreign_key_violation
    "23502": 400,  # not_null_violation
    "22P02": 400,  # invalid_text_representation (mis. enum tidak dikenal)
    "42883": 501,  # undefined_function   -> RPC belum ada di database
}

_FRIENDLY: dict[str, str] = {
    "42883": (
        "RPC belum tersedia di database. Jalankan `db/functions.sql` "
        "(atau minta tim mobile menyediakan fungsi ini di Supabase)."
    ),
}


class RpcError(Exception):
    """Kegagalan pemanggilan RPC yang sudah dipetakan ke HTTP status."""

    def __init__(self, message: str, *, status_code: int = 500, sqlstate: str | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.sqlstate = sqlstate

    @classmethod
    def from_postgres(cls, exc: asyncpg.PostgresError, *, rpc_name: str) -> "RpcError":
        sqlstate = getattr(exc, "sqlstate", None)
        status = _SQLSTATE_TO_HTTP.get(sqlstate or "", 500)
        detail = _FRIENDLY.get(sqlstate or "") or str(exc)
        return cls(
            f"{rpc_name}() gagal: {detail}",
            status_code=status,
            sqlstate=sqlstate,
        )
