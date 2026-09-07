# Kopi Rakyat — Backend POS Integration Service

Lapisan integrasi realtime antara **database online-ordering** (Supabase milik
tim mobile) dan **aplikasi POS barista**.

Backend ini **tidak mendesain ulang skema data** dan **tidak menduplikasi
business logic**. Perannya:

| Yang dilakukan | Yang TIDAK dilakukan |
|---|---|
| Mendeteksi order baru & perubahan stage dari tabel `orders` | Membuat model data sendiri |
| Broadcast realtime ke POS, di-scope per `store_id` | `INSERT`/`UPDATE` manual ke `orders`/`order_items` |
| Memanggil RPC `advance_order_stage()` atas nama POS | Menghitung harga, nomor order, atau loyalty |
| Menyediakan REST read-only untuk antrian & detail order | Melayani aplikasi mobile (mobile langsung ke Supabase) |

```
[Mobile App]  ──place_order() (RPC, JWT user)──►  [Supabase / PostgreSQL]
                                                    │        ▲
                              trigger NOTIFY ───────┘        │ advance_order_stage()
                              'pos_order_events'             │ (RPC, backend impersonasi
                                     │                       │  pemilik order)
                                     ▼                       │
        [Backend POS Integration (FastAPI)] ──WS per store_id──► [Dummy POS Client]
```

> **Status integrasi:** sudah disambungkan ke skema Supabase asli. Skema, RPC,
> dan schema Pydantic backend telah dicocokkan dengan skema asli tim mobile —
> lihat [docs/schema-comparison.md](docs/schema-comparison.md) untuk setiap
> perbedaan yang ditemukan & disesuaikan. Simulator mobile lama **tidak dipakai
> lagi** (dipindah ke `legacy/`) dan endpoint `/api/dev/*` **mati secara default**.

---

## 1. Menyambung ke Supabase asli

Inilah jalur produksi. Tidak ada perubahan kode — cukup `.env` + satu file SQL.

### 1.1 Isi `DATABASE_URL`

Supabase Dashboard → **Project Settings → Database → Connection string (URI)**,
mode **Session**. Gunakan role **`postgres`** (bukan `anon`/`authenticated`)
supaya backend bisa membaca order lintas user dan menyetel klaim JWT saat
memanggil RPC.

```env
DATABASE_URL=postgresql://postgres:<PASSWORD>@db.<ref>.supabase.co:5432/postgres
REALTIME_MODE=notify
ENABLE_DEV_ENDPOINTS=false
CORS_ORIGINS=https://pos.domain-anda.com
```

### 1.2 Pasang trigger realtime (sekali)

Backend mendengar order baru & perubahan stage lewat `LISTEN/NOTIFY`. Pasang
trigger di Supabase **satu kali**: buka **SQL Editor**, tempel isi
[`db/realtime.sql`](db/realtime.sql), Run.

`db/realtime.sql` hanya menambah **satu fungsi + dua trigger** pada tabel
`orders` — tidak mengubah kolom, data, atau RPC. Itulah **satu-satunya** objek
dari `db/` yang boleh di-apply ke Supabase asli.

> Tak boleh pasang trigger? Set `REALTIME_MODE=poll` — backend mem-polling
> perubahan stage tanpa menambah objek apa pun ke database (lihat §5).

