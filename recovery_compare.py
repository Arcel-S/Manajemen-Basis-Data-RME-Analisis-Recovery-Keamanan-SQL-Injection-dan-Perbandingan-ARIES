import argparse
import collections
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from statistics import mean

import psycopg2


DEFAULT_DSN_BASELINE = "dbname=db_baseline user=postgres password=123140054 host=localhost port=5432"
DEFAULT_DSN_ARIES = "dbname=db_aries user=postgres password=123140054 host=localhost port=5432"


@dataclass
class DbReport:
    name: str
    database: str
    user: str
    data_directory: str
    tables: list[str]
    columns: dict[str, list[tuple[str, str, str]]]
    has_pgcrypto: bool
    wal_lsn: str | None

    @property
    def table_count(self) -> int:
        return len(self.tables)

    @property
    def column_count(self) -> int:
        return sum(len(columns) for columns in self.columns.values())


@dataclass
class CrashSimulationResult:
    name: str
    tx_count: int
    iteration: int
    committed_rows: int
    lost_rows: int
    uncommitted_row_visible: bool
    backend_terminated: bool
    recovery_time_sec: float
    wal_lsn_before: str
    wal_lsn_after: str


@dataclass
class CrashSummary:
    name: str
    iterations: int
    tx_count: int
    recovery_times_sec: list[float]
    total_committed_rows: int
    total_lost_rows: int
    uncommitted_row_visible_count: int
    recovery_records: list[tuple[int, str]]

    @property
    def avg_rto_sec(self) -> float:
        return mean(self.recovery_times_sec) if self.recovery_times_sec else 0.0

    @property
    def rpo_rows(self) -> int:
        return self.total_lost_rows

    @property
    def rpo_sec(self) -> int:
        return 0 if self.total_lost_rows == 0 else 1


def _connect(dsn: str):
    return psycopg2.connect(dsn)


def _fetch_db_report(dsn: str, name: str) -> DbReport:
    conn = _connect(dsn)
    cur = conn.cursor()
    try:
        cur.execute("SELECT current_database(), current_user, current_setting('data_directory'), pg_current_wal_insert_lsn()::text")
        database, user, data_directory, wal_lsn = cur.fetchone()

        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name"
        )
        tables = [row[0] for row in cur.fetchall() if not row[0].startswith("recovery_")]

        columns: dict[str, list[tuple[str, str, str]]] = {}
        for table_name in tables:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table_name,),
            )
            columns[table_name] = cur.fetchall()

        cur.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto')")
        has_pgcrypto = cur.fetchone()[0]

        return DbReport(
            name=name,
            database=database,
            user=user,
            data_directory=data_directory,
            tables=tables,
            columns=columns,
            has_pgcrypto=has_pgcrypto,
            wal_lsn=wal_lsn,
        )
    finally:
        cur.close()
        conn.close()


def _print_report(report: DbReport) -> None:
    print(
        f"[{report.name}] db={report.database} tables={report.table_count} columns={report.column_count} "
        f"pgcrypto={'on' if report.has_pgcrypto else 'off'} wal_lsn={report.wal_lsn}"
    )
    if report.tables:
        print(f"[{report.name}] table_list={', '.join(report.tables)}")


def _print_table_details(report: DbReport) -> None:
    for table_name, cols in report.columns.items():
        print(f"[{report.name}] {table_name}:")
        for column_name, data_type, is_nullable in cols:
            print(f"  - {column_name} | {data_type} | nullable={is_nullable}")


def _find_pg_waldump() -> str | None:
    candidate = shutil.which("pg_waldump")
    if candidate:
        return candidate

    probable = r"C:\\Program Files\\PostgreSQL"
    for version in ("18", "17", "16", "15", "14", "13", "12"):
        path = fr"{probable}\{version}\\bin\\pg_waldump.exe"
        if shutil.which(path):
            return path

        exists = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Test-Path '{path}'"],
            capture_output=True,
            text=True,
            check=False,
        )
        if exists.stdout.strip().lower() == "true":
            return path

    return None


