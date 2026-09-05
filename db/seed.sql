-- =====================================================================
-- seed.sql — Data dummy untuk fase POC.
--
-- UUID sengaja di-hardcode agar simulator, test, dan dummy POS client bisa
-- merujuk id yang sama tanpa lookup. Idempotent (ON CONFLICT DO NOTHING /
-- DO UPDATE), aman dijalankan berulang.
--
-- Jangan jalankan file ini pada database Supabase asli milik tim mobile.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Dummy user (menggantikan autentikasi end-user penuh — PRD Bagian 4)
-- ---------------------------------------------------------------------
INSERT INTO auth.users (id, email, phone) VALUES
    ('11111111-1111-1111-1111-111111111111', 'budi@example.test',  '+628110000001'),
    ('22222222-2222-2222-2222-222222222222', 'sarah@example.test', '+628110000002')
ON CONFLICT (id) DO NOTHING;

INSERT INTO profiles (id, full_name, phone, tier, points, stamps) VALUES
    ('11111111-1111-1111-1111-111111111111', 'Budi Santoso',  '+628110000001', 'silver', 1200, 4),
    ('22222222-2222-2222-2222-222222222222', 'Sarah Amelia', '+628110000002', 'bronze',  150, 1)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- Stores (dasar scoping WebSocket & filter order per cabang)
-- ---------------------------------------------------------------------
INSERT INTO stores (id, key, name, address, distance_km, is_open, hours_note, map_x, map_y) VALUES
    ('aaaaaaaa-0000-0000-0000-000000000001', 'kemang',   'Kopi Rakyat Kemang',
     'Jl. Kemang Raya No. 12, Jakarta Selatan',   1.20, true, '07:00 - 22:00', 106.813, -6.260),
    ('aaaaaaaa-0000-0000-0000-000000000002', 'sudirman', 'Kopi Rakyat Sudirman',
     'Jl. Jend. Sudirman Kav. 52, Jakarta Pusat', 4.80, true, '06:30 - 21:00', 106.808, -6.224),
    ('aaaaaaaa-0000-0000-0000-000000000003', 'depok',    'Kopi Rakyat Margonda',
     'Jl. Margonda Raya No. 88, Depok',          12.40, false, 'Tutup sementara', 106.831, -6.379)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- Katalog
-- ---------------------------------------------------------------------
INSERT INTO categories (id, key, name, sort_order) VALUES
    ('bbbbbbbb-0000-0000-0000-000000000001', 'signature', 'Signature Coffee', 1),
    ('bbbbbbbb-0000-0000-0000-000000000002', 'non-coffee', 'Non-Coffee',      2),
    ('bbbbbbbb-0000-0000-0000-000000000003', 'snack',     'Snack',            3)
ON CONFLICT (id) DO NOTHING;

INSERT INTO products (id, category_id, slug, name, kind, base_price, description, origin, badge, active) VALUES
    ('cccccccc-0000-0000-0000-000000000001', 'bbbbbbbb-0000-0000-0000-000000000001',
     'kopi-susu-rakyat', 'Kopi Susu Rakyat', 'drink', 18000,
     'Espresso, susu segar, gula aren', 'Gayo', 'Best Seller', true),
    ('cccccccc-0000-0000-0000-000000000002', 'bbbbbbbb-0000-0000-0000-000000000001',
     'americano', 'Americano', 'drink', 15000,
     'Espresso + air', 'Toraja', NULL, true),
    ('cccccccc-0000-0000-0000-000000000003', 'bbbbbbbb-0000-0000-0000-000000000001',
     'caffe-latte', 'Caffe Latte', 'drink', 22000,
     'Espresso + steamed milk', 'Blend', NULL, true),
    ('cccccccc-0000-0000-0000-000000000004', 'bbbbbbbb-0000-0000-0000-000000000002',
     'matcha-latte', 'Matcha Latte', 'drink', 25000,
     'Matcha premium + susu', 'Uji', 'New', true),
    ('cccccccc-0000-0000-0000-000000000005', 'bbbbbbbb-0000-0000-0000-000000000003',
     'croissant-butter', 'Butter Croissant', 'food', 20000,
     'Croissant mentega, dipanggang harian', NULL, NULL, true),
    ('cccccccc-0000-0000-0000-000000000006', 'bbbbbbbb-0000-0000-0000-000000000002',
     'es-teh-manis', 'Es Teh Manis', 'drink', 10000,
     'Teh melati manis dingin', NULL, NULL, false)   -- sengaja inactive: untuk uji error path
