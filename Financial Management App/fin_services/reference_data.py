"""Parsers and seed data for the reference taxonomies.

Flask-free and DataFrame-free so the web routes, the CLI runners, the tests and
(later) the MCP server can all share them — same rule as the rest of fin_services.

Three source formats are decoded here:

* **Product codes** — ``[VEN-|ASO ]{Admin|Comm}-{BENEFIT}[(13|14|15)]``. The
  trailing number is the **HST rate**, i.e. the tax jurisdiction, not a pay
  frequency. Splitting it off ``benefit_code`` is what makes "Extended Health
  revenue nationally" answerable: today ``Admin-EH``, ``Admin-EH(13)``,
  ``Admin-EH(14)`` and ``Admin-EH(15)`` are four unrelated strings.
* **Policies** — ``"<Carrier> - <PolicyNo>"`` from the accounts CSV. Carrier is
  fully recoverable; the benefit suffix is *not* (most are numeric), so it is
  read from an allowlist only.
* **Source dates** — the accounts API returns ``"May 1, 2021"``, not ISO.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

LIST_DELIMITER = " | "

# ---------------------------------------------------------------------------
# Timestamps — house convention: ISO-8601 UTC with a trailing Z, made in Python
# ---------------------------------------------------------------------------


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Product codes
# ---------------------------------------------------------------------------

# Optional whitespace before the paren: "VEN-Admin-Sub Fee (15)" occurs.
_HST_SUFFIX = re.compile(r"\s*\((1[345])\)\s*$")
_VENDOR_PREFIX = re.compile(r"^ven-", re.I)
_ASO_PREFIX = re.compile(r"^aso\s+", re.I)
_ADMIN_PREFIX = re.compile(r"^admin-", re.I)
_COMM_PREFIX = re.compile(r"^comm-", re.I)

# Codes that carry no {Admin|Comm}- prefix and must be classified whole.
_STANDALONE_FEE_KIND = {
    "EMAIL FEED": "other",
    "STATEMENT OF WORK": "other",
    "GST-ROUNDING": "tax",
    "HST-ROUNDING": "tax",
    "NSF-FEE": "fee",
    "WIRE-FEE": "fee",
    "ADMIN ERROR - WRITE OFF": "adjustment",
}

# Benefit tokens that are really a fee or an adjustment despite an Admin- prefix.
_BENEFIT_FEE_KIND = {
    "ROUNDING": "adjustment",
    "PAD PROCESSING FEE": "fee",
    "PAPER BILL FEE": "fee",
}


def normalize_product_code(code: str) -> str:
    """Collapse casing and whitespace drift: COMM-EV/Comm-EV, VEN-admin-SA."""
    return re.sub(r"\s+", " ", str(code).strip()).upper()


def parse_product_code(code: str) -> dict:
    """Decompose a product code into channel, fee kind, benefit and HST rate.

    ``benefit_code`` is deliberately conservative — it normalises case and
    whitespace only. "Sub Fee" and "Subscription Fee" are left as distinct
    benefits rather than guessed into one; the reference review screen is the
    place to merge them if they really are the same thing.
    """
    raw = str(code).strip()
    normalized = normalize_product_code(raw)

    hst_rate = None
    m = _HST_SUFFIX.search(raw)
    body = raw
    if m:
        hst_rate = int(m.group(1))
        body = raw[: m.start()].strip()

    channel = "direct"
    if _VENDOR_PREFIX.match(body):
        channel = "vendor"
        body = _VENDOR_PREFIX.sub("", body, count=1).strip()
    elif _ASO_PREFIX.match(body):
        channel = "aso"
        body = _ASO_PREFIX.sub("", body, count=1).strip()

    fee_kind = None
    if _ADMIN_PREFIX.match(body):
        fee_kind = "admin"
        body = _ADMIN_PREFIX.sub("", body, count=1).strip()
    elif _COMM_PREFIX.match(body):
        fee_kind = "commission"
        body = _COMM_PREFIX.sub("", body, count=1).strip()
    else:
        fee_kind = _STANDALONE_FEE_KIND.get(normalize_product_code(body), "other")

    benefit_code = re.sub(r"\s+", " ", body).strip().upper() or None
    if benefit_code in _BENEFIT_FEE_KIND:
        fee_kind = _BENEFIT_FEE_KIND[benefit_code]

    return {
        "code": raw,
        "code_normalized": normalized,
        "channel": channel,
        "fee_kind": fee_kind,
        "benefit_code": benefit_code,
        "hst_rate": hst_rate,
    }


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

# Only ~530 of the ~5,170 policy suffixes are real benefit tokens; the rest are
# numeric (0008, 0053, 007). An allowlist is the only safe way to read one —
# never infer a benefit line from "0008".
_BENEFIT_LINE_ALLOWLIST = {
    "life": "Life",
    "deplife": "DepLife",
    "optlife": "OptLife",
    "ltd": "LTD",
    "std": "STD",
    "health": "Health",
    "dental": "Dental",
    "optional": "Optional",
    "eap": "EAP",
    "efap": "EFAP",
    "aso": "ASO",
    "ci": "CI",
    "ad&d": "AD&D",
    "add": "AD&D",
    "hsa": "HSA",
    "tsa": "TSA",
}

_PLACEHOLDER_POLICY_NOS = {"TBD", "N/A", "NA", "UNKNOWN"}


def parse_policy(raw: str) -> dict | None:
    """Split ``"<Carrier> - <PolicyNo>"`` into its parts.

    Returns None for a blank element. Splits on the *first* " - " because policy
    numbers themselves contain hyphens ("1013-DepLife") while carrier names in
    the observed data do not contain " - ".
    """
    value = str(raw).strip()
    if not value:
        return None

    carrier_name, _, policy_no = value.partition(" - ")
    carrier_name = carrier_name.strip()
    policy_no = policy_no.strip()

    if not policy_no:
        # No delimiter — the whole element is the policy reference.
        carrier_name, policy_no = "", value

    benefit_line = None
    if "-" in policy_no:
        suffix = policy_no.rsplit("-", 1)[1].strip()
        benefit_line = _BENEFIT_LINE_ALLOWLIST.get(suffix.lower())

    return {
        "carrier_name": carrier_name or None,
        "policy_no": policy_no,
        "benefit_line": benefit_line,
        "is_placeholder": 1 if policy_no.upper() in _PLACEHOLDER_POLICY_NOS else 0,
        "raw_value": value,
    }


# ---------------------------------------------------------------------------
# Lists and dates from the accounts CSV
# ---------------------------------------------------------------------------


def split_list(value) -> list[str]:
    """Split a pipe-joined accounts-CSV list field. Empty elements dropped."""
    if value is None:
        return []
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return []
    return [part.strip() for part in text.split("|") if part.strip()]


_SOURCE_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y")


def parse_source_date(value) -> str | None:
    """Normalise an accounts-API date ("May 1, 2021") to ISO yyyy-mm-dd.

    Returns None rather than raising — an unparseable date is counted into the
    import's parity report instead of failing the whole load.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none", ""):
        return None
    for fmt in _SOURCE_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_bool(value) -> int:
    """Accounts CSV writes booleans as the literal strings True/False."""
    return 1 if str(value).strip().lower() in ("true", "1", "yes") else 0


