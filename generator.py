import random

import psycopg2
from faker import Faker

faker_id = Faker('id_ID')

DB_HOST = "localhost"
DB_PORT = "5432"
DB_USER = "postgres"
DB_PASSWORD = "123140054"

DB_ARIES = f"dbname=db_aries user={DB_USER} password={DB_PASSWORD} host={DB_HOST} port={DB_PORT}"


def _connect(dsn):
    return psycopg2.connect(dsn)


def _fetch_user_maps(cur_a):
    cur_a.execute("SELECT user_id, username FROM users")
    aries_users = {username: user_id for user_id, username in cur_a.fetchall()}

    if not aries_users:
        raise RuntimeError("Tidak ada users di db_aries. Jalankan INSERT users terlebih dahulu di db_aries.")

    return aries_users


def _reset_synthetic_data(cur_a):
    cur_a.execute("TRUNCATE TABLE medical_records, patients RESTART IDENTITY CASCADE")


def run_synthesis(n=500):
    conn_a = _connect(DB_ARIES)
    cur_a = conn_a.cursor()

    try:
        aries_users = _fetch_user_maps(cur_a)
        _reset_synthetic_data(cur_a)
        conn_a.commit()

        print("Terhubung ke PostgreSQL:")
        print("- db_aries")
        print("Data sintetis lama sudah dibersihkan.")
        print(f"User tersedia di db_aries: {', '.join(sorted(aries_users.keys()))}")

        for i in range(n):
            nik = faker_id.ssn()
            nama = faker_id.name()
            tgl = str(faker_id.date_of_birth(minimum_age=1, maximum_age=85))
            goldar = random.choice(['A', 'B', 'AB', 'O'])
            diag = faker_id.sentence(nb_words=5)
            tindakan = faker_id.sentence(nb_words=8)
            obat = "Paracetamol 500mg, Amoxicillin"
            username = random.choice(sorted(aries_users.keys()))
            aries_user_id = aries_users[username]

            cur_a.execute("""
                INSERT INTO patients (nik, nama, tgl_lahir, gol_darah) 
                VALUES (%s, %s, %s, %s) RETURNING patient_id
            """, (nik, nama, tgl, goldar))
            p_id_a = cur_a.fetchone()[0]

            cur_a.execute("""
                INSERT INTO medical_records (patient_id, user_id, diagnosis, tindakan, obat)
                VALUES (%s, %s, %s, %s, %s)
            """, (p_id_a, aries_user_id, diag, tindakan, obat))

            if (i+1) % 100 == 0:
                print(f"Progress: {i+1} records inserted...")

        conn_a.commit()
        print("Sintesis Selesai!")

    except Exception as e:
        print(f"Error: {e}")
        conn_a.rollback()
    finally:
        cur_a.close()
        conn_a.close()

if __name__ == "__main__":
    run_synthesis(100000)