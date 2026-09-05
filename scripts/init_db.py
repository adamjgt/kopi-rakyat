#!/usr/bin/env python3
"""Apply schema.sql + functions.sql + seed.sql ke database di `DATABASE_URL`.

Alternatif docker-compose (yang meng-apply otomatis saat container dibuat).
Berguna bila Postgres sudah ada, atau untuk apply ulang setelah mengedit SQL.

    python scripts/init_db.py                 # schema + functions + seed
    python scripts/init_db.py --no-seed       # tanpa data dummy
    python scripts/init_db.py --functions-only  # setelah mengedit functions.sql
    python scripts/init_db.py --drop          # ⚠ hapus semua tabel POC dulu

Jangan pakai `--drop` (atau `--seed`) pada database Supabase asli tim mobile.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg  # noqa: E402

from app.config import get_settings  # noqa: E402

DB_DIR = Path(__file__).resolve().parent.parent / "db"

_DROP_SQL = """
DROP TABLE IF EXISTS loyalty_ledger, order_items, orders, store_queue_counters,
    order_no_counters, user_vouchers, vouchers, rewards, addresses, profiles,
    option_values, option_groups, products, categories, stores CASCADE;
DROP FUNCTION IF EXISTS place_order(uuid, uuid, fulfilment_mode, payment_method,
    jsonb, text, text, timestamptz, uuid) CASCADE;
DROP FUNCTION IF EXISTS advance_order_stage(uuid) CASCADE;
DROP FUNCTION IF EXISTS redeem_reward(uuid, uuid) CASCADE;
DROP FUNCTION IF EXISTS calc_option_delta(text, text, text, text, boolean) CASCADE;
DROP FUNCTION IF EXISTS notify_order_event() CASCADE;
DROP FUNCTION IF EXISTS touch_updated_at() CASCADE;
DROP TABLE IF EXISTS auth.users CASCADE;
DROP TYPE IF EXISTS fulfilment_mode, order_status, payment_status,
    payment_method, discount_type, user_tier CASCADE;
"""


async def run(args: argparse.Namespace) -> int:
    dsn = get_settings().database_url
    print(f"→ {dsn.rsplit('@', 1)[-1]}")

    try:
        conn = await asyncpg.connect(dsn=dsn)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ tidak bisa terhubung: {exc}")
        print("  Jalankan `docker compose up -d` atau sesuaikan DATABASE_URL di .env")
        return 1

    try:
        if args.drop:
            print("  … DROP objek POC")
            await conn.execute(_DROP_SQL)

        files = ["functions.sql"] if args.functions_only else ["schema.sql", "functions.sql"]
        if not args.functions_only and not args.no_seed:
            files.append("seed.sql")

        for name in files:
            path = DB_DIR / name
            if not path.is_file():
                print(f"✗ {name} tidak ditemukan di {DB_DIR}")
                return 1
            await conn.execute(path.read_text(encoding="utf-8"))
            print(f"  ✓ {name}")

        stores = await conn.fetchval("SELECT count(*) FROM stores")
        has_rpc = await conn.fetchval(
            "SELECT count(*) FROM pg_proc WHERE proname IN "
            "('place_order','advance_order_stage','redeem_reward')"
        )
        print(f"\nSiap — {stores} store, {has_rpc}/3 RPC terpasang.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"✗ gagal: {exc}")
        return 1
    finally:
        await conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-seed", action="store_true", help="Lewati data dummy")
    p.add_argument("--functions-only", action="store_true", help="Hanya apply functions.sql")
    p.add_argument("--drop", action="store_true", help="⚠ Hapus objek POC sebelum apply")
    return asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
