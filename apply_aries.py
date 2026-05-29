import argparse
import os
import sys
import psycopg2

DEFAULT_DSN = os.environ.get("DSN") or "dbname=db_baseline user=postgres password=123140054 host=localhost port=5432"
TARGET_TABLES = ["patients", "medical_records"]


def connect(dsn):
    return psycopg2.connect(dsn)


def ensure_pgcrypto(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    conn.commit()


def create_audit_table_and_function(conn):
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id bigserial PRIMARY KEY,
            operation text NOT NULL,
            table_name text NOT NULL,
            row_data jsonb,
            actor text,
            created_at timestamptz DEFAULT current_timestamp
        )
        """)

        cur.execute("""
        CREATE OR REPLACE FUNCTION audit_changes() RETURNS trigger AS $$
        BEGIN
            IF (TG_OP = 'DELETE') THEN
                INSERT INTO audit_logs(operation, table_name, row_data, actor)
                VALUES (TG_OP, TG_TABLE_NAME, row_to_json(OLD), current_user);
                RETURN OLD;
            ELSIF (TG_OP = 'UPDATE') THEN
                INSERT INTO audit_logs(operation, table_name, row_data, actor)
                VALUES (TG_OP, TG_TABLE_NAME, row_to_json(NEW), current_user);
                RETURN NEW;
            ELSIF (TG_OP = 'INSERT') THEN
                INSERT INTO audit_logs(operation, table_name, row_data, actor)
                VALUES (TG_OP, TG_TABLE_NAME, row_to_json(NEW), current_user);
                RETURN NEW;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """)
    conn.commit()


def attach_triggers(conn, tables):
    with conn.cursor() as cur:
        for t in tables:
            print(f"Attaching audit trigger to {t}")
            cur.execute(f"DROP TRIGGER IF EXISTS audit_trigger ON {t}")
            cur.execute(f"CREATE TRIGGER audit_trigger AFTER INSERT OR UPDATE OR DELETE ON {t} FOR EACH ROW EXECUTE FUNCTION audit_changes()")
    conn.commit()


def set_logged(conn, tables):
    with conn.cursor() as cur:
        for t in tables:
            print(f"Setting {t} to LOGGED")
            cur.execute(f"ALTER TABLE {t} SET LOGGED")
    conn.commit()


def set_db_synchronous(conn, value: str):
    cur = conn.cursor()
    try:
        cur.execute("SELECT current_database()")
        dbname = cur.fetchone()[0]
        cur.execute(f"ALTER DATABASE {dbname} SET synchronous_commit = %s", (value,))
        print(f"Set synchronous_commit = {value} for database {dbname}")
        conn.commit()
    finally:
        cur.close()


def drop_audit(conn):
    with conn.cursor() as cur:
        cur.execute("DROP TRIGGER IF EXISTS audit_trigger ON patients CASCADE")
        cur.execute("DROP TRIGGER IF EXISTS audit_trigger ON medical_records CASCADE")
        cur.execute("DROP FUNCTION IF EXISTS audit_changes() CASCADE")
        cur.execute("DROP TABLE IF EXISTS audit_logs CASCADE")
    conn.commit()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dsn", default=DEFAULT_DSN)
    p.add_argument("--with-audit", action="store_true", help="Also create audit table and triggers")
    p.add_argument("--enable-pgcrypto", action="store_true", help="Enable pgcrypto extension (optional)")
    p.add_argument("--remove-audit", action="store_true", help="Remove audit artifacts")
    p.add_argument("--revert-unlogged", action="store_true", help="Set target tables to UNLOGGED (revert)")
    p.add_argument("--set-synchronous-commit", choices=("on","off","local"), help="Set database synchronous_commit value")
    args = p.parse_args()

    try:
        conn = connect(args.dsn)
    except Exception as e:
        print("Failed to connect:", e)
        sys.exit(2)

    if args.remove_audit:
        drop_audit(conn)
        print("Removed audit artifacts")
        return

    if args.revert_unlogged:
        with conn.cursor() as cur:
            for t in TARGET_TABLES:
                cur.execute(f"ALTER TABLE {t} SET UNLOGGED")
        conn.commit()
        print("Reverted target tables to UNLOGGED")
        return

    if args.set_synchronous_commit:
        set_db_synchronous(conn, args.set_synchronous_commit)

    if args.with_audit:
        create_audit_table_and_function(conn)
        attach_triggers(conn, TARGET_TABLES)
    else:
        try:
            drop_audit(conn)
        except Exception:
            pass

    if args.enable_pgcrypto:
        ensure_pgcrypto(conn)

    set_logged(conn, TARGET_TABLES)

    print("ARIES-like settings applied to db_baseline (pgcrypto + audit + LOGGED)")


if __name__ == '__main__':
    main()
