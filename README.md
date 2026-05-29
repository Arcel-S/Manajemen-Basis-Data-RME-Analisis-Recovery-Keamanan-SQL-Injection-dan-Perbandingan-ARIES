# Manajemen Basis Data RME

Project tugas besar Mata Kuliah Manajemen Basis Data IF25-40405 yang membahas implementasi database rekam medis pada PostgreSQL, perbandingan recovery, dan pengujian keamanan SQL injection.

## Ringkasan Project

Repositori ini berisi beberapa komponen utama:

- skema database baseline dan ARIES-oriented untuk data rekam medis
- skrip pembangkitan data untuk pengujian
- skrip perbandingan recovery antara dua database
- skrip pengujian SQL injection
- dokumentasi hasil pengujian dan struktur database

## Fitur Utama

- Perbandingan database `db_baseline` dan `db_aries`
- Observasi recovery berbasis WAL dan rollback probe
- Pengujian SQL injection pada mode baseline dan proposed
- Dokumentasi hasil pengujian dalam format yang mudah dibaca

## Struktur File

- `apply_conventional.py` - menerapkan skema baseline / konvensional
- `apply_aries.py` - menerapkan skema ARIES-oriented
- `generator.py` - membuat data uji untuk database
- `recovery_compare.py` - membandingkan perilaku recovery dua database
- `recovery_compare.md` - dokumentasi cara kerja recovery compare
- `sqli.py` - menjalankan pengujian SQL injection
- `sqli_results.md` - ringkasan hasil pengujian SQL injection
- `database.md` - dokumentasi struktur database yang digunakan
- `Image.png` - gambar pendukung project
- `SourceCode.zip` - arsip source code untuk pengumpulan

## Prasyarat

- Windows 10 / 11
- PostgreSQL 16.x atau lebih baru
- Python 3.10+
- Library Python:
  - `faker`
  - `psycopg2-binary`

Instalasi dependency:

```bash
pip install faker psycopg2-binary
```

## Cara Menjalankan

### 1. Menyiapkan database

Pastikan database `db_baseline` dan `db_aries` sudah tersedia di PostgreSQL lokal.

### 2. Menerapkan skema

Jalankan skrip sesuai kebutuhan:

```bash
python apply_conventional.py
python apply_aries.py
```

### 3. Membuat data uji

```bash
python generator.py
```

### 4. Membandingkan recovery

```bash
python recovery_compare.py --baseline-dsn "dbname=db_baseline user=postgres password=YOUR_PASSWORD host=localhost port=5432" --aries-dsn "dbname=db_aries user=postgres password=YOUR_PASSWORD host=localhost port=5432" --crash-sim --tx-count 1000 --iterations 10 --run-demo
```

### 5. Menjalankan pengujian SQL injection

```bash
python sqli.py
```

## Hasil yang Dibahas

- Perbedaan struktur baseline dan ARIES-oriented
- Dampak recovery terhadap data committed dan uncommitted
- Ketahanan query parameterized terhadap SQL injection
- Ringkasan hasil pengujian dalam format dokumentasi

## Catatan

Dokumentasi di repo ini dibuat sesuai kondisi database dan skrip yang benar-benar dipakai pada project, bukan hanya rancangan awal.

## Author

Project ini dibuat untuk tugas besar Mata Kuliah Manajemen Basis Data IF25-40405.
