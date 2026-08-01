"""Helpers for seeding fact_revenue in tests."""

from __future__ import annotations

import sqlite3


def insert_batch(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO import_batch (uploaded_at, drilldown_from, drilldown_to, files_json, row_counts_json) "
        "VALUES ('2026-01-01T00:00:00Z', '2026-01', '2026-03', '{}', '{}')"
    )
    return cur.lastrowid


def insert_revenue(
    conn: sqlite3.Connection,
    *,
    period: str,
    client_key: str | None,
    amount: float,
    product_code: str = "ADMIN",
    quantity: float | None = None,
    rate: float | None = None,
    income_account: str = "Admin Fees earned on Premium",
    advisor_key: str | None = "Advisor A",
    oid: str | None = "100",
    premium_split: float = 0.0,
    lives_split: float = 0.0,
    import_id: int | None = None,
    name_raw: str | None = None,
) -> None:
    if import_id is None:
        import_id = insert_batch(conn)
    conn.execute(
        "INSERT INTO fact_revenue ("
        "import_id, txn_date, period, txn_type, invoice_no, name_raw, memo, "
        "client_key, advisor_key, product_code, income_account, oid, "
        "amount, quantity, rate, premium_split, lives_split"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            import_id,
            f"{period}-15",
            period,
            "Invoice",
            "1",
            name_raw if name_raw is not None else (client_key or "unknown"),
            None,
            client_key,
            advisor_key,
            product_code,
            income_account,
            oid,
            amount,
            quantity,
            rate,
            premium_split,
            lives_split,
        ),
    )
    conn.commit()