def account_status(is_active, is_updating) -> str:
    """Collapse isActive + isUpdating into one enum.

    485 of 1,492 accounts (33%) are terminated, so a boolean was never adequate
    for a drilldown that spans 13 months.
    """
    if parse_bool(is_updating):
        return "updating"
    return "active" if parse_bool(is_active) else "terminated"


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------

# (name, category, basis, exclude_from_reports)
# The 15 income accounts observed across all 13 periods. Anything new seen at
# import is auto-registered as ('unclassified', status='review') and surfaces on
# the reference review page rather than failing the load.
INCOME_ACCOUNT_SEEDS = [
    ("Admin Fees (earned on Premium)",                        "admin_fee",      "premium",  False),
    ("Admin Fees (earned on Claims)",                         "admin_fee",      "claims",   False),
    ("Admin Fees (earned on Sub. Fees)",                      "admin_fee",      "sub_fees", False),
    ("Admin Fees (earned on RRSP)",                           "admin_fee",      "rrsp",     False),
    ("Admin Fees (paid by Vendors)",                          "admin_fee",      "vendor",   False),
    ("Commissions (earned on Premium)",                       "commission",     "premium",  False),
    ("Commissions (earned on Claims)",                        "commission",     "claims",   False),
    ("Commissions (earned on Bonus)",                         "commission",     "bonus",    False),
    ("Admin Processing Fees:Admin Fees (NSF Charges)",        "processing_fee", "none",     False),
    ("Admin Processing Fees:Admin Fees (Mailed Statements)",  "processing_fee", "none",     False),
    ("Admin Processing Fees:Admin Fee (PAD Processing Fee)",  "processing_fee", "none",     False),
    ("Admin Processing Fees:Wires/Bank Charge Backs",         "processing_fee", "none",     False),
    ("Admin Errors/Write offs",                               "adjustment",     "none",     False),
    # The two accounts the old EXCLUDED_INCOME_ACCOUNTS frozenset filtered out.
    ("Referral Fees:Email Feed",                              "referral_fee",   "none",     True),
    ("Statement of Work",                                     "project",        "none",     True),
]

