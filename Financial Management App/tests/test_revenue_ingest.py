"""Unit tests for drilldown normalization and DB load rules."""

from __future__ import annotations

import pandas as pd
import pytest

from fin_services.revenue_ingest import load_import, normalize_drilldown
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
        {"NAME": "Acme", "GROUP ID": "Acme", "SYSTEM ID": "SysA", "ACCOUNT ID": "1"},
    ])
    accounts = pd.DataFrame([
        {
            "name": "Acme",
            "oid": "1",
            "livesCount": 2,
            "monthlyPremium": 100.0,
            "brokerList": "Adv",
            "consultingHouses": None,
            "isActive": "true",
            "benefitType": None,
        }
    ])
    drill = normalize_drilldown(_raw_drilldown_rows())
    enriched = enrich(drill, account_list, accounts)

    first = load_import(conn, enriched, accounts, {"drilldown": "a.xlsx"})
    assert first["revenue_rows"] == 1
    assert conn.execute("SELECT COUNT(*) FROM fact_revenue").fetchone()[0] == 1

    # Second import for same period replaces rows
    enriched2 = enriched.copy()
    enriched2["amount"] = 999.0
    second = load_import(conn, enriched2, accounts, {"drilldown": "b.xlsx"})
    assert second["import_id"] != first["import_id"]
    assert conn.execute("SELECT COUNT(*) FROM fact_revenue").fetchone()[0] == 1
    amt = conn.execute("SELECT amount FROM fact_revenue").fetchone()[0]
    assert amt == 999.0
    assert conn.execute("SELECT COUNT(*) FROM import_batch").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM account_snapshot").fetchone()[0] == 2
