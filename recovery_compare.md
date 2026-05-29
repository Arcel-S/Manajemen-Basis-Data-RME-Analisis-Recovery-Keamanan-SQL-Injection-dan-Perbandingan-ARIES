# Cara Kerja `recovery_compare.py`

## 1. Membaca dua database

Skrip terhubung ke dua database yang sudah ada:

- `db_baseline`
- `db_aries`

Untuk masing-masing database, skrip mengambil informasi berikut:

- nama database aktif
- user yang sedang dipakai
- lokasi `data_directory`
- daftar tabel di schema `public`
- daftar kolom untuk tiap tabel
- status ekstensi `pgcrypto`
- posisi WAL terakhir dengan `pg_current_wal_insert_lsn()`

### Metrik yang dibandingkan

Berikut metrik utama yang dipakai:

- `RTO`: waktu dari crash sampai query verifikasi berhasil lagi.
- `RPO`: data yang hilang setelah crash; pada simulasi ini dihitung sebagai jumlah baris committed yang tidak ditemukan lagi.
- `MTTR`: rata-rata RTO dari beberapa iterasi crash.
- `Checkpoint Impact`: penurunan throughput saat checkpoint berlangsung; pada mode sekarang ditampilkan sebagai `n/a` karena belum ada benchmark throughput checkpoint terpisah.
- `Per-data Recovery`: status tiap transaksi/data uji, apakah recovered atau lost setelah crash.
- `table_count`: jumlah tabel di schema `public`.
- `column_count`: jumlah total kolom dari semua tabel.
- `pgcrypto`: tidak dipakai lagi untuk skenario ARIES-oriented ini.
- `wal_lsn`: posisi WAL terakhir saat snapshot diambil.
- `probe rollback`: apakah data uji tetap ada atau hilang setelah rollback.
- `wal records`: jumlah record WAL yang terbaca dari transaksi uji.
- `top rmgrs`: jenis record WAL yang paling sering muncul, misalnya `Heap`, `Btree`, atau `XLOG`.

Hasil ini dipakai untuk memastikan bahwa struktur baseline dan ARIES-oriented memang berbeda, serta ARIES-oriented tetap menjaga tabel utama `LOGGED` dan audit trail aktif.

## 2. Probe recovery yang aman

Fungsi `_safe_recovery_probe()` membuat tabel sementara bernama `recovery_probe`, lalu memasukkan satu baris data ke tabel itu.

Setelah insert, skrip membaca LSN WAL terbaru dan langsung melakukan `rollback`.

Efeknya:

- data uji tidak benar-benar menetap di database
- perubahan bisa dipakai untuk melihat jejak WAL yang dihasilkan transaksi
- setelah rollback, tabel tidak terlihat sebagai hasil akhir transaksi uji

Ini aman karena tidak menyentuh tabel produksi seperti `patients`, `medical_records`, atau `users`.

### Apakah ini crash beneran?

Belum. Mekanisme yang ada sekarang bukan mematikan proses PostgreSQL atau men-terminate transaksi secara paksa.

Yang dilakukan adalah:

1. Membuka transaksi.
2. Menulis data uji ke tabel sementara.
3. Mencatat LSN WAL yang dihasilkan.
4. Melakukan `rollback`.

Jadi ini lebih tepat disebut simulasi recovery aman, bukan crash yang sesungguhnya.

Kalau ingin simulasi crash yang lebih dekat ke kasus ARIES, biasanya ada dua pendekatan:

- `pg_terminate_backend(pid)` untuk memutus backend yang sedang memegang transaksi.
- menghentikan service PostgreSQL secara paksa saat transaksi belum commit.

Untuk tugas ini, pendekatan aman lebih cocok karena tidak merusak data utama dan tetap cukup untuk melihat efek WAL serta rollback.

### Output yang paling penting

Saat `--crash-sim` dijalankan, output utama yang perlu dibaca adalah:

- `RTO_avg_sec`: waktu pemulihan rata-rata.
- `RPO_rows_lost`: jumlah data yang hilang.
- `MTTR_sec`: rata-rata waktu pemulihan dari beberapa iterasi.
- `uncommitted_visible_count`: apakah transaksi yang belum commit sempat muncul atau tidak.
- `per_data_recovery`: daftar status untuk tiap transaksi uji.
- `Tabel Perbandingan Recovery`: ringkasan Baseline vs Proposed dalam format tabel.
- `Status Metrik`: penanda apakah metrik sudah dihitung atau masih pending.

Kalau `RPO_rows_lost = 0`, artinya semua data committed berhasil pulih.

### Cara membaca recovery per data

Bagian `per_data_recovery` menampilkan status tiap transaksi uji dalam format:

