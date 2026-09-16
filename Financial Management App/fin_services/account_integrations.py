"""HRIS / payroll integration tracking — overview, CRUD and sheet import.

Nothing upstream carries this data: the accounts API returns 32 columns and none
of them names a vendor, so this is hand-maintained reference data.

Keyed on the **client** - the level a feed is contracted and maintained at.
``clients.id`` is a surrogate that does not drift (``client_keys`` absorbs
GROUP ID renames), so it anchors as safely as ``accounts.oid``. ``account_id``
is available, NULL by default, for an integration covering only one account.

Flask-free, like the rest of fin_services.

SQLite cannot express "no two live integrations for the same account and vendor
may overlap in time", so ``validate_no_overlap`` enforces it on write — the same
place the open-enum validation lives.
"""

from __future__ import annotations

import re
import sqlite3

import pandas as pd

from fin_services.reference_data import iso_now, split_list

ROLES = ("payroll", "hris", "benefits")

CONNECTION_TYPES = ("api", "sftp_feed", "file_upload", "manual", "none")
DIRECTIONS = ("inbound", "outbound", "bidirectional")

# The business's own vocabulary from the integration list, plus a terminal state.
# Using their words rather than an invented lifecycle keeps the page readable to
# the people who maintain it.
STATUSES = ("in_discussion", "preparation", "on_trial", "stable", "maintenance", "retired")

# A feed under maintenance, on trial or in preparation is still a feed - it must
# not drop the client out of a "clients with an integration" count.
ACTIVE_STATUSES = ("stable", "maintenance", "on_trial", "preparation")

# Source label -> stored status. The raw label is kept on status_raw so nothing
# the business wrote is lost to the mapping.
STATUS_FROM_SOURCE = {
    "stable": "stable",
    "preparation": "preparation",
    "in preparation": "preparation",
    "on trial": "on_trial",
    "trial": "on_trial",
    "in discussion": "in_discussion",
    "discussion": "in_discussion",
    "maintenance in progress": "maintenance",
    "maintenance": "maintenance",
    "retired": "retired",
}

ROLE_FROM_SOURCE = {"hris": "hris", "payroll": "payroll", "benefits": "benefits"}


class IntegrationError(ValueError):
    """Raised for a validation failure the service layer must enforce itself."""


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------


def list_vendors(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM integration_vendors WHERE status != 'retired' ORDER BY name"
    )]


def resolve_vendor(conn, name: str | None) -> tuple[int | None, str | None]:
    """Match a typed vendor name to the catalogue, by name then by alias.

    Returns ``(vendor_id, leftover_raw_name)``. An unmatched name is kept as raw
    text rather than rejected — a locked catalogue stops data entry dead the
    first time someone hits a vendor nobody anticipated. The review screen
    promotes raw names into the catalogue.
    """
    key = (name or "").strip()
    if not key:
        return None, None

    row = conn.execute(
        "SELECT id FROM integration_vendors WHERE LOWER(name) = LOWER(?)", (key,)
    ).fetchone()
    if row:
        return row[0], None

    for vendor in conn.execute("SELECT id, aliases FROM integration_vendors"):
        for alias in split_list(vendor["aliases"]):
            if alias.lower() == key.lower():
                return vendor["id"], None
    return None, key


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_no_overlap(conn, client_id: int, vendor_id: int | None, role: str,
                        effective_from: str, effective_to: str | None,
                        exclude_id: int | None = None) -> None:
    """Reject an integration whose active window overlaps an existing one.

    Two half-open ranges [a_from, a_to) and [b_from, b_to) overlap when
    a_from < b_to and b_from < a_to, treating a NULL end as open-ended.
    """
    sql = (
        "SELECT id, effective_from, effective_to FROM account_integrations "
        "WHERE client_id = ? AND role = ? AND status != 'retired' "
        "AND ((vendor_id IS NULL AND ? IS NULL) OR vendor_id = ?)"
    )
    params = [client_id, role, vendor_id, vendor_id]
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)

    for row in conn.execute(sql, params):
        other_to = row["effective_to"]
        starts_before_other_ends = other_to is None or effective_from < other_to
        other_starts_before_this_ends = effective_to is None or row["effective_from"] < effective_to
        if starts_before_other_ends and other_starts_before_this_ends:
            raise IntegrationError(
                f"Overlaps integration #{row['id']} "
                f"({row['effective_from']} to {other_to or 'current'}). "
                "Close the existing row first."
            )


