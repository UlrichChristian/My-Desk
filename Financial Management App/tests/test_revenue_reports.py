"""Unit tests for Biggest Clients rollup and income exclusions."""

from __future__ import annotations

import pandas as pd

from fin_services.revenue_reports import (
    EXCLUDED_INCOME_ACCOUNTS,
    biggest_clients,
    client_period_detail,
    report_from_db,
)
from tests.helpers import insert_batch, insert_revenue


def test_excluded_income_accounts():
    assert "Referral Fees:Email Feed" in EXCLUDED_INCOME_ACCOUNTS
    assert "Statement of Work" in EXCLUDED_INCOME_ACCOUNTS


def test_client_period_detail_by_income_bucket(conn):
    batch = insert_batch(conn)
    insert_revenue(
        conn, period="2026-03", client_key="Acme", amount=100.0,
        quantity=10.0, rate=10.0, product_code="ADMIN",
        income_account="Admin Fees (earned on Premium)",
        premium_split=50.0, lives_split=5.0, import_id=batch,
    )
    insert_revenue(
        conn, period="2026-03", client_key="Acme", amount=40.0,
        quantity=8.0, rate=5.0, product_code="SUB",
        income_account="Admin Fees (earned on Sub. Fees)",
        premium_split=0.0, lives_split=0.0, import_id=batch,
    )
    insert_revenue(
        conn, period="2026-03", client_key="Acme", amount=20.0,
        quantity=4.0, rate=5.0, product_code="SUB-B",
        income_account="Admin Fees (earned on Sub. Fees)",
        premium_split=0.0, lives_split=0.0, import_id=batch,
    )
    insert_revenue(
        conn, period="2026-03", client_key="Acme", amount=999.0,
        income_account="Statement of Work", import_id=batch,
    )
    detail = client_period_detail(conn, "2026-03", "Acme")
    assert detail["client"] == "Acme"
    assert detail["period"] == "2026-03"
    accounts = {b["income_account"] for b in detail["buckets"]}
    assert "Statement of Work" not in accounts
    assert len(detail["buckets"]) == 3
    products = {(b["income_account"], b["product_code"]) for b in detail["buckets"]}
    assert ("Admin Fees (earned on Sub. Fees)", "SUB") in products
    assert ("Admin Fees (earned on Sub. Fees)", "SUB-B") in products
    by_prod = {(b["income_account"], b["product_code"]): b for b in detail["buckets"]}
    assert by_prod[("Admin Fees (earned on Premium)", "ADMIN")]["certs"] == 10.0
    assert by_prod[("Admin Fees (earned on Sub. Fees)", "SUB")]["amount"] == 40.0


def test_biggest_clients_ranks_and_shares():
    enriched = pd.DataFrame([
        {
            "period": "2026-03",
            "client_key": "Alpha",
            "advisor": "A",
            "amount": 300.0,
            "premium_split": 100.0,
            "lives_split": 10.0,
            "income_account": "Admin Fees",
        },
        {
            "period": "2026-03",
            "client_key": "Beta",
            "advisor": "B",
            "amount": 100.0,
            "premium_split": 50.0,
            "lives_split": 5.0,
            "income_account": "Admin Fees",
        },
    ])
    rep = biggest_clients(enriched, "2026-03")
    assert list(rep["Client"]) == ["Alpha", "Beta"]
    assert rep["Revenue"].tolist() == [300.0, 100.0]
    assert abs(rep["Revenue Share"].sum() - 1.0) < 1e-9
    assert rep.attrs["total_revenue"] == 400.0


def test_biggest_clients_excludes_non_client_income():
    enriched = pd.DataFrame([
        {
            "period": "2026-03",
            "client_key": "Manulife",
            "advisor": None,
            "amount": 500.0,
            "premium_split": 0.0,
            "lives_split": 0.0,
            "income_account": "Referral Fees:Email Feed",
        },
        {
            "period": "2026-03",
            "client_key": "SOW Client",
            "advisor": None,
            "amount": 1000.0,
            "premium_split": 0.0,
            "lives_split": 0.0,
            "income_account": "Statement of Work",
        },
        {
            "period": "2026-03",
            "client_key": "Real Client",
            "advisor": "A",
            "amount": 200.0,
            "premium_split": 100.0,
            "lives_split": 10.0,
            "income_account": "Admin Fees earned on Premium",
        },
    ])
    rep = biggest_clients(enriched, "2026-03")
    assert list(rep["Client"]) == ["Real Client"]
    assert rep.attrs["total_revenue"] == 200.0


def test_report_from_db_excludes_referral_fees(conn):
    batch = insert_batch(conn)
    insert_revenue(
        conn,
        period="2026-03",
        client_key="Manulife",
        amount=999.0,
        income_account="Referral Fees:Email Feed",
        import_id=batch,
    )
    insert_revenue(
        conn,
        period="2026-03",
        client_key="SOW Co",
        amount=888.0,
        income_account="Statement of Work",
        import_id=batch,
    )
    insert_revenue(
        conn,
        period="2026-03",
        client_key="Acme",
        amount=100.0,
        import_id=batch,
        premium_split=50.0,
        lives_split=5.0,
    )
    rep = report_from_db(conn, "2026-03")
    assert list(rep["Client"]) == ["Acme"]
    assert rep.attrs["total_revenue"] == 100.0


def test_report_from_db_empty(conn):
    rep = report_from_db(conn)
    assert rep.empty
    assert rep.attrs["period"] is None
