"""Schema creation and idempotent migrations for the Financial Analysis store.

Reference spine anchored on the EA account ``oid`` — the one identifier that does
not drift. ``client_key`` is *derived* on every import (GROUP ID → SYSTEM ID →
QBO name), so nothing durable may key on it; ``client_keys`` maps every string
ever observed back to a stable ``clients.id`` instead.

  provenance  — revenue_imports, ingest_corrections
  identity    — clients, client_keys, accounts, advisors, consulting_houses,
                carriers, account_policies
  vintaged    — account_period_metrics (lives/premium per account per month)
  taxonomies  — income_accounts, products
  fact        — revenue_lines
  integrations— integration_vendors, account_integrations

See ``schema.dbml`` in the app root for the ERD and the rationale per table.

The legacy tables (fact_revenue, account_snapshot, dim_*, import_batch,
client_mapping_override) are intentionally still created here: both schemas
coexist until the parity harness is green and one full month has run on the new
tables. They are dropped in a separate, later change.

No migrations framework / version table — new tables go in _SCHEMA with
IF NOT EXISTS; new columns are added via introspect-and-ALTER in migrate_schema().
"""

import sqlite3

from fin_db.connection import DB_PATH

_SCHEMA = """
-- ---------------------------------------------------------------- provenance

CREATE TABLE IF NOT EXISTS revenue_imports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL DEFAULT 'drilldown'
                    CHECK(source IN ('drilldown','ar_aging','gl_export')),
    period_from     TEXT,
    period_to       TEXT,
    files_json      TEXT,
    row_counts_json TEXT,
    parity_json     TEXT,
    status          TEXT NOT NULL DEFAULT 'loaded'
                    CHECK(status IN ('loading','loaded','failed','superseded')),
    note            TEXT,
    created_on      TEXT NOT NULL,
    created_by      TEXT
);

-- Generalises client_mapping_override from "fix the client" to "fix any field".
-- All match_* columns are ANDed; NULL means no filter on that column. Applied
-- inside enrich() BEFORE the load, so a re-upload re-applies rather than wipes.
CREATE TABLE IF NOT EXISTS ingest_corrections (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    period_from          TEXT,
    period_to            TEXT,
    match_oid            TEXT,
    match_invoice_no     TEXT,
    match_product_code   TEXT,
    match_income_account TEXT,
    match_name           TEXT,
    match_precustomer    TEXT,
    match_memo           TEXT,
    match_memo_contains  TEXT,
    target_field         TEXT NOT NULL
                         CHECK(target_field IN ('client_key','quantity','rate',
                                                'product_code','income_account','exclude')),
    strategy             TEXT NOT NULL DEFAULT 'set_value'
                         CHECK(strategy IN ('set_value','derive_quantity_from_rate',
                                            'derive_rate_from_quantity','scale')),
    target_text          TEXT,
    target_number        REAL,
    status               TEXT NOT NULL DEFAULT 'active'
                         CHECK(status IN ('active','review','retired')),
    applied_count        INTEGER NOT NULL DEFAULT 0,
    last_applied_on      TEXT,
    note                 TEXT NOT NULL,
    created_on           TEXT NOT NULL,
    created_by           TEXT,
    updated_on           TEXT,
    last_modified_by     TEXT
);

-- ------------------------------------------------------------ client identity

CREATE TABLE IF NOT EXISTS clients (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name   TEXT NOT NULL,
    legal_name     TEXT,
    group_id       TEXT,
    system_id      TEXT,
    status         TEXT NOT NULL DEFAULT 'active'
                   CHECK(status IN ('active','terminated','merged')),
    merged_into_id INTEGER REFERENCES clients(id),
    created_on     TEXT NOT NULL,
    updated_on     TEXT
);

CREATE INDEX IF NOT EXISTS ix_clients_group ON clients(group_id);

-- THE GROUP ID RENAME FIX: every derived key string ever observed maps to a
-- stable client_id, so a rename is an alias insert rather than New + Lost.
CREATE TABLE IF NOT EXISTS client_keys (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id         INTEGER NOT NULL REFERENCES clients(id),
    key_value         TEXT NOT NULL,
    key_kind          TEXT NOT NULL
                      CHECK(key_kind IN ('group_id','system_id','qbo_name','manual')),
    is_current        INTEGER NOT NULL DEFAULT 1,
    first_seen_period TEXT,
    last_seen_period  TEXT,
    created_on        TEXT NOT NULL,
    created_by        TEXT,
    UNIQUE(key_value, key_kind)
);

CREATE INDEX IF NOT EXISTS ix_client_keys_client ON client_keys(client_id);

-- ------------------------------------------------------------- account spine

CREATE TABLE IF NOT EXISTS consulting_houses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    status     TEXT NOT NULL DEFAULT 'active'
               CHECK(status IN ('active','review','retired')),
    created_on TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS advisors (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    consulting_house_id INTEGER REFERENCES consulting_houses(id),
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active','review','retired')),
    created_on          TEXT NOT NULL,
    updated_on          TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    oid                    TEXT NOT NULL UNIQUE,
    name                   TEXT,
    legal_name             TEXT,
    client_id              INTEGER REFERENCES clients(id),
    advisor_id             INTEGER REFERENCES advisors(id),
    consulting_house_id    INTEGER REFERENCES consulting_houses(id),
    status                 TEXT NOT NULL DEFAULT 'active'
                           CHECK(status IN ('active','updating','terminated','unknown')),
    benefit_type           TEXT,
    benefit_package_type   TEXT,
    member_updates_type    TEXT,
    sso_enabled            INTEGER NOT NULL DEFAULT 0,
    gl_reference_code      TEXT,
    gl_reference_codes_raw TEXT,
    plan_design_names_raw  TEXT,
    effective_on           TEXT,
    first_billed_on        TEXT,
    last_pa_access_on      TEXT,
    source_modified_on     TEXT,
    source_error_count     INTEGER NOT NULL DEFAULT 0,
    source_warning_count   INTEGER NOT NULL DEFAULT 0,
    first_seen_import_id   INTEGER REFERENCES revenue_imports(id),
    last_seen_import_id    INTEGER REFERENCES revenue_imports(id),
    created_on             TEXT NOT NULL,
    updated_on             TEXT
);

CREATE INDEX IF NOT EXISTS ix_accounts_client  ON accounts(client_id);
CREATE INDEX IF NOT EXISTS ix_accounts_advisor ON accounts(advisor_id);
CREATE INDEX IF NOT EXISTS ix_accounts_status  ON accounts(status);

CREATE TABLE IF NOT EXISTS carriers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_on TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_policies (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL REFERENCES accounts(id),
    carrier_id     INTEGER REFERENCES carriers(id),
    policy_no      TEXT NOT NULL,
    benefit_line   TEXT,
    is_placeholder INTEGER NOT NULL DEFAULT 0,
    raw_value      TEXT NOT NULL,
    created_on     TEXT NOT NULL,
    UNIQUE(account_id, raw_value)
);

CREATE INDEX IF NOT EXISTS ix_account_policies_carrier ON account_policies(carrier_id);

-- ---------------------------------------------------------- the vintaging fix

-- One row per (account, month). Written only for the period the accounts CSV
-- honestly describes; earlier periods get no row so the ratio renders blank
-- rather than being computed against a later month's premium.
CREATE TABLE IF NOT EXISTS account_period_metrics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          INTEGER NOT NULL REFERENCES accounts(id),
    period              TEXT NOT NULL,
    lives               INTEGER,
    premium             REAL,
    status              TEXT,
    advisor_id          INTEGER REFERENCES advisors(id),
    consulting_house_id INTEGER REFERENCES consulting_houses(id),
    source              TEXT NOT NULL DEFAULT 'accounts_csv'
                        CHECK(source IN ('accounts_csv','manual','estimated')),
    captured_on         TEXT NOT NULL,
    import_id           INTEGER REFERENCES revenue_imports(id),
    created_on          TEXT NOT NULL,
    updated_on          TEXT,
    UNIQUE(account_id, period)
);

CREATE INDEX IF NOT EXISTS ix_apm_period ON account_period_metrics(period);

-- -------------------------------------------------------- reference taxonomies

CREATE TABLE IF NOT EXISTS income_accounts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT NOT NULL UNIQUE,
    category             TEXT NOT NULL DEFAULT 'unclassified'
                         CHECK(category IN ('admin_fee','commission','referral_fee',
                                            'processing_fee','project','adjustment',
                                            'tax','unclassified')),
    basis                TEXT CHECK(basis IS NULL OR basis IN
                                    ('premium','claims','sub_fees','rrsp','bonus','vendor','none')),
    is_client_revenue    INTEGER NOT NULL DEFAULT 1,
    exclude_from_reports INTEGER NOT NULL DEFAULT 0,
    sort_order           INTEGER NOT NULL DEFAULT 0,
    status               TEXT NOT NULL DEFAULT 'active'
                         CHECK(status IN ('active','review','retired')),
    note                 TEXT,
    created_on           TEXT NOT NULL,
    updated_on           TEXT
);

-- The trailing (13)/(14)/(15) on a product code is the HST RATE (13 Ontario,
-- 14 Nova Scotia, 15 NB/NL/PEI, none for GST-only provinces) — not a pay
-- frequency. benefit_code strips it so the same benefit is one line nationally.
CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT NOT NULL UNIQUE,
    code_normalized TEXT NOT NULL,
    channel         TEXT CHECK(channel IS NULL OR channel IN ('direct','vendor','aso')),
    fee_kind        TEXT CHECK(fee_kind IS NULL OR fee_kind IN
                               ('admin','commission','tax','fee','adjustment','other')),
    benefit_code    TEXT,
    hst_rate        INTEGER,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','review','retired')),
    created_on      TEXT NOT NULL,
    updated_on      TEXT
);

CREATE INDEX IF NOT EXISTS ix_products_benefit ON products(benefit_code, channel);
CREATE INDEX IF NOT EXISTS ix_products_hst     ON products(hst_rate);

-- ---------------------------------------------------------------------- fact

-- premium_split / lives_split are deliberately absent: they are a PivotTable
-- artifact, and storing them is what baked today's premium into 2025-08. The
-- figure is computed at query time from account_period_metrics.
CREATE TABLE IF NOT EXISTS revenue_lines (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id           INTEGER NOT NULL REFERENCES revenue_imports(id),
    source_row_no       INTEGER,
    period              TEXT NOT NULL,
    txn_date            TEXT,
    txn_type            TEXT,
    invoice_no          TEXT,
    name_raw            TEXT,
    customer_raw        TEXT,
    memo                TEXT,
    account_id          INTEGER REFERENCES accounts(id),
    client_id           INTEGER REFERENCES clients(id),
    advisor_id          INTEGER REFERENCES advisors(id),
    consulting_house_id INTEGER REFERENCES consulting_houses(id),
    product_id          INTEGER REFERENCES products(id),
    income_account_id   INTEGER REFERENCES income_accounts(id),
    oid                 TEXT,
    client_key_raw      TEXT,
    advisor_label       TEXT,
    consulting_house    TEXT,
    product_code_raw    TEXT,
    income_account_raw  TEXT,
    amount              REAL,
    quantity            REAL,
    rate                REAL,
    correction_id       INTEGER REFERENCES ingest_corrections(id),
    is_resolved         INTEGER NOT NULL DEFAULT 0,
    created_on          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_revenue_lines_period  ON revenue_lines(period);
CREATE INDEX IF NOT EXISTS ix_revenue_lines_client  ON revenue_lines(client_id, period);
CREATE INDEX IF NOT EXISTS ix_revenue_lines_account ON revenue_lines(account_id, period);
CREATE INDEX IF NOT EXISTS ix_revenue_lines_income  ON revenue_lines(income_account_id);
CREATE INDEX IF NOT EXISTS ix_revenue_lines_import  ON revenue_lines(import_id);

-- -------------------------------------------------------------- integrations

CREATE TABLE IF NOT EXISTS integration_vendors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    aliases    TEXT,
    status     TEXT NOT NULL DEFAULT 'active'
               CHECK(status IN ('active','review','retired')),
    note       TEXT,
    created_on TEXT NOT NULL,
    updated_on TEXT
);

-- One row per (client, vendor, ROLE).
--
-- Keyed on the CLIENT, because that is the level the business contracts and
-- maintains a feed at: the integration list is kept by client, and no client in
-- it has accounts on different systems. clients.id is a surrogate that does not
-- drift (client_keys absorbs GROUP ID renames), so it is as stable an anchor as
-- accounts.oid.
--
-- account_id stays available and NULL-by-default for the exception: an
-- integration that covers only one of a client's accounts. NULL means "all of
-- this client's accounts".
--
-- Role is a column rather than a set of flags because status belongs to the
-- role - Cando, Lloydminster and WF Steel all have an HRIS feed at a different
-- status from their payroll feed.
--
-- Statuses use the business's own vocabulary from the integration list rather
-- than an invented lifecycle.
CREATE TABLE IF NOT EXISTS account_integrations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id        INTEGER NOT NULL REFERENCES clients(id),
    account_id       INTEGER REFERENCES accounts(id),
    vendor_id        INTEGER REFERENCES integration_vendors(id),
    vendor_name_raw  TEXT,
    role             TEXT NOT NULL
                     CHECK(role IN ('payroll','hris','benefits')),
    connection_type  TEXT NOT NULL DEFAULT 'manual'
                     CHECK(connection_type IN ('api','sftp_feed','file_upload','manual','none')),
    direction        TEXT NOT NULL DEFAULT 'inbound'
                     CHECK(direction IN ('inbound','outbound','bidirectional')),
    status           TEXT NOT NULL DEFAULT 'stable'
                     CHECK(status IN ('in_discussion','preparation','on_trial',
                                      'stable','maintenance','retired')),
    status_raw       TEXT,
    effective_from   TEXT NOT NULL,
    effective_to     TEXT,
    external_ref     TEXT,
    note             TEXT,
    created_on       TEXT NOT NULL,
    created_by       TEXT,
    updated_on       TEXT,
    last_modified_by TEXT,
    CHECK (vendor_id IS NOT NULL OR vendor_name_raw IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ix_acct_integrations_client ON account_integrations(client_id);
CREATE INDEX IF NOT EXISTS ix_acct_integrations_vendor ON account_integrations(vendor_id);

-- COALESCE rather than a plain UNIQUE: SQLite treats NULLs as distinct, so a
-- bare UNIQUE would let the same client-wide feed be inserted twice.
CREATE UNIQUE INDEX IF NOT EXISTS ux_acct_integrations
    ON account_integrations(client_id, COALESCE(account_id, -1), vendor_id, role, effective_from);

-- ============================================================================
-- LEGACY — retained until the parity harness is green and one month has run on
-- the new tables. Dropped in a separate, later change. Do not build on these.
-- ============================================================================

CREATE TABLE IF NOT EXISTS import_batch (
    import_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    uploaded_at     TEXT NOT NULL,
    drilldown_from  TEXT,
    drilldown_to    TEXT,
    files_json      TEXT,
    row_counts_json TEXT
);

CREATE TABLE IF NOT EXISTS dim_client (
    client_key   TEXT PRIMARY KEY,
    group_id     TEXT,
    system_id    TEXT,
    display_name TEXT,
    legal_name   TEXT
);

CREATE TABLE IF NOT EXISTS dim_advisor (
    advisor_key TEXT PRIMARY KEY,
    name        TEXT
);

CREATE TABLE IF NOT EXISTS dim_product (
    product_code TEXT PRIMARY KEY,
    description  TEXT
);

CREATE TABLE IF NOT EXISTS dim_income_account (
    income_account TEXT PRIMARY KEY,
    category       TEXT
);

CREATE TABLE IF NOT EXISTS fact_revenue (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id      INTEGER REFERENCES import_batch(import_id),
    txn_date       TEXT,
    period         TEXT,
    txn_type       TEXT,
    invoice_no     TEXT,
    name_raw       TEXT,
    memo           TEXT,
    client_key     TEXT,
    advisor_key    TEXT,
    product_code   TEXT,
    income_account TEXT,
    oid            TEXT,
    amount         REAL,
    quantity       REAL,
    rate           REAL,
    premium_split  REAL,
    lives_split    REAL
);

CREATE INDEX IF NOT EXISTS ix_fact_revenue_period ON fact_revenue(period);
CREATE INDEX IF NOT EXISTS ix_fact_revenue_client ON fact_revenue(client_key);

CREATE TABLE IF NOT EXISTS account_snapshot (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id       INTEGER REFERENCES import_batch(import_id),
    as_of_date      TEXT,
    oid             TEXT,
    client_key      TEXT,
    lives           INTEGER,
    premium         REAL,
    active          INTEGER,
    benefit_type    TEXT,
    advisor         TEXT,
    consulting_house TEXT
);

CREATE INDEX IF NOT EXISTS ix_account_snapshot_oid ON account_snapshot(oid);

CREATE TABLE IF NOT EXISTS client_mapping_override (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_type  TEXT,
    match_value TEXT,
    client_key  TEXT,
    note        TEXT
);
"""


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    migrate_schema(conn)
    conn.commit()
    conn.close()


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Idempotent additive migrations — safe to call on every connection.

    New tables are created here too (executescript with IF NOT EXISTS) so a
    connection opened before init_db() still sees a complete schema.
    """
    conn.executescript(_SCHEMA)

    # Legacy fact_revenue columns added after the original release.
    fr_cols = {row["name"] for row in conn.execute("PRAGMA table_info(fact_revenue)")}
    for col in ("oid", "premium_split", "lives_split"):
        if col not in fr_cols:
            conn.execute(f"ALTER TABLE fact_revenue ADD COLUMN {col} REAL"
                         if col != "oid" else "ALTER TABLE fact_revenue ADD COLUMN oid TEXT")

    # Deploy B: drop estimated pre-2026-07 metrics so historical Revenue/Premium
    # is blank instead of today's premium. Idempotent (0 rows after the first run).
    from fin_services.revenue_ingest import drop_pre_vintage_metrics
    drop_pre_vintage_metrics(conn)

    _seed_reference_data(conn)
    conn.commit()


def _seed_reference_data(conn: sqlite3.Connection) -> None:
    """Seed the closed reference taxonomies. Idempotent — existence-checked.

    Mirrors the ``_seed_categories`` pattern in Focus Board's focus_db.
    Income accounts and products seen at import that are *not* here are
    auto-registered with status 'review' rather than being rejected.
    """
    from fin_services.reference_data import (
        INCOME_ACCOUNT_SEEDS,
        INTEGRATION_VENDOR_SEEDS,
        iso_now,
    )

    now = iso_now()

    for name, category, basis, excluded in INCOME_ACCOUNT_SEEDS:
        conn.execute(
            "INSERT INTO income_accounts (name, category, basis, exclude_from_reports, "
            "status, created_on) VALUES (?,?,?,?,'active',?) "
            "ON CONFLICT(name) DO NOTHING",
            (name, category, basis, 1 if excluded else 0, now),
        )

    for name, aliases in INTEGRATION_VENDOR_SEEDS:
        # Aliases are refreshed on conflict: a new spelling variant found in a
        # source file has to reach an existing catalogue row, or vendor rollup
        # fragments. Name and status are left alone.
        conn.execute(
            "INSERT INTO integration_vendors (name, aliases, status, created_on) "
            "VALUES (?,?,'active',?) "
            "ON CONFLICT(name) DO UPDATE SET aliases = excluded.aliases, updated_on = ?",
            (name, aliases, now, now),
        )
