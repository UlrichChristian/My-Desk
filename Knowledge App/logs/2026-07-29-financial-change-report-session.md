# Financial Change Report session — 2026-07-29 (evening)

Chat outcomes for Monthly Change Report / Biggest Clients follow-on work.

## Outcomes

### Income exclusions
- **`Referral Fees:Email Feed`** excluded from Biggest Clients + Change Report (H&D referral / Manulife — not client revenue). Still stored on ingest.
- **`Statement of Work`** excluded the same way (~$88.6k in current DB).
- Constant: `EXCLUDED_INCOME_ACCOUNTS` in `fin_services/revenue_reports.py`.

### Unit tests
- Pytest suite under `Financial Management App/tests/` (in-memory SQLite; does not touch `financial.db`).
- Covers mapping/enrich, rollups + exclusions, Change Report drivers, ingest normalize + replace-by-period, client detail, custom prior.
- Run: `cd "Financial Management App" && python -m pytest`
- Dev deps: `requirements-dev.txt`.

### Change Report UX
- **Row expand:** click a client → lazy-load prior/current `fact_revenue` lines via `GET /financial/change-report/detail?period=&prior=&client=`.
- **Selectable reference month:** Month + **vs** dropdown; prior defaults to calendar prior when present (`prior` query param). Export and expand use the same pair.
- **Sortable columns:** click headers for asc/desc; expand rows stay attached to their client.

### Mapping / data fixes
- **`(unmapped)`** was blank-name deferred DES recognition JEs (`Recognized Deferred Revenue - GST applied on DES invoice…`).
- **June 2026** line mapped manually to **WF Steel and Crane** (Matt Fraser / oid 2813). July had no such blank-name line.
- Persisted override: `client_mapping_override` `memo_contains` → WF Steel and Crane; `enrich` supports `memo_contains`.

### Aug 2025 qty/rate lumps (Certs ↔ Price explosion)
**Root cause:** many Aug 2025 subscription lines stored as `quantity = -1`, `rate = amount` instead of cert count × unit rate (usually $5). Comparing later months (real certs @ $5) to Aug produced huge offsetting Certs/Price that still summed to Δ.

**Fix applied in `financial.db`:** rebuild `quantity = ±amount / unit_rate`, keep `rate = unit_rate` (mode from later months; $5 for Admin-Subscription Fee). Sign matches later months (negative qty, positive rate).

**Clients fixed (Carol Vercaigne cohort, mostly Aug 2025):**
- Perimeter Aviation, PAL, Calm Air, BVGlazing, Keewatin Air, WesTower Comm, Northern M&B, Custom Helicopter
- Carson Air Ltd., Ben Machine Prod, R1 GP, Hansen Industries, Overlanders, DryAir Man. Corp. (subscription only), WBM, Alliance Maint., LV Control Mfg, Exchange Income, Bearskin Lake
- EIC Petroleum

**Skipped:** Statement of Work lumps (already excluded from reports).

**Not done:** full sweep of all remaining Aug lumps across advisors; durable ingest-time repair so re-import does not undo DB fixes.

## Key files
| Area | Path |
|------|------|
| Exclusions / Biggest Clients | `Financial Management App/fin_services/revenue_reports.py` |
| Change report + detail | `Financial Management App/fin_services/revenue_change.py` |
| Mapping + memo_contains | `Financial Management App/fin_services/revenue_mapping.py` |
| Routes | `Financial Management App/fin_web/routes.py` |
| UI | `templates/financial/change_report.html`, `static/financial/financial.css` |
| Tests | `Financial Management App/tests/` |

## Follow-ups (optional)
1. One-shot repair for remaining lump rows (`abs(qty)=1` and `rate≈amount`) across all clients/advisors.
2. Ingest/enrich sanitizer so re-imports keep cert×rate consistent.
3. Mapping review UI for overrides (plan already calls for it).
4. Re-import note: Aug 2025 period replace would wipe manual qty/rate fixes unless (2) lands first.
