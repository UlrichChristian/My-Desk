# MP-06 Trust Account Reconciliation
> Month-end trust account reconciliation process for EA — Trust Payable spreadsheet vs QBO AP Aging


---

## Trigger
Begin once QBO bank feed is cleared and carrier remittances are booked for the month.

---

## Files Required
Both files live in the **Accounting shared drive**:
- Trust Payable spreadsheet (prior month)
- Journal Entry template (prior month)

---

## Step 1 — Copy and Set Up New Month Tab
1. Copy the prior month's Trust Payable sheet and Journal Entry template tab in unison (note on sheet: "Copy Sheet and GE Sheet in unison")
2. Rename both tabs for the new month
3. Update formula links to point to the new prior month (each month links to its immediately preceding month — rolling chain)
4. Opening balance flows in automatically via formula link — no manual entry needed

---

## Step 2 — Enter Prior Month Carryovers
Enter in the **prior month carryover columns**:
- **60-day payments** — always populated every month (by design, not late — these clients are on a 60-day cycle and always remit the month after coverage)
- **30-day late payments** — situational; clients who paid late and whose cash landed in trust this month (usual suspects: Alida, sometimes Kii Health)
- **ASO late payments** — same logic as 30-day late

Note: 60-day carryovers are NOT late — they are the normal payment cycle for those clients.

---

## Step 3 — Enter Current Month Bills
Enter all bill categories into their respective columns:
- 30-day bills
- 60-day bills
- ASO (Admin Services Only)
- BASO (Budgeted Admin Services Only)
- Manual invoices

**QBO GL Pull process (for bill entry):**
1. Pull QBO General Ledger for the respective month (Transaction Detail by Account — broad dump)
2. Clean the sheet: select all → unmerge cells → unwrap text
3. Insert a column after Column A. If A* is empty, populate name from the row above; else use A* as-is. Name this column "Account" — ensures every row has an account name
4. Filter → select rows with "Premiums due to"
5. Copy selection to a new sheet
6. Filter for empty transaction dates → delete those rows
7. Pivot: Rows = Name and #; Values = Amount
8. ⚠️ Note: Excel sorts SUN (Sun Life) and NOV (Novus) to the top — these are registered as Sunday and November. Be aware when reviewing pivot output.
9. Copy pivot results into the Trust Payable sheet

---

## Step 4 — Enter Current Month Payments
Enter all payment categories:
- 30-day payments
- 60-day payments
- ASO payments
- BASO payments
- Manual invoice payments
- Withheld amounts (clients who have not yet paid — held in trust, not remitted to carrier)

**QBO quirks:**
- **GWL RRSP**: Separate QBO entry but listed under the regular GWL (Canada Life) row in the sheet
- **CLAGWL**: Combined account in QBO — allocate premiums to CLA (ClaimSecure)

**Withheld amounts column**: Purely for visibility/tracking. Client has not paid EA, so EA has not remitted to the carrier. Funds are not in trust yet.

---

## Step 5 — Enter QBO AP Balance
1. Open QBO → Reports → What You Owe → **A/P Aging Summary**
2. Set report date to the last day of the month (e.g. May 31st)
3. Enter each carrier's AP balance into the QB AP Balance column in the sheet

---

## Step 6 — Resolve Variances
The Variance column = QB AP Balance minus New Payable Balance. Goal: zero or fully explainable.

**Standard first move for any variance: check the QBO supplier ledger for unrecorded payments before investigating further.**

Common variance causes:
- **Unrecorded payments**: Payments made late in the month (e.g. May 27th EFTs) that are in QBO but not yet entered in the sheet → add to sheet
- **Timing differences**: Amount withheld in one month, credit applied to client bill in the following month (e.g. Desjardins Tipalti provincial credit) → expected, carries through to next month's rec, no action needed
- **Formula errors**: Cumulative Previous Balance formula must include the prior month outstanding (DG) column — easy to miss when copying tabs

**ADI and GBA note**: Variances for Assured Diagnostics and Global Benefits Advisors are typically cents. **Do NOT adjust the QBO 60-day invoice** — adjust the remittance advice instead. Trust account is already reconciled for those invoices. (Aman advised accordingly.)

---

## Carry Forward / Parking Rules
- Timing differences that will resolve next month: note in journal, no action
- Unresolved variances at session end: document status in journal and resume next session
- Desjardins provincial credit timing difference is a known recurring item — confirm it clears each June rec

---

## Related Notes
- MP-03 Remittances
- Trust Payable spreadsheet (Accounting shared drive)

## ## Additional Variance Causes (added 2026-06-30, May rec)

- **Invoice rounding errors**: If a variance traces back to a rounding mismatch introduced during invoice reconciliation (not the trust rec itself), fix at the source — amend the client invoice amount and route the rounding difference to admin rounding. Don't patch it in the trust sheet only; the invoice itself needs correcting.
- **Cross-carrier trust misallocation**: If premiums were booked into the wrong carrier's trust account (e.g. booked to Carrier A's Humanacare-style account when they belonged to Carrier B), and payments have already gone out, prefer an **extra bill + supplier credit** on each affected carrier over a straight journal entry. Nets to zero, clears AP cleanly, and is self-documenting for anyone reviewing later (a JE alone doesn't explain *why* without added context). Also check whether any refund or extra payment tied to the misallocation has hit the trust BS accounts yet — these can lag and need a separate catch-up adjustment across the affected months.
- **Refund higher than anticipated, partially owed to client**: When a carrier refund comes in larger than expected and the excess is being passed through to the client, the rec won't fully balance until the client payout posts — expected timing difference, not an error. Note and carry to next month.
- **Root-cause check for AP-side variances on a specific carrier**: A variance isolated to one carrier (vs. spread across many) often traces to a single missing invoice for that carrier rather than a calculation error — check unposted invoices for that carrier first.

## 2026-07-07 — Trust Payable Rec (Task #103) close-out

Three new variance patterns identified and cleared:

1. **Product-code mis-linking**: A product code added by Aman for Dialogue (DIA-GST-VMH) was mapped to the Manitoba Blue Cross (MBC) balance sheet accounts. Worth checking product-code-to-carrier mapping whenever a new product code is introduced.
2. **Carrier bill co-mingling**: A Sun Life minimum balance charge had been bundled into the MBC bill rather than billed/tracked separately. Flag: verify each carrier line on a combined bill actually belongs to that carrier.
3. **Cross-month credit reappearance**: A Tipalti credit withheld from an April DES bill resurfaced on a June client invoice, causing confusion about whether it had already been applied. Flag: when a credit is withheld from one bill, trace it forward until it's actually applied — don't assume it's resolved once withheld.
