# Productivity system — notes & thoughts

*A running capture of our conversations, decisions, and parked ideas. Last updated: 2026-06-25.*

## ▶ Start here (read this first in a new session)
This file is the **memory** for Christian's work/productivity sessions. Cowork chat history does NOT carry between sessions, but this file + the canvas do — so reading this catches you up.

- **Who:** Christian, accountant at Effortless Admin. Building a personal operating system (Eisenhower canvas + this running log).
- **Live tools:** sidebar artifact `operating-canvas` (v5) and folder copy `My operating canvas.html`. **This notes file is the system of record.** Canvas colour = azure blues.
- **As of 06-25 — major items cleared:** **Payroll (EA + ED) submitted ✓**. **Remittance-advice sequence COMPLETE** — MBC ✓, PBC ✓ (pivot macro), iASM ✓; Summary tab sent to Kathie (Medavie), confirmed by phone ✓; **notice email sent ✓** and **manual-bill advices out ✓** (Aman). Remaining today: **start accounting** (trust recon, bank recs, vacations); carried **ISL → HUB** + **CMRRA** emails.
- **Awaiting:** GreenShield reply on the GSC ERL BD-variance (sent 06-24).
- **Open follow-ups:** check the "Equ" 60-day bill in QBO ($25.44 overpaid); advise dev team to **revert ERL translations** (spell out old→new exactly); **PBC macro DONE** — Excel VBA pivot (`RemittancePivotPBC` in `EffortlessAdmin.xlam`); next, **mirror it in Process Street** (to-do + audit step). **iASM Volume Breakdown macro DONE** (`RemittancePivotIASM`) — also pending its Process Street mirror.
- **Standing rule:** every automation must be mirrored in Process Street as a to-do + an audit step.
- **Working style:** concise; earlier mornings; one trusted place over scattered systems.
- **Two-file setup:** this is the **active** file. Full day-by-day history lives in **`Productivity system - history.md`** (archive). At each **weekly review**, move completed daily logs out of here into the archive to keep this file lean.

### ⚙ Handoff rules → moved to `CLAUDE.md`
The procedure (catch-up read-order, the bash-Python file-editing rule, canvas-sync steps, leanness/archive rules, and the standing automation rule) now lives in **`CLAUDE.md`** in this folder — **read it first.**

*(Full chronological log below.)*

---

## The goal
Structure the mind — the projects, tasks, and duties on the plate — and deploy myself reliably against nice, achievable goals. Commit to structured days, earlier mornings, and more intentional time allocation. Want visual help, not just lists.

## The core reframe
This isn't a to-do problem, it's a **capture problem**. Tasks currently live in ~7 places:

- Cases system
- Written notebook
- Process Street
- BambooHR
- Email (Outlook)
- Slack
- Residue of meetings / phone calls

The mind is exhausted tracking *which system holds what*. No prioritization method fixes that. **The fix: one place reconciles all the others.** Keep the seven systems as homes for the work; pull *into* a single surface on a regular rhythm so nothing depends on memory.

## Frameworks we looked at (the "executive operating system")
- **Eisenhower matrix** — sort by urgent × important (Do now / Schedule / Delegate / Later-drop).
- **Personal kanban** — backlog → doing → done, with a work-in-progress limit (~3 in motion max).
- **Time-blocking + theme days** — give each block an owner on the calendar; a theme per day. A task without a time is a wish.
- **The 1–3–5 rule** — each day: one big thing, three medium, five small. Forces a realistic shape.
- **The weekly review** — the keystone habit. One protected hour to empty the head and set the week.
- **One trusted inbox** — the mind is for having ideas, not holding them.
- **The progress principle (Amabile)** — visible progress is the #1 driver of positive feeling at work → a running **wins log** beats an endless to-do list.

## What we built
- **Operating canvas** — a live, persistent artifact in the Cowork sidebar. Capture into an inbox, click items into the four Eisenhower buckets, tick them off into a **Wins** log that counts what's finished each week. Saves automatically.
- Backup copy saved to this folder: **My operating canvas.html** (portable; opens in any browser).
- **Access model:** sidebar = live daily driver (remembers data on this device); folder file = portable backup. *Each copy keeps its own memory — pick one home base (recommend the sidebar).*

