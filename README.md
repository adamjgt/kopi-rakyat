# Kopi Rakyat — Backend POS Integration Service

Lapisan integrasi realtime antara **database online-ordering** (skema milik tim
mobile) dan **aplikasi POS barista**, sesuai PRD v2.0 — fase Proof of Concept.

Backend ini **tidak mendesain ulang skema data** dan **tidak menduplikasi
business logic**. Perannya:

| Yang dilakukan | Yang TIDAK dilakukan |
|---|---|
| Mendeteksi order baru & perubahan stage dari tabel `orders` | Membuat model data sendiri |
| Broadcast realtime ke POS, di-scope per `store_id` | `INSERT`/`UPDATE` manual ke `orders`/`order_items` |
| Memanggil RPC `advance_order_stage()` atas nama POS | Menghitung harga, nomor order, atau loyalty |
| Menyediakan REST read-only untuk antrian & detail order | Melayani aplikasi mobile (mobile langsung ke Supabase) |

```
[Mobile App / Dummy Simulator]
        |  place_order()  (RPC)
        v
[PostgreSQL / Supabase]  ──trigger──> NOTIFY 'pos_order_events'
        ^                                     |
        |  advance_order_stage() (RPC)        v
[Backend POS Integration (FastAPI)] ──WS scoped per store_id──> [Dummy POS Client]
```

---

## 1. Quick Start

### 1.1 Jalankan PostgreSQL lokal

```bash
docker compose up -d
```

Skema, RPC, dan data dummy di-apply otomatis saat container pertama kali dibuat
(urutan: `schema.sql` → `functions.sql` → `seed.sql`). Postgres listen di
**host port 5433** agar tidak bentrok dengan instalasi lain.

<details>
<summary>Tidak punya Docker? Pakai PostgreSQL yang sudah ada.</summary>

Buat database kosong, set `DATABASE_URL` di `.env`, lalu:

```bash
python scripts/init_db.py            # schema + functions + seed
python scripts/init_db.py --no-seed  # tanpa data dummy
python scripts/init_db.py --drop     # ⚠ hapus objek POC lalu apply ulang
```
</details>

### 1.2 Siapkan environment Python

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows   (source .venv/bin/activate di *nix)
pip install -r requirements.txt
copy .env.example .env          # cp di *nix
```

### 1.3 Jalankan backend

```bash
uvicorn app.main:app --reload
```

| URL | Isi |
|---|---|
| <http://localhost:8000/pos/> | **Dummy POS test interface** |
| <http://localhost:8000/docs> | Swagger UI |
| <http://localhost:8000/api/health> | Health check |

### 1.4 Buka dummy POS, lalu kirim order dummy

Buka <http://localhost:8000/pos/>, pilih store **Kopi Rakyat Kemang**, lalu di
terminal lain:

```bash
python simulator/mobile_simulator.py --count 3 --store kemang
```

Order muncul di POS **tanpa refresh manual**. Klik tombol `→ diracik` untuk
memajukan stage; semua tab POS yang terbuka pada store yang sama ikut berubah.

---

## 2. Struktur Proyek

```
kopi rakyat/
├─ app/
│  ├─ main.py                 # entry point FastAPI, lifespan, CORS, health
│  ├─ config.py               # semua setting via env var / .env
│  ├─ db.py                   # asyncpg pool
│  ├─ repository.py           # query BACA (dipakai router + listener)
│  ├─ rpc/
│  │  ├─ place_order.py       # wrapper SELECT * FROM place_order(...)
│  │  ├─ advance_stage.py     # wrapper SELECT * FROM advance_order_stage(...)
│  │  └─ errors.py            # SQLSTATE -> HTTP status
│  ├─ routers/
│  │  ├─ stores.py  orders.py  ws.py
│  │  └─ dev_simulate.py      # ⚠ POC only
│  ├─ realtime/
│  │  ├─ listener.py          # LISTEN/NOTIFY + fallback polling
│  │  └─ ws_manager.py        # connection manager per store_id
│  └─ schemas/                # Pydantic request/response/event
├─ db/
│  ├─ schema.sql              # DDL seluruh tabel Bagian 8 + trigger realtime
│  ├─ functions.sql           # place_order, advance_order_stage, redeem_reward
│  └─ seed.sql                # store/produk/user dummy (UUID hardcoded)
├─ simulator/mobile_simulator.py
├─ pos_dummy_client/index.html
├─ scripts/init_db.py
├─ tests/
├─ docker-compose.yml  requirements.txt  .env.example  pytest.ini
```

`repository.py` adalah satu-satunya tambahan di luar struktur PRD Bagian 12.
Alasannya: router REST dan listener realtime harus menghasilkan bentuk data
yang **persis sama**, jadi query bacanya dipusatkan di satu tempat.

---

## 3. Konfigurasi

Semua lewat environment variable (lihat `.env.example`):

| Variable | Default | Keterangan |
|---|---|---|
| `DATABASE_URL` | `postgresql://kopi:kopi@localhost:5433/kopi_rakyat` | **Satu-satunya yang perlu diganti saat pindah ke Supabase asli.** |
| `REALTIME_MODE` | `notify` | `notify` = LISTEN/NOTIFY, `poll` = fallback polling |
| `REALTIME_CHANNEL` | `pos_order_events` | Channel NOTIFY |
| `POLL_INTERVAL_SECONDS` | `1.0` | Interval polling (mode `poll`) |
| `ENABLE_DEV_ENDPOINTS` | `true` | `false` → `/api/dev/*` tidak didaftarkan sama sekali |
| `CORS_ORIGINS` | `*` | Dipisah koma untuk membatasi origin |
| `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE` | `1` / `10` | Ukuran pool asyncpg |
| `LOG_LEVEL` | `INFO` | |

