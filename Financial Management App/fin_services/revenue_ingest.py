"""
Parse & normalize the three revenue source files, and load results into fin_db.

Parsers return normalized DataFrames; the DB loader applies the plan's ingestion
rules (replace-by-period for revenue, append-only account snapshots, import audit).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Canonical drilldown columns (new QBO "Ref #1 - Transaction Drill Down" export).
_INCOME_COLS = ("Account Name", "Full name")
_MEMO_COLS = ("Memo/Description", "Description")


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
    return df.rename(columns=lambda c: str(c).strip())


def parse_accounts(path: str | Path) -> pd.DataFrame:
    """Read the accounts export (.csv from Pull Accounts, or .xlsx)."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=object)
    else:
        df = pd.read_csv(path, dtype=object)
    return df.rename(columns=lambda c: str(c).strip())


# --------------------------------------------------------------------------
# DB load
# --------------------------------------------------------------------------

def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_import(conn, enriched: pd.DataFrame, accounts: pd.DataFrame, files: dict) -> dict:
    """Load an enriched drilldown + account snapshot into fin_db.

    - fact_revenue: replace-by-period (delete the periods this file covers, then insert).
    - account_snapshot: append, stamped with as_of_date = now.
    - dims: upsert (INSERT OR REPLACE).
    - import_batch: one audit row.
    """
    periods = sorted(p for p in enriched["period"].dropna().unique())
    now = _iso_now()

    cur = conn.execute(
        "INSERT INTO import_batch (uploaded_at, drilldown_from, drilldown_to, files_json, row_counts_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            now,
            periods[0] if periods else None,
            periods[-1] if periods else None,
            json.dumps(files),
            json.dumps({"revenue_rows": int(len(enriched)), "accounts": int(len(accounts))}),
        ),
    )
    import_id = cur.lastrowid

    # Replace-by-period.
    for period in periods:
        conn.execute("DELETE FROM fact_revenue WHERE period = ?", (period,))

    enriched.where(pd.notna(enriched), None).apply(
        lambda r: conn.execute(
            "INSERT INTO fact_revenue (import_id, txn_date, period, txn_type, invoice_no, "
            "name_raw, memo, client_key, advisor_key, product_code, income_account, oid, "
            "amount, quantity, rate, premium_split, lives_split) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                import_id,
                str(r["txn_date"])[:10] if r["txn_date"] is not None else None,
                r["period"], r["txn_type"], r["invoice_no"], r["name"], r["memo"],
                r["client_key"], r["advisor"], r["product_code"], r["income_account"],
                _str(r["oid"]), _num(r["amount"]), _num(r["quantity"]), _num(r["rate"]),
                _num(r["premium_split"]), _num(r["lives_split"]),
            ),
        ),
        axis=1,
    )

    # Append account snapshot.
    for _, a in accounts.iterrows():
        conn.execute(
            "INSERT INTO account_snapshot (import_id, as_of_date, oid, client_key, lives, "
            "premium, active, benefit_type, advisor, consulting_house) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                import_id, now, _str(a.get("oid")), None,
                _int(a.get("livesCount")), _num(a.get("monthlyPremium")),
                1 if str(a.get("isActive")).lower() in ("true", "1") else 0,
                _str(a.get("benefitType")), _str(a.get("brokerList")), _str(a.get("consultingHouses")),
            ),
        )

    conn.commit()
    return {"import_id": import_id, "periods": periods, "revenue_rows": int(len(enriched))}


def _num(v):
    try:
        return float(v) if v is not None and not pd.isna(v) else None
    except (TypeError, ValueError):
        return None


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None


def _str(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)