# (name, pipe-joined aliases)
INTEGRATION_VENDOR_SEEDS = [
    ("ADP",                 "ADP Workforce Now | ADP WFN | A.D.P. | ADP TeamPay | ADP Canada"),
    ("Ceridian Dayforce",   "Dayforce | Ceridian | Ceridian HCM | Powerpay"),
    ("SAP SuccessFactors",  "SAP | SuccessFactors | SAP HCM | SAP Success Factors"),
    ("Oracle HCM",          "Oracle | Oracle Fusion | Oracle HCM Cloud"),
    ("Avanti",              "Avanti Software"),
    ("TOPS",                "TOPS Software"),
    ("Workday",             "Workday HCM"),
    ("UKG",                 "UltiPro | Kronos | UKG Pro | UKG Ready"),
    ("BambooHR",            "Bamboo | Bamboo HR"),
    ("Humi",                "Humi HR"),
    ("Payworks",            ""),
    ("Nethris",             ""),
    ("Rise",                "Rise People | RisePeople"),
    ("QuickBooks Payroll",  "QBO Payroll | Intuit Payroll | Quickbooks | QuickBooks"),
    ("Other",               ""),
]


# ---------------------------------------------------------------------------
# Reference review — classify auto-inserted products / income accounts
# ---------------------------------------------------------------------------

INCOME_CATEGORIES = (
    "admin_fee", "commission", "referral_fee", "processing_fee",
    "project", "adjustment", "tax", "unclassified",
)
INCOME_BASES = ("premium", "claims", "sub_fees", "rrsp", "bonus", "vendor", "none")
PRODUCT_CHANNELS = ("direct", "vendor", "aso")
PRODUCT_FEE_KINDS = ("admin", "commission", "tax", "fee", "adjustment", "other")
REFERENCE_STATUSES = ("active", "review", "retired")


class ReferenceError(ValueError):
    """Raised for a validation failure on a reference-taxonomy edit."""


def review_counts(conn) -> dict:
    """How many auto-inserted rows are still waiting to be classified."""
    income = conn.execute(
        "SELECT COUNT(*) FROM income_accounts WHERE status = 'review'"
    ).fetchone()[0]
    products = conn.execute(
        "SELECT COUNT(*) FROM products WHERE status = 'review'"
    ).fetchone()[0]
    return {"income_accounts": income, "products": products, "total": income + products}