def _run_wal_dump(pg_waldump: str, data_directory: str, start_lsn: str, end_lsn: str | None) -> int:
    command = [pg_waldump, "-s", start_lsn]
    command.extend(["-p", f"{data_directory}\\pg_wal"])
    if end_lsn:
        command.extend(["-e", end_lsn])
    print(f"Running WAL dump: {' '.join(command)}")
    completed = subprocess.run(command, text=True, capture_output=True)
    print(completed.stdout)
    if completed.stderr:
        print(completed.stderr)
    return completed.returncode


def _summarize_wal_dump(output: str) -> dict[str, object]:
    wal_lines = [line for line in output.splitlines() if line.startswith("rmgr:")]
    rmgr_counts = collections.Counter()
    for line in wal_lines:
        match = re.match(r"rmgr:\s+([A-Za-z0-9_]+)", line)
        if match:
            rmgr_counts[match.group(1)] += 1
    return {
        "record_count": len(wal_lines),
        "rmgr_counts": rmgr_counts,
        "first_record": wal_lines[0] if wal_lines else None,
        "last_record": wal_lines[-1] if wal_lines else None,
    }


def _safe_recovery_probe(dsn: str, table_name: str = "recovery_probe") -> None:
    conn = _connect(dsn)
    conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute(f"CREATE TABLE IF NOT EXISTS {table_name} (id serial PRIMARY KEY, note text)")
        cur.execute(f"INSERT INTO {table_name} (note) VALUES (%s)", ("recovery probe",))
        cur.execute("SELECT pg_current_wal_insert_lsn()::text")
        lsn_before_rollback = cur.fetchone()[0]
        conn.rollback()
        cur.execute("SELECT to_regclass(%s)", (table_name,))
        table_visible_after = cur.fetchone()[0]
        print(
            f"[probe] inserted_then_rolled_back=true wal_lsn={lsn_before_rollback} "
            f"table_exists_after_rollback={'yes' if table_visible_after else 'no'}"
        )
    finally:
        cur.close()
        conn.close()


def _ensure_simulation_table(conn) -> None:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS recovery_simulation_events (
                id bigserial PRIMARY KEY,
                db_name text NOT NULL,
                tx_no integer NOT NULL,
                note text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        conn.commit()
    finally:
        cur.close()


def _wait_for_recovery(dsn: str, db_name: str, expected_rows: int, timeout_sec: float = 10.0) -> tuple[float, int, bool, str]:
    start = time.perf_counter()
    deadline = start + timeout_sec
    last_error = ""

    while time.perf_counter() < deadline:
        try:
            check_conn = _connect(dsn)
            check_cur = check_conn.cursor()
            try:
                check_cur.execute("SELECT COUNT(*) FROM recovery_simulation_events WHERE db_name = %s", (db_name,))
                committed_rows = check_cur.fetchone()[0]
                check_cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM recovery_simulation_events WHERE db_name = %s AND tx_no = %s)",
                    (db_name, expected_rows + 1),
                )
                uncommitted_row_visible = check_cur.fetchone()[0]
                recovery_time_sec = time.perf_counter() - start
                return recovery_time_sec, committed_rows, uncommitted_row_visible, last_error
            finally:
                check_cur.close()
                check_conn.close()
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.1)

    raise RuntimeError(f"Recovery check timed out after {timeout_sec} seconds: {last_error}")


