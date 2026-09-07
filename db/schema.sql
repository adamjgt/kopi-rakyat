-- =====================================================================
-- schema.sql — MIRROR LOKAL dari skema Supabase asli tim mobile.
--
-- Sumber kebenaran: supabase/migrations/20260901000000_init.sql pada repo
-- mobile app (kopi-rakyat-mobileapp). File ini adalah salinan setia struktur
-- tabel + RLS + sequence dari sana, dibuat idempotent agar bisa di-apply
-- berulang ke Postgres lokal untuk pengembangan & test.
--
-- ⚠️  JANGAN apply file ini ke Supabase asli — skema di sana sudah ada.
--     Yang perlu dipasang ke Supabase asli HANYA db/realtime.sql
--     (trigger NOTIFY untuk realtime POS).
--
-- Perbedaan vs. skema lama backend (yang berbasis asumsi) didokumentasikan
-- di docs/schema-comparison.md.
--
-- Urutan apply lokal: auth_local.sql → schema.sql → functions.sql →
--                     realtime.sql → seed.sql
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------
-- Profiles (satu baris per auth.users id; guest tidak punya baris di sini)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
    id                uuid PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
    full_name         text NOT NULL DEFAULT 'Pengguna',
    phone             text,
    avatar_url        text,
    tier              text NOT NULL DEFAULT 'Silver' CHECK (tier IN ('Silver', 'Gold')),
    points            integer NOT NULL DEFAULT 1200,
    stamps            integer NOT NULL DEFAULT 6 CHECK (stamps BETWEEN 0 AND 10),
    biometric_enabled boolean NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "profiles are self-readable" ON public.profiles;
DROP POLICY IF EXISTS "profiles are self-updatable" ON public.profiles;
DROP POLICY IF EXISTS "profiles are self-insertable" ON public.profiles;
CREATE POLICY "profiles are self-readable" ON public.profiles
    FOR SELECT USING (auth.uid() = id);
CREATE POLICY "profiles are self-updatable" ON public.profiles
    FOR UPDATE USING (auth.uid() = id);
CREATE POLICY "profiles are self-insertable" ON public.profiles
    FOR INSERT WITH CHECK (auth.uid() = id);

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profiles (id, phone)
    VALUES (new.id, new.phone)
    ON CONFLICT (id) DO NOTHING;
    RETURN new;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();

-- ---------------------------------------------------------------------
-- Stores
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.stores (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key         text UNIQUE NOT NULL,
    name        text NOT NULL,
    address     text NOT NULL,
    distance_km numeric(4, 1),
    is_open     boolean NOT NULL DEFAULT true,
    hours_note  text NOT NULL,
    map_x       numeric(4, 1) NOT NULL, -- posisi persen pada peta locator (placeholder)
    map_y       numeric(4, 1) NOT NULL,
    sort_order  integer NOT NULL DEFAULT 0
);

ALTER TABLE public.stores ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "stores are publicly readable" ON public.stores;
CREATE POLICY "stores are publicly readable" ON public.stores FOR SELECT USING (true);

-- ---------------------------------------------------------------------
-- Categories & products (drink + merch berbagi satu katalog)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.categories (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key        text UNIQUE NOT NULL,
    name       text NOT NULL,
    sort_order integer NOT NULL DEFAULT 0
);

ALTER TABLE public.categories ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "categories are publicly readable" ON public.categories;
CREATE POLICY "categories are publicly readable" ON public.categories FOR SELECT USING (true);

CREATE TABLE IF NOT EXISTS public.products (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text UNIQUE NOT NULL,
    name        text NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('drink', 'merch')),
    category_id uuid REFERENCES public.categories (id),
    base_price  integer NOT NULL,
    description text NOT NULL DEFAULT '',
    origin      text NOT NULL DEFAULT '',
    badge       text,
    image_url   text,
    active      boolean NOT NULL DEFAULT true,
    sort_order  integer NOT NULL DEFAULT 0
);

ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "products are publicly readable" ON public.products;
CREATE POLICY "products are publicly readable" ON public.products FOR SELECT USING (true);