def list_income_accounts(conn, status: str | None = "review") -> list[dict]:
    sql = "SELECT * FROM income_accounts"
    params: list = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY name"
    return [dict(r) for r in conn.execute(sql, params)]


def list_products(conn, status: str | None = "review") -> list[dict]:
    sql = "SELECT * FROM products"
    params: list = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY code"
    return [dict(r) for r in conn.execute(sql, params)]


def _require_enum(value, allowed, field: str):
    if value not in allowed:
        raise ReferenceError(f"{field} must be one of {', '.join(allowed)}.")
    return value


def update_income_account(
    conn,
    income_id: int,
    *,
    category: str,
    basis: str | None,
    exclude_from_reports: bool | int = False,
    status: str = "active",
    note: str | None = None,
    commit: bool = True,
) -> None:
    """Classify an income account and (usually) promote it out of review."""
    _require_enum(category, INCOME_CATEGORIES, "category")
    if basis in ("", None):
        basis = None
    else:
        _require_enum(basis, INCOME_BASES, "basis")
    _require_enum(status, REFERENCE_STATUSES, "status")

    row = conn.execute("SELECT id FROM income_accounts WHERE id = ?", (income_id,)).fetchone()
    if row is None:
        raise ReferenceError(f"No income account with id {income_id}.")

    conn.execute(
        "UPDATE income_accounts SET category = ?, basis = ?, exclude_from_reports = ?, "
        "status = ?, note = ?, updated_on = ? WHERE id = ?",
        (
            category, basis, 1 if exclude_from_reports else 0,
            status, (note or "").strip() or None, iso_now(), income_id,
        ),
    )
    if commit:
        conn.commit()


def update_product(
    conn,
    product_id: int,
    *,
    channel: str | None,
    fee_kind: str | None,
    benefit_code: str | None,
    hst_rate: int | str | None,
    status: str = "active",
    description: str | None = None,
    commit: bool = True,
) -> None:
    """Confirm or correct a product-code parse, then promote it out of review."""
    if channel in ("", None):
        channel = None
    else:
        _require_enum(channel, PRODUCT_CHANNELS, "channel")
    if fee_kind in ("", None):
        fee_kind = None
    else:
        _require_enum(fee_kind, PRODUCT_FEE_KINDS, "fee_kind")
    _require_enum(status, REFERENCE_STATUSES, "status")

    rate = None
    if hst_rate not in ("", None):
        try:
            rate = int(hst_rate)
        except (TypeError, ValueError) as exc:
            raise ReferenceError("hst_rate must be an integer.") from exc
        if rate not in (13, 14, 15):
            raise ReferenceError("hst_rate must be 13, 14 or 15.")

    row = conn.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone()
    if row is None:
        raise ReferenceError(f"No product with id {product_id}.")

    benefit = (benefit_code or "").strip().upper() or None
    conn.execute(
        "UPDATE products SET channel = ?, fee_kind = ?, benefit_code = ?, hst_rate = ?, "
        "status = ?, description = ?, updated_on = ? WHERE id = ?",
        (
            channel, fee_kind, benefit, rate, status,
            (description or "").strip() or None, iso_now(), product_id,
        ),
    )
    if commit:
        conn.commit()


def accept_parsed_products(conn, product_ids: list[int] | None = None) -> int:
    """Promote review products to active, keeping the ingest-time parse.

    Used for the first-pass queue: every unknown code lands as status='review'
    even when the grammar already classified it. Passing no ids accepts the
    whole queue.
    """
    if product_ids:
        placeholders = ",".join("?" * len(product_ids))
        cur = conn.execute(
            f"UPDATE products SET status = 'active', updated_on = ? "
            f"WHERE status = 'review' AND id IN ({placeholders})",
            (iso_now(), *product_ids),
        )
    else:
        cur = conn.execute(
            "UPDATE products SET status = 'active', updated_on = ? WHERE status = 'review'",
            (iso_now(),),
        )
    conn.commit()
    return cur.rowcount
