-- =====================================================================
-- functions.sql — RPC asli tim mobile (SALINAN SETIA).
--
-- Sumber kebenaran: supabase/migrations/20260901000000_init.sql pada repo
-- mobile app. Tiga fungsi ini adalah KONTRAK integrasi; backend Python
-- (app/rpc/*.py) mengikat signature-nya persis seperti di bawah.
--
-- ⚠️  JANGAN apply ke Supabase asli — fungsi ini sudah ada di sana. File ini
--     hanya untuk mirror lokal (pengembangan & test).
--
-- CATATAN PENTING soal `auth.uid()`:
--   place_order() dan advance_order_stage() TIDAK menerima p_user_id. Keduanya
--   memakai auth.uid() (id user dari JWT). Backend POS tersambung sebagai role
--   database (bukan lewat PostgREST), jadi auth.uid() default NULL. Backend
--   mengatasinya dengan meng-impersonasi pemilik order via GUC
--   request.jwt.claims sebelum memanggil RPC — lihat app/rpc/advance_stage.py
--   dan app/rpc/place_order.py. RPC-nya sendiri TIDAK diubah.
-- =====================================================================

-- ---------------------------------------------------------------------
-- place_order() — buat order + items dalam satu transaksi, tandai paid,
-- tambah +1 stamp & poin. user_id diambil dari auth.uid().
-- Harga (subtotal/discount/total/unit_price/line_total) DIHITUNG KLIEN dan
-- dikirim apa adanya; server tidak menghitung ulang dari katalog.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.place_order(
    p_store_id uuid,
    p_fulfilment_mode text,
    p_table_number text,
    p_address_id uuid,
    p_scheduled_for timestamptz,
    p_payment_method text,
    p_payment_provider text,
    p_subtotal integer,
    p_discount integer,
    p_delivery_fee integer,
    p_total integer,
    p_voucher_code text,
    p_items jsonb -- array of {product_id, name_snapshot, size, milk, ice, sugar, extra_shot, note, unit_price, qty, line_total}
) RETURNS public.orders
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_order public.orders;
    v_item jsonb;
    v_order_no text;
    v_pickup_code text;
BEGIN
    IF auth.uid() IS NULL THEN
        RAISE EXCEPTION 'Must be signed in to place an order';
    END IF;

    v_order_no := '#KR-' || to_char(nextval('public.order_no_seq'), 'FM0000');
    v_pickup_code := chr(65 + (random() * 25)::int) || '-' || lpad((floor(random() * 99))::text, 2, '0');

    INSERT INTO public.orders (
        order_no, user_id, store_id, fulfilment_mode, table_number, address_id,
        scheduled_for, payment_method, payment_provider, payment_status,
        subtotal, discount, delivery_fee, total, voucher_code, status, stage,
        pickup_code, paid_at
    ) VALUES (
        v_order_no, auth.uid(), p_store_id, p_fulfilment_mode, p_table_number, p_address_id,
        p_scheduled_for, p_payment_method, p_payment_provider, 'paid',
        p_subtotal, p_discount, p_delivery_fee, p_total, p_voucher_code, 'received', 0,
        v_pickup_code, now()
    ) RETURNING * INTO v_order;

    FOR v_item IN SELECT * FROM jsonb_array_elements(p_items) LOOP
        INSERT INTO public.order_items (
            order_id, product_id, name_snapshot, size, milk, ice, sugar,
            extra_shot, note, unit_price, qty, line_total
        ) VALUES (
            v_order.id,
            nullif(v_item ->> 'product_id', '')::uuid,
            v_item ->> 'name_snapshot',
            v_item ->> 'size', v_item ->> 'milk', v_item ->> 'ice', v_item ->> 'sugar',
            coalesce((v_item ->> 'extra_shot')::boolean, false),
            v_item ->> 'note',
            (v_item ->> 'unit_price')::integer,
            (v_item ->> 'qty')::integer,
            (v_item ->> 'line_total')::integer
        );
    END LOOP;

    UPDATE public.profiles
        SET stamps = least(10, stamps + 1), points = points + greatest(0, p_total / 1000)
        WHERE id = auth.uid();

    INSERT INTO public.loyalty_ledger (user_id, order_id, delta_stamps, delta_points, reason)
    VALUES (auth.uid(), v_order.id, 1, greatest(0, p_total / 1000), 'Pesanan ' || v_order_no);

    RETURN v_order;
END;
$$;

-- ---------------------------------------------------------------------
-- advance_order_stage() — majukan order tracking ke stage berikutnya.
-- Di-scope ke pemilik order (user_id = auth.uid()). Status dipetakan:
--   stage 1 -> preparing, 2 -> (delivery: on_the_way, else: ready), 3 -> completed.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.advance_order_stage(p_order_id uuid)
RETURNS public.orders
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_order public.orders;
BEGIN
    SELECT * INTO v_order FROM public.orders WHERE id = p_order_id AND user_id = auth.uid();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Order not found';
    END IF;
    UPDATE public.orders
        SET stage = least(3, stage + 1),
            status = CASE least(3, stage + 1)
                WHEN 1 THEN 'preparing'
                WHEN 2 THEN CASE fulfilment_mode WHEN 'delivery' THEN 'on_the_way' ELSE 'ready' END
                WHEN 3 THEN 'completed'
                ELSE status
            END
        WHERE id = p_order_id
        RETURNING * INTO v_order;
    RETURN v_order;
END;
$$;

-- ---------------------------------------------------------------------
-- redeem_reward() — tukar reward stamp-card. Di luar scope backend POS
-- (dipanggil mobile app). Di-scope ke auth.uid().
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.redeem_reward(p_reward_id uuid)
RETURNS public.profiles
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_reward public.rewards;
    v_profile public.profiles;
BEGIN
    SELECT * INTO v_reward FROM public.rewards WHERE id = p_reward_id AND active;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Reward not found';
    END IF;

    SELECT * INTO v_profile FROM public.profiles WHERE id = auth.uid() FOR UPDATE;
    IF v_profile.stamps < v_reward.stamps_cost THEN
        RAISE EXCEPTION 'Not enough stamps';
    END IF;

    UPDATE public.profiles SET stamps = stamps - v_reward.stamps_cost
        WHERE id = auth.uid() RETURNING * INTO v_profile;

    INSERT INTO public.loyalty_ledger (user_id, reward_id, delta_stamps, reason)
    VALUES (auth.uid(), p_reward_id, -v_reward.stamps_cost, 'Tukar: ' || v_reward.name);

    RETURN v_profile;
END;
$$;