def _validate_fields(role: str, connection_type: str, direction: str, status: str) -> None:
    if role not in ROLES:
        raise IntegrationError(f"role must be one of {ROLES}")
    if connection_type not in CONNECTION_TYPES:
        raise IntegrationError(f"connection_type must be one of {CONNECTION_TYPES}")
    if direction not in DIRECTIONS:
        raise IntegrationError(f"direction must be one of {DIRECTIONS}")
    if status not in STATUSES:
        raise IntegrationError(f"status must be one of {STATUSES}")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def resolve_client_id(conn, client: str) -> int:
    """Resolve a client by display name, key alias, or one of its account names.

    Four passes, all exact or normalised — never fuzzy. Fuzzy matching was tried
    and rejected: it confidently mapped "Lloydminster" to a Panago pizza store
    that merely had the city in its account name.
    """
    row = conn.execute(
        "SELECT id FROM clients WHERE LOWER(display_name) = LOWER(?)", (client,)
    ).fetchone()
    if row:
        return row["id"]

    row = conn.execute(
        "SELECT client_id AS id FROM client_keys WHERE LOWER(key_value) = LOWER(?)", (client,)
    ).fetchone()
    if row:
        return row["id"]

    # Normalised compare absorbs "&" vs "and" and punctuation drift
    # ("WF Steel & Crane" vs "WF Steel and Crane").
    key = _norm_client(client)
    for r in conn.execute("SELECT id, display_name FROM clients"):
        if _norm_client(r["display_name"]) == key:
            return r["id"]

    # Finally, an exact account name resolves to the client that owns it — the
    # list often names the operating company rather than the billing group.
    hits = conn.execute(
        "SELECT DISTINCT client_id FROM accounts "
        "WHERE client_id IS NOT NULL AND LOWER(name) = LOWER(?)", (client,)
    ).fetchall()
    if len(hits) > 1:
        raise IntegrationError(
            f"{client!r} matches accounts under {len(hits)} different clients — "
            "add it to CLIENT_ALIASES to say which."
        )
    if hits:
        return hits[0]["client_id"]

    # Same, normalised.
    for r in conn.execute(
        "SELECT client_id, name FROM accounts WHERE client_id IS NOT NULL AND name IS NOT NULL"
    ):
        if _norm_client(r["name"]) == key:
            return r["client_id"]

    raise IntegrationError(f"No client named {client!r}.")


def create_integration(conn, *, client: str, vendor_name: str, role: str,
                       oid: str | None = None,
                       connection_type="manual", direction="inbound", status="stable",
                       status_raw: str | None = None,
                       effective_from: str | None = None, effective_to=None,
                       external_ref=None, note=None, created_by=None,
                       commit: bool = True) -> int:
    """Record one role of one system for one client.

    Pass ``oid`` only for the exception where the integration covers a single
    account rather than the whole client; it is NULL otherwise.
    """
    client_id = resolve_client_id(conn, client)

    account_id = None
    if oid:
        account = conn.execute(
            "SELECT id, client_id FROM accounts WHERE oid = ?", (str(oid),)
        ).fetchone()
        if account is None:
            raise IntegrationError(f"No account with oid {oid!r}.")
        if account["client_id"] != client_id:
            raise IntegrationError(
                f"Account {oid} does not belong to {client!r}."
            )
        account_id = account["id"]

    _validate_fields(role, connection_type, direction, status)

    vendor_id, raw = resolve_vendor(conn, vendor_name)
    if vendor_id is None and not raw:
        raise IntegrationError("A vendor name is required.")

    effective_from = effective_from or iso_now()[:10]
    validate_no_overlap(conn, client_id, vendor_id, role, effective_from, effective_to)

    now = iso_now()
    cur = conn.execute(
        "INSERT INTO account_integrations (client_id, account_id, vendor_id, "
        "vendor_name_raw, role, connection_type, direction, status, status_raw, "
        "effective_from, effective_to, external_ref, note, created_on, created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (client_id, account_id, vendor_id, raw, role, connection_type, direction,
         status, status_raw, effective_from, effective_to, external_ref, note,
         now, created_by),
    )
    if commit:
        conn.commit()
    return cur.lastrowid


