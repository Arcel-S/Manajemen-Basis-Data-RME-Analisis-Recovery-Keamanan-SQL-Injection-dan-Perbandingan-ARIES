import psycopg2
import time
import re

BASE_DSN = "dbname=db_baseline user=postgres password=123140054 host=localhost"
TARGET_DSN = "dbname=db_proposed user=postgres password=123140054 host=localhost"
ENCRYPTION_KEY = "kunci_rahasia_kelompok_8"

PAYLOADS = [
    "' OR '1'='1",
    "'; SELECT * FROM users; --",
    "' UNION SELECT NULL, username, password_hash, NULL, NULL, NULL FROM users--",
    "1'; DROP TABLE dummy_test; --",
    "' AND 1=0--"
]

dangerous_keywords = re.compile(r";|DROP\b|DELETE\b|ALTER\b|TRUNCATE\b|INSERT\b", re.IGNORECASE)


def _prepare_test_tables(conn, cur, use_target_schema=False):
    cur.execute("CREATE TABLE IF NOT EXISTS patients_test (LIKE patients INCLUDING ALL)")
    cur.execute("CREATE TABLE IF NOT EXISTS medical_records_test (LIKE medical_records INCLUDING ALL)")
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM patients_test")
    if cur.fetchone()[0] == 0:
        try:
            if not use_target_schema:
                cur.execute("INSERT INTO patients_test (nik, nama, tgl_lahir, gol_darah) SELECT nik, nama, tgl_lahir, gol_darah FROM patients LIMIT 10")
                cur.execute("INSERT INTO medical_records_test (patient_id, user_id, diagnosis, tindakan, obat) SELECT patient_id, user_id, diagnosis, tindakan, obat FROM medical_records LIMIT 10")
            else:
                cur_b_conn = psycopg2.connect(BASE_DSN)
                cur_b = cur_b_conn.cursor()
                cur_b.execute("SELECT nik, nama, tgl_lahir, gol_darah FROM patients LIMIT 10")
                rows = cur_b.fetchall()
                for nik, nama, tgl, gol in rows:
                    cur.execute(
                        "INSERT INTO patients_test (nik_enc, nama_enc, tgl_lahir_enc, gol_darah) VALUES (pgp_sym_encrypt(%s,%s), pgp_sym_encrypt(%s,%s), pgp_sym_encrypt(%s,%s), %s)",
                        (nik, ENCRYPTION_KEY, nama, ENCRYPTION_KEY, tgl, ENCRYPTION_KEY, gol),
                    )
                cur_b.close()
                cur_b_conn.close()
            conn.commit()
        except Exception:
            conn.rollback()


def run_sqli_test(db_config, system_name, use_parameterized=False, use_target_schema=False):
    conn = psycopg2.connect(db_config)
    cur = conn.cursor()
    results = []

    print(f"--- Testing SQLi on {system_name} ---")
    _prepare_test_tables(conn, cur, use_target_schema=use_target_schema)

    for payload in PAYLOADS:
        entry = {"payload": payload, "executed": None, "rows": 0, "status": None}
        if dangerous_keywords.search(payload):
            entry['status'] = 'skipped (destructive)'
            results.append(entry)
            print(f"SKIP destructive payload: {payload}")
            continue

        start_time = time.time()
        try:
            if use_parameterized:
                if use_target_schema:
                    sql = "SELECT * FROM patients_test WHERE nama_enc = pgp_sym_encrypt(%s, %s)"
                    cur.execute(sql, (payload, ENCRYPTION_KEY))
                    entry['executed'] = sql
                else:
                    sql = "SELECT * FROM patients_test WHERE nama = %s"
                    cur.execute(sql, (payload,))
                    entry['executed'] = sql
            else:
                sql = f"SELECT * FROM patients_test WHERE nama = '{payload}'"
                cur.execute(sql)
                entry['executed'] = sql

            rows = cur.fetchall()
            entry['rows'] = len(rows)
            entry['status'] = 'bypassed' if len(rows) > 0 else 'blocked'

        except Exception as e:
            entry['status'] = f'error: {e}'
            conn.rollback()

        latency = (time.time() - start_time) * 1000
        entry['latency_ms'] = latency
        results.append(entry)

    try:
        cur.execute('DROP TABLE IF EXISTS medical_records_test')
        cur.execute('DROP TABLE IF EXISTS patients_test')
        conn.commit()
    except Exception:
        conn.rollback()

    cur.close()
    conn.close()
    return results


def pretty_print_results(system_name, results):
    print(f"\nResults for {system_name}:")
    for r in results:
        print(f"- Payload: {r['payload']}")
        print(f"  Executed: {r.get('executed')}")
        print(f"  Rows returned: {r['rows']}")
        print(f"  Status: {r['status']}")
        print(f"  Latency: {r.get('latency_ms',0):.2f} ms\n")


if __name__ == '__main__':
    base_results = run_sqli_test(BASE_DSN, 'Baseline (vulnerable concat)', use_parameterized=False, use_target_schema=False)
    prop_results = run_sqli_test(TARGET_DSN, 'Proposed (parameterized + encrypted)', use_parameterized=True, use_target_schema=True)

    pretty_print_results('Baseline (vulnerable concat)', base_results)
    pretty_print_results('Proposed (parameterized + encrypted)', prop_results)
