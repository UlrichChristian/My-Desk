"""Schema creation and idempotent migrations for the Financial Analysis store.

Dimensional model fed by the monthly revenue pipeline:
  facts       — fact_revenue (one row per drilldown line), account_snapshot (vintaged)
  dimensions  — dim_client, dim_advisor, dim_product, dim_income_account
  provenance  — import_batch (audit trail), client_mapping_override (persisted fixes)

No migrations framework / version table — new tables go in _SCHEMA with
IF NOT EXISTS; new columns are added via introspect-and-ALTER in migrate_schema().
"""

import sqlite3

from fin_db.connection import DB_PATH

_SCHEMA = """
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
    fr_cols = {row["name"] for row in conn.execute("PRAGMA table_info(fact_revenue)")}
    for col in ("oid", "premium_split", "lives_split"):
        if col not in fr_cols:
            conn.execute(f"ALTER TABLE fact_revenue ADD COLUMN {col} REAL"
                         if col != "oid" else "ALTER TABLE fact_revenue ADD COLUMN oid TEXT")
    conn.commit()
