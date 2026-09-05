-- =====================================================================
-- schema.sql — Replikasi skema Bagian 8 PRD (kontrak dari tim mobile)
-- Target: PostgreSQL 15+ (kompatibel Supabase)
--
-- CATATAN PENTING:
--   Skema ini adalah REPLIKA LOKAL dari skema yang dirancang tim mobile.
--   Backend POS Integration TIDAK mendesain ulang skema ini. File ini ada
--   semata agar fase POC bisa berjalan tanpa akses ke project Supabase asli.
--   Saat migrasi ke Supabase asli, file ini TIDAK perlu di-apply — cukup
--   ganti DATABASE_URL. Yang tetap dibutuhkan hanyalah trigger realtime di
--   bagian paling bawah file ini (lihat "REALTIME SUPPORT").
--
-- Idempotent: aman dijalankan berulang kali.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0. Extensions & skema auth minimal
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

-- Di Supabase asli, skema `auth` dan tabel `auth.users` sudah ada dan
-- dikelola oleh GoTrue. Untuk POC lokal kita buat versi minimal agar FK
-- ke auth.users(id) tidak error.
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text UNIQUE,
    phone         text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 1. Enum types
--
-- ASUMSI (lihat README bagian "Asumsi Eksplisit"): nilai enum di bawah
-- belum didefinisikan resmi oleh tim mobile. Nilai ini diturunkan dari
-- deskripsi PRD Bagian 7.2 dan 9.3.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'fulfilment_mode') THEN
        CREATE TYPE fulfilment_mode AS ENUM ('pickup', 'dine_in', 'delivery');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'order_status') THEN
        CREATE TYPE order_status AS ENUM ('pending', 'paid', 'active', 'completed', 'cancelled');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_status') THEN
        CREATE TYPE payment_status AS ENUM ('unpaid', 'paid', 'refunded', 'failed');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_method') THEN
        CREATE TYPE payment_method AS ENUM ('qris', 'gopay', 'ovo', 'card', 'cash', 'balance');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'discount_type') THEN
        CREATE TYPE discount_type AS ENUM ('percent', 'fixed');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_tier') THEN
        CREATE TYPE user_tier AS ENUM ('bronze', 'silver', 'gold', 'platinum');
    END IF;
END
$$;

