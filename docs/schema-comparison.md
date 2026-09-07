# Laporan Perbandingan Skema — Asli (Supabase) vs. Backend Lama

Task 1: membandingkan skema **asli tim mobile**
(`supabase/migrations/20260901000000_init.sql` di repo `kopi-rakyat-mobileapp`)
dengan `db/schema.sql` & `db/functions.sql` versi lama backend (yang berbasis
asumsi PRD). Backend-lah yang menyesuaikan — skema asli **tidak** diubah.

**Ringkasan:** skema lama backend dibangun dari tebakan dan berbeda cukup dalam.
Semua tabel `db/schema.sql` dan `db/functions.sql` sekarang sudah diganti menjadi
**salinan setia skema asli** (mirror lokal untuk dev/test). Perubahan kode Python
menyesuaikan `app/schemas/` dan `app/rpc/` (Task 2).

Legenda: 🔴 breaking (memengaruhi kode) · 🟡 beda tapi tak breaking · 🟢 sama.

---

## 1. Tipe / Enum

| Aspek | Asli (Supabase) | Backend lama | Dampak |
|---|---|---|---|
| Strategi tipe | **`text` + `CHECK`** untuk semua status/mode | **`ENUM` PostgreSQL** (`fulfilment_mode`, `order_status`, `payment_status`, `payment_method`, `discount_type`, `user_tier`) | 🔴 Wrapper RPC lama meng-cast `$3::fulfilment_mode`, `$4::payment_method` — tipe itu **tidak ada** di DB asli → error. Sudah diganti ke `::text`. |

Tidak ada satu pun `CREATE TYPE` di skema asli.

---

## 2. Tabel `orders` (inti integrasi POS)

