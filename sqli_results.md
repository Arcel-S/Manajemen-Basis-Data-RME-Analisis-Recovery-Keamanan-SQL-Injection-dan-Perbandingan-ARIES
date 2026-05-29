# Ringkasan Hasil Pengujian SQL Injection (sqli.py)

Tanggal: May 12, 2026

## Ringkasan singkat
- Menguji 5 payload terhadap dua mode:
  - Baseline (vulnerable concatenation) — mengeksekusi SQL dengan menggabungkan string.
  - Proposed (parameterized + encrypted) — menggunakan parameterized query; untuk kolom terenkripsi memakai `pgp_sym_encrypt`.
- Semua pengujian dijalankan pada salinan tabel `*_test` sehingga tidak mengubah produksi.
- Payload yang mengandung kata-kata/destruktif (mis. `;`, `DROP`) tidak dieksekusi (dilewati) untuk keamanan.

## Legend
- `Executed`: query yang dieksekusi (atau `None` bila payload di-skip). 
- `Rows returned`: jumlah baris yang dikembalikan; >0 menunjukkan payload berhasil *mengekstrak/mem-bypass* kondisi.
- `Status`: `bypassed` = payload berhasil mengembalikan baris; `blocked` = tidak ada baris; `skipped (destructive)` = payload berpotensi merusak dan tidak dieksekusi; `error` = query menyebabkan exception.
- `Latency`: waktu eksekusi dalam ms.

---

## Hasil — Baseline (vulnerable concat)

- Payload: `' OR '1'='1`
  - Executed: `SELECT * FROM patients_test WHERE nama = '' OR '1'='1'`
  - Rows returned: 10
  - Status: bypassed
  - Latency: 1.12 ms
  - Penjelasan: payload logika selalu true (`'1'='1'`) membuat query mengembalikan semua baris — contoh SQLi berhasil pada baseline.

- Payload: `'; SELECT * FROM users; --`
  - Executed: None
  - Rows returned: 0
  - Status: skipped (destructive)
  - Latency: 0.00 ms
  - Penjelasan: dilewati karena mengandung `;` (potensi eksekusi perintah tambahan). Tidak dieksekusi untuk keamanan.

- Payload: `' UNION SELECT NULL, username, password_hash, NULL, NULL, NULL FROM users--`
  - Executed: `SELECT * FROM patients_test WHERE nama = '' UNION SELECT NULL, username, password_hash, NULL, NULL, NULL FROM users--'`
  - Rows returned: 3
  - Status: bypassed
  - Latency: 5.04 ms
  - Penjelasan: UNION injection berhasil menggabungkan data dari `users` ke hasil — menunjukkan kebocoran data pada baseline.

- Payload: `1'; DROP TABLE dummy_test; --`
  - Executed: None
  - Rows returned: 0
  - Status: skipped (destructive)
  - Latency: 0.00 ms
  - Penjelasan: dilewati karena mengandung `DROP` (destruktif).

- Payload: `' AND 1=0--`
  - Executed: `SELECT * FROM patients_test WHERE nama = '' AND 1=0--'`
  - Rows returned: 0
  - Status: blocked
  - Latency: 0.48 ms
  - Penjelasan: kondisi selalu false sehingga tidak mengembalikan baris (payload tidak mengekstrak data).

---

## Hasil — Proposed (parameterized + encrypted)

- Payload: `' OR '1'='1`
  - Executed: `SELECT * FROM patients_test WHERE nama_enc = pgp_sym_encrypt(%s, %s)`
  - Rows returned: 0
  - Status: blocked
  - Latency: 1.94 ms
  - Penjelasan: parameterized + enkripsi mencegah payload mengubah struktur SQL; tidak ada data yang bocor.

- Payload: `'; SELECT * FROM users; --`
  - Executed: None
  - Rows returned: 0
  - Status: skipped (destructive)
  - Latency: 0.00 ms

- Payload: `' UNION SELECT NULL, username, password_hash, NULL, NULL, NULL FROM users--`
  - Executed: `SELECT * FROM patients_test WHERE nama_enc = pgp_sym_encrypt(%s, %s)`
  - Rows returned: 0
  - Status: blocked
  - Latency: 0.46 ms
  - Penjelasan: UNION attack tidak bekerja karena query parameterized dan kolom sensitif disimpan sebagai BYTEA terenkripsi.

- Payload: `1'; DROP TABLE dummy_test; --`
  - Executed: None
  - Rows returned: 0
  - Status: skipped (destructive)
  - Latency: 0.00 ms

- Payload: `' AND 1=0--`
  - Executed: `SELECT * FROM patients_test WHERE nama_enc = pgp_sym_encrypt(%s, %s)`
  - Rows returned: 0
  - Status: blocked
  - Latency: 0.38 ms

---

## Kesimpulan singkat
- Baseline rentan terhadap SQLi: payload logika (`' OR '1'='1`) dan UNION injection berhasil mengembalikan data dari tabel target (bukti exploitasi).
- Proposed (parameterized + enkripsi) menahan semua payload non-destruktif yang diuji: tidak ada baris yang dikembalikan.
- Mekanisme proteksi yang efektif di sini: parameterized queries (prevent injection) + menyimpan kolom sensitif sebagai ciphertext (BYTEA) sehingga attacker tidak bisa membandingkan plaintext langsung.

## Rekomendasi singkat
- Terus gunakan parameterized queries untuk seluruh input user.
- Jangan membangun SQL dinamis dengan konkatenasi string; jika perlu, gunakan library yang meng-escape identifier (psycopg2.sql).
- Simpan kunci enkripsi dan password di secret store / environment variables, bukan di kode.
- Untuk presentasi: tampilkan contoh output per-payload (file ini) dan demonstrasi live pada salinan tabel (`*_test`) agar tidak mengganggu produksi.

---

File ini dibuat otomatis dari output `sqli.py` — buka [Database/sqli.py](sqli.py) untuk kode yang menjalankan pengujian.
