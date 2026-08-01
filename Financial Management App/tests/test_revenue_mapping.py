"""Unit tests for PreCustomer resolution and enrich joins."""

from __future__ import annotations

import pandas as pd

from fin_services.revenue_mapping import VENDOR_ACCOUNT, enrich, resolve_precustomer


def test_resolve_group_system_id_after_colon():
    assert resolve_precustomer(
        "New Gold:Rainy River", None, "", "Admin Fees earned on Premium", {}
    ) == "Rainy River"


def test_resolve_prefers_customer_when_present():
    assert resolve_precustomer(
        "Ignored:X", "Group:SysId", "", "Admin Fees", {}
    ) == "SysId"


def test_resolve_vendor_strips_admin_fee_suffix():
    assert resolve_precustomer(
        "VendorCo", None, "Viacore Union Admin Fee", VENDOR_ACCOUNT, {}
    ) == "Viacore Union"


def test_resolve_vendor_keeps_non_suffix_memo():
    assert resolve_precustomer(
        "VendorCo", None, "Something else", VENDOR_ACCOUNT, {}
    ) == "Something else"


def test_resolve_asoc_looks_up_system_id():
    sysid_by_name = {"Acme Corp": "SYS-1"}
    assert resolve_precustomer(
        "Payer:ASOC",
        None,
        "Fee, Acme Corp - monthly",
        "Admin Fees",
        sysid_by_name,
    ) == "SYS-1"


def test_resolve_plain_name_without_colon():
    assert resolve_precustomer("Plain Client", None, "", "Admin Fees", {}) == "Plain Client"


def test_enrich_joins_system_id_and_oid():
    drilldown = pd.DataFrame([
        {
            "name": "Group:Rainy River",
            "customer": "Group:Rainy River",
            "memo": "",
            "income_account": "Admin Fees earned on Premium",
            "amount": 100.0,
            "quantity": 1.0,
            "rate": 100.0,
            "txn_date": "2026-03-01",
            "period": "2026-03",
            "txn_type": "Invoice",
            "invoice_no": "1",
            "product_code": "ADMIN",
            "item_split": None,
        },
        {
            "name": "Group:Rainy River",
            "customer": "Group:Rainy River",
            "memo": "",
            "income_account": "Admin Fees earned on Premium",
            "amount": 50.0,
            "quantity": 1.0,
            "rate": 50.0,
            "txn_date": "2026-03-02",
            "period": "2026-03",
            "txn_type": "Invoice",
            "invoice_no": "2",
            "product_code": "ADMIN",
            "item_split": None,
        },
    ])
    account_list = pd.DataFrame([
        {
            "NAME": "New Gold",
            "GROUP ID": "New Gold",
            "SYSTEM ID": "Rainy River",
            "ACCOUNT ID": "2850",
        }
    ])
    accounts = pd.DataFrame([
        {
            "name": "New Gold",
            "oid": "2850",
            "livesCount": 10,
            "monthlyPremium": 1000.0,
            "brokerList": "Jane Advisor",
            "consultingHouses": None,
        }
    ])

    out = enrich(drilldown, account_list, accounts)
    assert list(out["client_key"].unique()) == ["New Gold"]
    assert list(out["oid"].astype(str).unique()) == ["2850"]
    assert out["advisor"].iloc[0] == "Jane Advisor"
    # Two lines for same oid+period → premium/lives split in half each
    assert out["premium_split"].tolist() == [500.0, 500.0]
    assert out["lives_split"].tolist() == [5.0, 5.0]


def test_enrich_name_override():
    drilldown = pd.DataFrame([
        {
            "name": "Odd Name",
            "customer": "Odd Name",
            "memo": "",
            "income_account": "Admin Fees",
            "amount": 10.0,
            "quantity": 1.0,
            "rate": 10.0,
            "txn_date": "2026-03-01",
            "period": "2026-03",
            "txn_type": "Invoice",
            "invoice_no": "1",
            "product_code": "ADMIN",
            "item_split": None,
        }
    ])
    account_list = pd.DataFrame(columns=["NAME", "GROUP ID", "SYSTEM ID", "ACCOUNT ID"])
    accounts = pd.DataFrame(columns=[
        "name", "oid", "livesCount", "monthlyPremium", "brokerList", "consultingHouses",
    ])
    out = enrich(
        drilldown,
        account_list,
        accounts,
        overrides=[{"match_type": "name", "match_value": "Odd Name", "client_key": "Fixed"}],
    )
    assert out["client_key"].iloc[0] == "Fixed"


def test_enrich_memo_contains_override():
    drilldown = pd.DataFrame([
        {
            "name": None,
            "customer": None,
            "memo": "Recognized Deferred Revenue - GST applied on DES invoice 8,376 of 20,000",
            "income_account": "Admin Fees (earned on Sub. Fees)",
            "amount": 1656.0,
            "quantity": None,
            "rate": None,
            "txn_date": "2026-06-15",
            "period": "2026-06",
            "txn_type": "Journal Entry",
            "invoice_no": None,
            "product_code": None,
            "item_split": None,
        }
    ])
    account_list = pd.DataFrame(columns=["NAME", "GROUP ID", "SYSTEM ID", "ACCOUNT ID"])
    accounts = pd.DataFrame(columns=[
        "name", "oid", "livesCount", "monthlyPremium", "brokerList", "consultingHouses",
    ])
    out = enrich(
        drilldown,
        account_list,
        accounts,
        overrides=[{
            "match_type": "memo_contains",
            "match_value": "Recognized Deferred Revenue - GST applied on DES invoice",
            "client_key": "WF Steel and Crane",
        }],
    )
    assert out["client_key"].iloc[0] == "WF Steel and Crane"
