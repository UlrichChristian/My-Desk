"""
Parse & normalize the three revenue source files, and load results into fin_db.

Parsers return normalized DataFrames; the DB loader upserts the reference spine
(clients, accounts, advisors, carriers, policies, products, income accounts),
writes per-period account metrics, and then loads the revenue fact.

The spine is **upsert-only** — an import never deletes a reference row. Only
``revenue_lines`` is replace-by-period, and durable fixes live in
``ingest_corrections`` so a re-upload re-applies rather than wipes them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from fin_services.reference_data import (
    account_status,
    iso_now,
    parse_bool,
    parse_policy,
    parse_product_code,
    parse_source_date,
    split_list,
)

# Canonical drilldown columns (new QBO "Ref #1 - Transaction Drill Down" export).
_INCOME_COLS = ("Account Name", "Full name")
_MEMO_COLS = ("Memo/Description", "Description")

# The accounts CSV is a scraped grid whose columns depend on its configuration
# at scrape time. Fail loudly on a missing column rather than silently emptying
# a dimension that is now load-bearing.
REQUIRED_ACCOUNT_COLUMNS = (
    "oid", "name", "livesCount", "monthlyPremium", "isActive", "isUpdating",
    "brokerList", "consultingHouses", "policies", "benefitType",
)
REQUIRED_ACCOUNT_LIST_COLUMNS = ("ACCOUNT ID", "NAME", "GROUP ID", "SYSTEM ID")


def _first_present(cols, candidates):
    for c in candidates:
        if c in cols:
            return c
    return None


def normalize_drilldown(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize an already-tabular drilldown frame (header applied) to standard columns."""
    raw = raw.rename(columns=lambda c: str(c).strip())
    cols = set(raw.columns)
    income_col = _first_present(cols, _INCOME_COLS)
    memo_col = _first_present(cols, _MEMO_COLS)
    if "Transaction date" not in cols or income_col is None:
        raise ValueError(
            f"Drilldown is missing expected columns. Found: {sorted(cols)}"
        )

    txn_date = pd.to_datetime(raw["Transaction date"], errors="coerce")
    out = pd.DataFrame(
        {
            "txn_date": txn_date,
            "txn_type": raw.get("Transaction type"),
            "invoice_no": raw.get("#"),
            "name": raw.get("Name"),
            "customer": raw.get("Customer", raw.get("Name")),
            "memo": raw.get(memo_col) if memo_col else None,
            "income_account": raw[income_col].map(lambda v: v.strip() if isinstance(v, str) else v),
            "item_split": raw.get("Item split account"),
            "amount": pd.to_numeric(raw.get("Amount"), errors="coerce"),
            "product_code": raw.get("Product/Service"),
            "quantity": pd.to_numeric(raw.get("Quantity"), errors="coerce") if "Quantity" in cols else pd.NA,
            "rate": pd.to_numeric(raw.get("Rate"), errors="coerce") if "Rate" in cols else pd.NA,
        }
    )
    # Keep only real transaction rows (a valid date); drops the title/group-header rows.
    out = out[out["txn_date"].notna()].copy()
    out["period"] = out["txn_date"].dt.strftime("%Y-%m")
    out = out[out["amount"].notna()]
    return out.reset_index(drop=True)


def parse_drilldown(path: str | Path) -> pd.DataFrame:
    """Read a raw QBO drilldown .xlsx (with title preamble) and normalize it."""
    raw = pd.read_excel(path, header=None, dtype=object)
    header_idx = None
    for r in range(min(20, len(raw))):
        vals = [str(v).strip() for v in raw.iloc[r].tolist()]
        if "Transaction date" in vals:
            header_idx = r
            break
    if header_idx is None:
        raise ValueError("Could not find the 'Transaction date' header row in the drilldown.")
    header = [str(v).strip() if v is not None else "" for v in raw.iloc[header_idx].tolist()]
    body = raw.iloc[header_idx + 1:].copy()
    body.columns = header
    body = body.loc[:, [c for c in body.columns if c and c.lower() != "nan"]]
    return normalize_drilldown(body)


def parse_account_list(path: str | Path) -> pd.DataFrame:
    """Read the billing-site account list (.xlsx or .csv)."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=object)
    else:
        df = pd.read_excel(path, dtype=object)
    df = df.rename(columns=lambda c: str(c).strip())
    _assert_columns(df, REQUIRED_ACCOUNT_LIST_COLUMNS, "account list")
    return df


def parse_accounts(path: str | Path) -> pd.DataFrame:
    """Read the accounts export (.csv from Pull Accounts, or .xlsx)."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=object)
    else:
        df = pd.read_csv(path, dtype=object)
    df = df.rename(columns=lambda c: str(c).strip())
    _assert_columns(df, REQUIRED_ACCOUNT_COLUMNS, "accounts CSV")
    return df


