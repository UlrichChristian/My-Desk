"""Deploy B: drop pre-2026-07 account_period_metrics from the live store.

Those rows were written with metrics_mode='all_periods' for the Deploy A
parity gate, so every historical month carries today's premium. After this
delete, historical Revenue/Premium renders blank. July 2026 onward is kept.

Usage:
    python scripts/apply_vintaging.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from fin_db.connection import DB_PATH  # noqa: E402
from fin_services.revenue_ingest import (  # noqa: E402
    VINTAGE_KEEP_FROM,
    drop_pre_vintage_metrics,
)


def _counts(conn):
    return conn.execute(
        "SELECT period, source, COUNT(*) FROM account_period_metrics "
        "GROUP BY period, source ORDER BY period"
    ).fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be deleted without writing.",
    )
    args = parser.parse_args()

    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    print(f"DB {DB_PATH}")
    print("before:")
    for row in _counts(conn):
        print(f"  {row[0]}  {row[1]}  {row[2]}")

    doomed = conn.execute(
        "SELECT COUNT(*) FROM account_period_metrics WHERE period < ?",
        (VINTAGE_KEEP_FROM,),
    ).fetchone()[0]
    print(f"would delete {doomed} row(s) with period < {VINTAGE_KEEP_FROM}")

    if args.dry_run:
        print("dry-run: no changes")
        return 0

    deleted = drop_pre_vintage_metrics(conn)
    print(f"deleted {deleted}")
    print("after:")
    for row in _counts(conn):
        print(f"  {row[0]}  {row[1]}  {row[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
