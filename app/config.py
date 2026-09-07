"""Konfigurasi aplikasi.

Seluruh nilai dibaca dari environment variable / file `.env` (PRD Bagian 10):
migrasi dari Postgres lokal ke Supabase asli cukup dengan mengganti
`DATABASE_URL`, tanpa perubahan kode.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Koneksi database ---
    database_url: str = Field(
        default="postgresql://kopi:kopi@localhost:5433/kopi_rakyat",
        description="DSN PostgreSQL. Ganti ini saat pindah ke Supabase asli.",
    )
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10

    # --- Realtime ---
    realtime_mode: str = Field(
        default="notify",
        description="'notify' (LISTEN/NOTIFY) atau 'poll' (fallback polling).",
    )
    realtime_channel: str = "pos_order_events"
    poll_interval_seconds: float = 1.0

    # --- Aplikasi ---
    # Default FALSE: mobile app memanggil place_order() langsung ke Supabase,
    # jadi /api/dev/* tidak didaftarkan. Set true hanya untuk uji lokal.
    enable_dev_endpoints: bool = False
    cors_origins: str = "*"
    log_level: str = "INFO"

    @field_validator("realtime_mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"notify", "poll"}:
            raise ValueError("REALTIME_MODE harus 'notify' atau 'poll'")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
