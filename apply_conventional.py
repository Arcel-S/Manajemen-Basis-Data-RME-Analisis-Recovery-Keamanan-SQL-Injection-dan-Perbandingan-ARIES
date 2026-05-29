import argparse
import os
import sys
import psycopg2

DEFAULT_DSN = os.environ.get("DSN") or "dbname=db_baseline user=postgres password=123140054 host=localhost port=5432"
TARGET_TABLES = ["medical_records", "patients"]


def connect(dsn):
    return psycopg2.connect(dsn)


def drop_audit(conn):
    with conn.cursor() as cur:
        cur.execute("DROP TRIGGER IF EXISTS audit_trigger ON patients CASCADE")
        cur.execute("DROP TRIGGER IF EXISTS audit_trigger ON medical_records CASCADE")
        cur.execute("DROP FUNCTION IF EXISTS audit_changes() CASCADE")
        cur.execute("DROP TABLE IF EXISTS audit_logs CASCADE")
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


def set_current_session_synchronous(conn, value: str):
    cur = conn.cursor()
    try:
        cur.execute("SET synchronous_commit = %s", (value,))
        print(f"Set synchronous_commit = {value} for current session")
    finally:
        cur.close()


def set_unlogged(conn, tables, dry_run=False):
    with conn.cursor() as cur:
        for t in tables:
            if dry_run:
                print(f"DRY RUN: ALTER TABLE {t} SET UNLOGGED")
            else:
                print(f"Setting {t} to UNLOGGED")
                cur.execute(f"ALTER TABLE public.{t} SET UNLOGGED")
    if not dry_run:
        conn.commit()


def set_logged(conn, tables):
    with conn.cursor() as cur:
        for t in reversed(tables):
            print(f"Reverting {t} to LOGGED")
            cur.execute(f"ALTER TABLE public.{t} SET LOGGED")
    conn.commit()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dsn", default=DEFAULT_DSN)
    p.add_argument("--revert", action="store_true", help="Revert tables to LOGGED")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--make-worse", action="store_true", help="Make conventional worse by setting database-wide synchronous_commit=off (ALTER DATABASE; applies to new sessions)")
    p.add_argument("--set-current-session", choices=("on","off","local"), help="Set synchronous_commit for current session (immediate effect)")
    args = p.parse_args()

    try:
        conn = connect(args.dsn)
    except Exception as e:
        print("Failed to connect:", e)
        sys.exit(2)

    if args.revert:
        set_logged(conn, TARGET_TABLES)
        print("Reverted tables to LOGGED")
        return

    if args.make_worse:
        set_db_synchronous(conn, 'off')

    if args.set_current_session:
        set_current_session_synchronous(conn, args.set_current_session)

    drop_audit(conn)

    set_unlogged(conn, TARGET_TABLES, dry_run=args.dry_run)

    if args.dry_run:
        print("Dry run complete. No changes committed.")
    else:
        print("Conventional (UNLOGGED) settings applied to db_baseline")


if __name__ == '__main__':
    main()
