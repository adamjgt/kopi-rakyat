-- =====================================================================
-- seed.sql — Data dummy untuk mirror lokal (pengembangan & test).
--
-- Kompatibel dengan skema ASLI (db/schema.sql). UUID di-hardcode agar test
-- dan dummy POS client merujuk id yang sama. Idempotent.
--
-- ⚠️  JANGAN jalankan pada Supabase asli tim mobile.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Dummy user + profile (di Supabase, auth.users dikelola GoTrue)
-- Trigger on_auth_user_created otomatis membuat baris profiles; upsert di
-- bawah menyetel nilai yang kita inginkan. tier hanya 'Silver' | 'Gold'.
-- ---------------------------------------------------------------------
INSERT INTO auth.users (id, email, phone) VALUES
    ('11111111-1111-1111-1111-111111111111', 'budi@example.test',  '+628110000001'),
    ('22222222-2222-2222-2222-222222222222', 'sarah@example.test', '+628110000002')
ON CONFLICT (id) DO NOTHING;

INSERT INTO profiles (id, full_name, phone, tier, points, stamps) VALUES
    ('11111111-1111-1111-1111-111111111111', 'Budi Santoso', '+628110000001', 'Gold',   1200, 6),
    ('22222222-2222-2222-2222-222222222222', 'Sarah Amelia', '+628110000002', 'Silver',  150, 2)
ON CONFLICT (id) DO UPDATE
    SET full_name = EXCLUDED.full_name, phone = EXCLUDED.phone,
        tier = EXCLUDED.tier, points = EXCLUDED.points, stamps = EXCLUDED.stamps;

-- ---------------------------------------------------------------------
-- Stores (dasar scoping WebSocket & filter order per cabang)
-- map_x / map_y = posisi persen (0..100) pada peta locator placeholder.
-- ---------------------------------------------------------------------
INSERT INTO stores (id, key, name, address, distance_km, is_open, hours_note, map_x, map_y, sort_order) VALUES
    ('aaaaaaaa-0000-0000-0000-000000000001', 'kemang',   'Kopi Rakyat Kemang',
     'Jl. Kemang Raya No. 12, Jakarta Selatan',    1.2, true,  '07:00 - 22:00',    38.0, 62.0, 1),
    ('aaaaaaaa-0000-0000-0000-000000000002', 'sudirman', 'Kopi Rakyat Sudirman',
     'Jl. Jend. Sudirman Kav. 52, Jakarta Pusat',  4.8, true,  '06:30 - 21:00',    52.0, 30.0, 2),
    ('aaaaaaaa-0000-0000-0000-000000000003', 'depok',    'Kopi Rakyat Margonda',
     'Jl. Margonda Raya No. 88, Depok',           12.4, false, 'Tutup sementara',  70.0, 88.0, 3)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- Katalog  (products.kind hanya 'drink' | 'merch')
-- ---------------------------------------------------------------------
INSERT INTO categories (id, key, name, sort_order) VALUES
    ('bbbbbbbb-0000-0000-0000-000000000001', 'signature',  'Signature Coffee', 1),
    ('bbbbbbbb-0000-0000-0000-000000000002', 'non-coffee', 'Non-Coffee',       2),
    ('bbbbbbbb-0000-0000-0000-000000000003', 'merch',      'Merchandise',      3)
ON CONFLICT (id) DO NOTHING;

