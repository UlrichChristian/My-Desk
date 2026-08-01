# Telus (Telus Health) — Reconciliation & Billing Knowledge Base
> Create Telus knowledge base note capturing the internal prep call with Fatima

## 2026-07-29 — Internal prep call with Fatima Tarbhai
Context: internal working session ahead of two Telus meetings on 2026-07-30 (AM = billing, led by Christian; PM = feeds). Follow-up to an initial cadence call at the start of the month.

### Core structural findings

**1. Feed vs. shared login determines whether member-level data exists at all.**
- When a group is set up, Telus asks the client to choose: **shared login** (one login for the whole group, no member-level info recorded — just a headcount) or **individual login** (requires a file feed: ID, first name, last name, email, possibly DOB).
- For shared-login groups, Telus has **no member-level data whatsoever** — not even names.
- The individual-login feed exists to support Telus incentive programs (gift cards etc.), not for premium calculation — as far as known, this feed is not currently used to calculate premiums either way.

**2. Telus bills on static contracted headcount, not real eligibility.**
- Telus builds a contract at sale based on a reported headcount (e.g. "500 people" × PM × 12 months) and bills against that flat number — it does not fluctuate with real terminations/hires.
- EA bills based on actual real-time monthly eligibility.
- Confirmed this holds even for groups that do have a feed — the feed isn't being used to adjust the billed count.
- **Update from July 2 call:** Telus said they would start using EA's eligibility files to update population numbers going forward. Verbal only — not yet implemented, needs to be confirmed/firmed up in tomorrow's meeting.

**3. Guiding principle to lead with: EA is the source of truth and billing authority.**
- Telus is not currently structured to accommodate this — they need to figure out how their accounting/billing can defer to EA's numbers rather than running independently.
- Once this is accepted, Telus should turn off their own PPM/retainer billing entirely except for ad hoc charges, and post only after receiving EA's eligibility/remittance data.

**4. Two types of Telus invoices/statements — different treatment.**
- **PPM/retainer invoices** ("statement of outstanding invoices") — generated from Telus' own static contract data. EA ignores these entirely; not paid, not reconciled against.
- **Ad hoc manual invoices** (e.g. a one-off EAP session, substance abuse program usage charged to a specific group) — these are real, EA does pay them, and adds them to the client statement as a separate line item.

**5. Account/policy structure — likely not one flat EA bucket, but real gaps exist underneath.**
- Fatima's read: Telus' CSMs appear to work in separate portfolios/blocks (some overlap with EA, some not) — when Frank asked which groups have a feed, different CSMs answered for their own books, suggesting they aren't fully aggregated at the top.
- Counter-evidence: in a prior case, EA sent one payment covering ~19-20 different policies, and Telus appears to have applied it entirely to one group (New Gold) rather than allocating it correctly across policies — no single payment was ever properly applied, and Telus never sent an outstanding-balance notice for any of the other ~19 accounts despite this.
- Working theory: Telus may not be doing account-by-account reconciliation even where they nominally track separate accounts.

**6. Commission payment problem — same root cause suspected.**
- A prior client (Hub/Carolyn/Christine) switched away from Telus to GreenShield, believed to be because Telus couldn't properly pay commissions — likely because they weren't reconciling on an account-by-account basis.
- Fatima raised: should EA offer to pay commissions directly to Telus's groups to work around this? Christian's view: need to understand Telus's actual setup first before offering that.
- Action: confirm someone from Telus accounting is on tomorrow's billing call specifically to speak to this (Fatima following up with Kelly on this).

**7. Remittance mechanics (current state).**
- 60-day remittance cycle, paid via EFT.
- Payment sent 3 business days prior to month-end.
- Distribution: paymentdetails@telushealth.com, Valerie Murray, Edith Pearson (for Lifeworks-side groups). Legacy EQC groups go to a different address: Jeff Leach and billing@vc.telushealth.com.
- Two remittance streams: virtual healthcare and Lifeworks.
- Telus does **not** currently send any acknowledgment/confirmation of receipt or allocation — and EA does not want that changed (would add noise, not value, until deeper reconciliation is resolved).