## On storage / databases
- A SQLite DB is a good *backend* but not a *capture experience* — no UI, and capture friction decides whether a system survives. The canvas already is a small structured store under the hood.
- For a hub that aggregates the seven sources, a **spreadsheet** is recommended over SQLite for this use case: structured rows/columns, directly openable/sortable/filterable, and still readable/writable programmatically.
- Reserve a real database for when a *script* feeds it (i.e. when we automate the sweep), not as something touched by hand.

### Tomorrow's plan — 06-25
**Remittance advices (in order):**
1. Review **iASM** remittance advice
2. Amend **MBC** remittance advice
3. Review **PBC** remittance advice
4. **Send the remittance advice notice email** (only after iASM/MBC/PBC reviewed) — *deferred from tonight on purpose*
5. Send the **manual bill** remittance advices

**Also tomorrow:**
- **Payroll** (critical)
- **Start accounting:** trust account reconciliation · bank recs · booking vacations
- **ISL** email + **CMRRA** email (carried)

**Follow-ups carried:**
- Check "Equ" 60-day bill in QBO — $25.44 overpaid → reconcile.
- GSC ERL historical — awaiting GreenShield reply (BD variance sent 06-24).
- Confirm status of month-end cluster (RBC recs, Book Payroll, Month end).

*Canvas reseeded to v4 to reflect this (reload the board).*

### 06-25 progress
- **MBC remittance advice — amended & DONE ✓** (remittance sequence step 2 of 3 reviews).
- **NEW → advise DEV TEAM to revert the translations** back to the previous (correct) setup. *Comms/delegate item. Be explicit about exactly which mapping to restore — vague instructions are how the original since-inception mismatch happened; spell out old vs. new so they don't re-introduce a variance.*
- Remaining in remittance sequence: review **iASM**, review **PBC** → then **send the notice email** → then **manual bill** advices.

### 06-25 progress (afternoon update)
- **Remittance sequence — COMPLETE on Christian's side.** iASM reviewed ✓ (all three reviews — MBC/PBC/iASM — now done). **Summary tab sent to Kathie Blomsma (Medavie) and confirmed live by phone ✓.**
- **Delegated → Aman:** the **remittance notice email** and the **manual-bill advices** (he is handling the send). *Remittance sequence steps 4 & 5 off Christian's plate.*
- **Now in focus:** Payroll (critical). Calendar: Payroll Review w/ Shanette Spence 1:00pm MT; Breakfast Accounting Meeting 10:30am MT.

### 06-25 progress (evening update)
- **Payroll (EA + ED) submitted ✓** — the day's critical item cleared.
- **Remittance sequence fully closed ✓** — iASM reviewed, **notice email sent**, **manual-bill advices out** (Aman). Steps 1–5 all done.
- *Canvas reseeded to v7* — payroll + all remittance items moved to Wins. *Reload the board.*

### Automation principle (standing rule — 06-25)
**For any recurring task we automate: a macro/script is good, but it MUST be mirrored in Process Street as (1) a to-do step and (2) an audit step.** Automation without a documented process + audit = a black box — which is exactly how the ERL since-inception error stayed hidden. Pair every automation with PS to-do + PS audit.

- **PBC pivot macro — BUILT & TESTED ✓** (`RemittancePivotPBC.bas` → imported into `EffortlessAdmin.xlam`). Adapted from the existing generic `RemittancePivot` template for the condensed PBC net-premium format.
  - **Layout:** rows **Policy Number → Division**; columns **Benefit → Values → Dep Status** (granular split — intentional); values **Lives, Volume, Total Premium ("Premium"), Total**; tabular, subtotals off, grand totals on. Value-column widths tuned by Christian: Lives = 5, Volume/Premium/Total = 9.
  - **Robustness carried from the base:** auto-detects the data block (finds "Policy Number", trims the trailing Total row) so it tolerates either remittance format; adds only fields actually present (`Match`-gated); re-runnable (drops any prior "Summary" sheet first).
  - **(blank) fix:** blank-fills empty Dep Status cells with a single space so the pivot header reads empty instead of "(blank)". *This writes a space into the source sheet — must be flagged in the PS audit step.*
  - **NEXT (standing rule):** mirror the macro in **Process Street** — a to-do step + an audit step (incl. the Dep Status space-fill).
  - *Note: there are two PBC remittance file formats; this is the condensed one. The `Match`-gated logic should adapt to the other — confirm its headers when available.*
