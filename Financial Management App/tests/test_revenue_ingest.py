"""Unit tests for drilldown normalization and DB load rules."""

from __future__ import annotations

import pandas as pd
import pytest

from fin_services.revenue_ingest import (
    drop_pre_vintage_metrics,
    load_import,
    normalize_drilldown,
)
from fin_services.revenue_mapping import enrich


def _raw_drilldown_rows():
    return pd.DataFrame([
        {
            "Transaction date": "2026-03-15",
            "Transaction type": "Invoice",
            "#": "100",
            "Name": "Group:SysA",
            "Customer": "Group:SysA",
            "Memo/Description": "",
            "Account Name": "Admin Fees earned on Premium",
            "Item split account": None,
            "Amount": "250.00",
            "Product/Service": "ADMIN",
            "Quantity": "5",
            "Rate": "50",
        },
        {
            "Transaction date": None,  # header/group row — dropped
            "Transaction type": None,
            "#": None,
            "Name": None,
            "Customer": None,
            "Memo/Description": None,
            "Account Name": "Income",
            "Item split account": None,
            "Amount": None,
            "Product/Service": None,
            "Quantity": None,
            "Rate": None,
        },
    ])


def test_normalize_drilldown_keeps_dated_rows_and_sets_period():
    out = normalize_drilldown(_raw_drilldown_rows())
    assert len(out) == 1
    assert out.loc[0, "period"] == "2026-03"
    assert out.loc[0, "amount"] == 250.0
    assert out.loc[0, "quantity"] == 5.0
    assert out.loc[0, "rate"] == 50.0
    assert out.loc[0, "income_account"] == "Admin Fees earned on Premium"


def test_normalize_drilldown_requires_date_and_income_col():
    with pytest.raises(ValueError, match="missing expected columns"):
        normalize_drilldown(pd.DataFrame({"Amount": [1]}))


def test_load_import_replace_by_period(conn):
    account_list = pd.DataFrame([
        {"NAME": "Acme", "GROUP ID": "Acme", "SYSTEM ID": "SysA", "ACCOUNT ID": "1",
         "LEGAL NAME": "Acme Inc"},
    ])
    accounts = pd.DataFrame([
        {
            "name": "Acme",
            "oid": "1",
            "livesCount": 2,
            "monthlyPremium": 100.0,
            "brokerList": "Adv",
            "consultingHouses": "House A",
            "policies": "Carrier X - 123-Life",
            "isActive": "true",
            "isUpdating": "false",
            "benefitType": "Standard Group Benefits",
        }
    ])
    drill = normalize_drilldown(_raw_drilldown_rows())
    enriched = enrich(drill, account_list, accounts)

    first = load_import(conn, enriched, accounts, account_list, {"drilldown": "a.xlsx"})
    assert first["revenue_rows"] == 1
    assert conn.execute("SELECT COUNT(*) FROM revenue_lines").fetchone()[0] == 1

    # Second import for the same period replaces the fact rows...
    enriched2 = enrich(drill, account_list, accounts)
    enriched2["amount"] = 999.0
    second = load_import(conn, enriched2, accounts, account_list, {"drilldown": "b.xlsx"})
    assert second["import_id"] != first["import_id"]
    assert conn.execute("SELECT COUNT(*) FROM revenue_lines").fetchone()[0] == 1
    assert conn.execute("SELECT amount FROM revenue_lines").fetchone()[0] == 999.0
    assert conn.execute("SELECT COUNT(*) FROM revenue_imports").fetchone()[0] == 2


def test_load_import_upserts_spine_without_duplicating(conn):
    """The reference spine is upsert-only — re-importing must not duplicate it."""
    account_list = pd.DataFrame([
        {"NAME": "Acme", "GROUP ID": "Acme", "SYSTEM ID": "SysA", "ACCOUNT ID": "1",
         "LEGAL NAME": "Acme Inc"},
    ])
    accounts = pd.DataFrame([
        {
            "name": "Acme", "oid": "1", "livesCount": 2, "monthlyPremium": 100.0,
            "brokerList": "Adv", "consultingHouses": "House A",
            "policies": "Carrier X - 123-Life | Carrier Y - 999",
            "isActive": "true", "isUpdating": "false", "benefitType": "Standard",
        }
    ])
    drill = normalize_drilldown(_raw_drilldown_rows())

    def counts():
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("accounts", "clients", "client_keys", "advisors",
                      "consulting_houses", "carriers", "account_policies")
        }

    load_import(conn, enrich(drill, account_list, accounts), accounts, account_list, {})
    after_first = counts()
    load_import(conn, enrich(drill, account_list, accounts), accounts, account_list, {})
    assert counts() == after_first
    assert after_first["carriers"] == 2
    assert after_first["account_policies"] == 2

    # The benefit suffix is read from an allowlist; "999" must not become one.
    lines = dict(conn.execute(
        "SELECT policy_no, benefit_line FROM account_policies").fetchall())
    assert lines["123-Life"] == "Life"
    assert lines["999"] is None


