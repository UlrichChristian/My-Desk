# Plan — Financial Analysis: Revenue data platform + Biggest Clients (Phase 1)

## Context
The Financial Management app's menu shell (Tools + Financial Analysis sections) was
already built and shipped in a prior pass. This plan covers the first real Financial
Analysis capability.

It started as "a monthly biggest-clients report" but a design conversation reframed it.
Key realizations, in order:
1. The QBO **Transaction Drilldown Report** (custom report **"Ref #1 - Transaction
   Drill Down"**) exports a **rolling 12 months** in one file (~79k rows), so history
   comes from a single pull — no need to accumulate it upload-by-upload.
2. That drilldown carries `Quantity` and `Rate` per line (`Amount ≈ Rate × Quantity`),
   which *is* the price/volume data needed for the later Change Report
   (certs = Δquantity, admin-fee = Δrate, benefits = new product lines).
3. Because we want (a) MCP/Claude to query the data, (b) month-over-month change, and
   (c) **point-in-time-correct** premium/lives, the data must persist with vintages.
   That justifies a real SQLite database — reversing the earlier "no DB" lean.

**Decision:** build it in the app as a persistent, dimensional SQLite store fed by a
guided upload → normalize pipeline, with **Biggest Clients** as the first report that
proves the pipeline. Transformation logic lives in a Flask-free service layer so the
same engine powers the web UI **and** a future MCP tool.

## Scope
**Phase 1 (this plan):**
- `fin_db` SQLite package + schema (dimensional model below).
- Ingestion pipeline: parse the 3 source files, normalize, apply the client-mapping
  logic, load into the DB (replace-by-period for revenue; append snapshots).
- A mapping **review/override** surface for unresolved clients.
- The **Biggest Clients** report (on-screen + Excel export), reading from the DB.
- A **"Pull Accounts"** Tools-section utility that automates the accounts scrape
  (Selenium), producing input #3. Buildable alongside the report, not a blocker.
- Flask-free service layer (MCP-ready).

**Out of scope (later passes, same DB):** Cash Flow / P&L, the MCP tool itself
(fast-follow — the service layer is built to enable it), per-advisor bespoke tabs
(Heskin/Hamblin). **Monthly Change Report shipped as Phase 2** (see below).

## Build sequence (Christian's ordering)
1. **Framework, reachable via the website first.** Stand up the clickable skeleton:
   the `fin_db` package + schema wired into `c.py`, the `/financial/biggest-clients`
   route + page (upload surface for the 3 files), the `/financial/pull-accounts` route,
   and the tiles flipped live in `SECTIONS`. Navigable end-to-end even before the logic
   is filled in.
2. **Selenium "Pull Accounts" scraper**, so real account data (input #3) is actually in
   hand — paginated, read-only (see acquisition note below).
3. **Ingestion + normalization** into `fin_db` (parse/validate all 3 inputs, port the
   mapping logic, replace-by-period load, snapshots, mapping review/override).
4. **Biggest Clients report** + Excel export, validated against the sample workbook.
5. **Later passes:** MCP tool, Change Report, Cash Flow / P&L.

## Canonical inputs (the monthly "which reports to pull" guide)
1. **QBO → Custom reports → "Ref #1 - Transaction Drill Down"** → export to Excel.
   Canonical schema (row 5 header, col A blank): `Transaction date, Transaction type,
   #, Name, Description, Account Name, Item split account, Amount, Balance,
   Product/Service, Quantity, Rate`. Rolling 12 months. Dates are strings `mm/dd/yyyy`.
   The upload **validates this schema and rejects a mismatch** rather than mis-parsing.
2. **Account list** (BillingSiteExport): `ACCOUNT ID, NAME, LEGAL NAME, GROUP ID,
   SYSTEM ID, PLAN DESIGNS`. Billing-site export button → Christian **resaves as
   `.xlsx`** (the native export is legacy `.xls`, which the installed `xlrd` can't read).
3. **Accounts data** (AccountSiteExport, `ea_accounts_all.csv`): `oid, name,
   livesCount, monthlyPremium, brokerList, consultingHouses, benefitType, isActive, …`.
   **Provenance (traced):** not an export or API — a manual **Edge DevTools console
   scrape** of the admin accounts grid (`.accounts__account-row` / `.modern-grid-flex__col`),
   documented in `OneDrive/Scripts/Pull Account Page Date.docx`. Fragile: the column set
   depends on the grid's configured columns at scrape time.

**Acquisition — implemented (API, not DOM scrape):** a live investigation showed the
accounts grid is now a virtualized table exposing only ~6 columns (no advisor /
consulting house), so DOM scraping can't reproduce the report. The grid is backed by a
paginated JSON API that returns the **full** account objects:

```
GET https://app.effortlessadmin.com/accounts/api/accounts
    ?query=&filter=0-1;0-2;0-3&page=N&includePreviousPages=false&sorting=Name:ascending
-> {"total": <int>, "accounts": [ {oid, name, livesCount, monthlyPremium,
    brokerList[], consultingHouses[], policies[], planDesignNames[], benefitType, ...} ]}
```

`filter=0-1;0-2;0-3` = **all statuses** (Active; Terminated; Updating) — important
because the 12-month drilldown includes since-terminated clients. Page size 200.

The **"Pull Accounts" tool** reuses the payment-match Edge + `ready_callback` login
seam: launch Edge → user logs in → the tool fetches each API page *from inside the
authenticated browser* (`execute_async_script` + `fetch`, so session cookies come
along) → flattens arrays (`|`-joined) → writes the CSV. **Read-only** (GET only), so no
destructive-action safety checks. The QBO drilldown (#1) and account list (#2) stay
manual exports. The report pipeline accepts the accounts CSV **however produced**, so
Pull Accounts is decoupled from the report build.

All three files feed one run; the account files provide the point-in-time snapshot for
that import.

## Data model (`financial.db`, raw sqlite3, mirrors Focus Board `focus_db`)
**Facts**
- `fact_revenue(id, import_id, txn_date, period TEXT 'YYYY-MM', txn_type, invoice_no,
  name_raw, memo, client_key, advisor_key, product_code, income_account,
  amount REAL, quantity REAL, rate REAL)` — one row per drilldown line.
- `account_snapshot(id, import_id, as_of_date, oid, client_key, lives INT,
  premium REAL, active INT, benefit_type, advisor, consulting_house)` — **append-only**,
  time-stamped, so historical ratios use the right vintage.

**Dimensions** (refreshed each import)
- `dim_client(client_key PK, group_id, system_id, display_name, legal_name)`
- `dim_advisor(advisor_key PK, name)`
- `dim_product(product_code PK, description)`
- `dim_income_account(income_account PK, category)` — the revenue category
  (Admin Fees earned on Premium / Claims / Sub Fees, Commissions, Referral Fees…).

**Provenance & correctness**
- `import_batch(import_id PK, uploaded_at, drilldown_from, drilldown_to, files_json,
  row_counts_json)` — audit trail (also satisfies the Process Street standing rule).
- `client_mapping_override(id, match_type, match_value, client_key, note)` — persistent
  manual corrections applied on every future import.

## Transformation logic (ported from the user's Power Query → `fin_services`)
Per drilldown line, resolve **PreCustomer**:
- if `income_account == "Admin Fees (paid by Vendors)"` and memo ends with
  `" Admin Fee"` → memo minus that suffix (e.g. `"Viacore Union Admin Fee"` →
  `"Viacore Union"`); other non-empty memos stay as-is; empty memo falls through;
- else if `Name` contains `":ASOC"` → text between `", "` and `" -"` in `memo`, looked
  up in the account list `NAME` → that row's `SYSTEM ID`;
- else if `Customer`/`Name` contains `:` → text **after** the colon (QBO
  `Group:SystemId` form, e.g. `New Gold:Rainy River` → `Rainy River`);
- else → `Customer`/`Name`.

Then:
- **Join 1:** `PreCustomer` → account list `SYSTEM ID` (pull NAME, LEGAL NAME, GROUP ID,
  ACCOUNT ID).
- **Join 2:** account-list `ACCOUNT ID` → accounts `oid` (fallback: `NAME` → `name`)
  — pulls oid, lives, premium, brokerList = **advisor**, consultingHouses. Prefer oid
  because display names drift between the billing export and the admin CSV.
- **Client** = `GROUP ID`, or `SYSTEM ID` when GROUP ID is `N/A`. → `client_key`.
- **Splits:** `RowCount` per `oid`; `PremiumSplit = premium/RowCount`,
  `LivesSplit = lives/RowCount` (so pivots sum premium/lives without multiply-counting).
- Rows that still don't resolve, or match a flagged pattern, go to the **review list**;
  saved corrections land in `client_mapping_override` and are re-applied automatically.

Reuse the existing upload/batch convention from `fin_web/routes.py` (timestamped dirs
under `uploads/`) for the raw files; the DB is the normalized layer on top.

## Ingestion behavior
- **Revenue:** on import, delete `fact_revenue` rows whose `period` is within the new
  file's date range, then insert fresh (replace-by-period — latest pull is truth).
- **Snapshots:** always appended with `as_of_date` (never deleted).
- Every import writes an `import_batch` row.

## Biggest Clients report
Rollup by `client_key` over a chosen `period` (default latest month):
`Client, Advisor, Revenue (Σamount), Premium* (Σpremium_split), Revenue/Premium,
Lives* (Σlives_split), Revenue/Life, Revenue Share (% of period total)`, sorted by
Revenue desc — reproducing the example `Revenue by Client` sheet. On-screen table +
**Excel export** (openpyxl/pandas). Include a period selector (any month in the DB).
**To confirm during build:** the example report includes only a *subset* of income
accounts (its pivot filter was "Multiple Items"); derive that included-account set from
the example workbook and confirm with Christian (drives `dim_income_account.category`
and the report's revenue filter).

## Files
- **New:** `Financial Management App/fin_db/{__init__,connection,init_db}.py`
  (copy the `Focus Board/focus_db` pattern: `g.fin_db` key, `financial.db` beside the
  app folder, `PRAGMA foreign_keys`, `executescript` schema, introspect-and-ALTER
  migrations).
- **New:** `fin_services/revenue_ingest.py` (parse + validate 3 files),
  `revenue_mapping.py` (PreCustomer/Client + overrides), `revenue_reports.py` (rollups
  + Excel export). All Flask-free, `conn` as first arg — MCP-reusable.
- **Modify:** `fin_web/routes.py` — add `/financial/biggest-clients` (upload → generate
  → view → download) and a mapping-review route; flip the `biggest_clients` stub in
  `SECTIONS` to `available: True` with its `href_name`.
- **New templates:** `templates/financial/biggest_clients.html`, and a review page.
- **Pull Accounts tool:** `fin_services/pull_accounts.py` (Selenium scrape, adapted from
  the `Pull Account Page Date.docx` snippet; mirror `payment_match.py`'s Edge launch +
  `ready_callback` login wait), a `/financial/pull-accounts` route, a
  `templates/financial/pull_accounts.html`, and a new tile in the **Tools** section of
  `SECTIONS`.
- **Modify:** `C:/Christian/c.py` — `from fin_db.init_db import init_db as fin_init_db`
  and `from fin_db.connection import close_db as close_fin_db`; call `fin_init_db()` in
  `create_app()` and add `app.teardown_appcontext(close_fin_db)` (the app folder is
  already on `sys.path`).
- **Deps:** pandas + openpyxl (already present). Account list must arrive as .xlsx/.csv.

## Verification
1. **Engine correctness (acceptance test):** run the ETL over the sample inputs and
   confirm the Biggest Clients output reproduces the example `202603_Revenue.xlsx`
   "Revenue by Client" figures for March 2026 — e.g. New Gold ≈ 30,378.42,
   123Dentist ≈ 16,595.25, Optima ≈ 13,468.17, and the Revenue Share ordering.
   (Resolve the income-account subset first so totals reconcile.)
2. **End-to-end:** start `python C:\Christian\c.py`, log in, open
   `/financial/biggest-clients`, upload the 3 files, generate the report, download the
   Excel, and re-upload to confirm replace-by-period doesn't duplicate months.
3. **Point-in-time:** confirm two imports produce two `account_snapshot` vintages and
   the report uses the right one per period.
4. **Mapping review:** confirm unresolved clients surface, a saved override persists and
   auto-applies on the next import.
5. No console/server errors (browser console + preview logs).

---

## Phase 2 — Monthly Change Report

**Shipped:** `/financial/change-report` (+ Excel export). Service:
`fin_services/revenue_change.py`.

Compares selected month vs prior calendar month in `fact_revenue`. Client-level
table + summary strip.

| Driver | Rule |
|--------|------|
| New | client in current, not prior → all current revenue |
| Lost | client in prior, not current → −prior revenue |
| Certs | same client + product: `(q1 − q0) × r0` |
| Price | same client + product: `q1 × (r1 − r0)` |
| Benefits | product lines added/dropped for an existing client |
| Other | missing qty/rate, or amount residual vs qty×rate |

**Acceptance (verified 2026-03 vs 2026-02):** sum of drivers = Δ revenue within
cents; report prior/current totals match `SUM(amount)` for those periods.
