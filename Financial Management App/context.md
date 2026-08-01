# Financial Management App — Context & Design

## What this is
Flask Blueprint at `/financial` on :5002 (My Desk). QuickBooks automations and
financial tooling for Christian Ulrich.

## Architecture
- Entry: registered in `C:/Christian/c.py`
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
2. **Monthly Change Report** — live. Month-over-month revenue bridge: new/lost
   clients plus certs (Δquantity × prior rate), price (quantity × Δrate), and
   benefits (product lines added/dropped). Quantity/Rate on the QBO drilldown is the
   attribution source (resolves the earlier open data question).
3. **Cash Flow / P&L** — not built yet.

**Data pipeline:** QBO drilldown + account list + accounts CSV → upload on
Biggest Clients → `fin_db` (`financial.db`). Change Report reads the same store;
no separate ingest.

## Dependencies (runner only)
- pandas, openpyxl, selenium, Edge WebDriver (same as original script);
  Excel COM (pywin32) for native Biggest Clients pivot export when available.

## Open items
- Cash Flow / P&L report
- Optional: in-app status/progress instead of console-only runner
- Optional: MCP query tool over `fin_db`