---

## 4. API

### 4.1 REST

| Method | Endpoint | Keterangan |
|---|---|---|
| `GET` | `/api/stores` | Daftar cabang |
| `GET` | `/api/stores/{store_id}` | Detail satu cabang |
| `GET` | `/api/orders?store_id=&status=&stage=&fulfilment_mode=&limit=&offset=` | Antrian order + `order_items` |
| `GET` | `/api/orders/{order_id}` | Detail satu order |
| `PATCH` | `/api/orders/{order_id}/advance` | Majukan stage (→ `advance_order_stage()`) |
| `POST` | `/api/dev/simulate-order` | **POC only** — teruskan ke `place_order()` |
| `GET` | `/api/health` | Health check |

`store_id` pada `GET /api/orders` **wajib** — itulah yang menegakkan Store
Isolation di sisi REST. Tanpa parameter tersebut request ditolak `422`, bukan
mengembalikan order semua cabang.

Kode status error: `404` order/store/produk tidak ada · `409` ditolak aturan
bisnis RPC (toko tutup, produk nonaktif, stage sudah final) · `422` payload
tidak valid · `501` RPC belum ada di database.

> **Catatan format:** kolom uang (`subtotal`, `total`, `unit_price`, …) bertipe
> `numeric` dan diserialisasi Pydantic sebagai **string JSON** (mis. `"46000.00"`)
> supaya presisi tidak hilang. Klien perlu `Number(...)` / `float(...)`.

### 4.2 WebSocket — `/ws/pos/{store_id}`

| Event | Kapan | Payload |
|---|---|---|
| `pos.connected` | tepat setelah connect | `{store_id, store_key, store_name, is_open, clients}` |
| `order.created` | order baru dari `place_order()` | `{order: {...}, items: [...]}` |
| `order.stage_updated` | stage/status berubah | `{order_id, stage, status, updated_at}` |
| `pong` | balasan `"ping"` dari klien | `{}` |
| `error` | `store_id` tidak valid/tidak ada, lalu socket ditutup | `{message}` |

`order.created` sudah membawa `order_items` lengkap — POS tidak perlu request
kedua. Kirim `"ping"` sesekali sebagai keepalive (dummy client: tiap 25 detik).

`order.stage_updated` **selalu** dikirim oleh listener, bukan oleh endpoint
`PATCH`. Konsekuensinya: perubahan stage yang dilakukan langsung lewat SQL
(saat debugging) juga tetap sampai ke POS, dan tidak ada event ganda.

---

## 5. Memanggil RPC Langsung dari SQL (debugging manual)

Ketiga RPC bisa dipanggil tanpa lewat backend. Masuk ke psql:

```bash
docker compose exec postgres psql -U kopi -d kopi_rakyat
```

### `place_order()` — buat order + items, set paid, tambah stamp & poin