-- Opsi kustomisasi global untuk drink (size / milk / ice / sugar).
CREATE TABLE IF NOT EXISTS public.option_groups (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key        text UNIQUE NOT NULL, -- size | milk | ice | sugar
    label      text NOT NULL,
    sort_order integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS public.option_values (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id    uuid NOT NULL REFERENCES public.option_groups (id) ON DELETE CASCADE,
    key         text NOT NULL, -- mis. 'M', 'Oat', 'Sedikit'
    sub_label   text NOT NULL DEFAULT '',
    price_delta integer NOT NULL DEFAULT 0,
    sort_order  integer NOT NULL DEFAULT 0,
    UNIQUE (group_id, key)
);

ALTER TABLE public.option_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.option_values ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "option groups are publicly readable" ON public.option_groups;
DROP POLICY IF EXISTS "option values are publicly readable" ON public.option_values;
CREATE POLICY "option groups are publicly readable" ON public.option_groups FOR SELECT USING (true);
CREATE POLICY "option values are publicly readable" ON public.option_values FOR SELECT USING (true);

-- ---------------------------------------------------------------------
-- Vouchers (kode promo + voucher loyalty yang bisa diklaim)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.vouchers (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code           text UNIQUE NOT NULL,
    title          text NOT NULL,
    note           text NOT NULL DEFAULT '',
    discount_type  text NOT NULL CHECK (discount_type IN ('percent', 'fixed')),
    discount_value numeric NOT NULL,
    scope          text NOT NULL DEFAULT 'cart' CHECK (scope IN ('cart', 'merch')),
    valid_until    date,
    active         boolean NOT NULL DEFAULT true
);

ALTER TABLE public.vouchers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "vouchers are publicly readable" ON public.vouchers;
CREATE POLICY "vouchers are publicly readable" ON public.vouchers FOR SELECT USING (true);

CREATE TABLE IF NOT EXISTS public.user_vouchers (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    voucher_id uuid NOT NULL REFERENCES public.vouchers (id),
    claimed_at timestamptz NOT NULL DEFAULT now(),
    used_at    timestamptz,
    UNIQUE (user_id, voucher_id)
);

ALTER TABLE public.user_vouchers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users manage their own claimed vouchers" ON public.user_vouchers;
CREATE POLICY "users manage their own claimed vouchers" ON public.user_vouchers
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- ---------------------------------------------------------------------
-- Addresses (mode delivery)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.addresses (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    label      text NOT NULL DEFAULT 'Rumah',
    recipient  text NOT NULL,
    line1      text NOT NULL,
    city       text NOT NULL DEFAULT 'Jakarta Selatan',
    is_default boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.addresses ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users manage their own addresses" ON public.addresses;
CREATE POLICY "users manage their own addresses" ON public.addresses
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- ---------------------------------------------------------------------
-- Rewards (penukaran stamp-card)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.rewards (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    stamps_cost integer NOT NULL,
    active      boolean NOT NULL DEFAULT true,
    sort_order  integer NOT NULL DEFAULT 0
);

ALTER TABLE public.rewards ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "rewards are publicly readable" ON public.rewards;
CREATE POLICY "rewards are publicly readable" ON public.rewards FOR SELECT USING (true);

-- ---------------------------------------------------------------------
-- Orders  — INTI INTEGRASI POS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.orders (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_no         text UNIQUE NOT NULL,
    user_id          uuid REFERENCES auth.users (id) ON DELETE SET NULL,
    store_id         uuid REFERENCES public.stores (id),
    fulfilment_mode  text NOT NULL CHECK (fulfilment_mode IN ('delivery', 'pickup', 'dine_in', 'pre_order')),
    table_number     text,
    address_id       uuid REFERENCES public.addresses (id),
    scheduled_for    timestamptz,
    payment_method   text NOT NULL,
    payment_provider text NOT NULL DEFAULT 'simulated',
    payment_status   text NOT NULL DEFAULT 'pending' CHECK (payment_status IN ('pending', 'paid', 'failed')),
    subtotal         integer NOT NULL,
    discount         integer NOT NULL DEFAULT 0,
    delivery_fee     integer NOT NULL DEFAULT 0,
    total            integer NOT NULL,
    voucher_code     text,
    status           text NOT NULL DEFAULT 'received' CHECK (status IN ('received', 'preparing', 'on_the_way', 'ready', 'completed')),
    stage            integer NOT NULL DEFAULT 0,
    pickup_code      text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    paid_at          timestamptz
);

ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users manage their own orders" ON public.orders;
CREATE POLICY "users manage their own orders" ON public.orders
    FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

-- Index pendukung antrian POS (diizinkan menambah objek pendukung realtime).
CREATE INDEX IF NOT EXISTS idx_orders_store_created ON public.orders (store_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_store_stage   ON public.orders (store_id, stage);
CREATE INDEX IF NOT EXISTS idx_orders_store_status  ON public.orders (store_id, status);

CREATE TABLE IF NOT EXISTS public.order_items (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id      uuid NOT NULL REFERENCES public.orders (id) ON DELETE CASCADE,
    product_id    uuid REFERENCES public.products (id),
    name_snapshot text NOT NULL,
    size          text,
    milk          text,
    ice           text,
    sugar         text,
    extra_shot    boolean NOT NULL DEFAULT false,
    note          text,
    unit_price    integer NOT NULL,
    qty           integer NOT NULL DEFAULT 1,
    line_total    integer NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON public.order_items (order_id);

ALTER TABLE public.order_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users manage their own order items" ON public.order_items;
CREATE POLICY "users manage their own order items" ON public.order_items
    FOR ALL USING (
        EXISTS (SELECT 1 FROM public.orders o WHERE o.id = order_id AND o.user_id = auth.uid())
    ) WITH CHECK (
        EXISTS (SELECT 1 FROM public.orders o WHERE o.id = order_id AND o.user_id = auth.uid())
    );

-- ---------------------------------------------------------------------
-- Loyalty ledger (riwayat stamp + poin)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.loyalty_ledger (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    order_id     uuid REFERENCES public.orders (id),
    reward_id    uuid REFERENCES public.rewards (id),
    delta_stamps integer NOT NULL DEFAULT 0,
    delta_points integer NOT NULL DEFAULT 0,
    reason       text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.loyalty_ledger ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users read their own loyalty ledger" ON public.loyalty_ledger;
DROP POLICY IF EXISTS "users insert their own loyalty ledger" ON public.loyalty_ledger;
CREATE POLICY "users read their own loyalty ledger" ON public.loyalty_ledger
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "users insert their own loyalty ledger" ON public.loyalty_ledger
    FOR INSERT WITH CHECK (auth.uid() = user_id);

-- ---------------------------------------------------------------------
-- Sequence untuk order_no (#KR-0000)
-- ---------------------------------------------------------------------
CREATE SEQUENCE IF NOT EXISTS public.order_no_seq START 4471;
