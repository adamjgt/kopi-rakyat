# legacy/ — dikesampingkan

Isi folder ini **tidak lagi dipakai** setelah backend disambungkan ke database
Supabase asli.

## `legacy/simulator/`

Dummy mobile simulator dari fase Proof of Concept. Dulu ia menembak
`POST /api/dev/simulate-order` untuk membuat order tiruan. Sekarang:

- Aplikasi mobile asli memanggil `place_order()` **langsung ke Supabase**
  (lewat PostgREST + JWT user), bukan lewat backend ini.
- Endpoint `/api/dev/*` **dimatikan secara default** (`ENABLE_DEV_ENDPOINTS=false`).
- Payload simulator lama (yang mengandalkan server menghitung harga) **tidak
  cocok** dengan `place_order()` asli, yang menerima harga terhitung dari klien.

Disimpan hanya sebagai arsip. Jangan dijadikan acuan integrasi.