```text
tx_0001: recovered
tx_0002: recovered
tx_0003: recovered
tx_0004: lost
```

Artinya:

- transaksi 1 sampai 3 berhasil dipulihkan;
- transaksi 4 adalah data yang belum commit dan tidak ikut tersimpan setelah crash.

### Kalau ingin simulasi 500 transaksi dan crash

Mode `--crash-sim` menjalankan alur berikut pada masing-masing database:

1. Menyiapkan tabel simulasi `recovery_simulation_events`.
2. Menjalankan `tx_count` transaksi commit satu per satu.
3. Membuat satu transaksi tambahan yang belum commit.
4. Menutup backend transaksi itu dengan `pg_terminate_backend(pid)`.
5. Mengecek apakah baris yang belum commit ikut tersimpan atau tidak.

Dengan default `--tx-count 500`, ini berarti ada 500 transaksi committed lalu satu transaksi terakhir yang dipaksa gagal. Hasilnya bisa dipakai untuk melihat apakah recovery berhasil menjaga konsistensi setelah crash simulation.

Pada output program, RTO dan MTTR ditampilkan dalam detik, sedangkan RPO ditampilkan sebagai jumlah baris yang hilang. Kalau RPO bernilai 0, berarti tidak ada data committed yang hilang.

## 3. Membaca WAL dengan `pg_waldump`

Kalau `pg_waldump` tersedia, skrip akan memakainya untuk membaca log WAL pada rentang LSN yang baru saja dihasilkan.

Alur yang dipakai:

1. Ambil LSN sebelum dan sesudah probe.
2. Cari lokasi `pg_waldump` di PostgreSQL lokal.
3. Arahkan `pg_waldump` ke folder `pg_wal` milik server lewat `data_directory`.
4. Hitung jumlah record WAL dan tampilkan jenis record yang dominan.

Bagian ini berguna untuk membandingkan bagaimana PostgreSQL mencatat perubahan di level log, yang nanti bisa dipakai sebagai dasar diskusi ARIES vs baseline.

## 4. Kenapa cocok untuk perbandingan ARIES vs baseline

Untuk laporan atau presentasi, perbandingannya bisa dijelaskan seperti ini:

- Baseline: hanya dilihat dari efek transaksi dan rollback biasa.
- ARIES-oriented: selain rollback biasa, ada jejak WAL yang bisa dianalisis dan audit trail untuk observasi.

Jadi file ini bukan simulator ARIES penuh, tetapi alat inspeksi yang aman untuk menunjukkan perilaku recovery PostgreSQL dan jejak WAL yang dihasilkan.

## 4.1 Cara Kerja Singkat: ARIES vs Baseline

- **ARIES-oriented (LOGGED, durabilitas tinggi):**
	- Semua perubahan ditulis ke WAL (Write-Ahead Log) terlebih dahulu.
	- Saat crash, proses recovery membaca WAL untuk mengembalikan transaksi yang sudah committed dan membatalkan yang belum selesai.
	- Menjamin konsistensi dengan redo/undo berbasis log, sehingga RPO rendah dan recovery deterministik.

- **Baseline (lebih longgar, UNLOGGED / sync off):**
	- Beberapa tabel dapat dibuat `UNLOGGED` sehingga perubahan tidak selalu ditulis ke WAL, atau `synchronous_commit` dimatikan untuk throughput lebih tinggi.
	- Jika crash terjadi, data yang belum tertulis ke WAL atau buffer mungkin hilang; recovery bergantung pada checkpoint terakhir.
	- Memberikan performa lebih baik pada beban tulis, tetapi risiko kehilangan data (RPO) dan waktu pemulihan yang tak terduga lebih besar.

## 5. Cara menjalankan

Gunakan satu contoh eksekusi berikut:

```bash
python recovery_compare.py --baseline-dsn "dbname=db_baseline user=postgres password=123140054 host=localhost port=5432" --aries-dsn "dbname=db_aries user=postgres password=123140054 host=localhost port=5432" --crash-sim --tx-count 1000 --iterations 10 --run-demo
```

## 6. Ringkasan singkat

- `db_baseline` dipakai sebagai pembanding sederhana.
- `db_aries` menambahkan tabel `audit_logs` dan mempertahankan `LOGGED`.
- Probe recovery dilakukan dengan tabel uji, lalu di-rollback.
- `pg_waldump` dipakai untuk membaca record WAL dari transaksi uji, lalu hasilnya diringkas.

Kalau mau, bagian ini bisa tetap dijaga sebagai ringkasan konsep, sementara prosedur uji rinci disesuaikan terpisah bila diperlukan.