- **iASM Volume Breakdown macro — BUILT & TESTED ✓** (`RemittancePivotIASM.bas` → imported into `EffortlessAdmin.xlam`). Sibling to the PBC pivot but a different shape: a 60-day **iA Special Markets** volume report driven by **last month's “hack sheet”** (e.g. May hack → June package).
  - **Flow:** reminder MsgBox → file picker (hack sheet, opened **read-only**) → AutoFilter `TpaCode=EA` / `RemittancePartyName=iA Special Markets` / `PaymentTerm=60 days` → copy filtered rows into a **new workbook** `Source` sheet (curated 31-col layout, reordered, `PolicyNumber→Policy`) → data prep → build `Volume Breakdown` pivot → folder picker (defaults to the iASM package path) → save `YYYYMM_Volume_Breakdown.xlsx` (YYYYMM = current month).
  - **Pivot:** rows Policy → BenefitName → ProvinceCode → DependentStatus → RefVolume; values Max of CarrierRate, Sum of LifeCount/Volume/CarrierPremium/PST/GST/HST/BilledPremium; tabular, subtotals & grand totals off; style **PivotStyleLight8**; `Source` sheet hidden.
  - **Two data-prep steps (flag in PS audit):** (1) **RefVolume** col = Volume for the 5 voluntary benefits else `"-"` (live formula; BenefitName/Volume found by header); (2) blank **DependentStatus → `"-"`** (avoids pivot `(blank)`). Unlike PBC's space-fill, both act only on the *new* workbook — the hack sheet stays read-only.
  - **Robustness carried from siblings:** fields located by header (`Match`-gated), helper subs (`GetCol`/`AddDimField`/`AddVal`/`BuildPivot`/`SaveReport`), error handler restores calc/screen, re-runnable.
  - **NEXT (standing rule):** mirror in **Process Street** — a to-do step + an audit step (incl. both prep steps).
