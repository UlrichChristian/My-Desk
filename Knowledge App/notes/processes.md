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

## MP-03 — Remittances
*Links to: MP-04 Month End*

### MP-03-01 — Book Carrier Remittances at Time of Payment
Carrier remittances must be booked in QBO at the time of payment — not during bank feed cleanup at month end.

---

## MP-04 — Month End
*Links to: MP-02 Payroll, MP-03 Remittances*

*(Sub-processes to be added — see Month End Tasks on the board)*

---
