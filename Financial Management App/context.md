# Financial Management App — Context & Design

## What this is
Flask Blueprint at `/financial` on :5002 (My Desk). QuickBooks automations and
financial tooling for Christian Ulrich.

## Architecture
- Entry: registered in `c.py` **of this checkout**. Start My Desk with
  `python c.py` from the worktree root so `/financial` uses this folder's
  code and `financial.db`. `python C:\Christian\c.py` is the old app.
- Blueprint name: `financial`
- Templates: `templates/financial/` (namespaced)
- Static: `static/financial/` (namespaced)
- Uploads: `uploads/` (Excel batches + JSON config per run — not committed)

## Standing rule
Every automation mirrored in Process Street: to-do step + audit step.

## Layout
The `/financial` home is organized into two sections (see `SECTIONS` in
`fin_web/routes.py`), each rendering the shared `.card` grid:
1. **Tools** — QuickBooks automations and one-off utilities.
2. **Financial Analysis** — database-backed monthly reporting (in development).

## Tools (tile order)

### 1. Match Invoices & Payments
- Route: `/financial/payment-match`
- Source script: `OneDrive/Scripts/PaymentsMatch/202604_MatchInvoicesAndPayments.py`
- Service: `fin_services/payment_match.py`
- CLI runner: `run_payment_match.py --config uploads/.../config.json`
- **Flow:** upload prepared A/R aging Excel → optional preview → **Launch in console**
  opens Edge + a new terminal; user logs into QBO, presses Enter, batch runs.
- **Excel prep:** documented on the tool page (filter aging buckets; columns
  `Customer`/`CURRENT` or `Account`/`Payment`).
- **Safety checks:** Deposit To = ATB - Trust; amount received must be $0.00.

<!-- A "Carrier Billing Reconciliation" tile (RBC vs EA statement) was built and
     then fully removed on 2026-07-03 at Christian's request. Not in the app. -->

## Financial Analysis
Reports on `/financial`, fed by the revenue upload on Biggest Clients into
`financial.db`:

1. **Monthly Biggest Clients** — live. Top clients by revenue, month by month;
   on-screen table + Excel export with Data table and native PivotTables.
   Display-only Payroll / HRIS checkboxes (active feed = stable, maintenance,
   trial, or preparation) and a filter for clients missing a feed. Excel export
   carries Payroll / HRIS as Yes/No on the client sheet, the Data table, and
   the native client pivot.
2. **Monthly Change Report** — live. Month-over-month revenue bridge: new/lost
   clients plus certs (Δquantity × prior rate), price (quantity × Δrate), and
   benefits (product lines added/dropped). Quantity/Rate on the QBO drilldown is the
   attribution source (resolves the earlier open data question).
3. **HRIS & Payroll Integrations** — live. Which clients have a payroll or HRIS
   feed, on which system, and who still needs one. Hand-maintained (nothing
   upstream carries it); seeded from a sheet, maintained in-app.
4. **Reference Review** — live. Product codes and income accounts auto-inserted
   on import with `status=review`. Confirm the parse (or correct it), then
   accept; bulk “accept as parsed” for the first-pass product queue.
5. **Cash Flow / P&L** — not built yet.

**Data pipeline:** QBO drilldown + account list + accounts CSV → upload on
Biggest Clients → `fin_db` (`financial.db`). Change Report, Integrations and
Reference Review read the same store; no separate ingest.

## Schema
See `schema.dbml` (paste into dbdiagram.io for the ERD). Refactored 2026-09-14
onto a reference spine anchored on the EA account `oid` — the one identifier
that does not drift. `client_key` is *derived* on every import
(GROUP ID → SYSTEM ID → QBO name), so nothing durable keys on it; `client_keys`
maps every string ever seen back to a stable `clients.id`.

Rules worth knowing before changing the ingest:
- The spine (`accounts`, `clients`, `carriers`, `products`, …) is **upsert-only**.
  Only `revenue_lines` is replace-by-period.
- Durable fixes live in `ingest_corrections` and are re-applied inside `enrich()`
  *before* each load, so a re-upload never wipes them. `note` is NOT NULL.
- Premium and lives are **not** on the fact. They live on
  `account_period_metrics` keyed by `(account, month)`; the per-row split is
  derived at query time. Storing it is what stamped today's premium onto 2025-08.
- The `(13)`/`(14)`/`(15)` suffix on a product code is the **HST rate**
  (13 ON, 14 NS, 15 NB/NL/PEI), not a pay frequency. `products.benefit_code`
  strips it so a benefit is one line nationally.
- Legacy tables (`fact_revenue`, `account_snapshot`, `dim_*`, `import_batch`,
  `client_mapping_override`) are still created and still populated — they are the
  rollback and get dropped in a later change. Do not build on them.

## Dependencies (runner only)
- pandas, openpyxl, selenium, Edge WebDriver (same as original script);
  Excel COM (pywin32) for native Biggest Clients pivot export when available.

## Open items
- Drop the legacy tables (`fact_revenue`, `account_snapshot`, `dim_*`,
  `import_batch`, `client_mapping_override`) after a month of real use.
  Still created as rollback; do not build on them.
- Re-enter the Aug 2025 qty/rate manual repairs into `ingest_corrections`.
  The 2026-09-02 full re-import wiped them; nothing on disk recovers the
  values — Christian has to re-enter from source notes.
- WFSteel_Deferred_#1 duplicate JE — excluded here via `ingest_corrections`,
  still to fix in QuickBooks.
- Cash Flow / P&L report
- Optional: in-app status/progress instead of console-only runner
- Optional: MCP query tool over `fin_db`

## Deploy B (done 2026-09-16)
`load_import(..., metrics_mode="latest")` is the live import path. Pre-2026-07
`account_period_metrics` rows were deleted so historical Revenue/Premium
renders blank rather than against today's premium. July 2026 onward keeps
the current snapshot. The parity gate still loads with `all_periods` on
purpose so attribution can be compared without the blank column.
