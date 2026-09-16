"""Unit tests for HRIS / payroll integration tracking.

Matches the live service: one row per (client, vendor, role), client-keyed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from fin_services.account_integrations import (
    IntegrationError,
    client_role_flags,
    client_rollup,
    coverage_summary,
    create_integration,
    import_integration_sheet,
    integration_overview,
    resolve_vendor,
    retire_integration,
)

_NOW = "2026-01-01T00:00:00Z"


def _seed_account(conn, oid="100", name="Acme Ltd", client="Acme", status="active"):
    cid = conn.execute(
        "INSERT INTO clients (display_name, status, created_on) VALUES (?, 'active', ?)",
        (client, _NOW),
    ).lastrowid
    aid = conn.execute(
        "INSERT INTO accounts (oid, name, client_id, status, created_on) VALUES (?,?,?,?,?)",
        (oid, name, cid, status, _NOW),
    ).lastrowid
    conn.commit()
    return aid


def _add(conn, client="Acme", vendor="ADP", role="payroll", **kwargs):
    return create_integration(
        conn, client=client, vendor_name=vendor, role=role, **kwargs
    )


# --------------------------------------------------------------------- vendors


def test_resolve_vendor_matches_catalogue_name(conn):
    vid, raw = resolve_vendor(conn, "ADP")
    assert vid is not None and raw is None


def test_resolve_vendor_matches_alias_case_insensitively(conn):
    vid, raw = resolve_vendor(conn, "adp workforce now")
    named = conn.execute("SELECT name FROM integration_vendors WHERE id = ?", (vid,)).fetchone()
    assert named["name"] == "ADP"
    assert raw is None


def test_resolve_vendor_keeps_unknown_name_as_raw(conn):
    """A locked catalogue would stop data entry dead on the first new vendor."""
    vid, raw = resolve_vendor(conn, "Some Niche HRIS")
    assert vid is None
    assert raw == "Some Niche HRIS"


# ------------------------------------------------------------------ validation


def test_create_rejects_unknown_role(conn):
    _seed_account(conn)
    with pytest.raises(IntegrationError, match="role must"):
        create_integration(conn, client="Acme", vendor_name="ADP", role="both")


def test_create_rejects_unknown_account_oid(conn):
    _seed_account(conn)
    with pytest.raises(IntegrationError, match="No account"):
        _add(conn, oid="999")


def test_overlapping_windows_are_rejected(conn):
    _seed_account(conn)
    _add(conn, effective_from="2026-01-01")
    with pytest.raises(IntegrationError, match="Overlaps"):
        _add(conn, effective_from="2026-06-01")


def test_sequential_windows_are_allowed(conn):
    """Closing the old row first is the supported way to change vendor."""
    _seed_account(conn)
    first = _add(conn, effective_from="2026-01-01")
    retire_integration(conn, first, effective_to="2026-06-01")
    second = _add(conn, vendor="Workday", role="hris", effective_from="2026-06-01")
    assert second != first


def test_one_system_serving_both_is_two_rows(conn):
    """Status belongs to the role, so payroll + HRIS on Dayforce is two rows."""
    _seed_account(conn)
    _add(conn, vendor="Ceridian Dayforce", role="payroll")
    _add(conn, vendor="Ceridian Dayforce", role="hris")
    rows = [r for r in integration_overview(conn) if r["integration_id"]]
    assert {r["role"] for r in rows} == {"payroll", "hris"}
    assert {r["vendor"] for r in rows} == {"Ceridian Dayforce"}


# -------------------------------------------------------------------- overview


def test_overview_left_joins_so_clients_without_one_appear(conn):
    """Absence is the answer to 'who still needs an integration'."""
    _seed_account(conn, oid="100", name="Has One")
    _seed_account(conn, oid="200", name="Has None", client="Beta")
    _add(conn)

    rows = integration_overview(conn)
    without = [r for r in rows if r["integration_id"] is None]
    assert [r["client"] for r in without] == ["Beta"]


def test_overview_excludes_clients_with_only_terminated_accounts(conn):
    _seed_account(conn, oid="100", name="Live", client="Live")
    _seed_account(conn, oid="200", name="Gone", client="Gone", status="terminated")
    names = {r["client"] for r in integration_overview(conn)}
    assert names == {"Live"}


def test_retired_integration_drops_off_the_overview(conn):
    _seed_account(conn)
    iid = _add(conn)
    retire_integration(conn, iid)
    assert integration_overview(conn)[0]["integration_id"] is None


def test_coverage_summary_counts_clients(conn):
    _seed_account(conn, oid="100", name="A", client="Acme")
    _seed_account(conn, oid="200", name="B", client="Beta")
    _seed_account(conn, oid="300", name="C", client="Gamma")
    _add(conn, client="Acme", role="payroll")
    _add(conn, client="Beta", role="payroll")
    _add(conn, client="Beta", role="hris")

    s = coverage_summary(conn)
    assert s["clients"] == 3
    assert s["with_integration"] == 2
    assert s["without_integration"] == 1
    assert s["payroll"] == 2 and s["hris"] == 1
    assert s["by_vendor"] == {"ADP": 2}


def test_client_rollup_collapses_roles_on_one_system(conn):
    _seed_account(conn, oid="100", name="Div 1", client="BigCo")
    _seed_account(conn, oid="200", name="Div 2", client="BigCo")
    _add(conn, client="BigCo", role="payroll")
    _add(conn, client="BigCo", role="hris")

    rows = client_rollup(conn)
    assert len(rows) == 1
    assert rows[0]["client"] == "BigCo"
    assert rows[0]["payroll"] == 1 and rows[0]["hris"] == 1


# ---------------------------------------------------------------- sheet import


def test_import_sheet_by_client_and_role(conn):
    _seed_account(conn, oid="100")
    _seed_account(conn, oid="200", name="Beta Ltd", client="Beta")
    df = pd.DataFrame([
        {"Client": "Acme", "Vendor": "ADP", "Role": "payroll", "Status": "Stable"},
        {"Client": "Beta", "Vendor": "Dayforce", "Role": "hris", "Status": "Stable"},
    ])
    res = import_integration_sheet(conn, df)
    assert res["created"] == 2
    assert res["skipped"] == []

    by_client = {r["client"]: r for r in integration_overview(conn) if r["integration_id"]}
    assert by_client["Acme"]["vendor"] == "ADP" and by_client["Acme"]["role"] == "payroll"
    assert by_client["Beta"]["vendor"] == "Ceridian Dayforce"  # matched via alias
    assert by_client["Beta"]["role"] == "hris"


def test_import_sheet_resolves_account_name_as_client(conn):
    _seed_account(conn, oid="100", name="Acme Ltd")
    df = pd.DataFrame([{"Account": "acme ltd", "System": "Workday", "Role": "hris", "Status": "Stable"}])
    assert import_integration_sheet(conn, df)["created"] == 1


def test_import_sheet_skips_unknown_role(conn):
    _seed_account(conn)
    df = pd.DataFrame([{"Client": "Acme", "Vendor": "ADP", "Role": "both", "Status": "Stable"}])
    res = import_integration_sheet(conn, df)
    assert res["created"] == 0
    assert "unknown integration type" in res["skipped"][0]["reason"]


def test_import_sheet_reports_unmatched_vendors(conn):
    _seed_account(conn, oid="100")
    df = pd.DataFrame([
        {"Client": "Acme", "Vendor": "Obscure Payroll Co", "Role": "payroll", "Status": "Stable"},
    ])
    res = import_integration_sheet(conn, df)
    assert res["created"] == 1
    assert res["unmatched_vendors"] == ["Obscure Payroll Co"]
    row = [r for r in integration_overview(conn) if r["integration_id"]][0]
    assert row["vendor"] == "Obscure Payroll Co"


def test_import_sheet_requires_a_client_column(conn):
    with pytest.raises(IntegrationError, match="client column"):
        import_integration_sheet(conn, pd.DataFrame([{"oid": 1, "Vendor": "ADP"}]))


def test_import_sheet_requires_a_vendor_column(conn):
    with pytest.raises(IntegrationError, match="vendor column"):
        import_integration_sheet(conn, pd.DataFrame([{"Client": "Acme", "Notes": "x"}]))


def test_client_role_flags_counts_active_feeds_only(conn):
    _seed_account(conn, oid="1", client="Acme")
    _seed_account(conn, oid="2", name="Beta Ltd", client="Beta")
    _seed_account(conn, oid="3", name="Gamma Ltd", client="Gamma")
    _add(conn, client="Acme", role="payroll", status="stable")
    _add(conn, client="Acme", vendor="Raw HRIS", role="hris", status="in_discussion")
    _add(conn, client="Beta", vendor="Raw HRIS", role="hris", status="maintenance")
    _add(conn, client="Gamma", role="payroll", status="retired")

    flags = client_role_flags(conn)
    ids = {
        r["display_name"]: r["id"]
        for r in conn.execute("SELECT id, display_name FROM clients")
    }
    assert flags[ids["Acme"]] == {"payroll": True, "hris": False}
    assert flags[ids["Beta"]] == {"payroll": False, "hris": True}
    assert ids["Gamma"] not in flags