INSERT INTO products (id, category_id, slug, name, kind, base_price, description, origin, badge, active, sort_order) VALUES
    ('cccccccc-0000-0000-0000-000000000001', 'bbbbbbbb-0000-0000-0000-000000000001',
     'kopi-susu-rakyat', 'Kopi Susu Rakyat', 'drink', 18000,
     'Espresso, susu segar, gula aren', 'Gayo', 'Best Seller', true, 1),
    ('cccccccc-0000-0000-0000-000000000002', 'bbbbbbbb-0000-0000-0000-000000000001',
     'americano', 'Americano', 'drink', 15000, 'Espresso + air', 'Toraja', NULL, true, 2),
    ('cccccccc-0000-0000-0000-000000000003', 'bbbbbbbb-0000-0000-0000-000000000001',
     'caffe-latte', 'Caffe Latte', 'drink', 22000, 'Espresso + steamed milk', 'Blend', NULL, true, 3),
    ('cccccccc-0000-0000-0000-000000000004', 'bbbbbbbb-0000-0000-0000-000000000002',
     'matcha-latte', 'Matcha Latte', 'drink', 25000, 'Matcha premium + susu', 'Uji', 'New', true, 4),
    ('cccccccc-0000-0000-0000-000000000005', 'bbbbbbbb-0000-0000-0000-000000000003',
     'tumbler-rakyat', 'Tumbler Kopi Rakyat', 'merch', 85000,
     'Tumbler stainless 500ml', '', NULL, true, 5),
    ('cccccccc-0000-0000-0000-000000000006', 'bbbbbbbb-0000-0000-0000-000000000003',
     'beans-gayo-200g', 'Biji Kopi Gayo 200g', 'merch', 95000,
     'Roasted beans, sedang', 'Gayo', NULL, false, 6)
ON CONFLICT (id) DO NOTHING;

-- Opsi kustomisasi (katalog untuk mobile app; harga dihitung klien).
INSERT INTO option_groups (id, key, label, sort_order) VALUES
    ('d0000000-0000-0000-0000-000000000001', 'size',  'Ukuran',   1),
    ('d0000000-0000-0000-0000-000000000002', 'milk',  'Jenis Susu', 2),
    ('d0000000-0000-0000-0000-000000000003', 'ice',   'Es',       3),
    ('d0000000-0000-0000-0000-000000000004', 'sugar', 'Gula',     4)
ON CONFLICT (id) DO NOTHING;

INSERT INTO option_values (group_id, key, sub_label, price_delta, sort_order) VALUES
    ('d0000000-0000-0000-0000-000000000001', 'R',        'Regular',    0, 1),
    ('d0000000-0000-0000-0000-000000000001', 'M',        'Medium',  3000, 2),
    ('d0000000-0000-0000-0000-000000000001', 'L',        'Large',   6000, 3),
    ('d0000000-0000-0000-0000-000000000002', 'fresh',    'Susu Segar', 0, 1),
    ('d0000000-0000-0000-0000-000000000002', 'oat',      'Oat Milk',  6000, 2),
    ('d0000000-0000-0000-0000-000000000003', 'normal',   'Normal',     0, 1),
    ('d0000000-0000-0000-0000-000000000003', 'less_ice', 'Sedikit Es', 0, 2),
    ('d0000000-0000-0000-0000-000000000004', '100%',     'Normal',     0, 1),
    ('d0000000-0000-0000-0000-000000000004', '50%',      'Sedikit',    0, 2)
ON CONFLICT (group_id, key) DO NOTHING;

-- ---------------------------------------------------------------------
-- Alamat delivery (mode delivery)
-- ---------------------------------------------------------------------
INSERT INTO addresses (id, user_id, label, recipient, line1, city, is_default) VALUES
    ('eeeeeeee-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111',
     'Rumah', 'Budi Santoso', 'Jl. Bangka Raya No. 5', 'Jakarta Selatan', true)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- Voucher & reward (di luar scope backend POS — struktur untuk kelengkapan)
-- ---------------------------------------------------------------------
INSERT INTO vouchers (id, code, title, note, discount_type, discount_value, scope, valid_until, active) VALUES
    ('f0000000-0000-0000-0000-000000000001', 'KOPI10', 'Diskon 10%', 'Maks. Rp 10.000',
     'percent', 10, 'cart', DATE '2027-12-31', true),
    ('f0000000-0000-0000-0000-000000000002', 'HEMAT5K', 'Potongan Rp 5.000', '',
     'fixed', 5000, 'cart', DATE '2027-12-31', true)
ON CONFLICT (id) DO NOTHING;

INSERT INTO rewards (id, name, stamps_cost, active, sort_order) VALUES
    ('f1000000-0000-0000-0000-000000000001', 'Gratis Kopi Susu Rakyat', 8, true, 1),
    ('f1000000-0000-0000-0000-000000000002', 'Gratis Tumbler',         10, true, 2)
ON CONFLICT (id) DO NOTHING;