**8. Legacy EQC → Lifeworks migration.**
- 4 legacy EQC groups still on the old system/distribution.
- Per Frank, not high priority for Telus (tied up with file-feed migration pain points on their side).
- Expected to resolve organically — legacy groups will likely get moved over at renewal via sales/advisor conversations rather than a formal migration project. Fatima is comfortable leaving this as a lower-priority agenda item.

**9. Policy/client identifier gap on remittance advice.**
- At least one account was found sending Telus a policy number literally listed as **"TBD"** — traced to an onboarding gap (should have been verified before go-live).
- Christian's ask: needs a dedicated policy identifier column on the remittance advice regardless of which identifier Telus prefers — but the open question is *what* identifier Telus actually needs to look up a policy (name vs. policy number vs. something else, and what structure that policy number takes).

**10. Remittance advice format — two internal defaults exist, decision made not to push a change yet.**
- EA currently has two remittance format "defaults" internally (naming still TBD — Christian syncing with a colleague, Sharik, on this separately):
  - **Older / "three-file" format** — 3 separate files/sheets, less consolidated, does not include provincial tax detail (tax is sent as 2 separate files). This is what Telus currently receives.
  - **Newer / "detailed" format** — single consolidated file, more granular detail than the old one (despite the "consolidated" name being counterintuitive — new one has *more* detail, not less).
