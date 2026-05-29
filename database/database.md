# Kerangka Kerja Manajemen Basis Data Kesehatan Terpadu (RME) - Windows Version

- **Baseline System**: skema plaintext untuk data pasien dan rekam medis, tanpa ekstensi `pgcrypto`.
- **ARIES-oriented System**: skema plaintext dengan tabel utama tetap `LOGGED`, ditambah tabel audit `audit_logs` untuk observasi recovery.

Dokumen ini sengaja ditulis sesuai kondisi database yang benar-benar ada sekarang, bukan hanya rancangan awal.

---

## 1. Prasyarat

- Windows 10 / 11 atau Windows Server
- PostgreSQL 16.x atau lebih baru
- Python 3.10+
- Library Python: `faker`, `psycopg2`

Instalasi library Python:

```cmd
pip install faker psycopg2-binary
```

---

## 2. Struktur Database Aktual

### 2.1 Baseline System

Database: `db_baseline`

Tabel yang ada:

- `users`
- `patients`
- `medical_records`

Karakteristik baseline:

- data pasien disimpan dalam bentuk plaintext
- belum memakai `pgcrypto`
- belum ada tabel audit khusus

#### Skema tabel baseline

```sql
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(20),
    departemen VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE patients (
    patient_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nik VARCHAR(20),
    nama VARCHAR(100),
    tgl_lahir DATE,
    gol_darah CHAR(2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE medical_records (
    record_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID REFERENCES patients(patient_id),
    user_id UUID REFERENCES users(user_id),
    diagnosis TEXT,
    tindakan TEXT,
    obat TEXT,
    visit_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 ARIES-oriented System

Database: `db_aries`

Tabel yang ada:

- `users`
- `patients`
- `medical_records`
- `audit_logs`

Karakteristik ARIES-oriented:

- data pasien tetap plaintext agar perbandingan recovery adil
- tabel utama dijaga `LOGGED` supaya WAL tetap aktif
- ada audit trail otomatis lewat trigger

#### Skema tabel ARIES-oriented

```sql
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(20),
    departemen VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE patients (
    patient_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nik_enc BYTEA,
    nama_enc BYTEA,
    tgl_lahir_enc BYTEA,
    gol_darah CHAR(2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE medical_records (
    record_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID REFERENCES patients(patient_id),
    dokter_id UUID REFERENCES users(user_id),
    diagnosis_enc BYTEA,
    tindakan_enc BYTEA,
    obat TEXT,
    visit_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    aksi VARCHAR(50),
    tabel_target VARCHAR(50),
    ip_address INET,
    waktu TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20)
);
---

## 4. Catatan Penting

Beberapa hal yang perlu diluruskan dari versi awal dokumen:

- `pgcrypto` tidak lagi dipakai untuk skenario ARIES-oriented ini.
- Baseline dan ARIES-oriented sama-sama memakai PostgreSQL WAL; yang dibedakan adalah keberadaan tabel audit dan perlakuan schema saat recovery test.
- Frasa ΓÇ£tanpa log transaksi aktifΓÇ¥ untuk baseline kurang tepat kalau dibaca secara literal, karena PostgreSQL tetap punya WAL internal. Yang benar: baseline **tidak punya audit trail aplikasi** dan **tidak punya skema audit tambahan** seperti ARIES-oriented.
    VALUES (NULL, TG_OP, TG_TABLE_NAME, inet_client_addr(), 'SUCCESS');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_patients
AFTER INSERT OR UPDATE OR DELETE ON patients
FOR EACH ROW EXECUTE FUNCTION log_database_activity();

CREATE TRIGGER trg_audit_medical_records
AFTER INSERT OR UPDATE OR DELETE ON medical_records
FOR EACH ROW EXECUTE FUNCTION log_database_activity();
```

---

## 3. Data Pengguna Awal

Data pengguna awal yang dipakai pada kedua database:

```sql
INSERT INTO users (username, password_hash, role, departemen) VALUES 
('dr_budi', 'hashed_password_123', 'Dokter Spesialis', 'Kardiologi'),
('dr_siti', 'hashed_password_456', 'Dokter Umum', 'UGD'),
('admin_itera', 'hashed_password_789', 'Admin', 'IT')
ON CONFLICT (username) DO NOTHING;
```

---

## 4. Catatan Penting

Beberapa hal yang perlu diluruskan dari versi awal dokumen:

- Klaim `pg_audit` **belum terverifikasi** di database saat ini, jadi tidak dimasukkan sebagai bagian aktif dari skema aktual.
- Klaim `AES-256` juga **tidak ditulis sebagai fakta pasti** di sini. Untuk skenario ARIES-oriented ini, yang dipakai adalah tabel plaintext yang tetap `LOGGED`.
- Frasa ΓÇ£tanpa log transaksi aktifΓÇ¥ untuk baseline kurang tepat kalau dibaca secara literal, karena PostgreSQL tetap punya WAL internal. Yang benar: baseline **tidak punya audit trail aplikasi** dan **tidak punya skema enkripsi/trigger audit** seperti proposed.

---

## 5. Kesimpulan Singkat

- Baseline = plaintext, lebih sederhana, tanpa audit trail tabel.
- ARIES-oriented = plaintext, `LOGGED`, dan `audit_logs` dengan trigger otomatis.
- Perbedaan ini sudah sesuai dengan database yang sekarang terpasang.