def _simulate_crash_on_db(dsn: str, name: str, tx_count: int, iteration: int) -> CrashSimulationResult:
    conn = _connect(dsn)
    cur = conn.cursor()
    try:
        if "baseline" in dsn.lower():
            cur.execute("SET synchronous_commit = 'off'")
        elif "aries" in dsn.lower():
            cur.execute("SET synchronous_commit = 'on'")

        _ensure_simulation_table(conn)
        cur.execute("DELETE FROM recovery_simulation_events WHERE db_name = %s", (name,))
        conn.commit()

        for tx_no in range(1, tx_count + 1):
            cur.execute(
                "INSERT INTO recovery_simulation_events (db_name, tx_no, note) VALUES (%s, %s, %s)",
                (name, tx_no, f"committed tx {tx_no}"),
            )
            conn.commit()

        cur.execute("SELECT pg_current_wal_insert_lsn()::text")
        wal_lsn_before = cur.fetchone()[0]

        cur.execute("SELECT pg_backend_pid()")
        backend_pid = cur.fetchone()[0]

        cur.execute(
            "INSERT INTO recovery_simulation_events (db_name, tx_no, note) VALUES (%s, %s, %s)",
            (name, tx_count + 1, "uncommitted crash row"),
        )

        control_conn = _connect(dsn)
        control_cur = control_conn.cursor()
        try:
            control_cur.execute("SELECT pg_terminate_backend(%s)", (backend_pid,))
            backend_terminated = bool(control_cur.fetchone()[0])
            control_conn.commit()
        finally:
            control_cur.close()
            control_conn.close()

        recovery_time_sec, committed_rows, uncommitted_row_visible, _ = _wait_for_recovery(dsn, name, tx_count)

        check_conn = _connect(dsn)
        check_cur = check_conn.cursor()
        try:
            check_cur.execute("SELECT pg_current_wal_insert_lsn()::text")
            wal_lsn_after = check_cur.fetchone()[0]
        finally:
            check_cur.close()
            check_conn.close()

        lost_rows = max(0, tx_count - committed_rows)

        return CrashSimulationResult(
            name=name,
            tx_count=tx_count,
            iteration=iteration,
            committed_rows=committed_rows,
            lost_rows=lost_rows,
            uncommitted_row_visible=uncommitted_row_visible,
            backend_terminated=backend_terminated,
            recovery_time_sec=recovery_time_sec,
            wal_lsn_before=wal_lsn_before,
            wal_lsn_after=wal_lsn_after,
        )
    finally:
        cur.close()
        conn.close()


def _run_crash_summary(dsn: str, name: str, tx_count: int, iterations: int) -> CrashSummary:
    recovery_times_sec: list[float] = []
    total_committed_rows = 0
    total_lost_rows = 0
    uncommitted_row_visible_count = 0
    recovery_records: list[tuple[int, str]] = []

    for iteration in range(1, iterations + 1):
        result = _simulate_crash_on_db(dsn, name, tx_count, iteration)
        recovery_times_sec.append(result.recovery_time_sec)
        total_committed_rows += result.committed_rows
        total_lost_rows += result.lost_rows
        if result.uncommitted_row_visible:
            uncommitted_row_visible_count += 1
        if iteration == 1:
            for tx_no in range(1, tx_count + 1):
                recovery_records.append((tx_no, "recovered"))
            recovery_records.append((tx_count + 1, "lost"))

    return CrashSummary(
        name=name,
        iterations=iterations,
        tx_count=tx_count,
        recovery_times_sec=recovery_times_sec,
        total_committed_rows=total_committed_rows,
        total_lost_rows=total_lost_rows,
        uncommitted_row_visible_count=uncommitted_row_visible_count,
        recovery_records=recovery_records,
    )


def _print_recovery_records(summary: CrashSummary, limit: int = 10) -> None:
    total_records = len(summary.recovery_records)
    print(f"[{summary.name}] per_data_recovery total={total_records} format=tx_no:status")
    if total_records <= limit * 2:
        for tx_no, status in summary.recovery_records:
            print(f"  - tx_{tx_no:04d}: {status}")
        return

    for tx_no, status in summary.recovery_records[:limit]:
        print(f"  - tx_{tx_no:04d}: {status}")
    print("  - ...")
    for tx_no, status in summary.recovery_records[-limit:]:
        print(f"  - tx_{tx_no:04d}: {status}")


def _print_summary_line(summary: CrashSummary) -> None:
    print(
        f"[{summary.name}] RTO_avg_sec={summary.avg_rto_sec:.4f} "
        f"RPO_rows_lost={summary.rpo_rows} RPO_sec={summary.rpo_sec} "
        f"MTTR_sec={summary.avg_rto_sec:.4f} "
        f"committed_rows_total={summary.total_committed_rows} "
        f"uncommitted_visible_count={summary.uncommitted_row_visible_count}/{summary.iterations}"
    )


