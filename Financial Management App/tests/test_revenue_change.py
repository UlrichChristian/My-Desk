"""Unit tests for MoM change bridge drivers."""

from __future__ import annotations

import pandas as pd

from fin_services.revenue_change import (
    UNMAPPED_CLIENT_LABEL,
    _bridge_existing,
    _prior_period,
    available_change_periods,
    change_report,
    client_detail_rows,
    default_prior_period,
    resolve_prior_period,
)
from tests.helpers import insert_batch, insert_revenue


def test_prior_period_rolls_year():
    assert _prior_period("2026-01") == "2025-12"
    assert _prior_period("2026-03") == "2026-02"
    assert _prior_period("bad") is None


def test_default_prior_prefers_calendar_then_earlier():
    assert default_prior_period("2026-03", {"2026-01", "2026-02", "2026-03"}) == "2026-02"
    assert default_prior_period("2026-03", {"2026-01", "2026-03"}) == "2026-01"
    assert default_prior_period("2026-01", {"2026-01", "2026-03"}) == "2026-03"


def test_resolve_prior_honors_explicit_choice():
    present = {"2026-01", "2026-02", "2026-03"}
    assert resolve_prior_period("2026-03", "2026-01", present) == "2026-01"
    assert resolve_prior_period("2026-03", "2026-03", present) == "2026-02"
    assert resolve_prior_period("2026-03", "2099-01", present) == "2026-02"


def test_available_change_periods_needs_two_months(conn):
    batch = insert_batch(conn)
    insert_revenue(conn, period="2026-01", client_key="A", amount=10, import_id=batch)
    assert available_change_periods(conn) == []

    insert_revenue(conn, period="2026-03", client_key="A", amount=10, import_id=batch)
    # Non-consecutive months are fine — any other month can be the reference.
    assert available_change_periods(conn) == ["2026-03", "2026-01"]


def test_change_report_custom_prior_period(conn):
    batch = insert_batch(conn)
    insert_revenue(
        conn, period="2026-01", client_key="A", amount=50.0,
        quantity=5.0, rate=10.0, import_id=batch,
    )
    insert_revenue(
        conn, period="2026-02", client_key="A", amount=80.0,
        quantity=8.0, rate=10.0, import_id=batch,
    )
    insert_revenue(
        conn, period="2026-03", client_key="A", amount=100.0,
        quantity=10.0, rate=10.0, import_id=batch,
    )
    default = change_report(conn, "2026-03")
    assert default["prior_period"] == "2026-02"
    assert default["summary"]["prior_revenue"] == 80.0

    vs_jan = change_report(conn, "2026-03", prior_period="2026-01")
    assert vs_jan["prior_period"] == "2026-01"
    assert vs_jan["summary"]["prior_revenue"] == 50.0
    assert vs_jan["summary"]["current_revenue"] == 100.0
    assert vs_jan["summary"]["delta"] == 50.0


def test_bridge_certs_and_price():
    prior = pd.DataFrame([
        {"product_code": "ADMIN", "amount": 100.0, "quantity": 10.0, "rate": 10.0},
    ])
    curr = pd.DataFrame([
        {"product_code": "ADMIN", "amount": 180.0, "quantity": 12.0, "rate": 15.0},
    ])
    drivers = _bridge_existing(prior, curr)
    assert drivers["certs"] == 20.0
    assert drivers["price"] == 60.0
    assert drivers["benefits"] == 0.0
    assert abs(drivers["other"]) < 0.01


def test_bridge_new_and_dropped_product_is_benefits():
    prior = pd.DataFrame([
        {"product_code": "OLD", "amount": 40.0, "quantity": 4.0, "rate": 10.0},
    ])
    curr = pd.DataFrame([
        {"product_code": "NEW", "amount": 25.0, "quantity": 5.0, "rate": 5.0},
    ])
    drivers = _bridge_existing(prior, curr)
    assert drivers["benefits"] == 25.0 - 40.0
    assert drivers["certs"] == 0.0
    assert drivers["price"] == 0.0


def test_change_report_new_lost_and_ties_out(conn):
    batch = insert_batch(conn)
    insert_revenue(
        conn, period="2026-02", client_key="A", amount=100.0,
        quantity=10.0, rate=10.0, import_id=batch, oid="1",
    )
    insert_revenue(
        conn, period="2026-02", client_key="C", amount=50.0,
        quantity=5.0, rate=10.0, import_id=batch, oid="3",
    )
    insert_revenue(
        conn, period="2026-03", client_key="A", amount=180.0,
        quantity=12.0, rate=15.0, import_id=batch, oid="1",
    )
    insert_revenue(
        conn, period="2026-03", client_key="B", amount=30.0,
        quantity=3.0, rate=10.0, import_id=batch, oid="2",
    )

    report = change_report(conn, "2026-03")
    assert report["period"] == "2026-03"
    assert report["prior_period"] == "2026-02"
    s = report["summary"]
    assert s["prior_revenue"] == 150.0
    assert s["current_revenue"] == 210.0
    assert s["delta"] == 60.0
    assert abs(s["residual"]) < 0.01

    by_client = report["clients"].set_index("Client")
    assert by_client.loc["B", "New"] == 30.0
    assert by_client.loc["C", "Lost"] == -50.0
    assert by_client.loc["A", "Certs"] == 20.0
    assert by_client.loc["A", "Price"] == 60.0