```sql
SELECT * FROM place_order(
    p_user_id         := '11111111-1111-1111-1111-111111111111',
    p_store_id        := 'aaaaaaaa-0000-0000-0000-000000000001',
    p_fulfilment_mode := 'pickup',
    p_payment_method  := 'qris',
    p_items           := '[{"product_id":"cccccccc-0000-0000-0000-000000000001",
                            "qty":2,"size":"M","milk":"oat","ice":"less_ice",
                            "sugar":"50%","extra_shot":false,
                            "note":"less sugar please"}]'::jsonb,
    p_voucher_code    := NULL,
    p_table_number    := NULL,
    p_scheduled_for   := NULL,
    p_address_id      := NULL
);
```

Signature lengkap:
`place_order(p_user_id uuid, p_store_id uuid, p_fulfilment_mode fulfilment_mode,
p_payment_method payment_method, p_items jsonb, p_voucher_code text DEFAULT NULL,
p_table_number text DEFAULT NULL, p_scheduled_for timestamptz DEFAULT NULL,
p_address_id uuid DEFAULT NULL) RETURNS orders`

### `advance_order_stage()` — naikkan stage 0→1→2→3

```sql
SELECT * FROM advance_order_stage('<order-uuid>');

-- order terbaru yang belum selesai, untuk dicoba:
SELECT id, order_no, stage, status FROM orders
WHERE stage < 3 ORDER BY created_at DESC LIMIT 5;
```

Menolak dengan exception bila order sudah `stage = 3` atau `status = 'cancelled'`.

### `redeem_reward()` — di luar scope backend POS (dipanggil mobile app)

```sql
SELECT * FROM redeem_reward(
    '11111111-1111-1111-1111-111111111111',
    'ffffffff-1111-0000-0000-000000000001'
);
```

### Memeriksa jalur realtime tanpa backend

```sql
LISTEN pos_order_events;
-- jalankan place_order() di sesi psql lain, lalu tekan Enter di sesi ini.
```

---

## 6. Dummy Mobile Simulator

Berperan sebagai aplikasi mobile yang belum jadi (PRD 7.5).

```bash
python simulator/mobile_simulator.py                        # 1 order acak
python simulator/mobile_simulator.py --count 5 --interval 2
python simulator/mobile_simulator.py --store sudirman --mode dine_in
python simulator/mobile_simulator.py --watch                # pantau sampai stage 3
python simulator/mobile_simulator.py --list-stores
python simulator/mobile_simulator.py --seed 7               # hasil reproducible
```

`--watch` mem-polling `GET /api/orders/{id}` dan mencetak setiap perubahan
stage — inilah verifikasi bahwa update dari POS benar-benar tersimpan di
database, bukan sekadar berubah di layar POS.

Simulator memakai id produk dari `db/seed.sql`. Backend sengaja tidak
menyediakan endpoint katalog karena manajemen katalog di luar scope (PRD 4).

---

## 7. Dummy POS Test Interface

`http://localhost:8000/pos/` — halaman statis satu file, disajikan langsung
oleh backend (tidak perlu web server terpisah).

Fitur: pemilih store · antrian realtime · detail item lengkap dengan
size/milk/ice/sugar/note · `pickup_code` besar untuk mode pickup · nomor meja
untuk dine-in · tombol advance stage · filter per stage · log event · indikator
koneksi dengan auto-reconnect (exponential backoff).

Untuk menguji **store isolation**: buka dua tab, pilih store berbeda, lalu
kirim order ke salah satunya. Hanya tab yang cocok yang bereaksi.

---

## 8. Asumsi Eksplisit

> Bagian ini memenuhi PRD Bagian 7.2, 15, dan Acceptance Criteria terakhir.
> **Semua di bawah ini adalah tebakan wajar yang perlu dikonfirmasi tim mobile.**
> Semuanya terisolasi di `db/schema.sql` + `db/functions.sql` — mengoreksinya
> tidak menyentuh kode Python.

### 8.1 Nilai `stage` (0–3)

| stage | Arti yang diasumsikan |
|---|---|
| `0` | Order diterima / masuk antrian |
| `1` | Sedang diproses / diracik barista |
| `2` | Siap diambil (pickup) / siap dikirim (delivery) / diantar ke meja |
| `3` | Selesai / diterima customer |

Bagaimana stage 2 dan 3 dibedakan antar `fulfilment_mode` **belum
didefinisikan** — implementasi saat ini memperlakukan ketiganya sama.

