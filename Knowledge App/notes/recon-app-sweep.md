# Reconciliation App Sweep
> Design-audit sweep of the ASO Reconciliation App v3 (CMRRA app) — 17 branches in 3 tiers, worked with Claude Code.

Project: Reconciliation Database Project (#8). This is an architecture-and-design audit of the app itself, not a data reconciliation of clients. Grill-me depth happens in Claude Code; this note is the map and the checklist.

## Current state (anchor — from 2026-07-31 review + live DB)
- App v3, the CMRRA Reconciliation App.
- Both carrier invoices AND EA/CSIP statements are parsed into one bespoke `CarrierInvoice` JSON shape, then imported. ~15 hand-written parsers.
- Dual-statement reconciliation: opening/closing balances, float, balance-forward, claims paid, fee-factor splits, HCSA/ASO/PWA, carrier-vs-EA side-by-side.
- ~91K lines Python; ~10K recon engine; ~17-18K business logic; ~23K tests; ~20% dead/dormant.
- Canonical JSON has NO versioned machine-readable schema yet — dataclasses + imperative `validate()`, implicit CAD.
- Live DB: 13 carriers, 141 clients, 9,540 invoices, 442 fee mappings, 117 transaction types.
- Tables include `policy_fee_factors`, `recon1_ignored_refs`; retired `tpa_treatment`/`commission_treatment` columns still physically present.

## How to work a branch
Each branch is a Claude Code session prompt: "explain the current design of X, then find the gaps." Resolve dependencies before dependents. Capture the decision/finding back here or in the journal when the branch closes.

## Tier A — Architecture (do first; constrains everything else)
Dependency order matters here.
- **A1. Schema versioning + validation** (was: added #13). Foundational. Give the canonical JSON a real versioned machine-readable schema; add explicit currency; move validation off imperative `validate()`. Borrow EN 16931 rigor, not its wire format. → do this first.
- **A2. Data flow: parsing + import** (point 1). What each parser pulls; is the canonical shape shared across carrier + EA sides or two shapes compared later. Open question from grill: confirm one-shape vs two-shape.
- **A11. JSON frameworks consistency across parsers** (point 11). Are all ~15 parsers producing the canonical shape consistently? Where do they diverge? Ties directly to A1 and A2.
- **A2b. Parser failure modes + error handling** (was: #15). How a parse failure surfaces vs a real variance. MP-07 orphaned-admin failure mode at the app layer. 15 parsers = 15 silent-break points.
- **A6. New client / new policy shape** (point 6). What onboarding a client/policy looks like in the data model and UI.
- **A2r. Recon 1: import / compare logic** (point 2). How the two sides are diffed; role of `recon1_ignored_refs`.
- **A3. Export + handshake to main billing system** (point 3). Export process and the round-trip handshake between this system and EA billing.

## Tier B — UX / Change (design decisions, constrained by Tier A)
- **B4. UI concision pass** (point 4). Make it look more concise.
- **B5. Easier amendments for Kopika** (point 5). Amendment flow for the trained bookkeeper.
- **B16. Audit trail / amendment history** (was: #16). Who changed what, when. Pairs with B5; matters for Controller/CFO-grade robustness.
- **B7. Dashboard review** (point 7).
- **B8. General website design consistency** (point 8).

## Tier C — Operational / Scheduling
- **C9. Monthly timeline + Process Street interplay** (point 9). Where the app sits in the month-end workflow; what Process Street governs vs the app.
- **C10. Overnight audits with Claude** (point 10). Scheduling unattended audit runs.

## Housekeeping (fold in opportunistically, not a tier)
- **H14. Dead code / GC pass.** ~20% dormant. Safe cleanup tier = `scripts/archived scripts/` (~6K). Drop retired `tpa_treatment`/`commission_treatment` columns.
- **H17. Test coverage map.** ~23K lines of tests — which branches above are actually covered vs exposed.

## Suggested working order
A1 → A2 → A11 → A2b → A6 → A2r → A3 (architecture spine) → then B tier → then C tier. Housekeeping folds in wherever a branch touches the relevant code.