- **Canvas reseeded to v6** — iASM macro logged in Wins; “Mirror iASM macro in Process Street” added to Schedule. *Reload the board.*
- **Canvas reseeded to v5** — PBC review moved to Wins, PBC macro logged, and "Mirror PBC macro in Process Street" added to Schedule. *Reload the board.*
- **TODO / FOLLOW-UP — check the "Equ" 60-day bill in QBO.** A tax adjustment meant we paid **$25.44 more than was scheduled**. Verify the bill in QBO and reconcile the overpayment (apply as credit / adjust next bill as appropriate).
### 06-25 — Payroll App built (Claude Code session)
First tool in a new **Payroll App** (Flask, structure mirrors internal App v3). Lives in the `Payroll App` subfolder; **being moved to `C:\`** (off OneDrive) to stop file-sync gremlins. Runs locally: `python payroll.py` → http://127.0.0.1:5001 (Tools menu → BambooHR Report Pull). A CLI version exists too (`scripts/pull_bamboohr_report.py`); both share the same `services/` and produce identical output.

- **What it does:** pulls from the BambooHR REST API, by division (Effortless Admin + Effortless Dev): **timesheets** (now incl. project, task, break columns; names as "Last, First"), **time-off requests for the current period**, and **time-off requests for the previous period** (re-pulled to catch retroactive changes made after the prior run). Output: **one `.xlsx` per division** (web delivers them as a `.zip`; CLI writes both to `output/`).
- **Payroll date logic** (`services/periods.py`) — auto-fills the form: pay periods are **1–15** and **16–EOM**; **pay date = last business day on/before period end**; **submit = pay date − 3 business days**; the form auto-detects which run is due. **Timesheets** = full Sun–Sat weeks since last payroll (end = last Saturday before today; start = Sunday after the previous run's last Saturday). **Time-off** = the calendar half.
- **Decisions:** removed the balance "as-of" snapshot field (code kept, easy to restore). Business-day math is **Mon–Fri only — statutory holidays NOT yet handled** (config.HOLIDAYS hook exists; needs the stat-holiday dates). Timesheet start is currently *estimated* — becomes exact once we track the actual last payroll run (the "prior period" work).
- **Category classification — PENDING (scaffolded in config.py):** Vacation → record; some paid (e.g. Paid Sick) → ignore; **unpaid → reflected negatively for salaried staff**. Needs the exact BambooHR category names to wire up.
- **App v3 reference** captured in `Payroll App/docs/APPV3_REFERENCE.md` (what to borrow + paths) — DB layer for when tables come, waitress+logging for deploy, auth for multi-user. Read-access to App v3 on demand.
- **Standing rule (TODO):** the BambooHR pull is a recurring automation → must be **mirrored in Process Street as a to-do step + an audit step** (flag the break-field key and category buckets in the audit).

- **Moved to `C:\Payroll App` (06-25):** copied off OneDrive (to stop file-sync gremlins), confirmed it runs there, and **`git init` + initial commit** done (31 files tracked; `.gitignore` excludes `.env`, `output/`, `__pycache__`). **`C:\Payroll App` is now the working copy** — the OneDrive copies of **Payroll App and App v3 were deleted**. App v3 still available read-only on demand if needed (its patterns are digested in `Payroll App/docs/APPV3_REFERENCE.md`, which travelled with the folder). Optional later: drop the `cache_size=0` OneDrive workaround line in `payroll.py`.

## Parked ideas / possible next steps
- **Tailor the canvas to Christian (later):** layout, design, bucket labels, colors, what the wins log celebrates, the morning feel. To be done together.

### Framework coverage in the canvas — where we are (parked 06-24)
- **Eisenhower — fully reflected.** The four quadrants ARE the matrix (Do now / Schedule / Delegate / Later-drop). Sorting an inbox item into a bucket = the Eisenhower decision.
- **Kanban — only the bookends, not the engine.** Inbox ≈ backlog/capture, Wins ≈ Done. **Missing:** (a) a distinct **"Today / Doing" lane** (an in-progress stage — currently faked via the 'focus' tag + notes), and (b) a **WIP limit** (~3 in motion), which is kanban's core discipline. Without the WIP cap, Do-now drifts into another long list.
- **Progress principle — reflected** (the Wins log).
- **Not yet represented:** the 1–3–5 daily shape, time-blocking, and the weekly review.
- **Proposed next step (PARKED — work out later):** add a WIP-limited **"Today / Doing"** lane. Flow becomes: capture → triage into Eisenhower quadrants → *pull* max ~3 into Doing (live work) → Wins. This marries Eisenhower (priority) with kanban (flow) and is the change most likely to fix the 'long list eats the day' pattern.
- Colour preference confirmed: **true azure blues, no purple/indigo cast** (palette updated 06-24).
- **Flask app idea (Christian):** already has a Flask app running on a database. Could add a to-do section that ties into a separate to-do database. *Not kicking off today — worth a thought.*
- **Automated morning sweep (deferred):** scan Outlook email + Teams + calendar (Microsoft 365 is connected) and produce one consolidated "needs an action from you" list each morning. Could be a scheduled task.
- **Weekly capture sweep checklist/SOP (deferred):** a fixed ~30-min routine walking all seven sources in the same order, pulling open loops into the master surface.
- Sources I *can* reach now: Outlook email, Teams messages, calendar, SharePoint. Can't reach directly yet: cases system, Process Street, BambooHR, Slack.

## Working preferences
- Concise and direct; minimal fluff.
- Building toward: earlier mornings, structured/intentional days, a quiet block for the day's "big rock" before the noise.
