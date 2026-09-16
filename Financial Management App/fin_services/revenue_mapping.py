"""
Revenue transaction enrichment / client resolution.

Ports the Power Query that builds the "Data" sheet:
  PreCustomer  -> resolve SYSTEM ID from the QBO name (Group:SystemId after ':')
  Join 1       -> PreCustomer == account_list.SYSTEM ID   (NAME, GROUP ID, ACCOUNT ID)
  Join 2       -> ACCOUNT ID == accounts.oid
  Client       -> GROUP ID, or SYSTEM ID when GROUP ID == 'N/A'

All functions are Flask-free and DB-free, operating on DataFrames so they stay
reusable by the web routes, the MCP server and the validation scripts. This
module resolves *natural keys* only (oid, client_key, product code, advisor
name); ``revenue_ingest`` turns those into foreign keys.

Two behaviours changed in the schema refactor:

* **The premium/lives split is gone.** It divided an account's premium by its
  row count so Excel pivots would not multiply-count. Because the accounts CSV
  is a *today* snapshot, computing it here stamped September 2026 premium onto
  2025-08 rows. Premium now lives in ``account_period_metrics``, keyed by month.
* **The NAME fallback in Join 2 is gone.** ``accounts.name`` has 2 duplicates
  across 1,492 rows, so under FK-based attribution the fallback could silently
  bind revenue to the wrong account — worse than leaving the row unresolved.
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


def _missing(v) -> bool:
    return (
        v is None
        or (isinstance(v, float) and pd.isna(v))
        or (isinstance(v, str) and v.strip() in ("", NA_GROUP))
    )


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


# ---------------------------------------------------------------------------
# Durable ingest corrections
# ---------------------------------------------------------------------------

_MATCH_COLUMNS = {
    "match_oid": "oid",
    "match_invoice_no": "invoice_no",
    "match_product_code": "product_code",
    "match_income_account": "income_account",
    "match_name": "name",
    "match_precustomer": "PreCustomer",
    "match_memo": "memo",
}


def _correction_mask(df: pd.DataFrame, rule: dict) -> pd.Series:
    """Build the AND-ed row mask for one correction rule.

    A NULL match_* column means "no filter on that column". A rule with no
    filters at all matches nothing — a blanket rewrite is never what was meant.
    """
    mask = pd.Series(True, index=df.index)
    applied_any = False

    period_from, period_to = rule.get("period_from"), rule.get("period_to")
    if period_from:
        mask &= df["period"] >= period_from
        applied_any = True
    if period_to:
        mask &= df["period"] <= period_to
        applied_any = True

    for key, column in _MATCH_COLUMNS.items():
        value = _norm(rule.get(key))
        if value in (None, ""):
            continue
        if column not in df.columns:
            return pd.Series(False, index=df.index)
        mask &= df[column].map(_norm) == value
        applied_any = True

    needle = _norm(rule.get("match_memo_contains"))
    if needle:
        mask &= df["memo"].map(lambda m: isinstance(m, str) and needle in m)
        applied_any = True

    if not applied_any:
        return pd.Series(False, index=df.index)
    return mask


def apply_corrections(df: pd.DataFrame, corrections: list[dict] | None) -> pd.DataFrame:
    """Apply durable ingest corrections in place, recording which rule hit.

    Runs *before* the load so a re-upload re-applies every fix instead of wiping
    it — the defect that made re-importing Aug 2025 destroy the manual qty/rate
    repairs. Each rule's hit count comes back on ``df.attrs['correction_counts']``
    so a rule that has gone stale (0 hits) can be surfaced.
    """
    counts: dict[int, int] = {}
    if not corrections:
        df.attrs["correction_counts"] = counts
        return df

    for rule in corrections:
        if rule.get("status", "active") != "active":
            continue
        mask = _correction_mask(df, rule)
        hits = int(mask.sum())
        counts[rule.get("id")] = hits
        if not hits:
            continue

        field = rule.get("target_field")
        strategy = rule.get("strategy", "set_value")
        text, number = rule.get("target_text"), rule.get("target_number")

        if field == "exclude":
            df.loc[mask, "is_excluded_by_rule"] = 1
        elif field == "client_key":
            df.loc[mask, "client_key"] = text
        elif field in ("product_code", "income_account"):
            df.loc[mask, field] = text
        elif field == "quantity":
            if strategy == "derive_quantity_from_rate" and number:
                df.loc[mask, "quantity"] = df.loc[mask, "amount"] / number
                df.loc[mask, "rate"] = number
            elif strategy == "scale" and number:
                df.loc[mask, "quantity"] = df.loc[mask, "quantity"] * number
            else:
                df.loc[mask, "quantity"] = number
        elif field == "rate":
            if strategy == "derive_rate_from_quantity":
                qty = df.loc[mask, "quantity"].replace(0, pd.NA)
                df.loc[mask, "rate"] = df.loc[mask, "amount"] / qty
            elif strategy == "scale" and number:
                df.loc[mask, "rate"] = df.loc[mask, "rate"] * number
            else:
                df.loc[mask, "rate"] = number

        df.loc[mask, "correction_id"] = rule.get("id")

    df.attrs["correction_counts"] = counts
    return df


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------


def enrich(
    drilldown: pd.DataFrame,
    account_list: pd.DataFrame,
    accounts: pd.DataFrame,
    corrections: list[dict] | None = None,
) -> pd.DataFrame:
    """Return the drilldown resolved to natural keys.

    Expects normalized column names:
      drilldown:    name, memo, income_account, amount, quantity, rate, txn_date,
                    period, txn_type, invoice_no, product_code, item_split, customer
      account_list: NAME, GROUP ID, SYSTEM ID, ACCOUNT ID (case-sensitive headers)
      accounts:     name, oid, brokerList, consultingHouses
    """
    df = drilldown.copy()
    df["correction_id"] = pd.NA
    df["is_excluded_by_rule"] = 0

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
        if sid in al_by_sysid.index and col in al_by_sysid.columns:
            return al_by_sysid.at[sid, col]
        return None

    def _clean(v):
        return None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()

    df["bill_name"] = df["PreCustomer"].map(lambda s: _al(s, "NAME"))
    df["legal_name"] = df["PreCustomer"].map(lambda s: _al(s, "LEGAL NAME"))
    df["group_id"] = df["PreCustomer"].map(lambda s: _al(s, "GROUP ID"))
    df["system_id"] = df["PreCustomer"].map(lambda s: _al(s, "SYSTEM ID"))
    df["account_id"] = df["PreCustomer"].map(lambda s: _clean(_al(s, "ACCOUNT ID")))

    # --- Client ------------------------------------------------------------
    # Client = GROUP ID, unless it's missing/blank/'N/A' (the account list stores
    # "no group" as an empty cell OR the literal 'N/A'), in which case use SYSTEM ID.
    def _client(row):
        gid, sid, pre = _norm(row["group_id"]), _norm(row["system_id"]), _norm(row["PreCustomer"])
        if _missing(gid):
            return pre if _missing(sid) else sid
        return gid

    df["client_key"] = df.apply(_client, axis=1)
    df["client_key_kind"] = [
        "group_id" if not _missing(g) else ("system_id" if not _missing(s) else "qbo_name")
        for g, s in zip(df["group_id"], df["system_id"])
    ]
    df["resolved"] = ~df["system_id"].map(_missing)  # matched the account list

    # --- Join 2: account_list ACCOUNT ID -> accounts.oid -------------------
    # oid only. The former NAME fallback is deliberately gone: accounts.name has
    # 2 duplicates, so it could bind revenue to the wrong account silently.
    acc = accounts.rename(columns=lambda c: str(c).strip())
    known_oids = {
        _clean(v) for v in acc["oid"].dropna().tolist()
    } if "oid" in acc.columns else set()

    df["oid"] = [aid if aid in known_oids else None for aid in df["account_id"]]

    acc_by_oid = (
        acc.dropna(subset=["oid"])
           .assign(_oid=lambda x: x["oid"].map(_clean))
           .drop_duplicates("_oid")
           .set_index("_oid")
    ) if "oid" in acc.columns else pd.DataFrame()

    def _acc(oid, col):
        if oid is None or acc_by_oid.empty or oid not in acc_by_oid.index:
            return None
        if col not in acc_by_oid.columns:
            return None
        return acc_by_oid.at[oid, col]

    # Advisor / consulting house as observed at import. These are snapshots for
    # forensics and for Deploy A parity; the period-correct values live on
    # account_period_metrics.
    df["advisor"] = [_first_element(_acc(o, "brokerList")) for o in df["oid"]]
    df["consulting_house"] = [_first_element(_acc(o, "consultingHouses")) for o in df["oid"]]

    # --- durable corrections, applied before the load ----------------------
    df = apply_corrections(df, corrections)

    return df


def _first_element(value):
    """First element of a pipe-joined accounts-CSV list field.

    brokerList and consultingHouses hold exactly one element in 1,490 of 1,492
    rows, so the first element is the value; the raw string is preserved
    alongside it by the ingest layer.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text.split("|")[0].strip() or None
