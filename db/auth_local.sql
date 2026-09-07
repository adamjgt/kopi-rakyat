-- =====================================================================
-- auth_local.sql — LOCAL-ONLY stub of Supabase's `auth` schema.
--
-- ⚠️  JANGAN PERNAH menjalankan file ini pada database Supabase asli.
--     Di Supabase, skema `auth`, tabel `auth.users`, dan fungsi
--     `auth.uid()` / `auth.role()` sudah disediakan oleh GoTrue.
--
--     File ini hanya ada supaya `db/schema.sql` (mirror skema asli tim
--     mobile) bisa di-apply ke Postgres lokal untuk pengembangan & test:
--     FK ke `auth.users(id)` dan RLS policy yang memakai `auth.uid()`
--     butuh objek-objek ini agar tidak error.
--
-- `auth.uid()` di sini meniru implementasi Supabase: membaca klaim JWT dari
-- GUC `request.jwt.claims`. Backend POS meng-impersonasi pemilik order dengan
-- `set_config('request.jwt.claims', '{"sub": "<user_id>"}', true)` sebelum
-- memanggil RPC yang di-scope `auth.uid()` (lihat app/rpc/*.py).
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email              text UNIQUE,
    phone              text,
    raw_user_meta_data jsonb,
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- auth.uid() — id user dari klaim JWT aktif (NULL bila tidak ada sesi).
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(
        COALESCE(
            NULLIF(current_setting('request.jwt.claim.sub', true), ''),
            (NULLIF(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
        ),
        ''
    )::uuid;
$$;

-- auth.role() — role dari klaim JWT aktif (mis. 'authenticated').
CREATE OR REPLACE FUNCTION auth.role() RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT COALESCE(
        NULLIF(current_setting('request.jwt.claim.role', true), ''),
        (NULLIF(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role')
    );
$$;
