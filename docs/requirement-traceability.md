# Requirement Traceability Matrix — HRMS Payroll Suite

> Written 2026-10-09 against HEAD `8d44c5a`. Sources: `README.md`, `docs/phase0/go-no-go.md`,
> `docs/HANDOFF.md`, the ADRs, `docs/compliance/*`, and the delivery brief (workflows + engineering
> rules). "Automated evidence" points at `docs/api-test-results.md`; "Manual story" points at
> `docs/manual-uat-stories.md`.
>
> **Status vocabulary**
> ✅ **Done** — implemented and covered by a green automated test ·
> 🟡 **Partial / backend-only** — implemented but no UI, or only partially ·
> ⚠️ **Awaiting human sign-off** — implemented; business/statutory approval outstanding ·
> ⛔ **Not started / blocked** — no implementation.

---

## A. Phase and architecture decisions

| ID | Requirement | Source | Implementation | Automated evidence | Manual | Status |
|---|---|---|---|---|---|---|
| A1 | Pin Odoo **18.0 Community**; never load Enterprise | README, ADR-0001 | `versions/lock.txt`, `versions/pinned.env`, `ops/fetch_deps.sh` (sparse, fails on `ent_*`), `tools/check_addons.py` | static checks 0 errors; fetch verifies licence | — | ✅ Done |
| R-A2 | Drop TimeTrex; adopt LGPL `hr_payroll_community` | ADR-0002, go/no-go §3 | `.oca/` pins; `hr_payroll_community` dep in manifests | deps fetch + lock verify in run log | — | ✅ Done |
| A3 | Accounting is Invoicing-only (no Enterprise accountant) | ADR-0004 | `hr_payroll_account_community` depends on `account` only | install green | — | ✅ Done (scope) |
| ⚠️A4 | Per-establishment legal-basis resolution (**D6 open**) | ADR-0005, go-no-go §7 | `hrms.legal.basis` (`action_confirm`), resolution chain | Odoo suite (`test_statutory`) | UAT-04 | ⚠️ Approval open |
| A5 | India first, country-pluggable, effective-dated | README | catalog + `hrms.statutory.context` | standalone + Odoo | UAT-04 | ✅ Done |
| A6 | Goals/OKR (**D4 open**) | go-no-go §7 | none | — | — | ⛔ Not started |

## B. Non-negotiable engineering rules

| ID | Requirement | Implementation | Automated evidence | Manual story | Status |
|---|---|---|---|---|---|
| B1 | Never hardcode a statutory rate/cap/slab/deadline | effective-dated `hrms.statutory.rule` + sign-off-gated `.version`; 50-code catalog; `post_init_hook` asserts nothing resolves | `test_seed`, `test_statutory`, gate check (**50 codes, 0 resolve**) | UAT-03, UAT-04 | ✅ Done |
| B2 | No Odoo Enterprise code | `ops/fetch_deps.sh` + `tools/check_addons.py` reject `ent_*` | static checks 0 errors | — | ✅ Done |
| B3 | Segregation of duties in the model, not the view | `_check_signoff` (rule version), leave validate/refuse, payroll run approval | Odoo suite | UAT-04, UAT-09 | ✅ Done |
| B4 | Published rosters immutable; payroll refuses a checksum mismatch | roster period/assignment checksums | Odoo suite (`test_roster`) | UAT-08 | ✅ Done (UI unverified) |
| B5 | Payroll data read-only to the AI layer; every query logged | `group_hrms_ai_service`; `hrms.audit.log` | Odoo suite | UAT-02 | 🟡 Partial (AI layer not built) |
| B6 | A calculation with no configured input **raises**, never falls back to 0/CTC | all engines raise with the code to configure | standalone (structural guards) + gate | UAT-03 | ✅ Done |

## C. Functional workflows (delivery brief)

| ID | Workflow | Implementation | Automated evidence | Manual story | Status |
|---|---|---|---|---|---|
| C1 | Employee records + PAN/Aadhaar encryption + reveal audit | `hrms_core_ext` (`hr.employee`, crypto helpers, `hrms.audit.log`) | Odoo suite (+ new `test_core_ext_security`) | UAT-01, UAT-02 | ✅ UI present (HR Security page; F-01/F-02/F-03 fixed) |
| C2 | Statutory rule config + human sign-off | `hrms_statutory` (`rule`, `rule.version`, `catalog`) | standalone + Odoo + gate | UAT-03, UAT-04 | ✅ UI present (sign-off button; gap G2 fixed) |
| C3 | Payroll period lock (draft→review→locked→released) | `payroll.period.lock` | Odoo suite | UAT-05 | ✅ UI present (Compliance → Payroll Period Locks) |
| C4 | Roster: periods, shifts, assignments, demand, availability | `hrms_roster` | Odoo suite | UAT-05b, UAT-06 | ✅ UI present |
| C5 | Roster staffing solver (greedy, propose-only) | `hrms.roster.solver` + `solver.result` | standalone (14) + Odoo | UAT-07 | ✅ UI present |
| C6 | Payroll run lifecycle + coverage/integrity gates + SoD | `hrms_payroll_run` | Odoo suite | UAT-09, UAT-10 | ✅ UI present |
| C7 | Full & final settlement engine | `hrms_fnf` (`case`, `line`, encashment, gratuity, notice) | standalone (50) + Odoo | UAT-11, UAT-12 | ✅ UI present |
| C8 | SLA/statutory helpdesk + confidentiality | `hrms_helpdesk` + OCA `helpdesk_mgmt` | Odoo suite | UAT-13, UAT-14 | ✅ UI present |
| C9 | AI management layer (RAG/OCR, confirmation-gated) | none | — | UAT-15 | ⛔ Not started (gap G11) |
| C10 | REST API / integration service / webhooks / DLQ | none built (ORM-RPC only) | XML-RPC smoke | — | ⛔ Not started |
| C11 | Reports: payslip, Form 16, 24Q, ECR | none | — | — | ⛔ Not started (gap G12) |

