# Productivity system — history (archive)

*Long-term archive of the day-by-day log. Rarely opened — kept for reference/audit. The active file is **Productivity system - notes & thoughts.md**.*

**Convention:** at each weekly review, completed daily logs are moved out of the active notes file into here (most recent at top). The active file keeps only the ▶ Start-here header, active work, open follow-ups, and standing principles.

---

## Archived 2026-06-25 — daily logs for 06-22 → 06-24

## Current plate — snapshot from Outlook 365 To-Do (2026-06-22)
**Overdue financial-close cluster (highest priority / "Do now"):** RBC Reconciliations (06/11), Book Payroll (06/11 — confirm done vs. just unchecked), GSC ERL Remittance Variance (06/11), plus Month end and Reconciliation db update / status quo. Reads as one month-end push, ~11 days past due.
**Other overdue discrete tasks:** Address Updates (06/12), Lindsay ASO transition (06/18).
**Upcoming / "Schedule":** AgSafe July switch adviser in GB (07/02), ISL- (07/08).
**Projects / standing areas (not next actions — each needs one concrete next step, park the rest):** Remittance Project status quo meeting, Client Ongoing, Eye Recommend Carrier transition, Travel Policy, Humanacare Remit to, Process Street, United Cycle, CMRRA.
**Observation:** the list mixes dated tasks with undated projects/areas — a key source of the "heavy" feeling. Separating tasks from projects is step one.

### Sorted into the canvas (2026-06-22) — blue/grey/white build
**Do now (urgent + important):**
- Clients Ongoing (CORE) reconciliation — **focus, finish fast** (Christian flagged)
- GSC ERL file issue (Remittance Variance) — **focus, tackle** (Christian flagged; was due 06/11)
- RBC Reconciliations (overdue 06/11)
- Book Payroll (overdue 06/11 — confirm done vs. just unchecked)
- Month end

**Schedule (important, not urgent):** Reconciliation db update / status quo · Lindsay ASO transition (was 06/18) · Address Updates (was 06/12) · AgSafe July switch adviser in GB (07/02) · ISL- (07/08)

**Delegate / Later:** left empty for Christian to assign.

**Projects & standing areas (own lane, not daily tasks):** Remittance Project status quo meeting · Eye Recommend carrier transition · Humanacare remit to · United Cycle · CMRRA · Process Street · Travel Policy

### Update 2026-06-23
- **CORE reconciliation = DONE.** Took literally all of 06-22 plus part of Friday 06-19. Moved to Wins. → **Flag: this is a major recurring time sink worth examining** — candidate for automation (ties to the Flask app idea), streamlining, or partial delegation. Worth understanding *why* it consumes a full day+ before next cycle.
- Now top of Do now = **GSC ERL file issue** (next focus).
- **Process Street — updated** (done). ✓
- **Remittance Project — added an additional step** (progress; still ongoing).
- **NEW — Steve's Livestock reconciliation** → **Do now / focus.** Prep for a meeting tomorrow (06-24). Wasn't previously on the Outlook list.
  - *EOD 06-23 status:* thinking done + confirmed, data pulled. Remaining = just assemble/pull together (quick). **Meeting 10:00 AM 06-24** — do a short morning block to finish before then.
  - **DONE 06-23 6:43 PM** — finished tonight; fully prepared for the 10:00 AM meeting. ✓ Moved to Wins.