def test_load_import_writes_metrics_for_latest_period_only(conn):
    """The accounts CSV describes one month, so only that month gets metrics."""
    account_list = pd.DataFrame([
        {"NAME": "Acme", "GROUP ID": "Acme", "SYSTEM ID": "SysA", "ACCOUNT ID": "1",
         "LEGAL NAME": None},
    ])
    accounts = pd.DataFrame([
        {"name": "Acme", "oid": "1", "livesCount": 2, "monthlyPremium": 100.0,
         "brokerList": "Adv", "consultingHouses": None, "policies": None,
         "isActive": "true", "isUpdating": "false", "benefitType": None}
    ])
    drill = normalize_drilldown(_raw_drilldown_rows())
    two_months = pd.concat([drill, drill.assign(period="2026-04")], ignore_index=True)

    load_import(conn, enrich(two_months, account_list, accounts), accounts, account_list, {})
    periods = [r[0] for r in conn.execute(
        "SELECT period FROM account_period_metrics ORDER BY period")]
    assert periods == ["2026-04"], "older periods must stay blank, not inherit today's premium"


def test_drop_pre_vintage_metrics_keeps_july_onward(conn):
    """Deploy B: estimated history before 2026-07 is deleted; later months stay."""
    now = "2026-09-01T00:00:00Z"
    cid = conn.execute(
        "INSERT INTO clients (display_name, status, created_on) VALUES ('Acme','active',?)",
        (now,),
    ).lastrowid
    aid = conn.execute(
        "INSERT INTO accounts (oid, name, client_id, status, created_on) VALUES ('1','Acme',?,'active',?)",
        (cid, now),
    ).lastrowid
    imp = conn.execute(
        "INSERT INTO revenue_imports (source, files_json, row_counts_json, status, created_on) "
        "VALUES ('drilldown','{}','{}','loaded',?)",
        (now,),
    ).lastrowid
    for period in ("2026-05", "2026-06", "2026-07", "2026-08"):
        conn.execute(
            "INSERT INTO account_period_metrics (account_id, period, lives, premium, "
            "source, captured_on, import_id, created_on) VALUES (?,?,?,?,?,?,?,?)",
            (aid, period, 2, 100.0, "estimated", now, imp, now),
        )
    conn.commit()

    deleted = drop_pre_vintage_metrics(conn)
    kept = [r[0] for r in conn.execute(
        "SELECT period FROM account_period_metrics ORDER BY period")]
    assert deleted == 2
    assert kept == ["2026-07", "2026-08"]


def test_migrate_schema_applies_vintaging(conn):
    """App start / every connection must apply Deploy B, not only a one-shot script."""
    from fin_db.init_db import migrate_schema

    now = "2026-09-01T00:00:00Z"
    cid = conn.execute(
        "INSERT INTO clients (display_name, status, created_on) VALUES ('Acme','active',?)",
        (now,),
    ).lastrowid
    aid = conn.execute(
        "INSERT INTO accounts (oid, name, client_id, status, created_on) VALUES ('1','Acme',?,'active',?)",
        (cid, now),
    ).lastrowid
    conn.execute(
        "INSERT INTO account_period_metrics (account_id, period, lives, premium, "
        "source, captured_on, created_on) VALUES (?,?,?,?,?,?,?)",
        (aid, "2026-06", 2, 100.0, "estimated", now, now),
    )
    conn.commit()

    migrate_schema(conn)
    periods = [r[0] for r in conn.execute("SELECT period FROM account_period_metrics")]
    assert periods == []


def test_load_import_excludes_rows_matched_by_a_correction(conn):
    account_list = pd.DataFrame([
        {"NAME": "Acme", "GROUP ID": "Acme", "SYSTEM ID": "SysA", "ACCOUNT ID": "1",
         "LEGAL NAME": None},
    ])
    accounts = pd.DataFrame([
        {"name": "Acme", "oid": "1", "livesCount": 2, "monthlyPremium": 100.0,
         "brokerList": "Adv", "consultingHouses": None, "policies": None,
         "isActive": "true", "isUpdating": "false", "benefitType": None}
    ])
    drill = normalize_drilldown(_raw_drilldown_rows())
    rule = {"id": 1, "match_invoice_no": "100", "target_field": "exclude",
            "strategy": "set_value", "status": "active"}
    enriched = enrich(drill, account_list, accounts, corrections=[rule])

    res = load_import(conn, enriched, accounts, account_list, {})
    assert res["excluded"] == 1
    assert conn.execute("SELECT COUNT(*) FROM revenue_lines").fetchone()[0] == 0