### 8.2 Nilai `status`

Enum: `pending`, `paid`, `active`, `completed`, `cancelled`. Merepresentasikan
siklus hidup order, independen dari progres dapur. Pemetaan yang dipakai
`advance_order_stage()`:

| stage baru | status |
|---|---|
| 1, 2 | `active` |
| 3 | `completed` |

`place_order()` menghasilkan `status = 'paid'`, `payment_status = 'paid'`,
`stage = 0`. **Asumsi:** pembayaran dianggap sudah berhasil saat order dibuat
(model prepaid seperti Kopi Kenangan); belum ada integrasi payment gateway.

`cancelled` tidak pernah di-set oleh backend ini — belum ada RPC pembatalan
dalam kontrak tim mobile.

### 8.3 Nilai `fulfilment_mode`

Enum: `pickup`, `dine_in`, `delivery`. Aturan yang diasumsikan:

- `pickup` → `pickup_code` di-generate (format `A000`: huruf + 3 digit, nomor
  antrian **per toko per hari**). Mode lain `pickup_code = NULL`.
- `dine_in` → `table_number` wajib.
- `delivery` → `address_id` wajib, `delivery_fee` **flat Rp 10.000**
  (angka karangan — belum ada aturan ongkir resmi).

### 8.4 Format `items` (jsonb) pada `place_order()`

Array objek; per elemen: `product_id` (uuid, wajib), `qty` (int, default 1),
`size`, `milk`, `ice`, `sugar` (text, opsional), `extra_shot` (bool, default
false), `note` (text, opsional).

Harga dihitung `products.base_price + Σ option_values.price_delta`, dicocokkan
lewat `option_groups.key` → `option_values.key`. Boolean `extra_shot: true`
dipetakan ke `option_values.key = 'yes'` dalam group `extra_shot`.
**Opsi yang tidak dikenal diperlakukan sebagai delta 0, bukan error**, supaya
simulator POC tidak mudah gagal — tim mobile mungkin ingin ini lebih ketat.

### 8.5 Loyalitas (efek samping `place_order()`)

1 stamp per cup minuman (`products.kind = 'drink'`), 1 poin per Rp 1.000 dari
total akhir, dicatat ke `loyalty_ledger`. Aturan tier tidak diimplementasikan.

### 8.6 Voucher

Voucher tidak valid/kedaluwarsa → `place_order()` **gagal** (bukan diabaikan
diam-diam), supaya customer tidak salah paham soal harga. Diskon dibatasi
maksimal sebesar subtotal. Klaim voucher (`user_vouchers`) tidak dipakai —
di luar scope.

### 8.7 Penomoran order

`order_no` = `ORD-YYYYMMDD-NNNN` dengan counter **global harian** (tabel
`order_no_counters`), karena `orders.order_no` UNIQUE lintas toko. Nomor
antrian `pickup_code` memakai counter terpisah **per toko per hari**
(`store_queue_counters`). Kedua tabel counter ini tambahan kami, bukan bagian
skema tim mobile.

### 8.8 Objek tambahan di luar skema Bagian 8

Diizinkan PRD Bagian 15 ("boleh menambah index/trigger pendukung realtime"):

- trigger `trg_orders_notify_insert` / `trg_orders_notify_update` +
  fungsi `notify_order_event()` — sumber event realtime;
- trigger `trg_orders_touch` / `trg_profiles_touch` — mengisi `updated_at`;
- index `idx_orders_store_created`, `idx_orders_store_stage`, `idx_orders_store_status`;
- tabel counter pada 8.7.

**Hanya trigger notify yang tetap dibutuhkan di Supabase asli**, dan hanya bila
`REALTIME_MODE=notify`. Dengan `REALTIME_MODE=poll`, backend berjalan tanpa
menambah objek apa pun ke database tim mobile.

### 8.9 Skema `auth` lokal

`db/schema.sql` membuat `auth.users` minimal agar FK tidak error. Di Supabase
asli tabel ini sudah dikelola GoTrue — **jangan apply `schema.sql` ke sana.**

---

## 9. Testing

```bash
pytest              # semua test
pytest -m db        # hanya yang butuh database
pytest -m "not db"  # hanya unit test murni
```

Test yang butuh database **otomatis di-skip** (bukan gagal) bila PostgreSQL
tidak terjangkau, jadi `pytest` tetap hijau sebelum `docker compose up`.