### Today's focus — 06-24
- **123D ERL file correction** → Do now, focus.
- **Premium remittance** → Do now, **critical**.
- (10:00 AM Steve's Livestock meeting — prep done.)
- *Smaller / realistic today:* **CMRRA reconciliation + book meeting**; **ISL — email to HUB**; **RBC email** (most of the work already done — quick finish); **MBC policy correction**; **Buttcon double payment**.
- **Running order (rest of 06-24):** 1) GSC meeting → 2) check-in on Premium remittance + Reconciliation DB → 3) GSC ERL file. Possible management meeting may interrupt depending on GSC meeting length.
- **Steve's Livestock meeting — DONE 12:00 noon 06-24.** Went well; follow-up email sent. ✓ (full arc complete: prep → meeting → follow-up.)
- **Eye Recommend — responded to email** (progress on that standing area). ✓
- **Buttcon double payment — resolved itself, no involvement needed → dropped from today.** ✓
- Took a lunch break.
- **1:28 PM:** Premium remittance prep *in progress*. Next → check in on Reconciliation DB update → then 123D ERL file issue.
- *Interruptions absorbed:* a car-accident matter + a co-worker question (handled ad hoc).
- **DELEGATED:** requested a query from the dev team to feed the database → handing to the intern to import (he's most familiar with the DB now). *Delegate bucket in action.*
- Now heading into **GSC ERL** himself (focus work).
- *Sidetracked again:* phone call with Brianne (Perlinger) re: the Eye Recommend issue. **Eye Recommend is heating up today** (email + now a call) — arguably no longer just a standing area; consider promoting to an active item.
- **2:34 PM — 123D ERL issue likely CONFIRMED (root cause found).** The ERL file *translations were incorrect since inception*, so the bill pushed into the GSC system never matched the amounts actually remitted. → This very likely explains the **GSC ERL Remittance Variance** too (same underlying cause). Implications to handle: (1) historical correction — errors go back to inception, so prior periods may need restating; (2) fix the translation mapping at source so it stops recurring.
- *De-dupe clarification:* the **123D ERL correction** and the **GSC ERL remittance variance** were always **one to-do** (same issue) — merged on the canvas. The *other* GSC item was **Steve's Livestock reconciliation** (already done). So GSC = two items total, not three.
- **ERL forward fix DONE ✓** — translations corrected for the forward-going ERL file; recurring mismatch stopped at source.
- **New open item → GSC ERL historical discrepancies (Schedule).** Carrier will still see the historical errors. *Next action:* confirm with the carrier how they want it fixed. Christian can send them the **adjustment report**. Waiting on carrier direction.
- **3:10 PM — building the adjustment report.** Data pulled from the hacked sheet + ERL files pulled. Remaining steps: (a) combine the data, (b) show the monthly variances. (Claude offered to combine + produce a monthly-variance Excel if files are dropped in the folder.)
- **ADJUSTMENT REPORT BUILT ✓** — `123D ERL Adjustment Report - historical variance.xlsx` (in folder). Combined ERL + Hacked, monthly variances computed.
  - **Key finding: net variance = $0.00; every month ties to the penny.** Not a money problem — a *classification* problem.
  - **Benefit mis-maps (offsetting, since inception):** ERL **HL → carrier EH** ($5,443,429.46); ERL **DB → SO** ($38,996.65); ERL **OP → TR** ($165,741.24). DE & EA correct. *Inferred from exact offsets — confirm before sending to carrier.*
  - **Policy roll-up:** ERL reports parent policies (1000/3000/5000/6000/7000); carrier splits into divisions (1001/1002/2000/4000, 6001, 5001-5003, etc.) — re-allocate, totals already correct.
  - Tabs: Summary · Monthly Variance · Benefit Variance · Policy Variance · Variance Detail (Month×Policy×Benefit). 1,016 formulas, 0 errors.
- **EMAIL SENT to GreenShield (06-24) ✓** — BD variance report (`202606_123D_BD-Variance.xlsx`, SharePoint link) sent to Jyoti/AR/Cash Desk. Asked them to confirm the variances match their surpluses/deficits and to advise their preferred correction method. **Status: awaiting carrier reply.** Christian's own by-month-by-division pivot reconciles to $0 each month and flags exactly the three divisions GreenShield named (1000, 3000, 6000) — strong corroboration.
  - *Watch:* confirm the SharePoint link opens for external (greenshield.ca) recipients; have a one-liner ready on why BD8000 only appears Jun–Sep 2025.
- **4:22 PM — next block: Remittance Advices.** Starting with **tax adjustments** for **Canada Life, AGI, RBC, Manulife** (4 carriers).
- **5:04 PM — tax adjustments on remittance advices DONE ✓** (Canada Life, AGI, RBC, Manulife).
- **BLOCKED — premium payment can't be processed in QBO (QBO bug).** Waiting on QBO chat to respond (may take a while). External blocker — nothing actionable on Christian's side until QBO replies. → pick up when QBO responds / tomorrow.
- **EOD call ~5:10 PM.** Fatigue creeping in (disruptive night). Deferring remaining small items to tomorrow — sound call given financial work + tiredness. Premium payment resumes once QBO is fixed.
- **QBO back up — premium payment UNBLOCKED.** Processing it now (the one critical item). After this, stop for the day.
- **7:49 PM — PREMIUM PAYMENT DONE ✓** Payments booked in QBO + ATB file approved. The day's critical item is closed. **EOD.**

- *Pattern noted again:* afternoon meant for Steve's Life prep got eaten by ~2 hrs of invoice reconciliation. Reconciliation work keeps consuming days — recurring structural time sink to address.

**Build notes:** canvas restyled to blue/grey/white with graded blue shades (deepest navy = Do now → royal Schedule → medium Delegate → grey-blue Later). Added a dedicated Projects & areas lane with its own add box; project cards can be promoted into a bucket. Storage key bumped to `operating_canvas_v2` (seeded fresh). Folder copy refreshed.

## Storage — where canvas data lives right now
Entries typed into the sidebar canvas save to the **browser's local storage for that view, on this device** (key `operating_canvas_v1`). Local and private — not cloud, not the OneDrive folder, not a database. Persists across sessions/restarts, but: tied to one view on one device (no phone/cross-device sync), the folder `.html` copy keeps its own separate storage, and it's not independently backed up (clearing app browser data would wipe it). Good as a daily scratchpad; not yet a system of record. → strengthens the case for durable storage (Flask app + DB, or spreadsheet hub) when ready.