def _assert_columns(df: pd.DataFrame, required, label: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"{label} is missing required column(s): {missing}. "
            f"Found: {sorted(df.columns)}"
        )


# --------------------------------------------------------------------------
# DB load
# --------------------------------------------------------------------------


def _num(v):
    try:
        return float(v) if v is not None and not pd.isna(v) else None
    except (TypeError, ValueError):
        return None


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None


def _str(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    text = str(v).strip()
    return text or None


def _lookup_or_create(conn, table: str, name: str, cache: dict, now: str) -> int | None:
    """Get-or-insert a single-name reference row, memoised per load."""
    key = _str(name)
    if key is None:
        return None
    if key in cache:
        return cache[key]
    row = conn.execute(f"SELECT id FROM {table} WHERE name = ?", (key,)).fetchone()
    if row is None:
        cur = conn.execute(
            f"INSERT INTO {table} (name, created_on) VALUES (?, ?)", (key, now)
        )
        cache[key] = cur.lastrowid
    else:
        cache[key] = row[0]
    return cache[key]


def load_import(
    conn,
    enriched: pd.DataFrame,
    accounts: pd.DataFrame,
    account_list: pd.DataFrame,
    files: dict,
    created_by: str | None = None,
    metrics_mode: str = "latest",
) -> dict:
    """Load an enriched drilldown plus the reference spine into fin_db.

    ``metrics_mode``:
      ``latest``      — write account_period_metrics only for the newest period,
                        the one the accounts CSV honestly describes. Earlier
                        months get no row, so ratios render blank rather than
                        being computed against a later month's premium.
      ``all_periods`` — write every period from the same snapshot, flagged
                        ``source='estimated'``. This exactly reproduces the old
                        (wrong) behaviour and exists only for the Deploy A
                        parity gate, where revenue attribution is what is under
                        test and nothing else may move.
    """
    periods = sorted(p for p in enriched["period"].dropna().unique())
    now = iso_now()

    cur = conn.execute(
        "INSERT INTO revenue_imports (source, period_from, period_to, files_json, "
        "row_counts_json, status, created_on, created_by) "
        "VALUES ('drilldown', ?, ?, ?, ?, 'loading', ?, ?)",
        (
            periods[0] if periods else None,
            periods[-1] if periods else None,
            json.dumps(files),
            json.dumps({"revenue_rows": int(len(enriched)), "accounts": int(len(accounts))}),
            now,
            created_by,
        ),
    )
    import_id = cur.lastrowid

    client_ids = _upsert_clients(conn, enriched, account_list, now, periods)
    account_ids = _upsert_accounts(conn, accounts, account_list, client_ids, import_id, now)
    _upsert_policies(conn, accounts, account_ids, now)
    product_ids = _upsert_products(conn, enriched, now)
    income_ids = _upsert_income_accounts(conn, enriched, now)
    metric_periods = _upsert_period_metrics(
        conn, accounts, account_ids, periods, import_id, now, metrics_mode
    )

    stats = _load_revenue_lines(
        conn, enriched, import_id, client_ids, account_ids, product_ids, income_ids, now
    )

    _record_correction_hits(conn, enriched, now)

    parity = {
        "periods": {
            p: {
                "rows": int((enriched["period"] == p).sum()),
                "amount": round(float(enriched.loc[enriched["period"] == p, "amount"].sum()), 2),
            }
            for p in periods
        },
        "unresolved_rows": stats["unresolved"],
        "excluded_rows": stats["excluded"],
        "metric_periods": metric_periods,
    }
    conn.execute(
        "UPDATE revenue_imports SET status='loaded', parity_json=? WHERE id=?",
        (json.dumps(parity), import_id),
    )

    conn.commit()
    return {
        "import_id": import_id,
        "periods": periods,
        "revenue_rows": stats["rows"],
        "unresolved": stats["unresolved"],
        "excluded": stats["excluded"],
        "accounts": len(account_ids),
        "clients": len(client_ids),
        "metric_periods": metric_periods,
    }


# Months before this were never captured contemporaneously. Deploy A's parity
# load stamped today's premium onto all of them as source='estimated'.
VINTAGE_KEEP_FROM = "2026-07"


def drop_pre_vintage_metrics(conn, keep_from: str = VINTAGE_KEEP_FROM) -> int:
    """Delete metrics for months we never honestly observed (Deploy B).

    Historical Revenue/Premium then renders blank instead of being computed
    against a later snapshot. Rows from ``keep_from`` onward stay.
    """
    cur = conn.execute(
        "DELETE FROM account_period_metrics WHERE period < ?",
        (keep_from,),
    )
    conn.commit()
    return cur.rowcount


def _upsert_clients(conn, enriched, account_list, now, periods) -> dict:
    """Upsert clients and register every derived key string as an alias.

    client_keys is the GROUP ID rename fix: a renamed group inserts a new alias
    against the same client_id instead of presenting as New + Lost.
    """
    period_lo = periods[0] if periods else None
    period_hi = periods[-1] if periods else None

    seen = (
        enriched[["client_key", "client_key_kind", "group_id", "system_id", "bill_name", "legal_name"]]
        .dropna(subset=["client_key"])
        .drop_duplicates("client_key")
    )

    ids: dict[str, int] = {}
    for _, r in seen.iterrows():
        key = _str(r["client_key"])
        if key is None:
            continue
        kind = _str(r["client_key_kind"]) or "manual"

        row = conn.execute(
            "SELECT client_id FROM client_keys WHERE key_value = ? AND key_kind = ?",
            (key, kind),
        ).fetchone()
        if row:
            client_id = row[0]
            conn.execute(
                "UPDATE client_keys SET last_seen_period = ? WHERE key_value = ? AND key_kind = ?",
                (period_hi, key, kind),
            )
        else:
            existing = conn.execute(
                "SELECT id FROM clients WHERE display_name = ?", (key,)
            ).fetchone()
            if existing:
                client_id = existing[0]
            else:
                client_id = conn.execute(
                    "INSERT INTO clients (display_name, legal_name, group_id, system_id, "
                    "status, created_on) VALUES (?,?,?,?,'active',?)",
                    (key, _str(r["legal_name"]), _str(r["group_id"]), _str(r["system_id"]), now),
                ).lastrowid
            conn.execute(
                "INSERT INTO client_keys (client_id, key_value, key_kind, is_current, "
                "first_seen_period, last_seen_period, created_on) VALUES (?,?,?,1,?,?,?)",
                (client_id, key, kind, period_lo, period_hi, now),
            )
        ids[key] = client_id
    return ids


def _upsert_accounts(conn, accounts, account_list, client_ids, import_id, now) -> dict:
    """Upsert the account spine from the accounts CSV, enriched by the billing list."""
    al = account_list.rename(columns=lambda c: str(c).strip())
    by_oid = {}
    for _, r in al.iterrows():
        oid = _str(r.get("ACCOUNT ID"))
        if oid:
            by_oid[oid] = r

    advisor_cache: dict[str, int] = {}
    house_cache: dict[str, int] = {}
    ids: dict[str, int] = {}

    for _, a in accounts.iterrows():
        oid = _str(a.get("oid"))
        if oid is None:
            continue

        bill = by_oid.get(oid)
        group_key = _str(bill.get("GROUP ID")) if bill is not None else None
        system_key = _str(bill.get("SYSTEM ID")) if bill is not None else None
        client_key = group_key if group_key and group_key != "N/A" else system_key
        client_id = client_ids.get(client_key)

        house_names = split_list(a.get("consultingHouses"))
        advisor_names = split_list(a.get("brokerList"))
        house_id = _lookup_or_create(conn, "consulting_houses", house_names[0] if house_names else None, house_cache, now)
        advisor_id = _lookup_or_create(conn, "advisors", advisor_names[0] if advisor_names else None, advisor_cache, now)
        if advisor_id and house_id:
            conn.execute(
                "UPDATE advisors SET consulting_house_id = ?, updated_on = ? "
                "WHERE id = ? AND consulting_house_id IS NULL",
                (house_id, now, advisor_id),
            )

        ref_codes = split_list(a.get("referenceCodes"))
        values = (
            _str(a.get("name")),
            _str(bill.get("LEGAL NAME")) if bill is not None else None,
            client_id,
            advisor_id,
            house_id,
            account_status(a.get("isActive"), a.get("isUpdating")),
            _str(a.get("benefitType")),
            _str(a.get("benefitPackageType")),
            _str(a.get("memberUpdatesType")),
            parse_bool(a.get("ssoEnabled")),
            ref_codes[0] if ref_codes else None,
            " | ".join(ref_codes) or None,
            _str(a.get("planDesignNames")),
            parse_source_date(a.get("effectiveDate")),
            parse_source_date(a.get("firstBilledDate")),
            parse_source_date(a.get("lastPaAccess")),
            parse_source_date(a.get("lastModifiedDate")),
            len(split_list(a.get("errors"))),
            len(split_list(a.get("warnings"))),
            import_id,
        )

        row = conn.execute("SELECT id FROM accounts WHERE oid = ?", (oid,)).fetchone()
        if row:
            account_id = row[0]
            conn.execute(
                "UPDATE accounts SET name=?, legal_name=?, client_id=?, advisor_id=?, "
                "consulting_house_id=?, status=?, benefit_type=?, benefit_package_type=?, "
                "member_updates_type=?, sso_enabled=?, gl_reference_code=?, "
                "gl_reference_codes_raw=?, plan_design_names_raw=?, effective_on=?, "
                "first_billed_on=?, last_pa_access_on=?, source_modified_on=?, "
                "source_error_count=?, source_warning_count=?, last_seen_import_id=?, "
                "updated_on=? WHERE id=?",
                values + (now, account_id),
            )
        else:
            account_id = conn.execute(
                "INSERT INTO accounts (oid, name, legal_name, client_id, advisor_id, "
                "consulting_house_id, status, benefit_type, benefit_package_type, "
                "member_updates_type, sso_enabled, gl_reference_code, gl_reference_codes_raw, "
                "plan_design_names_raw, effective_on, first_billed_on, last_pa_access_on, "
                "source_modified_on, source_error_count, source_warning_count, "
                "last_seen_import_id, first_seen_import_id, created_on) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (oid,) + values + (import_id, now),
            ).lastrowid
        ids[oid] = account_id
    return ids


def _upsert_policies(conn, accounts, account_ids, now) -> None:
    """Parse "<Carrier> - <PolicyNo>" into carriers + account_policies."""
    carrier_cache: dict[str, int] = {}
    for _, a in accounts.iterrows():
        oid = _str(a.get("oid"))
        account_id = account_ids.get(oid)
        if account_id is None:
            continue
        for element in split_list(a.get("policies")):
            parsed = parse_policy(element)
            if not parsed:
                continue
            carrier_id = _lookup_or_create(conn, "carriers", parsed["carrier_name"], carrier_cache, now)
            conn.execute(
                "INSERT INTO account_policies (account_id, carrier_id, policy_no, "
                "benefit_line, is_placeholder, raw_value, created_on) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(account_id, raw_value) DO NOTHING",
                (account_id, carrier_id, parsed["policy_no"], parsed["benefit_line"],
                 parsed["is_placeholder"], parsed["raw_value"], now),
            )


def _upsert_products(conn, enriched, now) -> dict:
    """Register every product code, decomposed into benefit + HST rate.

    Unknown codes are auto-registered with status 'review' rather than rejected —
    the same supervised-escape-hatch rule the income accounts use.
    """
    ids: dict[str, int] = {}
    for code in sorted({_str(c) for c in enriched["product_code"].dropna().unique()} - {None}):
        row = conn.execute("SELECT id FROM products WHERE code = ?", (code,)).fetchone()
        if row:
            ids[code] = row[0]
            continue
        p = parse_product_code(code)
        ids[code] = conn.execute(
            "INSERT INTO products (code, code_normalized, channel, fee_kind, benefit_code, "
            "hst_rate, status, created_on) VALUES (?,?,?,?,?,?,'review',?)",
            (p["code"], p["code_normalized"], p["channel"], p["fee_kind"],
             p["benefit_code"], p["hst_rate"], now),
        ).lastrowid
    return ids


def _upsert_income_accounts(conn, enriched, now) -> dict:
    """Register income accounts. Unseeded ones land as 'unclassified'/'review'.

    This is the mechanism that surfaces a new revenue line the first time it
    appears, instead of it becoming an open question months later.
    """
    ids: dict[str, int] = {}
    for name in sorted({_str(c) for c in enriched["income_account"].dropna().unique()} - {None}):
        row = conn.execute("SELECT id FROM income_accounts WHERE name = ?", (name,)).fetchone()
        if row:
            ids[name] = row[0]
            continue
        ids[name] = conn.execute(
            "INSERT INTO income_accounts (name, category, status, created_on) "
            "VALUES (?, 'unclassified', 'review', ?)",
            (name, now),
        ).lastrowid
    return ids


def _upsert_period_metrics(conn, accounts, account_ids, periods, import_id, now, mode) -> list:
    """Write lives/premium per (account, period) — the vintaging fix."""
    if not periods:
        return []
    targets = periods if mode == "all_periods" else [periods[-1]]
    source = "estimated" if mode == "all_periods" else "accounts_csv"

    advisor_cache: dict[str, int] = {}
    house_cache: dict[str, int] = {}
    rows = []
    for _, a in accounts.iterrows():
        oid = _str(a.get("oid"))
        account_id = account_ids.get(oid)
        if account_id is None:
            continue
        advisors = split_list(a.get("brokerList"))
        houses = split_list(a.get("consultingHouses"))
        advisor_id = _lookup_or_create(conn, "advisors", advisors[0] if advisors else None, advisor_cache, now)
        house_id = _lookup_or_create(conn, "consulting_houses", houses[0] if houses else None, house_cache, now)
        for period in targets:
            rows.append((
                account_id, period, _int(a.get("livesCount")), _num(a.get("monthlyPremium")),
                account_status(a.get("isActive"), a.get("isUpdating")),
                advisor_id, house_id, source, now, import_id, now,
            ))

    conn.executemany(
        "INSERT INTO account_period_metrics (account_id, period, lives, premium, status, "
        "advisor_id, consulting_house_id, source, captured_on, import_id, created_on) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(account_id, period) DO UPDATE SET "
        "lives=excluded.lives, premium=excluded.premium, status=excluded.status, "
        "advisor_id=excluded.advisor_id, consulting_house_id=excluded.consulting_house_id, "
        "source=excluded.source, captured_on=excluded.captured_on, "
        "import_id=excluded.import_id, updated_on=excluded.created_on",
        rows,
    )
    return targets


def _load_revenue_lines(conn, enriched, import_id, client_ids, account_ids,
                        product_ids, income_ids, now) -> dict:
    """Replace-by-period load of the revenue fact."""
    periods = sorted(p for p in enriched["period"].dropna().unique())
    for period in periods:
        conn.execute("DELETE FROM revenue_lines WHERE period = ?", (period,))

    advisor_ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM advisors")}
    house_ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM consulting_houses")}

    # Rows an 'exclude' correction matched never reach the fact table. The rule
    # carries the reason, so the exclusion is explained and survives re-import.
    excluded = 0
    if "is_excluded_by_rule" in enriched.columns:
        keep = enriched["is_excluded_by_rule"].fillna(0).astype(int) == 0
        excluded = int((~keep).sum())
        enriched = enriched[keep]

    frame = enriched.where(pd.notna(enriched), None)
    rows, unresolved = [], 0
    for idx, r in enumerate(frame.itertuples(index=False), start=1):
        d = r._asdict()
        oid = _str(d.get("oid"))
        account_id = account_ids.get(oid)
        if account_id is None:
            unresolved += 1
        client_key = _str(d.get("client_key"))
        advisor = _str(d.get("advisor"))
        house = _str(d.get("consulting_house"))
        product_code = _str(d.get("product_code"))
        income_account = _str(d.get("income_account"))
        txn_date = d.get("txn_date")

        rows.append((
            import_id, idx, d.get("period"),
            str(txn_date)[:10] if txn_date is not None else None,
            _str(d.get("txn_type")), _str(d.get("invoice_no")),
            _str(d.get("name")), _str(d.get("customer")), _str(d.get("memo")),
            account_id, client_ids.get(client_key),
            advisor_ids.get(advisor), house_ids.get(house),
            product_ids.get(product_code), income_ids.get(income_account),
            oid, client_key, advisor, house, product_code, income_account,
            _num(d.get("amount")), _num(d.get("quantity")), _num(d.get("rate")),
            _int(d.get("correction_id")),
            1 if account_id is not None else 0,
            now,
        ))

    conn.executemany(
        "INSERT INTO revenue_lines (import_id, source_row_no, period, txn_date, txn_type, "
        "invoice_no, name_raw, customer_raw, memo, account_id, client_id, advisor_id, "
        "consulting_house_id, product_id, income_account_id, oid, client_key_raw, "
        "advisor_label, consulting_house, product_code_raw, income_account_raw, "
        "amount, quantity, rate, correction_id, is_resolved, created_on) "
        "VALUES (" + ",".join("?" * 27) + ")",
        rows,
    )
    return {"rows": len(rows), "unresolved": unresolved, "excluded": excluded}


def _record_correction_hits(conn, enriched, now) -> None:
    """Persist how many rows each correction rule touched.

    A rule whose count drops to 0 has gone stale and is silently no longer doing
    anything — that is the signal the reference review page surfaces.
    """
    for rule_id, hits in (enriched.attrs.get("correction_counts") or {}).items():
        if rule_id is None:
            continue
        conn.execute(
            "UPDATE ingest_corrections SET applied_count = ?, last_applied_on = ? WHERE id = ?",
            (int(hits), now, rule_id),
        )