ON CONFLICT (id) DO NOTHING;

INSERT INTO option_groups (id, key, label, sort_order) VALUES
    ('dddddddd-0000-0000-0000-000000000001', 'size',       'Ukuran',      1),
    ('dddddddd-0000-0000-0000-000000000002', 'milk',       'Jenis Susu',  2),
    ('dddddddd-0000-0000-0000-000000000003', 'ice',        'Level Es',    3),
    ('dddddddd-0000-0000-0000-000000000004', 'sugar',      'Level Gula',  4),
    ('dddddddd-0000-0000-0000-000000000005', 'extra_shot', 'Extra Shot',  5)
ON CONFLICT (id) DO NOTHING;

INSERT INTO option_values (group_id, key, sub_label, price_delta, sort_order) VALUES
    ('dddddddd-0000-0000-0000-000000000001', 'S',        'Small (12oz)',   -3000, 1),
    ('dddddddd-0000-0000-0000-000000000001', 'M',        'Medium (16oz)',      0, 2),
    ('dddddddd-0000-0000-0000-000000000001', 'L',        'Large (22oz)',    5000, 3),
    ('dddddddd-0000-0000-0000-000000000002', 'fresh',    'Susu Segar',         0, 1),
    ('dddddddd-0000-0000-0000-000000000002', 'oat',      'Oat Milk',        5000, 2),
    ('dddddddd-0000-0000-0000-000000000002', 'almond',   'Almond Milk',     6000, 3),
    ('dddddddd-0000-0000-0000-000000000002', 'none',     'Tanpa Susu',         0, 4),
    ('dddddddd-0000-0000-0000-000000000003', 'no_ice',   'Tanpa Es',           0, 1),
    ('dddddddd-0000-0000-0000-000000000003', 'less_ice', 'Sedikit Es',         0, 2),
    ('dddddddd-0000-0000-0000-000000000003', 'normal',   'Es Normal',          0, 3),
    ('dddddddd-0000-0000-0000-000000000004', '0%',       'Tanpa Gula',         0, 1),
    ('dddddddd-0000-0000-0000-000000000004', '50%',      'Setengah',           0, 2),
    ('dddddddd-0000-0000-0000-000000000004', '100%',     'Normal',             0, 3),
    ('dddddddd-0000-0000-0000-000000000005', 'yes',      'Tambah 1 Shot',   8000, 1)
ON CONFLICT (group_id, key) DO UPDATE SET price_delta = EXCLUDED.price_delta;

-- ---------------------------------------------------------------------
-- Alamat (hanya dipakai bila fulfilment_mode = delivery)
-- ---------------------------------------------------------------------
INSERT INTO addresses (id, user_id, label, recipient, line1, city, is_default) VALUES
    ('eeeeeeee-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111',
     'Rumah', 'Budi Santoso', 'Jl. Bangka IX No. 4', 'Jakarta Selatan', true)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- Promo & rewards (struktur saja — di luar scope, PRD Bagian 15)
-- ---------------------------------------------------------------------
INSERT INTO vouchers (id, code, title, discount_type, discount_value, scope, valid_until, active) VALUES
    ('ffffffff-0000-0000-0000-000000000001', 'HEMAT5K',  'Potongan Rp 5.000', 'fixed',    5000, 'all', NULL, true),
    ('ffffffff-0000-0000-0000-000000000002', 'DISKON20', 'Diskon 20%',        'percent',    20, 'all', NULL, true)
ON CONFLICT (id) DO NOTHING;

INSERT INTO rewards (id, name, stamps_cost, active, sort_order) VALUES
    ('ffffffff-1111-0000-0000-000000000001', 'Free Kopi Susu Rakyat', 8, true, 1)
ON CONFLICT (id) DO NOTHING;
