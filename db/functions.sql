-- =====================================================================
-- functions.sql — Implementasi RPC (PRD Bagian 8.2)
--
-- ⚠️  IMPLEMENTASI SEMENTARA MENGIKUTI KONTRAK YANG DIBERIKAN TIM MOBILE
--     — PERLU DIREVIEW ULANG SAAT INTEGRASI SUNGGUHAN.
--
--     PRD Bagian 8.2 hanya mendeskripsikan input/output & efek samping
--     ketiga fungsi ini secara naratif; tubuh fungsinya belum tersedia.
--     Isi di bawah adalah rekonstruksi wajar dari deskripsi tersebut agar
--     alur end-to-end POC bisa diuji. Ketika tim mobile menyerahkan versi
--     resminya, ganti seluruh file ini — backend Python TIDAK perlu
--     berubah selama signature & tipe return tetap sama.
--
-- Signature yang dipakai backend (app/rpc/*.py) — bagian yang benar-benar
-- menjadi kontrak integrasi:
--     place_order(p_user_id, p_store_id, p_fulfilment_mode, p_payment_method,
--                 p_items, p_voucher_code, p_table_number, p_scheduled_for,
--                 p_address_id) RETURNS orders
--     advance_order_stage(p_order_id) RETURNS orders
--     redeem_reward(p_user_id, p_reward_id) RETURNS profiles
-- =====================================================================

-- ---------------------------------------------------------------------
-- Helper: hitung total price_delta dari opsi kustomisasi satu item.
-- Opsi yang tidak dikenal di `option_values` diperlakukan sebagai delta 0
-- (bukan error) supaya simulator POC tidak mudah gagal.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION calc_option_delta(
    p_size       text,
    p_milk       text,
    p_ice        text,
    p_sugar      text,
    p_extra_shot boolean
) RETURNS numeric
LANGUAGE sql STABLE AS $$
    SELECT COALESCE(SUM(ov.price_delta), 0)
    FROM (
        VALUES ('size',       p_size),
               ('milk',       p_milk),
               ('ice',        p_ice),
               ('sugar',      p_sugar),
               ('extra_shot', CASE WHEN p_extra_shot THEN 'yes' ELSE NULL END)
    ) AS sel(group_key, value_key)
    JOIN option_groups og ON og.key = sel.group_key
    JOIN option_values ov ON ov.group_id = og.id AND ov.key = sel.value_key
    WHERE sel.value_key IS NOT NULL;
$$;

-- =====================================================================
-- 1. place_order()
--    Buat order + order_items sekaligus, set status paid, tambah stamp & poin.
--    Dipanggil oleh: Mobile App (nanti) / Dummy Simulator (fase ini).
-- =====================================================================
CREATE OR REPLACE FUNCTION place_order(
    p_user_id         uuid,
    p_store_id        uuid,
    p_fulfilment_mode fulfilment_mode,
    p_payment_method  payment_method,
    p_items           jsonb,
    p_voucher_code    text        DEFAULT NULL,
    p_table_number    text        DEFAULT NULL,
    p_scheduled_for   timestamptz DEFAULT NULL,
    p_address_id      uuid        DEFAULT NULL
) RETURNS orders
LANGUAGE plpgsql AS $$
DECLARE
    v_store        stores%ROWTYPE;
    v_order        orders%ROWTYPE;
    v_item         jsonb;
    v_product      products%ROWTYPE;
    v_qty          integer;
    v_extra_shot   boolean;
    v_unit_price   numeric(12,2);
    v_line_total   numeric(12,2);
    v_subtotal     numeric(12,2) := 0;
    v_discount     numeric(12,2) := 0;
    v_delivery_fee numeric(12,2) := 0;
    v_voucher      vouchers%ROWTYPE;
    v_order_seq    integer;
    v_queue_seq    integer;
    v_order_no     text;
    v_pickup_code  text;
    v_stamps       integer := 0;
    v_points       integer := 0;
BEGIN
    ----------------------------------------------------------------
    -- Validasi input
    ----------------------------------------------------------------
    IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) = 0 THEN
        RAISE EXCEPTION 'items must be a non-empty JSON array'
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT * INTO v_store FROM stores WHERE id = p_store_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'store % not found', p_store_id USING ERRCODE = 'no_data_found';
    END IF;
    IF NOT v_store.is_open THEN
        RAISE EXCEPTION 'store % (%) is currently closed', v_store.key, v_store.name
            USING ERRCODE = 'check_violation';
    END IF;

    IF p_fulfilment_mode = 'delivery' AND p_address_id IS NULL THEN
        RAISE EXCEPTION 'address_id is required for delivery orders'
            USING ERRCODE = 'check_violation';
    END IF;
    IF p_fulfilment_mode = 'dine_in' AND p_table_number IS NULL THEN
        RAISE EXCEPTION 'table_number is required for dine_in orders'
            USING ERRCODE = 'check_violation';
    END IF;

    ----------------------------------------------------------------
    -- Nomor order (global harian) & nomor antrian (per toko harian)
    ----------------------------------------------------------------
    INSERT INTO order_no_counters (day, last_seq) VALUES (CURRENT_DATE, 1)
    ON CONFLICT (day) DO UPDATE SET last_seq = order_no_counters.last_seq + 1
    RETURNING last_seq INTO v_order_seq;

    INSERT INTO store_queue_counters (store_id, day, last_seq) VALUES (p_store_id, CURRENT_DATE, 1)
    ON CONFLICT (store_id, day) DO UPDATE SET last_seq = store_queue_counters.last_seq + 1
    RETURNING last_seq INTO v_queue_seq;

    v_order_no := 'ORD-' || to_char(CURRENT_DATE, 'YYYYMMDD')
                         || '-' || lpad(v_order_seq::text, 4, '0');

    -- pickup_code hanya relevan untuk mode pickup (PRD 7.6).
    IF p_fulfilment_mode = 'pickup' THEN
        v_pickup_code := chr(65 + ((v_queue_seq / 1000) % 26))
                      || lpad((v_queue_seq % 1000)::text, 3, '0');
    END IF;

    IF p_fulfilment_mode = 'delivery' THEN
        v_delivery_fee := 10000;   -- ASUMSI: flat fee POC, belum ada aturan resmi
    END IF;

    ----------------------------------------------------------------
    -- Header order (nilai uang diisi 0 dulu, di-update setelah item)
    ----------------------------------------------------------------
    INSERT INTO orders (
        order_no, user_id, store_id, address_id, fulfilment_mode, table_number,
        scheduled_for, payment_method, payment_status, subtotal, discount,
        delivery_fee, total, voucher_code, status, stage, pickup_code
    ) VALUES (
        v_order_no, p_user_id, p_store_id, p_address_id, p_fulfilment_mode, p_table_number,
        p_scheduled_for, p_payment_method, 'paid', 0, 0,
        v_delivery_fee, 0, p_voucher_code, 'paid', 0, v_pickup_code
    ) RETURNING * INTO v_order;

    ----------------------------------------------------------------
    -- Item + snapshot opsi
    ----------------------------------------------------------------
    FOR v_item IN SELECT * FROM jsonb_array_elements(p_items)
    LOOP
        SELECT * INTO v_product
        FROM products
        WHERE id = (v_item->>'product_id')::uuid;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'product % not found', v_item->>'product_id'
                USING ERRCODE = 'no_data_found';
        END IF;
        IF NOT v_product.active THEN
            RAISE EXCEPTION 'product % (%) is not active', v_product.slug, v_product.name
                USING ERRCODE = 'check_violation';
        END IF;

        v_qty        := COALESCE((v_item->>'qty')::integer, 1);
        v_extra_shot := COALESCE((v_item->>'extra_shot')::boolean, false);

        IF v_qty <= 0 THEN
            RAISE EXCEPTION 'qty for product % must be > 0', v_product.slug
                USING ERRCODE = 'check_violation';
        END IF;

        v_unit_price := v_product.base_price + calc_option_delta(
            v_item->>'size', v_item->>'milk', v_item->>'ice',
            v_item->>'sugar', v_extra_shot
        );
        v_line_total := v_unit_price * v_qty;
        v_subtotal   := v_subtotal + v_line_total;

        INSERT INTO order_items (
            order_id, product_id, name_snapshot, size, milk, ice, sugar,
            extra_shot, note, unit_price, qty, line_total
        ) VALUES (
            v_order.id, v_product.id, v_product.name,
            v_item->>'size', v_item->>'milk', v_item->>'ice', v_item->>'sugar',
            v_extra_shot, v_item->>'note', v_unit_price, v_qty, v_line_total
        );

        -- ASUMSI loyalitas: 1 stamp per cup minuman, 1 poin per Rp 1.000 total.
        IF COALESCE(v_product.kind, 'drink') = 'drink' THEN
            v_stamps := v_stamps + v_qty;
        END IF;
    END LOOP;

    ----------------------------------------------------------------
    -- Voucher (opsional). Voucher tidak valid = diabaikan diam-diam?
    -- Tidak: kita gagalkan supaya customer tidak salah paham soal harga.
    ----------------------------------------------------------------
    IF p_voucher_code IS NOT NULL THEN
        SELECT * INTO v_voucher
        FROM vouchers
        WHERE code = p_voucher_code
          AND active
          AND (valid_until IS NULL OR valid_until > now());

        IF NOT FOUND THEN
            RAISE EXCEPTION 'voucher % is invalid or expired', p_voucher_code
                USING ERRCODE = 'check_violation';
        END IF;

        v_discount := CASE v_voucher.discount_type
                          WHEN 'percent' THEN v_subtotal * v_voucher.discount_value / 100
                          ELSE v_voucher.discount_value
                      END;
        v_discount := LEAST(v_discount, v_subtotal);   -- tidak boleh negatif
    END IF;

    ----------------------------------------------------------------
    -- Finalisasi total & loyalitas
    ----------------------------------------------------------------
    v_points := floor((v_subtotal - v_discount + v_delivery_fee) / 1000)::integer;

    UPDATE orders SET
        subtotal = v_subtotal,
        discount = v_discount,
        total    = v_subtotal - v_discount + v_delivery_fee
    WHERE id = v_order.id
    RETURNING * INTO v_order;

    IF p_user_id IS NOT NULL AND (v_stamps > 0 OR v_points > 0) THEN
        UPDATE profiles
        SET stamps = stamps + v_stamps,
            points = points + v_points
        WHERE id = p_user_id;

        IF FOUND THEN
            INSERT INTO loyalty_ledger (user_id, order_id, delta_stamps, delta_points, reason)
            VALUES (p_user_id, v_order.id, v_stamps, v_points, 'order:' || v_order.order_no);
        END IF;
    END IF;

    RETURN v_order;
END;
$$;

-- =====================================================================
-- 2. advance_order_stage()
--    Naikkan stage order (0→1→2→3) & update status sesuai fulfilment_mode.
--    Dipanggil oleh: Backend POS Integration saat barista update progres.
--
--    ASUMSI stage (PRD Bagian 7.2 — belum resmi dari tim mobile):
--      0 = diterima/antre, 1 = diracik, 2 = siap diambil/dikirim, 3 = selesai.
--    ASUMSI status: stage 1..2 -> 'active', stage 3 -> 'completed'.
-- =====================================================================
CREATE OR REPLACE FUNCTION advance_order_stage(p_order_id uuid)
RETURNS orders
LANGUAGE plpgsql AS $$
DECLARE
    v_order     orders%ROWTYPE;
    v_new_stage smallint;
    v_status    order_status;
BEGIN
    -- Kunci baris: dua barista bisa menekan tombol nyaris bersamaan.
    SELECT * INTO v_order FROM orders WHERE id = p_order_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'order % not found', p_order_id USING ERRCODE = 'no_data_found';
    END IF;

    IF v_order.status = 'cancelled' THEN
        RAISE EXCEPTION 'order % is cancelled and cannot be advanced', v_order.order_no
            USING ERRCODE = 'check_violation';
    END IF;
    IF v_order.stage >= 3 THEN
        RAISE EXCEPTION 'order % is already at final stage (3)', v_order.order_no
            USING ERRCODE = 'check_violation';
    END IF;

    v_new_stage := v_order.stage + 1;
    v_status    := CASE WHEN v_new_stage >= 3 THEN 'completed'::order_status
                        ELSE 'active'::order_status END;

    UPDATE orders
    SET stage = v_new_stage,
        status = v_status
    WHERE id = p_order_id
    RETURNING * INTO v_order;   -- trigger notify_order_event() ikut jalan di sini

    RETURN v_order;
END;
$$;

-- =====================================================================
-- 3. redeem_reward()  — STUB (PRD Bagian 4: di luar scope fase ini)
--    Kurangi stamp user, catat ke loyalty_ledger.
--    Dipanggil oleh: Mobile App. Backend POS tidak memanggil ini.
-- =====================================================================
CREATE OR REPLACE FUNCTION redeem_reward(p_user_id uuid, p_reward_id uuid)
RETURNS profiles
LANGUAGE plpgsql AS $$
DECLARE
    v_reward  rewards%ROWTYPE;
    v_profile profiles%ROWTYPE;
BEGIN
    SELECT * INTO v_reward FROM rewards WHERE id = p_reward_id AND active;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'reward % not found or inactive', p_reward_id
            USING ERRCODE = 'no_data_found';
    END IF;

    SELECT * INTO v_profile FROM profiles WHERE id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'profile % not found', p_user_id USING ERRCODE = 'no_data_found';
    END IF;
    IF v_profile.stamps < v_reward.stamps_cost THEN
        RAISE EXCEPTION 'insufficient stamps: have %, need %',
            v_profile.stamps, v_reward.stamps_cost USING ERRCODE = 'check_violation';
    END IF;

    UPDATE profiles SET stamps = stamps - v_reward.stamps_cost
    WHERE id = p_user_id RETURNING * INTO v_profile;

    INSERT INTO loyalty_ledger (user_id, reward_id, delta_stamps, delta_points, reason)
    VALUES (p_user_id, p_reward_id, -v_reward.stamps_cost, 0, 'reward:' || v_reward.name);

    RETURN v_profile;
END;
$$;