### 1.3 Jalankan

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate di *nix)
pip install -r requirements.txt
copy .env.example .env          # cp di *nix, lalu isi DATABASE_URL
uvicorn app.main:app --reload
```

Selesai. Saat pelanggan checkout di aplikasi mobile, ordernya muncul di POS
tanpa refresh. **JANGAN** apply `db/schema.sql`, `db/functions.sql`,
`db/auth_local.sql`, atau `db/seed.sql` ke Supabase — objek itu sudah ada di
sana; file-file itu hanya mirror untuk dev lokal.

### Kenapa perlu impersonasi user?

`place_order()` dan `advance_order_stage()` asli di-scope ke `auth.uid()` (id
user dari JWT). Backend tersambung sebagai role database, jadi `auth.uid()`
default NULL. Sebelum memanggil RPC, backend menyetel GUC `request.jwt.claims`
(transaction-local) ke pemilik order — persis sumber yang dibaca `auth.uid()`.
RPC milik tim mobile dipakai **apa adanya**, tanpa modifikasi. Detail:
[docs/schema-comparison.md §9](docs/schema-comparison.md).

---

## 2. Menjalankan secara lokal (tanpa Supabase)

Untuk pengembangan/demo, tersedia Postgres lokal yang berisi **mirror** skema
asli (+ data dummy). Butuh Docker:

```bash
docker compose up -d
```

`db/*.sql` di-apply otomatis saat container pertama dibuat (urutan:
`auth_local` → `schema` → `functions` → `realtime` → `seed`). Postgres listen di
**host port 5433**.

<details>
<summary>Tidak punya Docker? Pakai PostgreSQL yang sudah ada.</summary>

```bash
python scripts/init_db.py            # apply mirror + seed
python scripts/init_db.py --no-seed  # tanpa data dummy
python scripts/init_db.py --drop     # ⚠ hapus objek mirror lalu apply ulang
```
`.env` `DATABASE_URL` diarahkan ke database lokal itu. Untuk demo lokal, set
`ENABLE_DEV_ENDPOINTS=true` agar bisa menyuntik order via `/api/dev/*`.
</details>

Lalu:

```bash
uvicorn app.main:app --reload
```

| URL | Isi |
|---|---|
| <http://localhost:8000/pos/> | **Dummy POS test interface** |
| <http://localhost:8000/docs> | Swagger UI |
| <http://localhost:8000/api/health> | Health check |

---

## 3. Struktur `db/`

| File | Apply ke Supabase asli? | Isi |
|---|---|---|
| `db/schema.sql` | ❌ **Tidak** | Mirror tabel + RLS + sequence dari skema asli. |
| `db/functions.sql` | ❌ **Tidak** | Salinan RPC asli (`place_order`, `advance_order_stage`, `redeem_reward`). |
| `db/auth_local.sql` | ❌ **Tidak** | Stub skema `auth` Supabase (untuk dev lokal). |
| `db/seed.sql` | ❌ **Tidak** | Data dummy lokal. |
| **`db/realtime.sql`** | ✅ **Ya** (bila `notify`) | Trigger NOTIFY `pos_order_events`. |

Sumber kebenaran skema = `supabase/migrations/…` di repo mobile app. `db/schema.sql`
& `db/functions.sql` adalah salinan setianya (dibuat idempotent) supaya dev/test
lokal berjalan di atas kontrak yang sama persis dengan Supabase asli.

---

## 4. Konfigurasi (env var)

| Variable | Default | Keterangan |
|---|---|---|
| `DATABASE_URL` | *(local docker)* | **Ganti ini saat pindah ke Supabase.** Pakai role `postgres`, mode Session. |
| `REALTIME_MODE` | `notify` | `notify` = LISTEN/NOTIFY (butuh `db/realtime.sql`), `poll` = polling snapshot |
| `REALTIME_CHANNEL` | `pos_order_events` | Channel NOTIFY |
| `POLL_INTERVAL_SECONDS` | `1.0` | Interval polling (mode `poll`) |
| `ENABLE_DEV_ENDPOINTS` | `false` | `true` → daftarkan `/api/dev/*` (hanya untuk uji lokal) |
| `CORS_ORIGINS` | `*` | Dipisah koma untuk membatasi origin POS |
| `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE` | `1` / `10` | Ukuran pool asyncpg |
| `LOG_LEVEL` | `INFO` | |

---

## 5. Realtime — dua mode

| Mode | Cara kerja | Objek DB dibutuhkan |
|---|---|---|
| `notify` *(default)* | Trigger `notify_order_event()` mem-`pg_notify` id+metadata setiap INSERT/perubahan `stage`\|`status`; backend `LISTEN` lalu fetch data lengkap. Latensi mendekati nol. | `db/realtime.sql` |
| `poll` | Bandingkan snapshot `(stage, status)` order aktif tiap `POLL_INTERVAL_SECONDS`. Tabel `orders` asli tak punya `updated_at`, jadi tak ada watermark waktu. | **tidak ada** |

Kedua mode menghasilkan event identik ke POS, jadi klien tak perlu tahu mode
mana yang aktif.

---

## 6. API

### 6.1 REST

| Method | Endpoint | Keterangan |
|---|---|---|
| `GET` | `/api/stores` | Daftar cabang |
| `GET` | `/api/stores/{store_id}` | Detail satu cabang |
| `GET` | `/api/orders?store_id=&status=&stage=&fulfilment_mode=&limit=&offset=` | Antrian order + `order_items` |
| `GET` | `/api/orders/{order_id}` | Detail satu order |
| `PATCH` | `/api/orders/{order_id}/advance` | Majukan stage (→ `advance_order_stage()`) |
| `GET` | `/api/health` | Health check |

`store_id` pada `GET /api/orders` **wajib** — itulah yang menegakkan Store
Isolation. Tanpa parameter tersebut request ditolak `422`.

Kode status error: `404` order/store tidak ada · `409` ditolak aturan bisnis RPC
atau order tanpa pemilik · `422` payload tidak valid · `501` RPC belum ada.

> **Format uang:** kolom `subtotal`, `total`, `unit_price`, dst. bertipe
> **`integer`** (rupiah bulat) di skema asli, dan diserialisasi sebagai **angka
> JSON biasa** (mis. `48000`) — bukan lagi string desimal.

### 6.2 WebSocket — `/ws/pos/{store_id}`

| Event | Kapan | Payload |
|---|---|---|
| `pos.connected` | setelah connect | `{store_id, store_key, store_name, is_open, clients}` |
| `order.created` | order baru | `{order: {...}, items: [...]}` |
| `order.stage_updated` | stage/status berubah | `{order_id, stage, status, updated_at}` |
| `pong` | balasan `"ping"` | `{}` |
| `error` | `store_id` invalid | `{message}` |

`order.created` sudah membawa `order_items` lengkap. `order.stage_updated`
selalu dikirim oleh listener (bukan endpoint `PATCH`), jadi perubahan stage dari
sumber mana pun tetap sampai ke POS tanpa event ganda.

---

## 7. Memanggil RPC langsung (debugging)

Karena `place_order()`/`advance_order_stage()` di-scope `auth.uid()`, set klaim
dulu dalam transaksi yang sama:

```sql
BEGIN;
SELECT set_config('request.jwt.claims',
                  '{"sub":"11111111-1111-1111-1111-111111111111"}', true);

-- advance stage order milik user di atas:
SELECT * FROM advance_order_stage('<order-uuid>');
COMMIT;
```

Signature RPC asli:

```sql
place_order(p_store_id uuid, p_fulfilment_mode text, p_table_number text,
  p_address_id uuid, p_scheduled_for timestamptz, p_payment_method text,
  p_payment_provider text, p_subtotal int, p_discount int, p_delivery_fee int,
  p_total int, p_voucher_code text, p_items jsonb) RETURNS orders

advance_order_stage(p_order_id uuid) RETURNS orders
```

`place_order()` menerima harga **terhitung dari klien** (mobile app), bukan
menghitung dari katalog. Tiap elemen `p_items`:
`{product_id, name_snapshot, size, milk, ice, sugar, extra_shot, note,
unit_price, qty, line_total}`.

---

## 8. Dummy POS Test Interface

`http://localhost:8000/pos/` — halaman statis satu file yang disajikan backend.
Fitur: pemilih store · antrian realtime · detail item · `pickup_code` · tombol
advance stage · filter per stage · log event · auto-reconnect. Untuk menguji
store isolation: buka dua tab, pilih store berbeda; hanya store yang cocok
bereaksi.

---

## 9. Testing

```bash
pytest              # semua test
pytest -m db        # hanya yang butuh database
pytest -m "not db"  # hanya unit test murni
```

Test `db` butuh Postgres berisi mirror skema asli (dan `ENABLE_DEV_ENDPOINTS=true`
untuk menyuntik order lewat `/api/dev/*`). Otomatis **di-skip** (bukan gagal)
bila database tidak terjangkau.

| File | Cakupan |
|---|---|
| `tests/test_rpc.py` | `place_order()` (harga dari klien, snapshot item, order_no `#KR-…`, stamp/poin) & `advance_order_stage()` (0→1→2→3, status `preparing`/`ready`/`on_the_way`/`completed`, idempotent di stage final, scope pemilik) |
| `tests/test_orders_api.py` | Store isolation, filter `status`/`stage`/`fulfilment_mode`, join `order_items`, urutan & limit, health, stores |
| `tests/test_ws_manager.py` | Store isolation di lapisan WebSocket, pembuangan koneksi mati |
| `tests/test_schemas.py` | Validasi `PlaceOrderRequest` & bentuk event WS sesuai skema asli |

### Bukti realtime (Task 3)

Diverifikasi end-to-end terhadap Postgres berisi **mirror skema asli** + trigger
`db/realtime.sql`, lewat modul backend sungguhan (listener → ws_manager → RPC
wrapper), bukan mock:

- `order.created` sampai ke POS store yang tepat, **lengkap dengan `order_items`**;
- `order.stage_updated` sampai untuk tiap transisi (`preparing` → `ready` →
  `completed`);
- POS store lain (Sudirman) menerima **0 event** — store isolation terjaga;
- Perubahan tersimpan permanen di DB; loyalty (`+1 stamp`, poin) ikut tercatat.

Semua `pytest` (50 test) lulus, 31 di antaranya dijalankan langsung terhadap DB
mirror skema asli.

---

## 10. Migrasi & catatan untuk tim mobile

Yang perlu dikonfirmasi:

1. **Progres order digerakkan siapa?** `advance_order_stage()` asli di-scope ke
   **pemilik order** (dirancang untuk timer auto-advance sisi pelanggan). Backend
   POS memanggilnya dengan impersonasi pemilik. Perlu disepakati apakah barista
   (POS) memang boleh memajukan stage, atau progres murni dari aplikasi pelanggan.
2. **Pembayaran.** `place_order()` selalu men-set `payment_status='paid'` &
   `payment_provider` dari payload (`simulated`). Integrasi gateway sungguhan
   menyusul.
3. **Pembatalan order.** Belum ada RPC pembatalan; status `orders` asli pun tak
   punya nilai `cancelled`.

---

## 11. Di luar scope fase ini

Aplikasi mobile · UI POS production · autentikasi end-user · gateway pembayaran
sungguhan · `redeem_reward()` penuh · klaim voucher · CRUD katalog · pembatalan
order · push notification · deployment skala besar.

---

## 12. Arsip

`legacy/simulator/` — dummy mobile simulator fase PoC, **tidak dipakai lagi**
(aplikasi mobile asli memanggil `place_order()` langsung ke Supabase). Lihat
[`legacy/README.md`](legacy/README.md).