- Manitoba Blue Cross (MBC/MABC — separate carrier, see `carriers` note) was raised as a comparison: they wanted a manually-created, aggregate-style report closer to the old format, not the new one — confirms format preference varies by carrier, isn't just "newer is universally better."
- **Sequencing decision for tomorrow: don't lead with a remittance format change.** Order of operations agreed with Fatima:
  1. Confirm whether historical accounts are actually reconciled.
  2. Fix billing authority (Telus deferring to EA's numbers).
  3. Fix account/policy setup/structure.
  4. *Only then* revisit remittance advice format and client/policy identifier requests.
- If it comes up naturally tomorrow, fine to mention format flexibility — but not to push it as a priority ask.

### Open items explicitly deferred for tomorrow / later
- Whether Telus can disable individual member logins automatically once someone drops off the eligibility file (Telus confirmed yes — terminations do flow through on the feed for news/terms/nonpayment/suspension).
- Whether there's a cost difference to clients between shared-login and individual-login setups — if none, propose defaulting all mutual EA/Telus groups to individual login + feed (always member-level data).
- **Explicitly do NOT raise:** any framing around groups not paying / accounts being suspended or terminated on Telus's end. No EA groups with Telus have been terminated, and Christian does not want this on Telus's radar as a possibility at all right now.

### Tomorrow's meeting plan (2026-07-30)
- **AM — billing meeting**, Christian leading. Agenda, in order:
  1. Status: are the ~18 months of historical accounts actually reconciled? If not — recommend a standing weekly 30–60 min working call with Telus's rep, starting from the oldest unreconciled item and working forward systematically until cleared.
  2. Billing authority — EA as source of truth, get Telus's acknowledgment and understand what it takes structurally on their end to accommodate it.
  3. Account/policy setup — are policies lumped under one EA umbrella or genuinely tracked separately? (Ties to the commission and payment-application issues above.)
  4. If time allows: remittance advice format and policy/client identifier — present current format, ask what identifier Telus needs, but don't force it as a priority.
  5. Legacy EQC → Lifeworks migration status — lower priority, can be brief.
- Fatima wants confirmation that someone from Telus **accounting/AR** (not just the onboarding-side contact, Valerie) is on the call, plus ideally a **project manager** with actual authority to drive fixes — the current Telus contact indicated she may need to escalate for a PM since she's on contract and may not have the standing to resolve this alone.
- Christian considering inviting Suzy internally; will confirm.
- **PM — feeds meeting**, separate session, content not yet detailed in this call.

### Contact tracking chart (Fatima building)
Structured around three areas — Collections, Billing Inquiries, Escalation — each needing one named contact (Christian set as the default across all three for now, pending Telus's own contact structure). Fields being populated: payment method (EFT, 60-day cycle), payment date (3 business days pre month-end), distribution list/remittance streams (2: virtual healthcare, Lifeworks), notification-of-receipt (deliberately not requested), policy identifier column (pending Telus's answer), remittance advice format (deferred per sequencing above).

## ## 2026-07-30 — AM Billing Meeting (Kerry, Telus AR/Billing)

Follow-up to the 2026-07-29 internal prep call. Full transcript archived at `meeting-transcripts/telus/2026-07-30_telus-billing-am.md`.

### Billing authority — direction confirmed
- Kerry confirmed **Option 1** (EA remains billing authority, Telus posts as receivable off EA's remittance advice) as the preferred path — matches a pattern Telus already runs for other "self-remit" clients: Telus still generates an invoice/invoice number internally but simply never sends it.
- Population mismatches between what EA remits and what Telus has on file become **Telus's reconciliation problem, not EA's** once self-remit is set up — Kerry was explicit on this.
- Telus's own tolerance guideline for population drift is **~5% employee fluctuation** before it's worth a manual true-up; true-ups happen at year-end (write-off or catch-up payment), not monthly.
- Two invoice/retainer streams reconfirmed as understood correctly: PPM/retainer (self-remit target) vs. ad hoc/manual invoices (Telus stays source of truth, EA bills as separate line item, remits with invoice number — unchanged).

### Suspension/termination risk — resolved
- Kerry confirmed directly: **Telus never suspends or terminates coverage for nonpayment.** This removes the urgency Christian had flagged in the prep call about needing to actively monitor/intervene on that risk.

### Account structure — no aggregation
- Kerry clarified Telus CSMs are accountable for their own block of groups end-to-end — an aggregate "one EA bucket" framing will not work operationally, because Telus's AR team needs per-account population changes flagged to update the linked billing record. Christian agreed — reconciliation must stay account-by-account, no grouping.

### Identifier structure clarified (via live ISL Engineering example)
- Telus uses **two separate identifiers**: a **Customer ID** (e.g. `6258` — used purely for invoicing) linked to an **ORG ID** (used on Telus's side to actually update population/policy records). These are distinct systems internally.
- Kerry's read: the remittance advice identifier column Telus needs is most likely **Customer ID** (matches what's on their invoices) — not yet 100% confirmed, pending her own team.
- Live example (ISL Engineering, policy #6258 per EA / customer #6258 per Telus): an apparent $356K "owed" balance on Telus's system was traced to an **unrelated line of business**, not an EA-administered plan — a rec-sheet-reading false alarm, not a real variance (consistent with existing principle: distinguish rec sheet errors from real carrier variances before escalating).
- On the actual EA-relevant EAP line: EA's $37,381.13 remittance was confirmed received by Telus, with $1,528.81 specifically allocated to ISL — Telus's own system shows a lower expected amount (~$1,400ish) because it's still billing off a **population of 492 last updated April 2025**, while EA is currently remitting for **538 employees**. Confirms the discrepancy is a stale-population issue on Telus's side, not a misapplied payment.
- Good news surfaced live: this $37,381.13 remittance **is** being allocated correctly across separate Telus accounts today — an improvement over the state ~18 months ago, when Fatima's working theory is that Telus was not doing account-by-account reconciliation even for accounts nominally tracked separately (per prior New Gold misallocation finding in the 2026-07-29 note).

### EQ Care → Lifeworks migration
- Kerry has no visibility into the EQ Care side (separate team). All **new** Telus groups going forward are set up under Lifeworks by default already — lower-priority item, no change to prior assessment.

### Next steps / action items
- **Fatima** — send Kerry the existing master client list (the one Julie on Kerry's team already built from a prior meeting with Frank, rather than duplicating a new list) with added columns for: self-billed status, Customer ID vs. ORG ID, a fund-allocation-confirmation flag (Christian's ask — needs this on record), and an outstanding-deficit flag.
- **Kerry** — once she has the spreadsheet, pull her billing system to confirm who Telus is actually billing vs. self-remitting, and take the findings to her finance team/manager with a recommendation to convert remaining applicable clients to self-remit.
- **Kerry** — confirm with her team whether the remittance advice identifier should be Customer ID or ORG ID (leaning Customer ID).
- Fatima stayed on the call after Christian dropped for a short internal alignment chat with Kerry ahead of the separate PM feeds meeting the same day.