| Kolom | Asli | Backend lama | Dampak |
|---|---|---|---|
| `status` | `text` CHECK **`received` / `preparing` / `on_the_way` / `ready` / `completed`**, default `received` | enum `pending`/`paid`/`active`/`completed`/`cancelled`, default `pending` | 🔴 Nilai status sepenuhnya berbeda. |
| `stage` | `integer`, default 0 (tanpa batas atas) | `smallint` CHECK `0..3` | 🟡 Sama makna; batas atas Pydantic `le=3` dilepas. |
| `fulfilment_mode` | CHECK `delivery`/`pickup`/`dine_in`/**`pre_order`** | enum `pickup`/`dine_in`/`delivery` (tanpa `pre_order`) | 🔴 `pre_order` ditambahkan ke schema Python. |
| `payment_method` | `text` **NOT NULL** (bebas) | enum `qris`/`gopay`/`ovo`/`card`/`cash`/`balance`, nullable | 🔴 Jadi `str` bebas (bukan enum). |
| `payment_status` | `text` CHECK `pending`/`paid`/`failed`, default `pending` | enum `unpaid`/`paid`/`refunded`/`failed`, default `unpaid` | 🔴 Nilai berbeda (mis. `pending` bukan `unpaid`). |
| `payment_provider` | **ADA** — `text NOT NULL DEFAULT 'simulated'` | **TIDAK ADA** | 🔴 Ditambahkan ke `Order` + query repository. |
| `paid_at` | **ADA** — `timestamptz` | **TIDAK ADA** | 🔴 Ditambahkan. |
| `updated_at` | **TIDAK ADA** | `timestamptz NOT NULL` + trigger `touch_updated_at` | 🔴 Dihapus dari query & schema; poll & trigger notify tak boleh mengandalkannya. |
| `subtotal`/`discount`/`delivery_fee`/`total` | **`integer`** (rupiah bulat) | `numeric(12,2)` | 🔴 Money jadi `int`; serialisasi JSON = angka biasa (bukan string). |
| `store_id` | `uuid` REFERENCES stores **(nullable)** | `uuid NOT NULL` REFERENCES stores | 🟡 Asli membolehkan NULL. |
| `order_no` | `text UNIQUE`, format **`#KR-4471`** (`nextval(order_no_seq)`) | `text UNIQUE`, format `ORD-YYYYMMDD-NNNN` (tabel counter harian) | 🟡 Format berbeda; regex test disesuaikan. |
| `pickup_code` | selalu di-generate `X-99` | hanya untuk mode pickup, format `A000` | 🟡 Asli tak bergantung mode. |

Kolom yang **sama** (🟢): `id`, `order_no` (UNIQUE), `user_id`, `table_number`,
`address_id`, `scheduled_for`, `voucher_code`, `created_at`.

---

## 3. Tabel `order_items`

| Kolom | Asli | Backend lama | Dampak |
|---|---|---|---|
| `unit_price` / `line_total` | **`integer`** | `numeric(12,2)` | 🔴 Money jadi `int`. |
| `qty` | `integer` default 1 (tanpa CHECK) | `integer` CHECK `> 0` | 🟢 |
| `product_id` | nullable | nullable | 🟢 |

Kolom lain (`name_snapshot`, `size`, `milk`, `ice`, `sugar`, `extra_shot`,
`note`) 🟢 sama.

---

## 4. Tabel `stores`

| Kolom | Asli | Backend lama | Dampak |
|---|---|---|---|
| `address` | `text NOT NULL` | nullable | 🟡 |
| `hours_note` | `text NOT NULL` | nullable | 🟡 |
| `map_x` / `map_y` | `numeric(4,1) **NOT NULL**` (posisi persen) | `numeric(8,3)` nullable | 🔴 Presisi & nullability beda; seed harus mengisi. |
| `distance_km` | `numeric(4,1)` | `numeric(6,2)` | 🟡 |
| `sort_order` | **ADA** `integer` | **TIDAK ADA** | 🟡 Ditambahkan ke schema `Store`. |
| `created_at` | **TIDAK ADA** | `timestamptz` | 🔴 Dihapus dari schema `Store`. |

---

## 5. Tabel `products`

| Kolom | Asli | Backend lama | Dampak |
|---|---|---|---|
| `kind` | `text` CHECK **`drink` / `merch` saja** | `text` bebas (komentar `drink`/`food`/`bean`) | 🔴 Seed `food`/`bean` melanggar CHECK; seed baru pakai `merch`. |
| `base_price` | **`integer`** | `numeric(12,2)` | 🔴 |
| `description` / `origin` | `text NOT NULL DEFAULT ''` | nullable | 🟡 |
| `sort_order` | **ADA** | **TIDAK ADA** | 🟡 |

`option_values.price_delta`: asli `integer`, lama `numeric` 🔴. Sisanya 🟢.

---

## 6. Tabel `profiles`

| Kolom | Asli | Backend lama | Dampak |
|---|---|---|---|
| `full_name` | `text NOT NULL DEFAULT 'Pengguna'` | nullable | 🟡 |
| `tier` | `text` CHECK **`Silver` / `Gold`** (kapital), default `Silver` | enum `bronze`/`silver`/`gold`/`platinum` | 🔴 Nilai & kapitalisasi beda; seed pakai `Silver`/`Gold`. |
| `points` | default **1200** | default 0 | 🟡 |
| `stamps` | default **6**, CHECK `0..10` | default 0, CHECK `>= 0` | 🟡 |
| `updated_at` | **TIDAK ADA** | ADA | 🟡 (repository hanya baca `full_name`). |

Kolom join yang dipakai backend (`profiles.full_name`) 🟢 tetap ada.

---

## 7. Tabel lain

- **`vouchers`**: asli punya `note`, `valid_until` bertipe **`date`** (lama:
  `timestamptz`), `scope` CHECK `cart`/`merch`. 🟡
- **`addresses`**: asli `recipient`/`line1` NOT NULL, `is_default` default
  `true` (lama `false`). 🟡
- **`categories`**, **`rewards`**, **`loyalty_ledger`**, **`user_vouchers`**:
  🟢 setara.
- Tabel bantu lama **`order_no_counters`** & **`store_queue_counters`**: 🔴
  **tidak ada** di skema asli (asli pakai `order_no_seq`). Dihapus dari mirror.

---

## 8. RPC — perbedaan signature (paling kritis)

### 8.1 `place_order()` 🔴 signature berbeda total

**Asli** (13 parameter, **tanpa `p_user_id`** — pakai `auth.uid()`):

```sql
place_order(
  p_store_id uuid, p_fulfilment_mode text, p_table_number text,
  p_address_id uuid, p_scheduled_for timestamptz, p_payment_method text,
  p_payment_provider text, p_subtotal int, p_discount int, p_delivery_fee int,
  p_total int, p_voucher_code text, p_items jsonb
) RETURNS orders
```

**Backend lama** (9 parameter, dengan `p_user_id`, tipe enum):

```sql
place_order(p_user_id uuid, p_store_id uuid, p_fulfilment_mode fulfilment_mode,
  p_payment_method payment_method, p_items jsonb, p_voucher_code text DEFAULT NULL,
  p_table_number text DEFAULT NULL, p_scheduled_for timestamptz DEFAULT NULL,
  p_address_id uuid DEFAULT NULL) RETURNS orders
```

Perbedaan perilaku:

| Hal | Asli | Backend lama |
|---|---|---|
| Identitas user | `auth.uid()` (JWT) | parameter `p_user_id` |
| Harga | **dihitung KLIEN**, dikirim (`subtotal`,`total`,`unit_price`,`line_total`,`name_snapshot`) | dihitung SERVER dari `base_price + Σ price_delta` |
| `p_payment_provider` | ada | tak ada |
| Validasi toko tutup / produk nonaktif / voucher / ongkir | **tidak ada** | ada |
| `name_snapshot` item | dari payload | dari `products.name` |
| Status hasil | `received`, `payment_status = paid`, `stage 0` | `paid`, `stage 0` |
| Loyalty | +1 stamp (flat), poin = `total/1000` | +1 stamp per cup, poin = `total/1000` |
| Format `order_no` | `#KR-4471` | `ORD-YYYYMMDD-NNNN` |

Format `p_items` (jsonb) berbeda: **asli** butuh `name_snapshot`, `unit_price`,
`line_total` per item (klien yang hitung). Lama hanya `product_id`+opsi (server
hitung).

### 8.2 `advance_order_stage(p_order_id uuid)` 🟡 signature sama, perilaku beda

| Hal | Asli | Backend lama |
|---|---|---|
| Signature | `advance_order_stage(uuid) RETURNS orders` | sama ✅ |
| Scope | `WHERE id = p_order_id AND **user_id = auth.uid()**` | `WHERE id = p_order_id` (tanpa scope user) |
| Peta status | 1→`preparing`, 2→(delivery `on_the_way`, else `ready`), 3→`completed` | 1–2→`active`, 3→`completed` |
| Stage final | `least(3, stage+1)` — **idempotent**, tak error | **RAISE** 409 bila sudah stage 3 |
| Order dibatalkan | tak ada konsep | RAISE bila `status='cancelled'` |

Signature-nya sama, jadi `SELECT * FROM advance_order_stage($1::uuid)` tetap
valid — **tetapi** filter `auth.uid()` bikin panggilan gagal (`Order not found`)
saat backend tersambung sebagai role DB (auth.uid() = NULL). Lihat §9.

### 8.3 `redeem_reward()` 🔴 signature berbeda (di luar scope POS)

- **Asli:** `redeem_reward(p_reward_id uuid) RETURNS profiles` (pakai `auth.uid()`).
- **Lama:** `redeem_reward(p_user_id uuid, p_reward_id uuid) RETURNS profiles`.

Backend POS tidak memanggil ini (dipanggil mobile app), jadi tak ada wrapper.

---

## 9. Temuan kritis: `auth.uid()` pada RPC

`place_order()` dan `advance_order_stage()` **mengandalkan `auth.uid()`** (id
dari JWT, disetel Supabase saat request lewat PostgREST). Backend POS tersambung
langsung sebagai **role database** (bukan lewat PostgREST), sehingga `auth.uid()`
default **NULL** →

- `place_order()` → `RAISE 'Must be signed in to place an order'`;
- `advance_order_stage()` → baris tak ketemu → `RAISE 'Order not found'`.

**Solusi (tanpa mengubah RPC):** backend meng-impersonasi pemilik order dengan
menyetel GUC `request.jwt.claims` (transaction-local) sebelum memanggil RPC —
persis sumber yang dibaca `auth.uid()`:

```python
# app/db.py
await conn.execute("SELECT set_config('request.jwt.claims', $1, true)",
                   json.dumps({"sub": str(user_id), "role": "authenticated"}))
```

`app/rpc/advance_stage.py` membaca `orders.user_id` lebih dulu, lalu impersonasi
user itu, lalu memanggil RPC — di transaksi yang sama. RPC milik tim mobile
dipakai **apa adanya**.

> Catatan desain untuk dikonfirmasi tim mobile: `advance_order_stage()` asli
> di-scope ke **pemilik order** (dirancang untuk timer auto-advance sisi
> pelanggan), bukan untuk barista. Impersonasi membuatnya jalan untuk POS, tapi
> perlu disepakati apakah progres order semestinya digerakkan POS atau aplikasi
> pelanggan.

---

## 10. Konsekuensi untuk kode Python (Task 2)

| Berkas | Perubahan |
|---|---|
| `app/schemas/orders.py` | Enum status/mode → nilai asli; `+pre_order`; money `int`; `+payment_provider`,`+paid_at`; `-updated_at`; `payment_method: str`; `SimulateOrderRequest`→`PlaceOrderRequest` (13 field, harga dari klien). |
| `app/schemas/stores.py` | `+sort_order`, `-created_at`, NOT NULL sesuai asli. |
| `app/schemas/events.py` | `stage` lepas `le=3`; status memakai enum baru. |
| `app/rpc/place_order.py` | Signature 13 param + impersonasi `user_id`. |
| `app/rpc/advance_stage.py` | Lookup `user_id` → impersonasi → panggil RPC. |
| `app/db.py` | `+set_auth_claims()`. |
| `app/repository.py` | `_ORDER_COLUMNS`: `-updated_at`, `+payment_provider`,`+paid_at`. |
| `app/realtime/listener.py` | Poll tak lagi pakai `updated_at` (snapshot diff). |
| `db/*.sql` | Semua diganti jadi mirror skema asli + `realtime.sql` terpisah. |