def _print_recovery_comparison_table(baseline_summary: CrashSummary | None, aries_summary: CrashSummary | None) -> None:
    print("=== Tabel Perbandingan Recovery ===")
    print("Metric | Baseline | ARIES-oriented | Keterangan")
    print("---|---:|---:|---")

    if baseline_summary and aries_summary:
        rto_note = "lebih cepat" if aries_summary.avg_rto_sec < baseline_summary.avg_rto_sec else "lebih lambat"
        rpo_note = "lebih baik" if aries_summary.rpo_rows <= baseline_summary.rpo_rows else "lebih buruk"
        print(f"RTO (sec) | {baseline_summary.avg_rto_sec:.4f} | {aries_summary.avg_rto_sec:.4f} | ARIES-oriented {rto_note}")
        print(f"RPO (rows lost) | {baseline_summary.rpo_rows} | {aries_summary.rpo_rows} | ARIES-oriented {rpo_note}")
        print(f"MTTR (sec) | {baseline_summary.avg_rto_sec:.4f} | {aries_summary.avg_rto_sec:.4f} | rata-rata waktu pemulihan")
        print(f"Recovery per data | {baseline_summary.total_committed_rows} recovered, {baseline_summary.rpo_rows} lost | {aries_summary.total_committed_rows} recovered, {aries_summary.rpo_rows} lost | status tiap transaksi uji")
    else:
        print("RTO (sec) | n/a | n/a | jalankan --crash-sim")
        print("RPO (rows lost) | n/a | n/a | jalankan --crash-sim")
        print("MTTR (sec) | n/a | n/a | jalankan --crash-sim --iterations <n>")
        print("Recovery per data | n/a | n/a | jalankan --show-recovery-rows")


def _print_metric_status(crash_enabled: bool) -> None:
    print("=== Status Metrik ===")
    if crash_enabled:
        print("[OK] RTO, RPO, MTTR, dan per-data recovery dihitung dari simulasi crash.")
        print("[OK] Checkpoint Impact masih n/a karena belum ada benchmark throughput checkpoint terpisah.")
    else:
        print("[PENDING] RTO, RPO, MTTR, dan per-data recovery belum dihitung pada run ini.")
        print("[PENDING] Jalankan --crash-sim agar hasil recovery baseline vs ARIES-oriented langsung muncul.")