## D. Statutory / legal design changes (go-no-go §6.2)

| ID | Requirement | Implementation | Automated evidence | Manual story | Status |
|---|---|---|---|---|---|
| D1 | New "wages" definition + 50% anti-subterfuge add-back | `hrms.wages.composition` (`compute`) | Odoo suite (limited) | — | 🟡 Backend-only, unvalidated |
| D2 | F&F: wages paid within **2 working days**, per-component deadlines | `hrms_fnf` deadline fields | Odoo suite | UAT-11 | 🟡 Present, unvalidated |
| D3 | Gratuity: FTE/pro-rata + extensions + effective-dated ceiling | `hrms.gratuity.service.period`, `gratuity_arithmetic` | standalone (81) | — | 🟡 Unvalidated |
| D4 | Worker re-skilling fund (retrenchment) | **catalog codes only** + reason text; no F&F component | — | — | ⛔ Not implemented |
| D5 | Wage ceilings/thresholds as effective-dated config | catalog codes (`IN.PF.*`, `IN.ESI.*`, …) | gate | UAT-03 | ✅ Done (skeletons) |
| D6 | Leave encashment = policy **+** statutory, state-varied | `hrms_fnf` encashment + `IN.LEAVE.*` | standalone (50) | UAT-11 | 🟡 Unvalidated |
| D7 | Overtime **explicit consent** artefact per assignment | only catalog code `IN.OT.CONSENT_REQUIRED`; no artefact | — | — | ⛔ Not implemented |
| D8 | Overtime caps effective-dated, not hardcoded | catalog codes exist; solver uses `solver.setting`, not statutory | — | — | 🟡 Partial (HANDOFF §5 blocking-5) |
| D9 | Legal basis snapshotted into the immutable calculation | `hrms.statutory.context` snapshot in version/result | Odoo suite | UAT-04 | ✅ Done |

## E. Non-functional / compliance

| ID | Requirement | Implementation | Evidence | Manual story | Status |
|---|---|---|---|---|---|
| E1 | Audit log is append-only | `hrms.audit.log` overrides `write`/`unlink` to raise | Odoo suite | UAT-02 | ✅ Done |
| E2 | PII encrypted at rest (PAN/Aadhaar), HMAC helpers | `hrms.mixin.encrypted`, crypto helpers | Odoo suite | UAT-01 | 🟡 Backend-only |
| E3 | Checksum integrity on roster + payroll inputs | `input_checksum` (non-stored) + roster checksums | Odoo suite | UAT-08, UAT-10 | ✅ Done |
| E4 | Idempotent integration + dead-letter | `integration.sync.log.find_by_idempotency`/`action_dead_letter` | Odoo suite | — | 🟡 Backend-only, no caller |
| E5 | QA: tests with every module + ADR per decision | 105 Odoo + 190 standalone; 9 ADRs | green run | — | ✅ Done |

## F. Explicitly out of scope / blocked (no false claims)

| Item | Why |
|---|---|
| Payroll **amounts** are correct | No statutory value is signed off; every engine raises. Correct by design, not a bug. |
| TDS on real payslips | Input write-back unbuilt (`HANDOFF §5` blocking-2). |
| CA validation of any rate | `CA-SIGNOFF-REQUEST.md` **not sent**. |
| UI for `hrms_core_ext` / `hrms_statutory` | ~~No views (gaps G1/G2)~~ Views added; not yet visually inspected. |
| External services (`services/`) | Phase 3/4, not built. |

---

## Summary

| Status | Count |
|---|---|
| ✅ Done (green automated coverage) | 13 |
| 🟡 Partial / backend-only / unvalidated | 13 |
| ⚠️ Awaiting human sign-off (D6) | 1 |
| ⛔ Not started / not implemented | 5 |

**Reading this table:** every ✅ means an automated test passed. Every 🟡 means the code exists but
something important is missing (a view, a writer, or a professional's sign-off). No row claims
statutory correctness, and none may be flipped to "verified" by the assistant.
