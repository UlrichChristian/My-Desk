"""
Revenue transaction enrichment / client resolution.

Ports the Power Query that builds the "Data" sheet:
  PreCustomer  -> resolve SYSTEM ID from the QBO name (Group:SystemId after ':')
  Join 1       -> PreCustomer == account_list.SYSTEM ID   (NAME, GROUP ID, ACCOUNT ID)
  Join 2       -> ACCOUNT ID == accounts.oid (fallback: NAME == name)
                  pulls oid, lives, premium, broker
  Client       -> GROUP ID, or SYSTEM ID when GROUP ID == 'N/A'
  Splits       -> premium/lives divided by the row count per oid (so pivots don't
                  multiply-count an account's premium/lives across its many lines)

All functions are Flask-free and operate on DataFrames so they're reusable by the web
routes, the MCP server, and the validation script.
"""

from __future__ import annotations

import pandas as pd

VENDOR_ACCOUNT = "Admin Fees (paid by Vendors)"
VENDOR_SUFFIX = " Admin Fee"
NA_GROUP = "N/A"


def _between(text, start: str, end: str):
    """Text between the first `start` and the following `end` (Power Query BetweenDelimiters)."""
    if not isinstance(text, str):
        return None
    i = text.find(start)
    if i < 0:
        return None
    i += len(start)
    j = text.find(end, i)
    if j < 0:
        return None
    return text[i:j].strip()


def _norm(v):
    return v.strip() if isinstance(v, str) else v


def resolve_precustomer(name, customer, memo, income_account, sysid_by_name: dict) -> object:
    """The PreCustomer rule from the Power Query.

    QBO customer names are often ``Group:SystemId`` (e.g. ``New Gold:Rainy River``).
    The account list joins on SYSTEM ID, so the default branch takes the text after
    the colon. Vendor-paid invoices strip a trailing `` Admin Fee`` from the memo;
    ``:ASOC`` payers extract the account name from the memo and look up SYSTEM ID.
    """
    income_account = _norm(income_account)
    memo = memo if isinstance(memo, str) else ""
    if income_account == VENDOR_ACCOUNT:
        if memo.endswith(VENDOR_SUFFIX):
            return memo[: -len(VENDOR_SUFFIX)]
        if memo.strip():
            return memo
        # Empty memo — fall through to the Group:SystemId / customer logic below.
    if isinstance(name, str) and ":ASOC" in name:
        extracted = _between(memo, ", ", " -")
        return sysid_by_name.get(extracted) if extracted else None
    source = customer if (isinstance(customer, str) and customer.strip()) else name
    if isinstance(source, str) and ":" in source:
        after = source.split(":", 1)[1].strip()
        if after and not after.startswith("ASOC"):
            return after
    return source


