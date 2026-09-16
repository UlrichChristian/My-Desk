"""Helpers for seeding revenue_lines (and the reference spine) in tests.

The signature is deliberately unchanged from the pre-refactor version so test
bodies read the same. What moved is where the values land: premium and lives are
no longer columns on the fact, so ``premium_split``/``lives_split`` are
translated into an ``account_period_metrics`` row for the account and month.
"""

from __future__ import annotations

import sqlite3

_NOW = "2026-01-01T00:00:00Z"


def insert_batch(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO revenue_imports (source, period_from, period_to, files_json, "
        "row_counts_json, status, created_on) "
        "VALUES ('drilldown', '2026-01', '2026-03', '{}', '{}', 'loaded', ?)",
        (_NOW,),
    )
    return cur.lastrowid


def _get_or_create(conn, table: str, name: str | None, extra_cols="", extra_vals=()):
    if name is None:
        return None
    row = conn.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    cols = f"name, created_on{extra_cols}"
    ph = ",".join("?" * (2 + len(extra_vals)))
    return conn.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({ph})", (name, _NOW, *extra_vals)
    ).lastrowid


def _client_id(conn, client_key: str | None):
    if client_key is None:
        return None
    row = conn.execute("SELECT id FROM clients WHERE display_name = ?", (client_key,)).fetchone()
    if row:
        return row[0]
    cid = conn.execute(
        "INSERT INTO clients (display_name, status, created_on) VALUES (?, 'active', ?)",
        (client_key, _NOW),
    ).lastrowid
    conn.execute(
        "INSERT INTO client_keys (client_id, key_value, key_kind, created_on) "
        "VALUES (?, ?, 'group_id', ?)",
        (cid, client_key, _NOW),
    )
    return cid


def _account_id(conn, oid: str | None, client_id, advisor_id):
    if oid is None:
        return None
    row = conn.execute("SELECT id FROM accounts WHERE oid = ?", (oid,)).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO accounts (oid, name, client_id, advisor_id, status, created_on) "
        "VALUES (?, ?, ?, ?, 'active', ?)",
        (oid, f"Account {oid}", client_id, advisor_id, _NOW),
    ).lastrowid


def _product_id(conn, code: str | None):
    if code is None:
        return None
    row = conn.execute("SELECT id FROM products WHERE code = ?", (code,)).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO products (code, code_normalized, benefit_code, fee_kind, channel, "
        "status, created_on) VALUES (?, ?, ?, 'admin', 'direct', 'active', ?)",
        (code, code.upper(), code.upper(), _NOW),
    ).lastrowid


def _income_account_id(conn, name: str | None):
    if name is None:
        return None
    row = conn.execute("SELECT id FROM income_accounts WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO income_accounts (name, category, status, created_on) "
        "VALUES (?, 'unclassified', 'review', ?)",
        (name, _NOW),
    ).lastrowid


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

    advisor_id = _get_or_create(conn, "advisors", advisor_key)
    client_id = _client_id(conn, client_key)
    account_id = _account_id(conn, oid, client_id, advisor_id)
    product_id = _product_id(conn, product_code)
    income_id = _income_account_id(conn, income_account)

    conn.execute(
        "INSERT INTO revenue_lines (import_id, period, txn_date, txn_type, invoice_no, "
        "name_raw, memo, account_id, client_id, advisor_id, product_id, income_account_id, "
        "oid, client_key_raw, advisor_label, product_code_raw, income_account_raw, "
        "amount, quantity, rate, is_resolved, created_on) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            import_id, period, f"{period}-15", "Invoice", "1",
            name_raw if name_raw is not None else (client_key or "unknown"), None,
            account_id, client_id, advisor_id, product_id, income_id,
            oid, client_key, advisor_key, product_code, income_account,
            amount, quantity, rate, 1 if account_id else 0, _NOW,
        ),
    )

    # premium/lives now live per (account, month). The report divides them by the
    # account's line count for the period, so scale back up by the current count
    # to reproduce the per-row split the caller asked for.
    if account_id is not None and (premium_split or lives_split):
        n = conn.execute(
            "SELECT COUNT(*) FROM revenue_lines WHERE account_id = ? AND period = ?",
            (account_id, period),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO account_period_metrics (account_id, period, lives, premium, "
            "advisor_id, source, captured_on, import_id, created_on) "
            "VALUES (?,?,?,?,?,'accounts_csv',?,?,?) "
            "ON CONFLICT(account_id, period) DO UPDATE SET "
            "lives=excluded.lives, premium=excluded.premium",
            (account_id, period, lives_split * n, premium_split * n,
             advisor_id, _NOW, import_id, _NOW),
        )

    conn.commit()