| File | Cakupan |
|---|---|
| `tests/test_rpc.py` | `place_order()` & `advance_order_stage()`: harga dari base_price + option delta, snapshot opsi, pickup_code, delivery fee, voucher, urutan stage 0→1→2→3, pemetaan status, penolakan produk nonaktif / toko tutup / stage final, persistensi |
| `tests/test_orders_api.py` | Store isolation, filter `status`/`stage`/`fulfilment_mode`, join `order_items`, urutan & limit, health, stores |
| `tests/test_ws_manager.py` | Store isolation di lapisan WebSocket, pembuangan koneksi mati |
| `tests/test_schemas.py` | Validasi payload PRD 9.3, bentuk event PRD 9.5/9.6 |

### Hasil verifikasi

Diverifikasi terhadap PostgreSQL sungguhan (bukan mock): **54 test lulus**.
Alur end-to-end diuji pada kedua mode realtime — order dari simulator sampai ke
POS, advance stage ter-broadcast balik, POS store lain tidak menerima apa pun:

| Mode | `order.created` | `order.stage_updated` |
|---|---|---|
| `notify` | 93 ms | 32 ms |
| `poll` (interval 0.5 s) | 328 ms | 484 ms |

Keduanya jauh di bawah target < 2 detik (PRD Bagian 11).

> Catatan: verifikasi dilakukan pada PostgreSQL 12; target proyek adalah
> PostgreSQL 15+/Supabase. Tidak ada fitur versi-spesifik yang dipakai —
> `gen_random_uuid()` diambil dari extension `pgcrypto` agar kompatibel ke bawah.

---

## 10. Checklist Acceptance Criteria (PRD Bagian 14)

- [x] Order dari simulator langsung muncul di dummy POS store yang sesuai, tanpa refresh manual
- [x] POS satu store tidak menerima notifikasi order store lain
- [x] Tombol advance stage memanggil `advance_order_stage()` dan hasilnya ter-broadcast ke semua POS store tersebut
- [x] `order_items` yang tampil sesuai snapshot tersimpan (size, milk, ice, sugar, note, qty, line_total)
- [x] Data konsisten setelah backend restart (tidak ada state di memori)
- [x] Cara pemanggilan RPC terdokumentasi, termasuk contoh SQL langsung (Bagian 5)
- [x] Asumsi skema dinyatakan eksplisit (Bagian 8)

---

## 11. Migrasi ke Supabase Asli

1. Ganti `DATABASE_URL` di `.env` dengan connection string Supabase
   (Dashboard → Project Settings → Database → URI, mode *Session*).
   **Tidak ada perubahan kode.**
2. **Jangan** apply `db/schema.sql` atau `db/seed.sql` ke sana.
3. Pilih salah satu jalur realtime:
   - minta tim mobile memasang trigger `notify_order_event()` dari bagian
     *REALTIME SUPPORT* di `db/schema.sql`, lalu pakai `REALTIME_MODE=notify`; atau
   - set `REALTIME_MODE=poll` — tidak perlu menambah objek apa pun.
4. Set `ENABLE_DEV_ENDPOINTS=false` — mobile app memanggil `place_order()`
   langsung ke Supabase, tidak lewat backend ini.
5. Batasi `CORS_ORIGINS` ke origin POS yang sebenarnya.
6. Bandingkan `db/functions.sql` dengan RPC resmi tim mobile. Selama
   **signature dan tipe return sama**, kode Python tidak perlu berubah.

### Yang perlu dikonfirmasi ke tim mobile

1. Definisi resmi enum `status` dan makna `stage` per `fulfilment_mode` (8.1–8.3).
2. Signature persis `place_order()` — urutan & nama parameter (`app/rpc/place_order.py` mengikat urutan ini).
3. Format `items` jsonb, terutama penanganan opsi tak dikenal (8.4).
4. Aturan ongkir, voucher, dan loyalty yang sebenarnya (8.5–8.6).
5. Boleh/tidaknya memasang trigger NOTIFY di database mereka (8.8).

---

## 12. Di Luar Scope Fase Ini

Aplikasi mobile · UI POS production · autentikasi end-user · autentikasi antara
backend dan database · `redeem_reward()` penuh (stub saja) · klaim voucher ·
CRUD katalog produk · pembatalan order · push notification · deployment skala
besar.