def enrich(
    drilldown: pd.DataFrame,
    account_list: pd.DataFrame,
    accounts: pd.DataFrame,
    overrides: list[dict] | None = None,
) -> pd.DataFrame:
    """Return the drilldown enriched with PreCustomer, Client, advisor, premium/lives splits.

    Expects normalized column names:
      drilldown:    name, memo, income_account, amount, quantity, rate, txn_date, period,
                    txn_type, invoice_no, product_code, item_split, customer
      account_list: NAME, GROUP ID, SYSTEM ID (case-insensitive lookups built below)
      accounts:     name, oid, livesCount, monthlyPremium, brokerList, consultingHouses
    """
    df = drilldown.copy()

    # --- lookups from the account list -------------------------------------
    al = account_list.rename(columns=lambda c: str(c).strip())
    sysid_by_name = dict(zip(al["NAME"].map(_norm), al["SYSTEM ID"].map(_norm)))
    al_by_sysid = (
        al.dropna(subset=["SYSTEM ID"])
          .assign(_sid=al["SYSTEM ID"].map(_norm))
          .drop_duplicates("_sid")
          .set_index("_sid")
    )

    # --- PreCustomer -------------------------------------------------------
    payer = df["customer"] if "customer" in df.columns else df["name"]
    df["PreCustomer"] = [
        resolve_precustomer(n, c, m, ia, sysid_by_name)
        for n, c, m, ia in zip(df["name"], payer, df["memo"], df["income_account"])
    ]
    # fall back to the customer/payer field if a branch resolved to nothing
    df["PreCustomer"] = df["PreCustomer"].where(df["PreCustomer"].notna(), payer)

    # --- Join 1: PreCustomer -> account_list SYSTEM ID ---------------------
    def _al(sid, col):
        sid = _norm(sid)
        if sid in al_by_sysid.index:
            return al_by_sysid.at[sid, col]
        return None

    df["bill_name"] = df["PreCustomer"].map(lambda s: _al(s, "NAME"))
    df["group_id"] = df["PreCustomer"].map(lambda s: _al(s, "GROUP ID"))
    df["system_id"] = df["PreCustomer"].map(lambda s: _al(s, "SYSTEM ID"))
    df["account_id"] = df["PreCustomer"].map(
        lambda s: (lambda v: str(v).strip() if v is not None and not (isinstance(v, float) and pd.isna(v)) else None)(
            _al(s, "ACCOUNT ID")
        )
    )

    # --- Client ------------------------------------------------------------
    # Client = GROUP ID, unless it's missing/blank/'N/A' (the account list stores
    # "no group" as an empty cell OR the literal 'N/A'), in which case use SYSTEM ID.
    def _missing(v) -> bool:
        return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and v.strip() in ("", NA_GROUP))

    def _client(row):
        gid, sid, pre = _norm(row["group_id"]), _norm(row["system_id"]), _norm(row["PreCustomer"])
        if _missing(gid):
            return pre if _missing(sid) else sid
        return gid

    df["client_key"] = df.apply(_client, axis=1)
    df["resolved"] = ~df["system_id"].map(_missing)  # matched the account list

    # --- manual overrides (persisted corrections) --------------------------
    if overrides:
        for ov in overrides:
            mt, mv, ck = ov.get("match_type"), _norm(ov.get("match_value")), ov.get("client_key")
            if mt == "name":
                df.loc[df["name"].map(_norm) == mv, "client_key"] = ck
            elif mt == "precustomer":
                df.loc[df["PreCustomer"].map(_norm) == mv, "client_key"] = ck
            elif mt == "memo":
                df.loc[df["memo"].map(_norm) == mv, "client_key"] = ck
            elif mt == "memo_contains" and mv:
                needle = mv
                df.loc[
                    df["memo"].map(lambda m: isinstance(m, str) and needle in m),
                    "client_key",
                ] = ck

    # --- Join 2: account_list ACCOUNT ID -> accounts.oid (NAME as fallback) --
    # Prefer oid: names drift (e.g. "Vibrant Community Health" vs
    # "Vibrant Healthcare Alliance") while ACCOUNT ID / oid stay stable.
    acc = accounts.rename(columns=lambda c: str(c).strip())
    acc_by_oid = (
        acc.dropna(subset=["oid"])
          .assign(_oid=lambda x: x["oid"].map(lambda v: str(v).strip() if v is not None else None))
          .drop_duplicates("_oid")
          .set_index("_oid")
    )
    acc_by_name = (
        acc.dropna(subset=["name"])
          .assign(_name=lambda x: x["name"].map(_norm))
          .drop_duplicates("_name")
          .set_index("_name")
    )

    def _acc_row(account_id, bill_name):
        aid = str(account_id).strip() if account_id is not None else None
        if aid and aid in acc_by_oid.index:
            return acc_by_oid.loc[aid]
        name = _norm(bill_name)
        if name in acc_by_name.index:
            return acc_by_name.loc[name]
        return None

    def _acc(account_id, bill_name, col):
        row = _acc_row(account_id, bill_name)
        if row is None or col not in row.index:
            return None
        return row[col]

    df["oid"] = [
        _acc(aid, bn, "oid") for aid, bn in zip(df["account_id"], df["bill_name"])
    ]
    df["premium"] = pd.to_numeric(
        [_acc(aid, bn, "monthlyPremium") for aid, bn in zip(df["account_id"], df["bill_name"])],
        errors="coerce",
    )
    df["lives"] = pd.to_numeric(
        [_acc(aid, bn, "livesCount") for aid, bn in zip(df["account_id"], df["bill_name"])],
        errors="coerce",
    )
    df["advisor"] = [
        _acc(aid, bn, "brokerList") for aid, bn in zip(df["account_id"], df["bill_name"])
    ]
    df["consulting_house"] = [
        _acc(aid, bn, "consultingHouses") for aid, bn in zip(df["account_id"], df["bill_name"])
    ]

    # --- splits: premium/lives per (oid, period) divided by that group's line
    # count, so summing over a period reconstructs the account's premium/lives
    # exactly once. Keyed by period because the drilldown spans many months.
    counts = df.groupby(["oid", "period"])["amount"].transform("size")
    df["row_count"] = counts
    df["premium_split"] = df["premium"] / counts
    df["lives_split"] = df["lives"] / counts

    return df
