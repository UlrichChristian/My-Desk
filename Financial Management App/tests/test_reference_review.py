"""Classify auto-inserted products / income accounts on the review screen."""

from __future__ import annotations

import pytest

from fin_services.reference_data import (
    ReferenceError,
    accept_parsed_products,
    list_income_accounts,
    list_products,
    review_counts,
    update_income_account,
    update_product,
)

_NOW = "2026-01-01T00:00:00Z"


def _insert_product(conn, code="NEW-CODE", status="review"):
    return conn.execute(
        "INSERT INTO products (code, code_normalized, channel, fee_kind, "
        "benefit_code, hst_rate, status, created_on) "
        "VALUES (?, ?, 'direct', 'admin', 'EH', 13, ?, ?)",
        (code, code.upper(), status, _NOW),
    ).lastrowid


def test_seeded_income_accounts_are_active_not_review(conn):
    counts = review_counts(conn)
    assert counts["income_accounts"] == 0
    names = {r["name"] for r in list_income_accounts(conn, status="active")}
    assert "Referral Fees:Email Feed" in names
    assert "Statement of Work" in names


def test_new_income_account_surfaces_on_the_review_list(conn):
    conn.execute(
        "INSERT INTO income_accounts (name, category, status, created_on) "
        "VALUES ('SHSP Fees', 'unclassified', 'review', ?)",
        (_NOW,),
    )
    conn.commit()
    waiting = list_income_accounts(conn, status="review")
    assert [r["name"] for r in waiting] == ["SHSP Fees"]
    assert review_counts(conn)["income_accounts"] == 1


def test_update_income_account_promotes_out_of_review(conn):
    income_id = conn.execute(
        "INSERT INTO income_accounts (name, category, status, created_on) "
        "VALUES ('SHSP Fees', 'unclassified', 'review', ?)",
        (_NOW,),
    ).lastrowid
    conn.commit()
    update_income_account(
        conn, income_id,
        category="admin_fee", basis="premium", exclude_from_reports=False, status="active",
    )
    row = conn.execute("SELECT * FROM income_accounts WHERE id = ?", (income_id,)).fetchone()
    assert row["status"] == "active"
    assert row["category"] == "admin_fee"
    assert row["basis"] == "premium"
    assert review_counts(conn)["income_accounts"] == 0


def test_update_income_account_rejects_unknown_category(conn):
    income_id = conn.execute(
        "SELECT id FROM income_accounts WHERE name = 'Statement of Work'"
    ).fetchone()[0]
    with pytest.raises(ReferenceError, match="category"):
        update_income_account(conn, income_id, category="not_a_category", basis="none")


def test_update_product_confirms_parse_and_promotes(conn):
    product_id = _insert_product(conn)
    conn.commit()
    assert review_counts(conn)["products"] == 1
    update_product(
        conn, product_id,
        channel="vendor", fee_kind="admin", benefit_code="eh", hst_rate=13, status="active",
    )
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    assert row["status"] == "active"
    assert row["channel"] == "vendor"
    assert row["benefit_code"] == "EH"
    assert row["hst_rate"] == 13
    assert review_counts(conn)["products"] == 0


def test_update_product_rejects_bogus_hst_rate(conn):
    product_id = _insert_product(conn)
    conn.commit()
    with pytest.raises(ReferenceError, match="hst_rate"):
        update_product(
            conn, product_id,
            channel="direct", fee_kind="admin", benefit_code="EH", hst_rate=12,
        )


def test_accept_parsed_products_clears_the_queue(conn):
    _insert_product(conn, "A")
    _insert_product(conn, "B")
    already = _insert_product(conn, "C", status="active")
    conn.commit()
    n = accept_parsed_products(conn)
    assert n == 2
    assert review_counts(conn)["products"] == 0
    still = conn.execute("SELECT status FROM products WHERE id = ?", (already,)).fetchone()
    assert still["status"] == "active"
    codes = [r["code"] for r in list_products(conn, status="active")]
    assert "A" in codes and "B" in codes


def test_accept_parsed_products_can_target_ids(conn):
    keep = _insert_product(conn, "KEEP")
    accept = _insert_product(conn, "ACCEPT")
    conn.commit()
    n = accept_parsed_products(conn, product_ids=[accept])
    assert n == 1
    assert list_products(conn, status="review")[0]["id"] == keep
