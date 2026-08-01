# Financial Analysis — Foundation Build Session (2026-07-29)

Session that turned the Financial Management app from a single-tool launcher into a
menu-driven app with a database-backed Financial Analysis section, and built the first
report (Monthly Biggest Clients) end-to-end. This is the design + foundational-build
narrative; later same-day entries in `2026-07-29.md` (20:38 onward) cover the
follow-on refinements (Change Report, Excel pivots, referral exclusion, pytest).

## What was built
1. **Menu shell.** Reworked `/financial` home from a flat tool grid into two sections
   in `SECTIONS` (`fin_web/routes.py`): **Tools** and **Financial Analysis**. Analysis
   reports started as disabled "Coming soon" cards.
2. **Pull Accounts tool** (`fin_services/pull_accounts.py`, `run_pull_accounts.py`,
   route + template). Gets input #3 (lives / premium / advisor per account).
3. **Ingestion + mapping + report engine** (`fin_services/revenue_ingest.py`,
   `revenue_mapping.py`, `revenue_reports.py`) feeding `fin_db` (`financial.db`), with
   the **Monthly Biggest Clients** page + Excel export.

## Key decisions (the "why")
- **App, not a smart Excel sheet.** Debated where the revenue report should live. Decider:
  the roadmap needs month-over-month change + MCP querying + point-in-time premium/lives,
  which a refresh-in-place workbook can't accumulate. Reversed the earlier "no DB" lean →
  a persistent dimensional SQLite store, with a Flask-free service layer so the same
  engine can power the web UI and a future MCP tool.
- **One QBO pull carries a rolling 12 months.** The custom report **"Ref #1 - Transaction
  Drill Down"** exports ~79k rows across 12 months in one file — history comes from a
  single pull, and its `Quantity`/`Rate` columns are the price/volume data the later
  Change Report needs.
- **Pull Accounts: DOM scrape -> API.** Started building a Selenium virtual-scroll scraper
  per an old DevTools snippet. Live investigation showed the accounts grid was rebuilt
  and now exposes only ~6 visible columns (no advisor / consulting house), so scraping
  couldn't reproduce the report. Found the grid's backing JSON API instead:
  `GET /accounts/api/accounts?query=&filter=<statuses>&page=N&sorting=Name:ascending`
  returning `{"total", "accounts":[...]}`, 200/page, full 33-field objects incl.
  `brokerList` (advisor) and `consultingHouses`. Rewrote the tool to log in via Edge then
  page the API from inside the authenticated browser (`execute_async_script` + `fetch`).
  Far more complete and robust than DOM scraping, and no scroll logic.
- **All statuses, not just active.** The grid default `filter=0-1` is Active-only. Since
  the 12-month drilldown includes since-terminated clients, the pull must use all
  statuses. Confirmed the value by ticking Active+Terminated+Updating and reading the
  request: `filter=0-1;0-2;0-3` (URL-encoded `%3B`). Set as the tool default.
- **Revenue = all income accounts** (later refined by the follow-on session to exclude
  `Referral Fees:Email Feed` and `Statement of Work`). Verified against the sample that
  the pivot's "(Multiple Items)" filter had essentially every income account selected —
  no hidden category exclusion; the only gaps were 3 clients with tiny manual line tweaks.

## Mapping engine (ported from the user's Power Query)
Per drilldown line: resolve **PreCustomer** (vendor rows -> memo minus " Admin Fee";
`:ASOC` rows -> name between ", " and " -" looked up to SYSTEM ID; else -> Customer),
then Join 1 `PreCustomer -> account-list SYSTEM ID`, Join 2 `account-list NAME ->
accounts.name` (oid, lives, premium, brokerList=advisor, consultingHouses), Client =
GROUP ID else SYSTEM ID. Splits: premium/lives divided by line count per (oid, period)
so a period's sum reconstructs premium/lives once.

Two bugs found and fixed during validation:
1. Else-branch used the QBO `Name` field; it must use **`Customer`** (Name is the payer
   for broker-paid invoices). Name and Customer differ in ~4,100 of 6,924 rows.
2. `_client` treated an empty `GROUP ID` (NaN) as truthy and returned NaN as the client;
   the account list stores "no group" as an empty cell OR the string 'N/A'. Handle both
   -> fall back to SYSTEM ID. `resolved` flag keyed off SYSTEM-ID match, not GROUP ID.

## Validation (acceptance test)
Ran the engine on the sample workbook's raw sheets: reproduces the March 2026 "Revenue by
Client" **to the penny** — New Gold 30,378.42 (Premium 1,362,192 / 1,607 lives / 6.90%
share), 123Dentist 16,595.25, Optima 13,468.17, Globalization 11,555.46, PAL 8,180.00 —
447 clients, only 2 unresolved rows. The real 12-month drilldown parses to 79,610 rows
across all 12 months; re-import is idempotent (replace-by-period, no duplication).

## "Doesn't navigate to a list" — resolved
After a real import the page showed no list. Cause was a stale running server started
before the report route/template landed (the data imported fine). Current state verified
via Flask test client: `/financial`, `/financial/biggest-clients`, `/financial/change-report`
all return 200; Biggest Clients renders 443 clients for the latest period (2026-07).
Fix if it recurs: restart My Desk so the server picks up new route code.

## Current data (financial.db)
Import #6 holds the full year: 79,610 revenue rows across 2025-08 .. 2026-07, 1,489
accounts, 489 clients, 4 unmapped rows.

## Process Street (standing rule — still to mirror)
Two automations need a to-do + audit step each:
- **Monthly Accounts Data Pull** (Pull Accounts): audit = row count vs the grid's
  all-statuses total; brokerList/consultingHouses populated.
- **Revenue Import** (Biggest Clients): audit = reconcile top clients against a known
  month (the acceptance test); check the unmapped-row count.

## Next
Mapping review/override UI (table exists, no editing screen yet); wire the MCP tool to
the service layer; Cash Flow / P&L. (Change Report shipped in the follow-on session.)
