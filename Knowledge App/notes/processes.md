# Processes
> How-to notes and pointers to Process Street steps for recurring procedures.

---

## MP-01 — New Employee
*Links to: MP-02 Payroll*

### MP-01-01 — QBO Vacation Accrual Subaccount Setup
When a new staff member is added, a QBO subaccount must be created for vacation accrual tracking before the next month-end booking.

**Account setup:**
- Account name: [Employee Full Name]
- Account type: Other Current Liabilities
- Detail type: Payroll Liabilities
- ✅ Make this a subaccount
- Parent account: Payroll - Vacation Accrual
- Currency: CAD Canadian Dollar
- Default tax code: (leave blank)

**Reminder:** Check QBO for missing subaccount before running vacation accrual journal entries each month end.

---

## MP-02 — Payroll
*Links to: MP-01 New Employee, MP-04 Month End*

### MP-02-01 — Vacation Accrual Adjustment on Salary Increase
When an employee receives a salary increase, a one-time catch-up journal entry is required to true up their vacation accrual liability to the new rate.

**Formula:**
> **Adjustment = Hours since last pay period × (New hourly rate − Old hourly rate)**

**Steps:**
1. Identify the effective date of the salary increase
2. Calculate hours worked between the last pay period end date and the effective date
3. Apply the formula above for each affected employee
4. Book as a journal entry to the employee's Payroll - Vacation Accrual subaccount (Dr. Vacation Accrual Expense / Cr. [Employee] Vacation Accrual Liability)

**Timing:** One-time entry only — regular accruals going forward will use the new rate automatically via the CSV import template.

---

## MP-FIN — Financial Management App
*In-app reminders live on each tool page. Mirror here and in Process Street: a to-do step and an audit step. No black-box automations.*

### MP-FIN-01 — HRIS / Payroll integration import
Hand-maintained. Nothing upstream names a vendor.

**To-do:** Import the sheet (or add one row) on `/financial/integrations`. Unmatched clients are reported, never guessed.

**Audit:** Coverage summary (clients with / without a feed, counts by vendor) matches the source list. Unmatched vendor names are either added to the catalogue or left flagged.

### MP-FIN-02 — Monthly revenue import
**To-do:** Upload drilldown + account list + accounts CSV on Biggest Clients. Import writes metrics only for the latest month (`metrics_mode=latest`).

**Audit:** Period total and unresolved-row count vs the prior run. Premium/lives are expected blank before 2026-07.

### MP-FIN-03 — Reference review
**To-do:** Clear `/financial/reference-review` after each import (`status=review` product codes and income accounts).

**Audit:** Queue count is zero, or remaining items have a reason to stay in review.

### Parked (not this change)
- Drop legacy `fin_db` tables after a month of real use.
- Re-enter wiped Aug 2025 qty/rate fixes into `ingest_corrections` (values are not on disk).
- Delete the duplicate `WFSteel_Deferred_#1` journal entry in QuickBooks.

---

## MP-03 — Remittances
*Links to: MP-04 Month End*

### MP-03-01 — Book Carrier Remittances at Time of Payment
Carrier remittances must be booked in QBO at the time of payment — not during bank feed cleanup at month end.

---

## MP-04 — Month End
*Links to: MP-02 Payroll, MP-03 Remittances*

*(Sub-processes to be added — see Month End Tasks on the board)*

---