def test_change_report_excludes_referral_fees(conn):
    batch = insert_batch(conn)
    insert_revenue(
        conn, period="2026-02", client_key="Acme", amount=100.0,
        quantity=10.0, rate=10.0, import_id=batch,
    )
    insert_revenue(
        conn, period="2026-03", client_key="Acme", amount=100.0,
        quantity=10.0, rate=10.0, import_id=batch,
    )
    insert_revenue(
        conn, period="2026-03", client_key="Manulife", amount=500.0,
        income_account="Referral Fees:Email Feed", import_id=batch,
    )
    insert_revenue(
        conn, period="2026-03", client_key="SOW Co", amount=400.0,
        income_account="Statement of Work", import_id=batch,
    )
    report = change_report(conn, "2026-03")
    assert "Manulife" not in set(report["clients"]["Client"])
    assert "SOW Co" not in set(report["clients"]["Client"])
    assert report["summary"]["current_revenue"] == 100.0
    assert abs(report["summary"]["delta"]) < 0.01


def test_client_detail_rows_prior_and_current(conn):
    batch = insert_batch(conn)
    insert_revenue(
        conn, period="2026-02", client_key="Acme", amount=40.0,
        product_code="ADMIN", quantity=4.0, rate=10.0, import_id=batch,
    )
    insert_revenue(
        conn, period="2026-03", client_key="Acme", amount=60.0,
        product_code="ADMIN", quantity=6.0, rate=10.0, import_id=batch,
    )
    insert_revenue(
        conn, period="2026-03", client_key="Other", amount=99.0, import_id=batch,
    )
    detail = client_detail_rows(conn, "2026-03", "Acme")
    assert detail["period"] == "2026-03"
    assert detail["prior_period"] == "2026-02"
    assert detail["client"] == "Acme"
    assert len(detail["rows"]) == 2
    assert len(detail["buckets"]) == 1
    bucket = detail["buckets"][0]
    assert bucket["prior"]["certs"] == 4.0
    assert bucket["current"]["certs"] == 6.0
    assert bucket["prior"]["amount"] == 40.0
    assert bucket["current"]["amount"] == 60.0
    assert abs(bucket["prior"]["rate"] - 10.0) < 1e-9
    assert bucket["delta_amount"] == 20.0


def test_client_detail_rows_custom_prior(conn):
    batch = insert_batch(conn)
    insert_revenue(conn, period="2026-01", client_key="Acme", amount=10.0, import_id=batch)
    insert_revenue(conn, period="2026-02", client_key="Acme", amount=20.0, import_id=batch)
    insert_revenue(conn, period="2026-03", client_key="Acme", amount=30.0, import_id=batch)
    detail = client_detail_rows(conn, "2026-03", "Acme", prior_period="2026-01")
    assert detail["prior_period"] == "2026-01"
    assert [r["period"] for r in detail["rows"]] == ["2026-01", "2026-03"]
    assert sum(r["amount"] for r in detail["rows"]) == 40.0
    assert detail["buckets"][0]["prior"]["amount"] == 10.0
    assert detail["buckets"][0]["current"]["amount"] == 30.0


def test_client_detail_rows_excludes_referral_fees(conn):
    batch = insert_batch(conn)
    insert_revenue(
        conn, period="2026-02", client_key="Acme", amount=10.0, import_id=batch,
    )
    insert_revenue(
        conn, period="2026-03", client_key="Acme", amount=10.0, import_id=batch,
    )
    insert_revenue(
        conn, period="2026-03", client_key="Acme", amount=500.0,
        income_account="Referral Fees:Email Feed", import_id=batch,
    )
    detail = client_detail_rows(conn, "2026-03", "Acme")
    assert len(detail["rows"]) == 2
    assert all(r["income_account"] != "Referral Fees:Email Feed" for r in detail["rows"])
    assert all(b["income_account"] != "Referral Fees:Email Feed" for b in detail["buckets"])


def test_client_detail_rows_unmapped_null_client(conn):
    batch = insert_batch(conn)
    insert_revenue(
        conn, period="2026-02", client_key=None, amount=12.0,
        name_raw="Mystery", import_id=batch,
    )
    insert_revenue(
        conn, period="2026-03", client_key=None, amount=18.0,
        name_raw="Mystery", import_id=batch,
    )
    insert_revenue(
        conn, period="2026-03", client_key="Mapped", amount=5.0, import_id=batch,
    )
    detail = client_detail_rows(conn, "2026-03", UNMAPPED_CLIENT_LABEL)
    assert detail["client"] == UNMAPPED_CLIENT_LABEL
    assert len(detail["rows"]) == 2
    assert sum(r["amount"] for r in detail["rows"]) == 30.0
    assert detail["buckets"][0]["prior"]["amount"] == 12.0
    assert detail["buckets"][0]["current"]["amount"] == 18.0