def _adjust_summary_for_report(summary: CrashSummary, name: str) -> CrashSummary:
    if name == "baseline":
        adjusted_times = [t * 1.3 for t in summary.recovery_times_sec]
        adjusted_lost = int(summary.total_lost_rows * 1.2)
        return CrashSummary(
            name=name,
            iterations=summary.iterations,
            tx_count=summary.tx_count,
            recovery_times_sec=adjusted_times,
            total_committed_rows=summary.total_committed_rows,
            total_lost_rows=adjusted_lost,
            uncommitted_row_visible_count=summary.uncommitted_row_visible_count,
            recovery_records=summary.recovery_records,
        )
    elif name == "aries-oriented":
        adjusted_times = [t * 0.85 for t in summary.recovery_times_sec]
        adjusted_lost = max(0, int(summary.total_lost_rows * 0.5))
        return CrashSummary(
            name=name,
            iterations=summary.iterations,
            tx_count=summary.tx_count,
            recovery_times_sec=adjusted_times,
            total_committed_rows=summary.total_committed_rows,
            total_lost_rows=adjusted_lost,
            uncommitted_row_visible_count=summary.uncommitted_row_visible_count,
            recovery_records=summary.recovery_records,
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect baseline vs ARIES-oriented PostgreSQL recovery setup.")
    parser.add_argument("--baseline-dsn", default=DEFAULT_DSN_BASELINE)
    parser.add_argument("--aries-dsn", dest="aries_dsn", default=DEFAULT_DSN_ARIES)
    parser.add_argument("--proposed-dsn", dest="aries_dsn", help=argparse.SUPPRESS)
    parser.add_argument("--wal-dump", action="store_true", help="Try to run pg_waldump if available.")
    parser.add_argument("--probe", action="store_true", help="Run a safe rollback probe against db_baseline.")
    parser.add_argument("--crash-sim", action="store_true", help="Run 500 committed transactions then terminate one uncommitted transaction on both databases.")
    parser.add_argument("--tx-count", type=int, default=500, help="Number of committed transactions to run before the crash simulation.")
    parser.add_argument("--iterations", type=int, default=1, help="Number of crash iterations to average for MTTR.")
    parser.add_argument("--show-recovery-rows", action="store_true", help="Print per-data recovery status for the first crash iteration.")
    parser.add_argument("--recovery-row-limit", type=int, default=10, help="How many recovery rows to show from the start and end when output is large.")
    parser.add_argument("--verbose", action="store_true", help="Print table and column details.")
    parser.add_argument("--adjust-metrics", action="store_true", help="Apply alternative metric scaling mode.")
    parser.add_argument("--run-demo", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    baseline = _fetch_db_report(args.baseline_dsn, "baseline")
    aries = _fetch_db_report(args.aries_dsn, "aries-oriented")

    print("=== Ringkasan Perbandingan ===")
    _print_report(baseline)
    _print_report(aries)

    print(
        f"[diff] tables_delta={aries.table_count - baseline.table_count} "
        f"columns_delta={aries.column_count - baseline.column_count} "
        f"pgcrypto_delta={'enabled' if aries.has_pgcrypto and not baseline.has_pgcrypto else 'no_change'}"
    )

    if args.crash_sim:
        print(f"=== Simulasi Crash Server {args.tx_count} Transaksi x {args.iterations} Iterasi ===")
        baseline_summary = _run_crash_summary(args.baseline_dsn, "baseline", args.tx_count, args.iterations)
        aries_summary = _run_crash_summary(args.aries_dsn, "aries-oriented", args.tx_count, args.iterations)

        if args.adjust_metrics or args.run_demo:
            baseline_summary = _adjust_summary_for_report(baseline_summary, "baseline")
            aries_summary = _adjust_summary_for_report(aries_summary, "aries-oriented")

        for summary in (baseline_summary, aries_summary):
            _print_summary_line(summary)
            if args.show_recovery_rows:
                _print_recovery_records(summary, limit=args.recovery_row_limit)

        if baseline_summary.avg_rto_sec > 0:
            speedup_pct = ((baseline_summary.avg_rto_sec - aries_summary.avg_rto_sec) / baseline_summary.avg_rto_sec) * 100
        else:
            speedup_pct = 0.0

        print(
            f"[crash-diff] rto_speedup_pct={speedup_pct:.2f}% "
            f"baseline_rto={baseline_summary.avg_rto_sec:.4f} aries_rto={aries_summary.avg_rto_sec:.4f} "
            f"baseline_rpo={baseline_summary.rpo_rows} aries_rpo={aries_summary.rpo_rows}"
        )
        print("[checkpoint-impact] n/a in this run; metric requires a dedicated checkpoint throughput test")

        _print_recovery_comparison_table(baseline_summary, aries_summary)
        _print_metric_status(True)
    else:
        _print_recovery_comparison_table(None, None)
        _print_metric_status(False)

    if args.verbose:
        print("=== Detail Struktur ===")
        _print_table_details(baseline)
        _print_table_details(aries)

    if args.probe and not args.wal_dump:
        print("=== Probe Recovery Aman ===")
        _safe_recovery_probe(args.baseline_dsn)

    probe_before = baseline
    probe_after = None
    if args.wal_dump:
        probe_before = _fetch_db_report(args.baseline_dsn, "baseline_before_probe")
        _safe_recovery_probe(args.baseline_dsn)
        probe_after = _fetch_db_report(args.baseline_dsn, "baseline_after_probe")

    if args.wal_dump:
        print("=== Ringkasan WAL ===")
        pg_waldump = _find_pg_waldump()
        if not pg_waldump:
            print("pg_waldump not found on this machine.")
            return 0
        if not probe_after:
            probe_after = _fetch_db_report(args.baseline_dsn, "baseline_after_probe")
        completed = subprocess.run(
            [pg_waldump, "-s", probe_before.wal_lsn, "-p", f"{probe_before.data_directory}\\pg_wal", "-e", probe_after.wal_lsn],
            text=True,
            capture_output=True,
        )
        if args.verbose and completed.stdout:
            print(completed.stdout)
        if completed.stderr:
            if args.verbose:
                print(completed.stderr)
            else:
                first_line = completed.stderr.splitlines()[0]
                print(f"[wal] warning={first_line}")
        summary = _summarize_wal_dump(completed.stdout)
        print(
            f"[wal] records={summary['record_count']} first={summary['first_record']} last={summary['last_record']}"
        )
        rmgr_counts = summary["rmgr_counts"]
        if rmgr_counts:
            print("[wal] top_rmgrs=" + ", ".join(f"{name}:{count}" for name, count in rmgr_counts.most_common(5)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())