-- ---------------------------------------------------------------------
-- 2. Identitas & Akun
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS profiles (
    id                uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name         text,
    phone             text,
    avatar_url        text,
    tier              user_tier NOT NULL DEFAULT 'bronze',
    points            integer  NOT NULL DEFAULT 0 CHECK (points  >= 0),
    stamps            integer  NOT NULL DEFAULT 0 CHECK (stamps  >= 0),
    biometric_enabled boolean  NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS addresses (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    label      text,
    recipient  text,
    line1      text NOT NULL,
    city       text,
    is_default boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_addresses_user ON addresses(user_id);

-- ---------------------------------------------------------------------
-- 3. Lokasi
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stores (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key         text UNIQUE NOT NULL,
    name        text NOT NULL,
    address     text,
    distance_km numeric(6,2),
    is_open     boolean NOT NULL DEFAULT true,
    hours_note  text,
    map_x       numeric(8,3),
    map_y       numeric(8,3),
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 4. Katalog Produk
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categories (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key        text UNIQUE NOT NULL,
    name       text NOT NULL,
    sort_order integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id uuid REFERENCES categories(id) ON DELETE SET NULL,
    slug        text UNIQUE NOT NULL,
    name        text NOT NULL,
    kind        text,                       -- 'drink' | 'food' | 'bean' | ...
    base_price  numeric(12,2) NOT NULL CHECK (base_price >= 0),
    description text,
    origin      text,
    badge       text,
    image_url   text,
    active      boolean NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);

CREATE TABLE IF NOT EXISTS option_groups (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key        text UNIQUE NOT NULL,        -- 'size' | 'milk' | 'ice' | 'sugar' | 'extra_shot'
    label      text NOT NULL,
    sort_order integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS option_values (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id    uuid NOT NULL REFERENCES option_groups(id) ON DELETE CASCADE,
    key         text NOT NULL,              -- 'M' | 'oat' | 'less_ice' | '50%' | 'yes' ...
    sub_label   text,
    price_delta numeric(12,2) NOT NULL DEFAULT 0,
    sort_order  integer NOT NULL DEFAULT 0,
    UNIQUE (group_id, key)
);

-- ---------------------------------------------------------------------
-- 5. Promo & Loyalitas  (di luar scope backend POS — struktur saja)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vouchers (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code           text UNIQUE NOT NULL,
    title          text,
    discount_type  discount_type NOT NULL DEFAULT 'fixed',
    discount_value numeric(12,2) NOT NULL DEFAULT 0,
    scope          text,
    valid_until    timestamptz,
    active         boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS user_vouchers (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    voucher_id uuid NOT NULL REFERENCES vouchers(id) ON DELETE CASCADE,
    claimed_at timestamptz NOT NULL DEFAULT now(),
    used_at    timestamptz
);
CREATE INDEX IF NOT EXISTS idx_user_vouchers_user ON user_vouchers(user_id);

CREATE TABLE IF NOT EXISTS rewards (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    stamps_cost integer NOT NULL CHECK (stamps_cost > 0),
    active      boolean NOT NULL DEFAULT true,
    sort_order  integer NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------
-- 6. Transaksi — INTI INTEGRASI POS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_no        text UNIQUE NOT NULL,
    user_id         uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    store_id        uuid NOT NULL REFERENCES stores(id) ON DELETE RESTRICT,
    address_id      uuid REFERENCES addresses(id) ON DELETE SET NULL,
    fulfilment_mode fulfilment_mode NOT NULL,
    table_number    text,
    scheduled_for   timestamptz,
    payment_method  payment_method,
    payment_status  payment_status NOT NULL DEFAULT 'unpaid',
    subtotal        numeric(12,2) NOT NULL DEFAULT 0,
    discount        numeric(12,2) NOT NULL DEFAULT 0,
    delivery_fee    numeric(12,2) NOT NULL DEFAULT 0,
    total           numeric(12,2) NOT NULL DEFAULT 0,
    voucher_code    text,
    status          order_status NOT NULL DEFAULT 'pending',
    stage           smallint NOT NULL DEFAULT 0 CHECK (stage BETWEEN 0 AND 3),
    pickup_code     text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Index pendukung antrian POS (diizinkan oleh PRD Bagian 15).
CREATE INDEX IF NOT EXISTS idx_orders_store_created ON orders(store_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_store_stage   ON orders(store_id, stage);
CREATE INDEX IF NOT EXISTS idx_orders_store_status  ON orders(store_id, status);

CREATE TABLE IF NOT EXISTS order_items (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id      uuid NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id    uuid REFERENCES products(id) ON DELETE SET NULL,
    name_snapshot text NOT NULL,
    size          text,
    milk          text,
    ice           text,
    sugar         text,
    extra_shot    boolean NOT NULL DEFAULT false,
    note          text,
    unit_price    numeric(12,2) NOT NULL DEFAULT 0,
    qty           integer NOT NULL DEFAULT 1 CHECK (qty > 0),
    line_total    numeric(12,2) NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);

CREATE TABLE IF NOT EXISTS loyalty_ledger (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    order_id      uuid REFERENCES orders(id) ON DELETE SET NULL,
    reward_id     uuid REFERENCES rewards(id) ON DELETE SET NULL,
    delta_stamps  integer NOT NULL DEFAULT 0,
    delta_points  integer NOT NULL DEFAULT 0,
    reason        text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_loyalty_user ON loyalty_ledger(user_id);

-- ---------------------------------------------------------------------
-- 7. Penomoran order harian (pendukung place_order)
--    Tabel bantu agar order_no & pickup_code aman dari race condition.
-- ---------------------------------------------------------------------
-- Nomor antrian per toko per hari -> dipakai untuk `pickup_code`.
CREATE TABLE IF NOT EXISTS store_queue_counters (
    store_id  uuid NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    day       date NOT NULL,
    last_seq  integer NOT NULL DEFAULT 0,
    PRIMARY KEY (store_id, day)
);

-- Nomor order global per hari -> dipakai untuk `order_no` (kolomnya UNIQUE
-- lintas toko, jadi counter-nya tidak boleh di-scope per toko).
CREATE TABLE IF NOT EXISTS order_no_counters (
    day      date PRIMARY KEY,
    last_seq integer NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------
-- 8. updated_at otomatis
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_orders_touch ON orders;
CREATE TRIGGER trg_orders_touch
    BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

DROP TRIGGER IF EXISTS trg_profiles_touch ON profiles;
CREATE TRIGGER trg_profiles_touch
    BEFORE UPDATE ON profiles
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- =====================================================================
-- REALTIME SUPPORT
--
-- Satu-satunya objek pada file ini yang WAJIB tetap ada saat pindah ke
-- Supabase asli (kecuali tim memilih memakai Supabase Realtime / polling).
-- Payload sengaja dibuat ringkas (hanya id + metadata) karena pg_notify
-- dibatasi 8000 byte; backend melakukan fetch data lengkap setelahnya.
-- =====================================================================
CREATE OR REPLACE FUNCTION notify_order_event() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_event text;
BEGIN
    IF TG_OP = 'INSERT' THEN
        v_event := 'order.created';
    ELSIF NEW.stage IS DISTINCT FROM OLD.stage
       OR NEW.status IS DISTINCT FROM OLD.status THEN
        v_event := 'order.stage_updated';
    ELSE
        RETURN NEW;  -- perubahan kolom lain tidak menarik bagi POS
    END IF;

    PERFORM pg_notify('pos_order_events', json_build_object(
        'event',      v_event,
        'order_id',   NEW.id,
        'store_id',   NEW.store_id,
        'stage',      NEW.stage,
        'status',     NEW.status,
        'updated_at', NEW.updated_at
    )::text);

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_orders_notify_insert ON orders;
CREATE TRIGGER trg_orders_notify_insert
    AFTER INSERT ON orders
    FOR EACH ROW EXECUTE FUNCTION notify_order_event();

DROP TRIGGER IF EXISTS trg_orders_notify_update ON orders;
CREATE TRIGGER trg_orders_notify_update
    AFTER UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION notify_order_event();
