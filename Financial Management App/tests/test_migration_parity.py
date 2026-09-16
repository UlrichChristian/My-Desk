"""Merge gate for the schema refactor.

Loads the preserved source files through the NEW pipeline and asserts the result
matches what the OLD ``fact_revenue`` store holds, to the cent.

The refactor changes attribution from a derived string (``client_key``) to a
foreign key resolved through the account, replaces a hardcoded exclusion set with
a table flag, and moves premium/lives to ``account_period_metrics``. Any one of
those alone would shift numbers; together, across 85,847 rows and 13 periods, a
regression would be invisible. This test is what makes it visible.

Skipped automatically when the preserved upload or the legacy DB is not present,
so it never breaks a clean checkout.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fin_db.init_db import _SCHEMA, migrate_schema  # noqa: E402
from fin_services.reference_data import iso_now  # noqa: E402
from fin_services.revenue_ingest import (  # noqa: E402
    load_import,
    parse_account_list,
    parse_accounts,
    parse_drilldown,
)
from fin_services.revenue_mapping import enrich  # noqa: E402

LEGACY_DB = Path(r"C:\Christian\Financial Management App\financial.db")
SOURCE_DIR = Path(
    r"C:\Christian\Financial Management App\uploads\revenue_20260902_152747_e5add880"
)

# Differences that are real, understood, and deliberately accepted. Anything not
# listed here failing the gate is a regression.
KNOWN_ATTRIBUTION_CHANGES: dict[str, str] = {
    # (none — the WFSteel duplicate is handled by an ingest_corrections exclusion
    # rule rather than being tolerated here, so the totals tie exactly.)
}

EXCLUDED = ("Referral Fees:Email Feed", "Statement of Work")

pytestmark = pytest.mark.skipif(
    not LEGACY_DB.exists() or not SOURCE_DIR.exists(),
    reason="legacy financial.db or preserved upload not available",
)


@pytest.fixture(scope="module")
def loaded():
    """A copy of the legacy DB with the new pipeline loaded alongside it."""
    tmp = Path(tempfile.gettempdir()) / "fin_migration_parity.db"
    if tmp.exists():
        os.remove(tmp)
    shutil.copy(LEGACY_DB, tmp)

    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    migrate_schema(conn)

    # The two durable fixes the old store held, as the migration script writes them.
    now = iso_now()
    conn.execute(
        "INSERT INTO ingest_corrections (match_memo_contains, target_field, strategy, "
        "target_text, note, created_on, created_by) VALUES (?,?,?,?,?,?, 'migration')",
        ("Recognized Deferred Revenue - GST applied on DES invoice", "client_key",
         "set_value", "WF Steel and Crane",
         "Blank-name deferred DES recognition JE -> WF Steel", now),
    )
    conn.execute(
        "INSERT INTO ingest_corrections (period_from, period_to, match_invoice_no, "
        "target_field, strategy, note, created_on, created_by) "
        "VALUES (?,?,?, 'exclude', 'set_value', ?, ?, 'migration')",
        ("2026-08", "2026-08", "WFSteel_Deferred_#1",
         "Duplicate journal entry — reuses reference #1 with February's amount, "
         "description and cumulative balance.", now),
    )
    conn.commit()

    drilldown = parse_drilldown(SOURCE_DIR / "Transaction_Drilldown_Report.xlsx")
    account_list = parse_account_list(SOURCE_DIR / "Custom_Account_List.xlsx")
    accounts = parse_accounts(SOURCE_DIR / "ea_accounts.csv")
    rules = [dict(r) for r in conn.execute(
        "SELECT * FROM ingest_corrections WHERE status = 'active'")]
    enriched = enrich(drilldown, account_list, accounts, corrections=rules)

    # all_periods reproduces the old (wrong) premium behaviour on purpose: this
    # gate tests attribution, and the vintaging fix ships separately so a
    # screen-filling blank column cannot camouflage a revenue regression.
    result = load_import(
        conn, enriched, accounts, account_list,
        files={"source": SOURCE_DIR.name}, metrics_mode="all_periods",
    )
    yield conn, result
    conn.close()


def _old(conn, sql, *params):
    return conn.execute(sql, params).fetchall()


def test_row_count_matches(loaded):
    conn, _ = loaded
    old = conn.execute("SELECT COUNT(*) FROM fact_revenue").fetchone()[0]
    new = conn.execute("SELECT COUNT(*) FROM revenue_lines").fetchone()[0]
    assert new == old


def test_revenue_per_period_ties_to_the_cent(loaded):
    conn, _ = loaded
    old = {r[0]: (r[1], round(r[2], 2)) for r in _old(
        conn,
        "SELECT period, COUNT(*), SUM(amount) FROM fact_revenue "
        "WHERE COALESCE(income_account,'') NOT IN (?,?) GROUP BY period", *EXCLUDED)}
    new = {r[0]: (r[1], round(r[2], 2)) for r in conn.execute(
        "SELECT rl.period, COUNT(*), SUM(rl.amount) FROM revenue_lines rl "
        "JOIN income_accounts ia ON ia.id = rl.income_account_id "
        "WHERE ia.exclude_from_reports = 0 GROUP BY rl.period")}
    assert set(new) == set(old)
    mismatches = {p: (old[p], new[p]) for p in old if old[p] != new[p]}
    assert not mismatches, f"period totals moved: {mismatches}"


def test_revenue_per_income_account_ties(loaded):
    """Catches a mistake in the exclusion flags specifically."""
    conn, _ = loaded
    old = {(r[0], r[1]): round(r[2], 2) for r in conn.execute(
        "SELECT period, income_account, SUM(amount) FROM fact_revenue "
        "GROUP BY period, income_account")}
    new = {(r[0], r[1]): round(r[2], 2) for r in conn.execute(
        "SELECT period, income_account_raw, SUM(amount) FROM revenue_lines "
        "GROUP BY period, income_account_raw")}
    diffs = {k: (old.get(k), new.get(k)) for k in set(old) | set(new)
             if abs((old.get(k) or 0) - (new.get(k) or 0)) > 0.005}
    assert not diffs, f"income-account totals moved: {diffs}"


def test_client_attribution_is_unchanged(loaded):
    conn, _ = loaded
    old = {r[0]: round(r[1], 2) for r in _old(
        conn,
        "SELECT client_key, SUM(amount) FROM fact_revenue "
        "WHERE COALESCE(income_account,'') NOT IN (?,?) GROUP BY client_key", *EXCLUDED)}
    new = {r[0]: round(r[1], 2) for r in conn.execute(
        "SELECT c.display_name, SUM(rl.amount) FROM revenue_lines rl "
        "JOIN income_accounts ia ON ia.id = rl.income_account_id "
        "LEFT JOIN clients c ON c.id = rl.client_id "
        "WHERE ia.exclude_from_reports = 0 GROUP BY c.display_name")}

    diffs = {
        k: (old.get(k), new.get(k))
        for k in set(old) | set(new)
        if abs((old.get(k) or 0) - (new.get(k) or 0)) > 0.005
        and k not in KNOWN_ATTRIBUTION_CHANGES
    }
    assert not diffs, (
        "client attribution moved without an entry in KNOWN_ATTRIBUTION_CHANGES: "
        f"{dict(list(diffs.items())[:10])}"
    )


def test_account_spine_covers_every_account_both_ways(loaded):
    conn, _ = loaded
    spine = {r[0] for r in conn.execute("SELECT oid FROM accounts")}
    legacy = {str(r[0]) for r in conn.execute(
        "SELECT DISTINCT oid FROM account_snapshot WHERE import_id = "
        "(SELECT MAX(import_id) FROM account_snapshot) AND oid IS NOT NULL")}
    assert spine == legacy, (
        f"only in spine: {sorted(spine - legacy)[:5]}, "
        f"only in legacy: {sorted(legacy - spine)[:5]}"
    )


def test_unresolved_rows_do_not_regress(loaded):
    """The name-fallback join was removed; the residue must not grow."""
    conn, result = loaded
    assert result["unresolved"] <= 38, (
        f"{result['unresolved']} rows failed to resolve to an account, was 38"
    )


def test_every_correction_rule_actually_fired(loaded):
    """A rule matching nothing is a silently dead fix."""
    conn, _ = loaded
    dead = [dict(r) for r in conn.execute(
        "SELECT id, target_field, note FROM ingest_corrections "
        "WHERE status = 'active' AND applied_count = 0")]
    assert not dead, f"correction rules matched no rows: {dead}"


def test_reference_spine_is_populated(loaded):
    conn, _ = loaded
    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("clients", "accounts", "advisors", "consulting_houses",
                  "carriers", "account_policies", "products", "income_accounts")
    }
    assert counts["accounts"] == 1492
    assert counts["clients"] == 492
    assert counts["carriers"] == 47
    assert counts["products"] == 148
    assert counts["account_policies"] == 5170
    # The dimension layer this refactor replaced held 0 rows in every table.
    assert all(v > 0 for v in counts.values()), counts


def test_reimport_does_not_duplicate_the_spine(loaded):
    """The spine is upsert-only — a second import must not grow it."""
    conn, _ = loaded
    before = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("clients", "accounts", "carriers", "account_policies", "products")
    }
    drilldown = parse_drilldown(SOURCE_DIR / "Transaction_Drilldown_Report.xlsx")
    account_list = parse_account_list(SOURCE_DIR / "Custom_Account_List.xlsx")
    accounts = parse_accounts(SOURCE_DIR / "ea_accounts.csv")
    rules = [dict(r) for r in conn.execute(
        "SELECT * FROM ingest_corrections WHERE status = 'active'")]
    load_import(
        conn, enrich(drilldown, account_list, accounts, corrections=rules),
        accounts, account_list, files={}, metrics_mode="all_periods",
    )
    after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
    assert after == before
