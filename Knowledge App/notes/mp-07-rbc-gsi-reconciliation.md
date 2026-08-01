
# MP-07 — RBC GSI Reconciliation
> Cascadia batch of 8 submitted to RBC (Case #2458400, ack'd); Canada Pet Health reviewed and sent to RBC 2026-07-09

## Scope

- **New Gold Inc.** — Policy 0001005098. Invoices received via email.
- **Ottawa Community Housing** — self-admin AD&D/LTD via EA; Individual Protection for 3 execs billed separately.
- **Cascadia / North American Pipe & Steel** — Policy I0001004061 (Class 2A).
- **Canada Pet Health Insurance** — reviewed 2026-07-09.
- **Algoma University** — unconfirmed, may not belong to this batch.

## Core Risk Framework — Three Failure Modes

All variances trace back to synchronization drift between EA's internal system and the carrier's system, surfacing three ways:

1. **Termination not reported** — member terminated on EA's system, but carrier never notified within required window (30 days for RBC). Carrier keeps billing; retroactive credit may be denied if outside the window.
2. **Coverage not activated** — carrier/client confirms coverage should exist, but it's never set up on EA's platform. Risk: a claim could be wrongly declined since EA's system shows no coverage.
3. **Orphaned administration** — neither billed nor remitted by EA despite client believing coverage is active. Highest risk — no record of who's responsible or whether coverage was ever in force.

## Policy-by-Policy Status

### New Gold (0001005098) — RECONCILED
- Member-level variances (net $1,656.65 owed to RBC) resolved via correspondence through May 2026.
- Ongoing monthly remittance confirmed at $782.37 (RBC's Apr 29/26 email confirms payment received, no premium owing).
- Patterns identified: termination-lag billing (partial/no reversal after term date); retroactive double-count where a correctly-billed retro premium gets re-applied in a later invoice, then an "amendment" over-corrects in the other direction.

### Ottawa Community Housing — IN PROGRESS (owner: Suzy, tracked as Task #118)
- Individual Protection benefit ($656.63/mo, Billing Division 1) for 3 executives (Giguere, Gilligan, Youdale) confirmed via Nov 2025 RBC correspondence but never activated on EA's platform — should have gone live July 2025/Nov 2025.
- Root cause: Failure Mode 2 (coverage-activation gap). Confirmed decision via email ≠ implemented decision.
- Suzy is fixing directly (retroactive activation, back-charges netted against credit carrying forward on RBC invoice); coordinating with Frank Piazza (HUB).
- Separately: Division 2 tax breakdown discrepancy ($21.83, misallocated to Div 2 instead of Div 3) — RESOLVED 2026-07-09, corrected in 60-day Provincial Tax Breakdown sheet (task #137, done).

### Cascadia / North American Pipe & Steel (I0001004061, Class 2A) — IN PROGRESS
- Root cause (primary cluster): Failure Mode 1 — EA terminated members internally but never notified RBC within the 30-day window. Confirmed via EA GBS team (Jireh) correspondence with RBC (Tammey), where termination dates run 6–11+ months before the notification was sent. RBC has requested backup proof of earlier submission; credit recovery uncertain for anything outside the 30-day window.
- **2026-07-03 SUBMITTED**: Batch of 8 members (Berkley, De Leon, Falcon, Friesen, Hofman, Huff, Moin, Taylor) sent to RBC — updated total **-$1,947.66** (Case #2458400). RBC (Rasita Chandran, Client Services Operations Rep) confirmed receipt and will process — actual bill adjustment not yet reflected on statements, awaiting.
- Kim Clark and Alma Perez Covarrubias NOT part of this batch — still open, unresolved.
- Wybou still open/reopened — unresolved.

**Member-level detail:**

| Member | Variance (as of Jul 3/26 submission) | Status |
|---|---|---|
| Berkley, Angela | -204.60 | SUBMITTED 2026-07-03 (Case #2458400) — RBC ack'd, awaiting processing |
| Clark, Kim | 254.94 | OPEN — dates to 2024, needs deeper investigation, NOT in Jul 3 batch |
| De Leon, Dean | -212.48 | SUBMITTED 2026-07-03 (Case #2458400) — RBC ack'd, awaiting processing |
| Falcon, Ricardo | -846.56 | SUBMITTED 2026-07-03 (Case #2458400) — RBC ack'd, awaiting processing |
| Friesen, Mark | 490.62 | SUBMITTED 2026-07-03 (Case #2458400) — member returned to work Jul 2025, RBC never restarted billing (waived in error); requested waiver removal + retro-bill. RBC ack'd, awaiting processing |
| Hofman, Christopher | -276.90 | SUBMITTED 2026-07-03 (Case #2458400) — RBC ack'd, awaiting processing |
| Huff, Debra | -564.60 | SUBMITTED 2026-07-03 (Case #2458400) — RBC ack'd, awaiting processing |
| Moin, Urusa | -256.98 | SUBMITTED 2026-07-03 (Case #2458400) — RBC ack'd, awaiting processing |
| Perez Covarrubias, Alma | -63.72 | OPEN — dates to 2024, needs deeper investigation, NOT in Jul 3 batch |
| Taylor, William | -76.16 | SUBMITTED 2026-07-03 (Case #2458400) — RBC ack'd, awaiting processing |
| Tedla, Awet | 33.36 | IN PROGRESS — policy commenced Feb 2026, EA billed from Jan in error; corrected by GBS team, expected to flow through |
| Bolt, Anusia | (was 38.91) | RESOLVED — rec sheet error, no actual discrepancy (EA billed same as RBC) |
| Hayes, Jason | (was -263.24) | RESOLVED — credit for term-date gap (Mar–Jun) found on statement, cleared |
| Traver, Shane | -49.80 | RESOLVED — separate/unrelated RBC credit already given, missed on rec sheet; not an actual issue |
| Wybou, Alycia | -135.58 | REOPENED — same $135.58 credit appears twice on statement (Feb and March). Not explained by the Traver credit (different amount, unrelated). Needs confirmation: two legitimate reversal months, or RBC double-crediting the same month. |

### Canada Pet Health Insurance — REVIEWED 2026-07-09
- Not reconciled since ~Jul 2024. Review identified $1,428.75 in credits owed across 15 members, mostly terminated members billed past termination date.
- Email sent to RBC (Rasita Chandran) with variance summary + source file (202507_CanadaPetHealth.xlsx), requesting confirmation/adjustment and reflection on upcoming statement. Also flagged members still showing "not yet terminated" with RBC, requesting status confirmation on those.
- Awaiting RBC response.

### Algoma University — UNCONFIRMED

## Process Learnings

- A carrier/client-confirmed billing decision (via email) is not the same as an implemented one — verify the platform actually reflects it before assuming it's live (OCH gap).
- Distinguish **rec sheet errors** (Bolt, Traver — resolved by re-checking, not by carrier action) from **real carrier variances**. Don't assume every "resolved" line means the same thing — Bolt/Hayes/Traver were rec-sheet or lookup corrections, while Wybou's apparent resolution needs re-verification because a similar-looking credit turned out to be a different, unrelated item.
- When two credits of the same amount appear on a statement, don't assume they're duplicates of one entry until confirming each against a specific reversal month — and don't assume they're unrelated either. Verify against the number of months actually over-billed.
- Termination-to-carrier-notification lag appears to be a recurring gap, not a one-off (multiple Cascadia members, 6–11+ months late) — may be worth checking whether this connects to the offboarding process (MP-05) as a root-cause fix rather than patching case-by-case.
- 30-day notification windows are a hard constraint with some carriers (RBC) — late notification risks losing the credit entirely, shifting exposure to EA/client rather than the carrier absorbing it.
- Variances left unresolved continue to grow month over month while billing continues uncorrected (Cascadia batch grew from -1,406.95 running total to a -1,947.66 submission total between early builds and the Jul 3 email) — reinforces that timely notification/submission matters even before the underlying root cause is fixed.
- A carrier confirming "we will process accordingly" is acknowledgment of receipt, not confirmation the adjustment has posted — verify against the next statement before considering an item closed.

## Open Actions

- [x] Notify RBC — Friesen + 7 other Cascadia terminations: submitted 2026-07-03 (Case #2458400), RBC ack'd
- [ ] Confirm Cascadia Jul 3 batch (8 members) actually reflected on RBC statement — not yet verified
- [ ] Confirm Wybou — is the Feb/March $135.58 credit a legitimate double-month reversal or an RBC double-credit error
- [ ] Investigate — Clark, Kim (dates to 2024)
- [ ] Investigate — Perez Covarrubias, Alma (dates to 2024)
- [ ] OCH — confirm Suzy's retroactive fix (Task #118)
- [x] Canada Pet Health — reviewed, email sent to RBC 2026-07-09 (Task #142, done)
- [ ] Confirm Canada Pet Health credits ($1,428.75) actually reflected on RBC statement — not yet verified
- [ ] Algoma University — confirm whether this belongs to the RBC GSI batch at all

## 2026-07-09 — Task #114 closed, monthly follow-up now recurring

Task #114 (RBC GSI Reconciliations) marked done and taken off the board. Ongoing follow-up is now handled via recurring template #143 ("RBC GSI Reconciliation — Monthly Follow-up"), which checks whether the Cascadia batch (Case #2458400) and Canada Pet Health credits actually post to the RBC statement, and tracks the still-open items (Clark, Perez Covarrubias, Wybou, OCH #118). This note remains the source of full history/detail.

## 2026-07-09 — Monthly follow-up moved to Process Street

Correction: monthly follow-up is NOT tracked as a My Desk recurring task. It already lives in Process Street, and Christian is training Kopika on it there. My Desk template #143 was relabeled SUPERSEDED (no delete function exists for recurring templates) and should not be started. This note remains the reference for full reconciliation history/detail regardless of which tool tracks the recurring cadence.