def retire_integration(conn, integration_id: int, effective_to: str | None = None,
                       modified_by: str | None = None) -> None:
    """Close an integration. Never deletes — history is the point of the table."""
    now = iso_now()
    conn.execute(
        "UPDATE account_integrations SET status = 'retired', effective_to = ?, "
        "updated_on = ?, last_modified_by = ? WHERE id = ?",
        (effective_to or now[:10], now, modified_by, integration_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

# LEFT JOIN from clients on purpose: only ~60 of ~490 clients have a feed, so
# absence is the answer to "who still needs one".
_OVERVIEW_SQL = """
SELECT
    c.id                                    AS client_id,
    c.display_name                          AS client,
    (SELECT COUNT(*) FROM accounts a
      WHERE a.client_id = c.id AND a.status IN ('active','updating')) AS active_accounts,
    (SELECT COALESCE(SUM(m.lives), 0) FROM accounts a
       JOIN account_period_metrics m
         ON m.account_id = a.id
        AND m.period = (SELECT MAX(period) FROM account_period_metrics)
      WHERE a.client_id = c.id)             AS lives,
    ai.id                                   AS integration_id,
    ai.role,
    COALESCE(v.name, ai.vendor_name_raw)    AS vendor,
    (ai.vendor_id IS NULL AND ai.vendor_name_raw IS NOT NULL) AS vendor_unmatched,
    ai.connection_type, ai.direction,
    ai.status                               AS integration_status,
    ai.status_raw,
    ai.effective_from, ai.effective_to, ai.external_ref, ai.note,
    acc.oid                                 AS scoped_oid,
    acc.name                                AS scoped_account
FROM clients c
LEFT JOIN account_integrations ai
       ON ai.client_id = c.id AND ai.effective_to IS NULL AND ai.status != 'retired'
LEFT JOIN integration_vendors v ON v.id = ai.vendor_id
LEFT JOIN accounts acc          ON acc.id = ai.account_id
{where}
ORDER BY (ai.id IS NULL), c.display_name, ai.role
"""


def integration_overview(conn, *, only_active_clients: bool = True,
                         with_integration: bool | None = None) -> list[dict]:
    """One row per client per integration role; clients with none appear once."""
    clauses = []
    if only_active_clients:
        clauses.append(
            "(EXISTS (SELECT 1 FROM accounts a WHERE a.client_id = c.id "
            "AND a.status IN ('active','updating')) OR ai.id IS NOT NULL)"
        )
    if with_integration is True:
        clauses.append("ai.id IS NOT NULL")
    elif with_integration is False:
        clauses.append("ai.id IS NULL")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return [dict(r) for r in conn.execute(_OVERVIEW_SQL.format(where=where))]


def client_role_flags(conn) -> dict[int, dict[str, bool]]:
    """Which clients have an active payroll / HRIS feed.

    ``ACTIVE_STATUSES`` is the same rule as coverage: preparation, trial,
    stable and maintenance all count; in_discussion and retired do not.
    """
    placeholders = ",".join("?" * len(ACTIVE_STATUSES))
    rows = conn.execute(
        "SELECT DISTINCT client_id, role FROM account_integrations "
        f"WHERE role IN ('payroll', 'hris') AND status IN ({placeholders})",
        ACTIVE_STATUSES,
    ).fetchall()
    flags: dict[int, dict[str, bool]] = {}
    for row in rows:
        entry = flags.setdefault(row["client_id"], {"payroll": False, "hris": False})
        entry[row["role"]] = True
    return flags


def coverage_summary(conn) -> dict:
    """Headline counts for the overview page, counted in CLIENTS."""
    rows = integration_overview(conn)
    with_any = [r for r in rows if r["integration_id"] is not None]
    clients_with = {r["client_id"] for r in with_any}
    all_clients = {r["client_id"] for r in rows}

    by_vendor: dict[str, set] = {}
    for r in with_any:
        by_vendor.setdefault(r["vendor"] or "(unnamed)", set()).add(r["client_id"])
    by_status: dict[str, int] = {}
    for r in with_any:
        by_status[r["integration_status"]] = by_status.get(r["integration_status"], 0) + 1

    return {
        "clients": len(all_clients),
        "with_integration": len(clients_with),
        "without_integration": len(all_clients - clients_with),
        "feeds": len(with_any),
        "payroll": sum(1 for r in with_any if r["role"] == "payroll"),
        "hris": sum(1 for r in with_any if r["role"] == "hris"),
        "by_vendor": {k: len(v) for k, v in
                      sorted(by_vendor.items(), key=lambda kv: -len(kv[1]))},
        "by_status": dict(sorted(by_status.items(), key=lambda kv: -kv[1])),
        "unmatched_vendors": sorted(
            {r["vendor"] for r in with_any if r["vendor_unmatched"] and r["vendor"]}
        ),
    }


def client_rollup(conn) -> list[dict]:
    """One row per client and system, with the roles it serves side by side."""
    return [dict(r) for r in conn.execute("""
        SELECT c.display_name                       AS client,
               COALESCE(v.name, ai.vendor_name_raw) AS vendor,
               MAX(ai.role = 'payroll')             AS payroll,
               MAX(ai.role = 'hris')                AS hris,
               GROUP_CONCAT(DISTINCT ai.status)     AS statuses,
               MIN(ai.effective_from)               AS since
        FROM account_integrations ai
        JOIN clients c                  ON c.id = ai.client_id
        LEFT JOIN integration_vendors v ON v.id = ai.vendor_id
        WHERE ai.effective_to IS NULL AND ai.status != 'retired'
        GROUP BY c.display_name, COALESCE(v.name, ai.vendor_name_raw)
        ORDER BY c.display_name
    """)]


# ---------------------------------------------------------------------------
# Sheet import — the integration list is kept BY CLIENT
# ---------------------------------------------------------------------------

_COLUMN_ALIASES = {
    "client": ("client", "account", "employer", "name", "company"),
    "role": ("type", "role", "used for", "integration type"),
    "vendor": ("system", "vendor", "provider", "platform"),
    "status": ("status", "state"),
    "connection_type": ("connection", "connection type", "method"),
    "effective_from": ("effective from", "go live", "go-live", "start", "live date"),
    "note": ("note", "notes", "comment", "comments"),
}

# Names in the integration list that do not match a client or account record on
# their own. Each was checked against the database by hand; the comment says why.
# Anything not in here and not an exact match is REPORTED, never guessed — the
# cost of binding a feed to the wrong employer is far higher than a manual fix.
CLIENT_ALIASES = {
    # Each was looked up in the database by hand; the comment says what it is.
    "1password (agilebits)": "Agilebits",              # AgileBits Inc dba 1Password
    "altis recruitment": "Altis Recruit.",
    "aurora cannabis": "Aurora",                       # Aurora Cannabis Enterprises Inc.
    "build it by design": "Build It",                  # accounts terminated
    "cabinovo": "Cabinovo",                            # accounts terminated
    "canada pet health (trupanion)": "Trupanion",
    "cando": "Cando Rail",                             # Cando Rail & Terminals
    "dialpad": "Dialpad Canada Inc.",
    "dp world contract logistics canada (aka syncreon)": "Syncreon Canada",
                                                       # oid 2659 sits under Syncreon Canada,
                                                       # NOT the separate DP World client
    "fotenn consultants": "Fotenn",
    "ggfl": "GGFL LLP",
    "greenhouse juice": "Greenhouse",                  # Greenhouse Juice Co.
    "mccay duff": "McCay Duff LLP",
    "multiview": "Multiview Inc",
    "nexus water group": "Nexus Water Gr",
    "osg canada": "OSG Canada Ltd.",
    "pollard": "Pollard Banknote LTD",
    "renaissance repair and supply": "Renaissance",
    "russell hendrix": "Russell Food Equip",           # confirmed: Russell Hendrix acquired Russell Food
    "service quality measurement group": "SQM Group",
    "veg": "Veterinary Em. Group",                     # confirmed: Veterinary Emergency Group
    "tipalti canada": "Tipalti",
    "wagonmaster": "Wagonmaster Holdings",             # accounts terminated
    "westower": "WesTower Comm",
}

# On the list but not yet clients — integrations under discussion for prospects.
# They import automatically once the client is onboarded.
NOT_YET_CLIENTS = {"kndS".lower(), "lloydminster"}

# One list entry covering two distinct clients.
CLIENT_SPLITS = {
    "lifestyles and carrington": ["Lifestyles", "Carrington"],
}


def _norm_client(value: str) -> str:
    text = str(value).lower().replace("&", " and ").replace("/", " ")
    text = re.sub(r"[^a-z0-9()]+", " ", text)
    return " ".join(text.split())


def _match_columns(df: pd.DataFrame) -> dict:
    lowered = {str(c).strip().lower(): c for c in df.columns}
    found = {}
    for field, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                found[field] = lowered[alias]
                break
    return found


def import_integration_sheet(conn, df: pd.DataFrame, created_by: str | None = None,
                             dry_run: bool = False) -> dict:
    """Load the integration list, which is kept by CLIENT and by role.

    Each list row is one (client, role, system, status). A client's feed covers
    every one of its active accounts, so a row expands to one integration per
    account — the grain the rest of the schema uses.

    Nothing is written when any row fails to resolve unless ``dry_run`` is False
    and you accept the reported skips; run with ``dry_run=True`` first.
    """
    cols = _match_columns(df)
    for required in ("client", "vendor"):
        if required not in cols:
            raise IntegrationError(
                f"Could not find a {required} column. Looked for "
                f"{_COLUMN_ALIASES[required]}; sheet has {list(df.columns)}"
            )

    created, skipped, unresolved_clients = 0, [], {}
    unmatched_vendors, resolved_clients = set(), set()

    for idx, row in df.iterrows():
        line = idx + 2  # header is row 1 in the spreadsheet
        raw_client = str(row[cols["client"]]).strip()
        vendor = str(row[cols["vendor"]]).strip() if pd.notna(row[cols["vendor"]]) else ""
        if not raw_client or not vendor:
            skipped.append({"row": line, "client": raw_client,
                            "reason": "missing client or system"})
            continue

        raw_role = str(row[cols["role"]]).strip() if "role" in cols and pd.notna(row[cols["role"]]) else ""
        role = ROLE_FROM_SOURCE.get(raw_role.lower())
        if role is None:
            skipped.append({"row": line, "client": raw_client,
                            "reason": f"unknown integration type {raw_role!r}"})
            continue

        raw_status = (str(row[cols["status"]]).strip()
                      if "status" in cols and pd.notna(row[cols["status"]]) else "Stable")
        status = STATUS_FROM_SOURCE.get(raw_status.lower())
        if status is None:
            skipped.append({"row": line, "client": raw_client,
                            "reason": f"unknown status {raw_status!r}"})
            continue

        for target in CLIENT_SPLITS.get(_norm_client(raw_client), [raw_client]):
            if _norm_client(target) in NOT_YET_CLIENTS:
                skipped.append({"row": line, "client": target,
                                "reason": "not a client yet — integration under discussion"})
                continue

            resolved = CLIENT_ALIASES.get(_norm_client(target), target)
            try:
                resolve_client_id(conn, resolved)
            except IntegrationError as exc:
                unresolved_clients.setdefault(target, str(exc))
                skipped.append({"row": line, "client": target, "reason": str(exc)})
                continue

            vid, vraw = resolve_vendor(conn, vendor)
            if vid is None and vraw:
                unmatched_vendors.add(vraw)

            resolved_clients.add(resolved)
            if dry_run:
                created += 1
                continue
            try:
                create_integration(
                    conn, client=resolved, vendor_name=vendor, role=role,
                    status=status, status_raw=raw_status,
                    connection_type="sftp_feed",
                    effective_from=(str(row[cols["effective_from"]]).strip()[:10]
                                    if "effective_from" in cols
                                    and pd.notna(row[cols["effective_from"]]) else None),
                    note=(str(row[cols["note"]]).strip()
                          if "note" in cols and pd.notna(row[cols["note"]]) else None),
                    created_by=created_by, commit=False,
                )
                created += 1
            except IntegrationError as exc:
                skipped.append({"row": line, "client": target, "reason": str(exc)})
            except sqlite3.IntegrityError as exc:
                skipped.append({"row": line, "client": target, "reason": f"constraint: {exc}"})

    if not dry_run:
        conn.commit()

    return {
        "created": created,
        "skipped": skipped,
        "clients_resolved": len(resolved_clients),
        "unresolved_clients": unresolved_clients,
        "unmatched_vendors": sorted(unmatched_vendors),
    }
