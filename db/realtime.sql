-- =====================================================================
-- realtime.sql — Trigger NOTIFY untuk realtime POS.
--
-- ✅  INI SATU-SATUNYA FILE DB YANG PERLU DI-APPLY KE SUPABASE ASLI
--     (dan hanya bila REALTIME_MODE=notify). Semua file db/ lainnya adalah
--     mirror lokal dan TIDAK boleh di-apply ke Supabase.
--
-- Aman & non-invasif: hanya menambah satu fungsi + dua trigger pada tabel
-- `orders`. Tidak mengubah kolom, data, atau RPC apa pun.
--
-- Cara apply ke Supabase asli: buka Dashboard → SQL Editor, tempel isi file
-- ini, Run. (Atau via psql/`supabase db execute`.) Idempotent.
--
-- Payload sengaja ringkas (id + metadata) karena pg_notify dibatasi ~8000
-- byte; backend melakukan fetch data lengkap setelah menerima sinyal.
--
-- CATATAN: tabel `orders` asli TIDAK punya kolom `updated_at`, jadi stempel
-- waktu event memakai now() (waktu transaksi). Ini hanya informatif bagi POS.
-- =====================================================================

CREATE OR REPLACE FUNCTION public.notify_order_event() RETURNS trigger
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
        'updated_at', now()
    )::text);

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_orders_notify_insert ON public.orders;
CREATE TRIGGER trg_orders_notify_insert
    AFTER INSERT ON public.orders
    FOR EACH ROW EXECUTE FUNCTION public.notify_order_event();

DROP TRIGGER IF EXISTS trg_orders_notify_update ON public.orders;
CREATE TRIGGER trg_orders_notify_update
    AFTER UPDATE ON public.orders
    FOR EACH ROW EXECUTE FUNCTION public.notify_order_event();
