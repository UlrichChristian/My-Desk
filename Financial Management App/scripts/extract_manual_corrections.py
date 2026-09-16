"""One-shot migration helper: recover every durable fix the old store held.

Run this BEFORE the legacy tables are dropped. It does two things, both
read-only against the old tables:

1. **Translate ``client_mapping_override`` rows into ``ingest_corrections``.**
   Straight shape change — the old table only ever fixed ``client_key``.

2. **Find manual qty/rate edits made directly in the DB.** Re-parses the
   preserved drilldown with the current parser and diffs it against the stored
   ``fact_revenue``. Any row whose stored quantity/rate differs from what the
   file says was edited by hand, and that edit would be silently destroyed by
   the next re-import. Each one is emitted as a *candidate* correction rule for
   review — nothing is written to ``ingest_corrections`` without ``--apply``.

An empty diff is itself a finding: it means the manual fixes were already lost
to an earlier re-import, which is worth knowing before the old tables go.

Usage:
    python scripts/extract_manual_corrections.py --source <upload dir> [--apply]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import pandas as pd  # noqa: E402

from fin_db.connection import DB_PATH  # noqa: E402
from fin_services.reference_data import iso_now  # noqa: E402
from fin_services.revenue_ingest import parse_drilldown  # noqa: E402

# The old override table matched on these; map them onto the new rule columns.
_MATCH_TYPE_TO_COLUMN = {
    "name": "match_name",
    "precustomer": "match_precustomer",
    "memo": "match_memo",
    "memo_contains": "match_memo_contains",
}

_KEY_COLUMNS = ["period", "invoice_no", "product_code", "income_account", "amount"]

# Exclusions confirmed against the source data and signed off by Christian.
# Each needs a reason good enough to justify dropping revenue from a report.
KNOWN_EXCLUSIONS = [
    {
        "period_from": "2026-08",
        "period_to": "2026-08",
        "match_invoice_no": "WFSteel_Deferred_#1",
        "note": (
            "Duplicate journal entry. The WF Steel deferred-revenue recognition "
            "series runs #1-#6 for 2026-02 to 2026-07; this 2026-08 line reuses "
            "reference #1 with the same $1,632 amount, the same description "
            "('1,632 of 20,000') and the same cumulative Balance (618,111.23) as "
            "the February entry. A running balance cannot legitimately repeat, so "
            "this is a copied line, not an August recognition. Confirmed "
            "2026-09-14. Remove at source in QuickBooks."
        ),
    },
]


def migrate_overrides(conn, apply: bool) -> list[dict]:
    """Translate client_mapping_override rows into ingest_corrections rules."""
    try:
        rows = conn.execute(
            "SELECT id, match_type, match_value, client_key, note FROM client_mapping_override"
        ).fetchall()
    except Exception:
        return []

    out = []
    for r in rows:
        column = _MATCH_TYPE_TO_COLUMN.get(r["match_type"])
        if column is None:
            print(f"  ! unknown match_type {r['match_type']!r} on override {r['id']} — skipped")
            continue
        rule = {
            column: r["match_value"],
            "target_field": "client_key",
            "strategy": "set_value",
            "target_text": r["client_key"],
            "note": r["note"] or f"Migrated from client_mapping_override #{r['id']}",
        }
        out.append(rule)
        if apply:
            exists = conn.execute(
                f"SELECT id FROM ingest_corrections WHERE {column} = ? AND target_field='client_key'",
                (r["match_value"],),
            ).fetchone()
            if exists:
                print(f"  = already present: {r['match_value'][:50]!r}")
                continue
            conn.execute(
                f"INSERT INTO ingest_corrections ({column}, target_field, strategy, "
                "target_text, note, created_on, created_by) "
                "VALUES (?, 'client_key', 'set_value', ?, ?, ?, 'migration')",
                (r["match_value"], r["client_key"], rule["note"], iso_now()),
            )
            print(f"  + migrated: {r['match_value'][:50]!r} -> {r['client_key']!r}")
    return out


def seed_known_exclusions(conn, apply: bool) -> int:
    """Insert the reviewed exclusion rules. Idempotent on (invoice_no, period)."""
    added = 0
    for rule in KNOWN_EXCLUSIONS:
        exists = conn.execute(
            "SELECT id FROM ingest_corrections WHERE target_field='exclude' "
            "AND match_invoice_no = ? AND COALESCE(period_from,'') = ?",
            (rule["match_invoice_no"], rule.get("period_from") or ""),
        ).fetchone()
        if exists:
            print(f"  = already present: {rule['match_invoice_no']}")
            continue
        added += 1
        if not apply:
            print(f"  ~ would add exclusion: {rule['match_invoice_no']} "
                  f"({rule.get('period_from')})")
            continue
        conn.execute(
            "INSERT INTO ingest_corrections (period_from, period_to, match_invoice_no, "
            "target_field, strategy, note, created_on, created_by) "
            "VALUES (?,?,?, 'exclude', 'set_value', ?, ?, 'migration')",
            (rule.get("period_from"), rule.get("period_to"), rule["match_invoice_no"],
             rule["note"], iso_now()),
        )
        print(f"  + excluded: {rule['match_invoice_no']} ({rule.get('period_from')})")
    return added


def find_manual_edits(conn, drilldown_path: Path) -> pd.DataFrame:
    """Diff stored fact_revenue qty/rate against a fresh parse of the source."""
    parsed = parse_drilldown(drilldown_path)
    parsed = parsed.assign(
        invoice_no=parsed["invoice_no"].astype(str),
        product_code=parsed["product_code"].astype(str),
        income_account=parsed["income_account"].astype(str),
        amount=parsed["amount"].round(2),
    )

    stored = pd.DataFrame(
        conn.execute(
            "SELECT period, invoice_no, product_code, income_account, amount, quantity, rate "
            "FROM fact_revenue"
        ).fetchall(),
        columns=_KEY_COLUMNS + ["quantity", "rate"],
    )
    if stored.empty:
        return stored
    stored = stored.assign(
        invoice_no=stored["invoice_no"].astype(str),
        product_code=stored["product_code"].astype(str),
        income_account=stored["income_account"].astype(str),
        amount=stored["amount"].round(2),
    )

    # The key is NOT unique — a single (period, invoice, product, account, amount)
    # can cover many lines. A row-wise merge would pair them arbitrarily and
    # report every such group as edited. Compare the sorted multiset of
    # (quantity, rate) pairs within each group instead, so only a group whose
    # contents genuinely differ is flagged.
    def _bag(df):
        out = {}
        for key, grp in df.groupby(_KEY_COLUMNS, dropna=False):
            pairs = [
                (
                    None if pd.isna(q) else round(float(q), 4),
                    None if pd.isna(r) else round(float(r), 4),
                )
                for q, r in zip(grp["quantity"], grp["rate"])
            ]
            # NULL quantity/rate is common, so sort with None ordered first
            # rather than letting it collide with a float comparison.
            out[key] = sorted(
                pairs,
                key=lambda p: (p[0] is None, p[0] or 0.0, p[1] is None, p[1] or 0.0),
            )
        return out

    db_bags, file_bags = _bag(stored), _bag(parsed)

    rows = []
    for key, db_pairs in db_bags.items():
        file_pairs = file_bags.get(key)
        if file_pairs is not None and db_pairs == file_pairs:
            continue
        rows.append({
            **dict(zip(_KEY_COLUMNS, key)),
            "rows_db": len(db_pairs),
            "rows_file": 0 if file_pairs is None else len(file_pairs),
            "qty_rate_db": db_pairs,
            "qty_rate_file": file_pairs,
        })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True,
                    help="upload dir holding the preserved Transaction_Drilldown_Report.xlsx")
    ap.add_argument("--apply", action="store_true",
                    help="write the migrated override rules (candidates are never auto-written)")
    args = ap.parse_args()

    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print(f"DB: {DB_PATH}\n")

    print("1. client_mapping_override -> ingest_corrections")
    rules = migrate_overrides(conn, args.apply)
    if not rules:
        print("  (none found)")
    elif not args.apply:
        print(f"  {len(rules)} rule(s) would be migrated — re-run with --apply")
    print()

    print("2. reviewed exclusions")
    if not seed_known_exclusions(conn, args.apply):
        print("  (nothing new)")
    print()

    drilldown = next(Path(args.source).glob("*Drilldown*.xlsx"), None)
    if drilldown is None:
        print(f"! no *Drilldown*.xlsx in {args.source} — skipping the manual-edit diff")
        conn.commit()
        return 1

    print(f"3. manual qty/rate edits  (vs {drilldown.name})")
    edits = find_manual_edits(conn, drilldown)
    if edits.empty:
        print("  NONE FOUND.")
        print("  Either no manual edits were ever made, or an earlier re-import")
        print("  already destroyed them. Worth confirming before the old tables go.")
    else:
        print(f"  {len(edits)} row(s) differ from the source file:\n")
        by_period = edits.groupby("period").size()
        for period, n in by_period.items():
            print(f"    {period}: {n} row(s)")
        print()
        cols = ["period", "invoice_no", "product_code", "amount",
                "rows_db", "rows_file", "qty_rate_db", "qty_rate_file"]
        print(edits[cols].head(30).to_string(index=False))
        out = Path(args.source) / "manual_edit_candidates.csv"
        edits[cols].to_csv(out, index=False)
        print(f"\n  full list written to {out}")
        print("  Review, then add the ones to keep as ingest_corrections rules.")

    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
