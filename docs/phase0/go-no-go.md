# Phase 0 — Validation Spike: Go/No-Go Note

- **Status:** CONDITIONAL GO — do not start Phase 1 until the four blocking decisions below are signed off
- **Date:** 2026-10-05
- **Scope:** Validation only. No platform code written.
- **Method:** Every claim marked ✅ was verified directly against the upstream git/PyPI/site of record on 2026-10-05, not inferred from marketing pages. Claims marked ⚠️ are unverified research that **requires sign-off by a qualified Indian payroll/tax professional** before it enters configuration.

---

## 1. Verdict summary

| # | Proposed component | Verdict | Action |
|---|---|---|---|
| 1 | Open HRMS on pinned Odoo version | ✅ **GO**, with corrected module list | Use the LGPL/AGPL subset only. All `ent_*` modules are Enterprise OPL-1 and are excluded. |
| 2 | TimeTrex CE as payroll engine | ❌ **NO-GO** | CE is sunset; tax engine is US/Canada only. Replace (see §3). |
| 3 | OCA helpdesk for pinned version | ✅ **GO** | `helpdesk_mgmt` + `helpdesk_mgmt_sla` + 5 bonus modules, all healthy at 18.0. |
| 4 | Community expenses / no Planning | ✅ **CONFIRMED as stated** — plus one new blocker (§5.2) | `hr_expense` is Community. `planning` is Enterprise. New: full accounting is Enterprise. |
| 5 | India Labour Codes status | ⚠️ **GO with material re-work to Phase 3A** | Codes are live since 21 Nov 2025; **all-exit 2-working-day wage deadline** is the biggest workflow change. |

**Headline:** The scope is achievable on Odoo Community, but **not on the stack as specified**. Two substitutions are mandatory (TimeTrex out, accounting scope reduced or licensed) and one design assumption must be reversed (the F&F deadline).

---

## 2. Question 1 — Does Open HRMS support the chosen Odoo version?

### 2.1 Pinned version selection

| Candidate | OCA/helpdesk | OCA/hr | Open HRMS | Verdict |
|---|---|---|---|---|
| Odoo **17.0** | branch exists, migration issue #523 still open (stale) | migrated | supported | Rejected — stale OCA branch |
| Odoo **18.0** | ✅ active, last commit **2026-10-01** | ✅ active, last commit **2026-10-01** | ✅ present | **SELECTED** |
| Odoo **19.0** | branch exists | branch exists | supported | Rejected — too new, no `l10n-in`, ecosystem not settled |
| Odoo **20.0** | branch stub | branch stub | n/a | Rejected — pre-release |

✅ `odoo/odoo@18.0` last commit **2026-10-03** — actively maintained.
✅ Odoo 18 `setup.py` declares `python_requires='>=3.10'`. Odoo 18 is *tested* against 3.10–3.12; **pin 3.12** in images. (Host here is 3.13 — do not run Odoo on the host interpreter.)

### 2.2 Open HRMS module audit — the critical correction

Open HRMS ships **two parallel module families**. Only one is Community-safe.

**✅ USE (Community-safe, verified manifest at branch `18.0`):**

| Module | Version | License | Depends on | Role in our stack |
|---|---|---|---|---|
| `hr_payroll_community` | 18.0.1.0.0 | **LGPL-3** | `hr_contract`, `hr_holidays` | **Payroll engine shell** (replaces TimeTrex) |
| `hr_payroll_account_community` | 18.0.1.0.0 | **LGPL-3** | `hr_payroll_community`, `account` | Accounting posting — note: targets CE Invoicing, **not** Enterprise accountant |
| `ohrms_core` | 18.0.x | LGPL-3 | hr stack | Loans, salary advance, property/assets, branch transfer |
| `hr_resignation` | 18.0.1.0.0 | **LGPL-3** | `hr_employee_updation` | Separation workflow → **triggers F&F case (3A)** |
| `hr_employee_shift` | 18.0.1.0.0 | LGPL-3 | `hr_payroll_community`, `resource` | Basic shift scheduling — baseline for 3D |
| `ohrms_loan_accounting` | 18.0.1.0.0 | LGPL-3 | — | Loan accounting postings |
| `oh_appraisal` | 18.0.1.0.0 | **AGPL-3** | `hr`, `survey` | Appraisals (built on `survey`) |

`hr_payroll_community` contains the right model skeleton: `hr_payslip`, `hr_payslip_line`, `hr_salary_rule`, `hr_salary_rule_category`, `hr_payroll_structure`, `hr_payslip_run`, `hr_contribution_register`, `hr_payslip_input`, `hr_payslip_worked_days`, `hr_contract_advantage_template`. ✅ verified by directory listing.

**❌ DO NOT USE (Odoo Enterprise, OPL-1 — violates the "no Enterprise code" rule):**

`ent_hrms_core`, `ent_hrms_dashboard`, `ent_hr_employee_shift`, `ent_hrms_payroll`, `ent_hr_payroll_extension`, `ent_hrms_appraisal`, `ent_hrms_goals`.

### 2.3 Gaps against the Phase 1 brief

| Brief asked for | Status |
|---|---|
| Appraisals | ✅ `oh_appraisal` (AGPL-3) |
| Goals / OKR | ❌ **No LGPL/AGPL Open HRMS goals module exists.** `oh_goals` is Enterprise-only. → Build custom or defer to Phase 4. |
| Resignation / separation | ✅ `hr_resignation` (LGPL-3) |
| Loans | ✅ `ohrms_core` + `ohrms_loan_accounting` |
| Appraisal ACV/HR-manager workflows | ⚠️ Thin. The LGPL appraisal is survey-backed and basic; expect to extend for the maker-checker and 9-box needs. |

⚠️ **Maturity risk (highest in this audit):** the `18.0` branch of the Open HRMS repo shows a last commit of `2026-08-19` titled *"Initial Commit"*. For the most safety-critical component in the platform, this is an effectively **fresh, unproven branch**. Mitigated by mandatory Gate 1A below.

---

## 3. Question 2 — Can TimeTrex handle Indian statutory rules?

### 3.1 Verdict: NO-GO. Three independent blockers.

**Blocker 1 — Community Edition is sunset and no longer obtainable.** ✅ verified
- `portal.timetrex.com/download.php` → **HTTP 403**, redirecting to `timetrex.com/request-demo?trial=1`. No CE download artifact exists at any version.
- `github.com/timetrex/timetrex` is a **2018 stub**: 10 stars, last push 2018-11-06, single `README.md` file, no code.
- Vendor's own blog (2025-11-26): *"While the Community Edition has been sunsetted, the commercial On-Site editions provide enterprise-grade features"* and *"TimeTrex has shifted its licensing model, moving away from the legacy Community Edition."*
- Consequence: **the CE cannot be version-pinned, vendored, or patched.** A supply-chain-pinned, reproducible image is impossible. This alone is disqualifying for an enterprise payroll platform.

**Blocker 2 — the tax engine is US/Canada only, with no India layer.** ✅ verified against the vendor's own tax-formula reference
- Documented formulas: `US-Medicate`, `US-Social Security`, `US-Federal Unemployment`, `US-Federal Income Tax`, `Province/State Income Tax`, `US-State Unemployment`, `Local (City/District/County) Income Tax`, `Canada-CPP`, `Canada-CPP2`, `Canada-EI`.
- Year-end forms: W-2, 1099, 940, 941, T4, ROE. **No Form 16, no 24Q, no ECR, no ESI contribution file, no multi-state PT slabs.**
- Nothing for PF, ESI, Professional Tax, TDS (old/new regime), gratuity, or LWF. Absence is total, not partial — and we could not patch it anyway (Blocker 1).

**Blocker 3 — Community Edition cannot do the SSO we require.** ✅ verified from vendor's own comparison table: `LDAP / SSO` → Community = **"Removed (Legacy)"**; Professional+ = Included. The Phase 1 Keycloak requirement is unsatisfiable on CE.

### 3.2 Recommended fallback — and the architecture inversion it forces

**Recommendation: adopt `hr_payroll_community` (LGPL-3) as the payroll engine inside Odoo, and build the India statutory layer ourselves.**

This is exactly the fallback the brief anticipated, with one correction: the fallback is **not** "Open HRMS payroll as a black box." `hr_payroll_community` is a ~3k-LOC generic engine. Essentially **all** Indian statutory logic is ours to write — which is correct, because the "never hardcode statutory rates" rule demands an effective-dated, source-referenced rules layer that no off-the-shelf module provides anyway.

**The architecture inverts, and this is a net simplification:**

```
BEFORE (spec)                          AFTER (recommended)
──────────────────────────────          ──────────────────────────────────
Odoo CE   : people, attendance,   ──►   Odoo CE : system of record for
            leave, expenses              people + payroll + accounting
                │
                │  JSON-RPC
                ▼
Integration : FastAPI + RabbitMQ
                │
                ▼
TimeTrex   : pay calculation,      ──►   INTEGRATION SERVICE: bridges
             separate Postgres DB          Odoo ⇄ Roster ⇄ AI only.
             masters pay                     No separate payroll DB.
```

Consequences:
- **Payroll calculation moves from TimeTrex into our own rules module** — which is what Phase 3A/3B already assumed ("the payroll rules engine computes").
- **The sync contract collapses.** `GET/POST /payroll/hours` no longer crosses a service boundary; it becomes a payroll-period-lock orchestration inside Odoo. `/sync/employees/{id}` becomes a no-op for the payroll side.
- **F&F off-cycle payment** now runs on `hr_payslip_run` with an off-cycle structure instead of a TimeTrex off-cycle run.
- **Lost:** TimeTrex's scheduling engine (irrelevant — 3D builds its own CP-SAT solver) and job costing (not in scope).
- **Gained:** one payslip store, one F&F/payslip numbering domain, no double-calculation reconciliation risk, no dual-database PII surface (materially better for Aadhaar/PAN/DPDP compliance).

### 3.3 Mandatory Gate 1A — payroll engine bake-off (must pass before Phase 1 commits)

The `hr_payroll_community` 18.0 branch is unproven. In week 1, before any Phase 1 work, prove:

1. One golden-file employee: mid-period salary change, LOP, one absence → hand-computed payslip matches to the paisa.
2. Retro edit in an **open** period recomputes correctly.
3. Retro edit in a **locked** period is rejected (proves our lock works).
4. Salary rule referencing a contribution-register field and an effective-dated config table.
5. `hr_payroll_account_community` posts a payslip journal to CE `account` with GST-analytic lines.

**If any of 1–4 fails, fall back to Plan B:** build an independent calculation service (Python, own DB) as calculation system-of-record, storing immutable payslip snapshots in Odoo for presentation. ~6 extra weeks. Decide at Gate 1A, not later.

---

## 4. Question 3 — OCA helpdesk, Community expenses, Planning

### 4.1 OCA helpdesk — ✅ GO, better than expected ✅ verified against `OCA/helpdesk@18.0`

| Module | Version | License | What it gives us |
|---|---|---|---|
| `helpdesk_mgmt` | 18.0.1.18.0 | AGPL-3 | Ticket core, teams, categories, portal |
| `helpdesk_mgmt_sla` | 18.0.2.1.0 | AGPL-3 | SLA policies. **`depends` includes `resource`** → per-country business-hours calendars ✅ |
| `helpdesk_type` | 18.0.1.2.1 | AGPL-3 | Ticket types |
| `helpdesk_type_sla` | 18.0.1.0.0 | AGPL-3 | SLA **per ticket type** → maps to payroll/grievance/escape SLAs ✅ |
| `helpdesk_mgmt_rating` | 18.0.1.0.2 | AGPL-3 | **CSAT** out of the box ✅ |
| `helpdesk_portal_restriction` | 18.0.1.1.0 | AGPL-3 | Portal scoping |
| `helpdesk_mgmt_merge` | 18.0.1.0.2 | AGPL-3 | Merge duplicates |

Repo health: ✅ last commit **2026-10-01**; `18.0` is the default branch.

**What we still build in 3C:** escalation *matrix* (L1→L2→HR head), SLA **pause** while awaiting employee, breach alerting, auto-assignment (round-robin/skill/load), reopen rules, **confidential-ticket record rules** (payroll/grievance locked to assigned team), KB↔AI deflection, SLA dashboards. `helpdesk_mgmt_sla` gives the timer + calendar; it does not give pause/resume or escalation chains.

### 4.2 Community expenses — ✅ GO ✅ verified

`addons/hr_expense` exists in `odoo/odoo@18.0` and is **LGPL-3 (Community)**. Flow: draft → employee submits → manager approves → accountant validates → accounting entries. ✅

Also Community at 18.0: `hr`, `hr_attendance`, `hr_holidays`, `hr_contract`, `hr_recruitment`, `hr_skills`, `hr_timesheet`, `survey`, `resource`, `product`, `account`, `l10n_in`. ✅

Caveat: Community `hr_expense` lacks the Enterprise "Reimbursement in Payslip" feature. Our 3B endpoint set (`/payroll/reimbursements/push`) already treats this as **our** code, so this is aligned — but it means reimbursements are paid via our own pay codes, not an Odoo-native mechanism.

### 4.3 No Planning module in Community — ✅ CONFIRMED ✅ verified

`odoo/odoo@18.0/addons/planning` → **HTTP 404**. Not in the Community repo. Odoo's editions matrix leaves Planning blank for Community. Odoo's `planning` is referenced only in Enterprise docs.

→ **Phase 3D's plan to build a custom `hr_roster` module is correct and necessary.** Note `hr_employee_shift` (LGPL-3) gives shift schedules + a `resource.calendar` extension as a starting point, but it has no solver, no hard-constraint engine, and no explainability — 3D still builds the CP-SAT service and the constraint config model.

### 4.4 ⚠️ NEW FINDING — OCA India localization does not exist at our pin

✅ Verified by branch content audit:

| OCA/l10n-india branch | addons present |
|---|---|
| 14.0 | 1 |
| 15.0 / 16.0 / 17.0 / **18.0** / 19.0 | **0** |

The `18.0` branch contains only repo metadata; last commit **2025-02-02**.

**Implications:**
- No OCA India payroll/HR/statutory module exists. Consistent with the TimeTrex NO-GO — **the entire India statutory layer is bespoke work.**
- India accounting/GST must come from Odoo core `addons/l10n_in` ✅ present in Community (chart of accounts + GST).
- `l10n_in_hr_payroll` → **HTTP 404** in CE. Odoo's own India *payroll* localization is Enterprise. Consistent with §4.3: no CE shortcut for India payroll.

---

## 5. New findings not in the original brief

### 5.1 Odoo Community has no full accounting

✅ `odoo/odoo@18.0/addons/account_accountant` → **HTTP 404** (Enterprise). Community ships `account` (Invoicing) only.

The brief commits Odoo to being "system of record for … accounting postings" and 3B requires "Post to Odoo accounting with GST tax lines." Against Invoicing:
- ✅ Works: chart of accounts, journal entries, taxes/GST, vendor bills, analytic.
- ❌ Missing: general ledger reporting, bank statement reconciliation, consolidation, deferred/accrual tooling.

**This is a scope decision for you, not something I can resolve.** Options in §7, Decision D3.

Note `hr_payroll_account_community` depends on `account`, **not** `account_accountant` ✅ — so it works on CE Invoicing. Our posting path is viable; it is the *GL close* that is thin.

### 5.2 Keycloak ↔ TimeTrex is impossible anyway

Reinforces §3.1 Blocker 3. Removes an entire integration surface from the plan.

### 5.3 Host environment is not yet build-ready

✅ measured: Debian 13, Python 3.13.5, **no `docker`**, no `kubectl`, no `helm`, 11 GB free disk, 14 GB RAM (9.2 GB already used).

Implications: Docker Compose cannot run here until the engine is installed; 11 GB is insufficient for an Odoo + PostgreSQL + multi-service stack plus images. Recommend a dedicated host with ≥100 GB and ≥32 GB RAM before Gate 1A.

---

## 6. Question 4 — India Labour Codes: status and impact

> ⚠️ **Everything in this section is research, not configuration.** It is recorded so the payroll specialist can confirm or correct it. Per the working rules, **no figure here may be hardcoded** — all rates, caps, slabs and deadlines must enter the system as effective-dated configuration with a source reference and professional sign-off. See `docs/compliance/statutory-config-register.md`.

### 6.1 Status as of 2026-10-05

| Fact | Source |
|---|---|
| All four Labour Codes **in force from 21 November 2025** (S.O. 5319(E)–5322(E)), replacing 29 central statutes | MoLE; KSMG |
| IR Code and OSH Code commenced **in full**. Wages Code and SS Code commenced **listed provisions only** (Wages Code gap = s.42(1)(2)(3)(10)(11) + s.67(2)(s)(t), State Advisory Board provisions) | KSMG |
| SS Code list read with corrigendum **S.O. 5936(E), 19 Dec 2025**; **EPF Act repealed** via that corrigendum | KSMG; Cyril Amarchand |
| **Final Central Rules notified 8 May 2026** (G.S.R. 342(E)–345(E)), effective on publication | KPMG India; MoLE |
| MoLE published official FAQs; as of **16 March 2026** | labour.gov.in FAQ PDF |
| **State rules: only ~10 States/UTs notified.** Andhra Pradesh, Arunachal Pradesh, Bihar, Gujarat, Meghalaya, Manipur, Sikkim, Tripura, Puducherry, DNH&DD notified; Maharashtra, Karnataka, Tamil Nadu, Telangana, Haryana, Punjab **still pending** (>10 months in) | ET (2026-10-01); LKS; KSMG |
| Until a State notifies, existing/repealed rules continue **insofar as not inconsistent** with the Codes | MoLE |
| Minimum wages: where a **daily** wage is fixed, hourly = daily ÷ 8, monthly = hourly × 26 | KPMG |
| ESI circulars (Dec 2025): new "wages" definition applies to ESI contribution computation | Cyril Amarchand |

### 6.2 Impact on payroll and F&F — the material changes

**🔴 P1 — F&F deadline now applies to EVERY exit, including voluntary resignation.**
All wages must be paid within **2 working days** of the last working day regardless of resignation / termination / retrenchment. Previously this applied only to employer-initiated exits; no statutory deadline applied to resignation. Gratuity, PF and other dues keep their own separate timelines.
→ **Design change for 3A:** the brief's "configurable statutory payment deadline" must ship with a **default of 2 working days for the wages component**, and per-component deadlines. A single global F&F deadline is now incorrect. This also means F&F cannot be a leisurely 30–45 day workflow — it needs an accelerated path that runs clearance and wage computation **in parallel**, with the clearance override as the only escape valve.

**🔴 P1 — New statutory "wages" definition drives PF, ESI and gratuity from 21 Nov 2025.**
Definition = all remuneration in money **including** basic, DA, retaining allowance **plus** other components (incl. HRA, conveyance) **where and to the extent exclusions exceed 50% of total remuneration** (the 50% anti-subterfuge proviso). MoLE FAQ: overtime allowance is a wages component; **excess over 50% of remuneration is added back**. Payments not in the Code on Social Security s.2(88) components are excluded from gratuity.
→ **Design change:** we need a **wages-composition engine**, not a fixed "basic + DA" basis. Every salary component needs a classification tag, and the 50% test must be evaluated per employee per period. This is a first-class rules object and the single highest-value piece of logic in the whole platform.
→ Salary structures with low basic and high allowances will see **PF, ESI and gratuity liabilities rise**. This must be surfaced as a pre-go-live impact report, and CTC will typically rise.

**🟠 P2 — Gratuity eligibility widened; formula restated.**
- 15 days' last-drawn wages per completed year **or part thereof in excess of six months** (MoLE FAQ, via Fisher Phillips).
- **Fixed-term employees: pro-rata gratuity after 1 year**, no 5-year rule — SS Code s.53 read with Social Security Central Rules r.33(1)(a) and IR Code s.2(o)(c). Trigger on **expiry of the term**, not resignation.
- Any subsequent fixed-term period of >6 months but <1 year **may be rounded off as one additional year** (KPMG).
- Payment **within 30 days**, with interest for delay; notice to employee and authority required.
- Central Government may specify a ceiling and the wage baseline divisor; piece-rated workers use average wages of the preceding 3 months; seasonal workers 7 days per season.
→ **Design change for 3A:** gratuity cannot be a single `if service > 5 years` branch. Needs: a service-period model that handles FTE contracts and contract extensions, and an **effective-dated, sign-off-gated** rate/ceiling/divisor configuration.

**🟠 P2 — Worker re-skilling fund: a new F&F-triggered liability.**
For **retrenchment** in an industrial establishment, the employer transfers **15 days' last-drawn wages** per retrenched worker to the designated account **within 10 days**; collected amount may be transferred to the worker **within 45 days**.
→ **New F&F component** + two independent statutory clocks. Must be modelled separately from gratuity (different trigger, different destination, different deadlines).

**🟡 P3 — Wage ceilings and thresholds moved.**
Chapter III wage ceiling raised to **₹25,000 from 17 September 2026** (S.O. 5109(E)). ESI applicability currently tracks **₹21,000/month**. Bonus threshold currently ₹21,000.
→ These are exactly the values that must live in the effective-dated config table with source + sign-off, never in code.

**🟡 P3 — Leave encashment is a legal entitlement, not just policy.**
Codes permit **annual** encashment with a 30-day carry-forward. **State Shops & Establishment Acts diverge** — Maharashtra allows 45 days carry-forward, and *casual* leave lapses.
→ **Design change for 3A:** leave encashment = policy component **+** statutory entitlement, computed per applicable law. The "applicable law" is not national — it resolves per State, and for 28 States the old law still governs. This is a **per-establishment legal-basis selector**, and it is the hardest configuration object in the platform.

**🟡 P3 — Overtime now requires explicit employee consent**, with weekly/monthly caps and a 50%-of-remuneration rule interacting with the wages definition. Spread-over limits and OT caps under the OSH Code are rule-dependent and not yet operable centrally.
→ Directly constrains Phase 3D. The solver's overtime hard limits must be effective-dated config per state/establishment, and **cannot be hardcoded**. Note: consent cannot be expressed as a roster constraint — it needs an explicit employee-consent artefact per assignment.

### 6.3 The structural risk

**The Centre–State divergence is the real risk, not the Centre.** Commencement is national; *rules* are not. ~10 of 36 States/UTs have notified; the largest GCC/manufacturing clusters have not. For a multi-establishment India deployment, "which law applies" is a **first-class, per-establishment, per-component** question — and it will change as States notify.

Consequences for the design:
1. Every statutory rule resolves through a chain: `country → state → establishment → contract type → effective date`. Never a global constant.
2. The legal basis chosen for each calculation must be **snapshotted into the immutable calculation version** (which the brief already requires) so historical payslips and F&F statements stay defensible after a State notifies a new rule.
3. A **statutory-change watch process** is a go-live prerequisite, not a nice-to-have. Six instrument classes change what binds: new commencement notification/corrigendum, Act amending a Code, amendment to Central Rules, State rules notification, appointment of an authority, and an enabling-section notification fixing a rate/ceiling/threshold.

---

## 7. Decisions requiring your sign-off

| ID | Decision | Recommendation |
|---|---|---|
| **D1** | **Drop TimeTrex.** Adopt `hr_payroll_community` (LGPL-3) as the payroll engine in Odoo; integration service bridges Odoo ⇄ Roster ⇄ AI only. | **Approve.** Not optional — CE is unobtainable and has no India tax support. |
| **D2** | **Accept Odoo 18.0** as the pinned version (not 17.0, not 19.0). | **Approve.** Only version where OCA helpdesk is actively maintained. |
| **D3** | **Accounting scope on Community.** Choose: **(a)** accept CE Invoicing — journal entries + GST work, GL close/reconciliation is manual or external; **(b)** license Odoo Enterprise for `account_accountant` (breaks the no-Enterprise rule, adds cost); **(c)** build GL reporting/reconciliation on top of CE `account` + OCA `mis_builder` (⚠️ `OCA/mis_builder` 18.0 last commit 2026-08-11 — usable but not fast-moving; `OCA/account-financial-report` has no 18.0 branch). | **(a) for Phase 1**, with GL reporting deferred. Revisit before 3B needs GST reconciliation at scale. |
| **D4** | **Goals/OKR has no Community module.** Build custom in Phase 4, or drop from initial scope. | Defer to Phase 4, build custom. |
| **D5** | **Gate 1A bake-off** before committing to the payroll engine (§3.3). | **Approve.** The engine's 18.0 branch is one "Initial Commit" old; this is the correct place to de-risk. |
| **D6** | **Per-establishment legal-basis model** (§6.3) — a significant addition to the Phase 1 schema. | **Approve.** Without it we cannot correctly compute F&F or gratuity for a multi-State India footprint post-Codes. |

---

## 8. Recommended path forward

**Gate 1A (week 1, blocking):**
1. Provision a build host (≥100 GB, ≥32 GB RAM, Docker). Current host is not viable (§5.3).
2. Stand up Odoo CE 18.0 + Python 3.12 + PostgreSQL 16; install the LGPL Open HRMS set.
3. Execute the 5-point payroll bake-off (§3.3). Hand-compute against a payroll specialist.
4. Engage a **qualified Indian payroll/tax professional** to review `docs/compliance/statutory-config-register.md` and sign off every entry.

**Gate 1B (week 2), only after 1A passes:** Phase 1 schema + integration service skeleton + RBAC matrix.

**Explicitly not started, pending approval:** Phase 1 code, Phase 2 AI layer, Phase 3A–3D, Phase 4.

---

## Appendix — Evidence log (verified 2026-10-05)

| Claim | Method | Result |
|---|---|---|
| OCA/helpdesk 18.0 health + module list | GitHub contents API + raw `__manifest__.py` | 34 addons; last commit 2026-10-01 |
| `helpdesk_mgmt_sla` depends on `resource` (business hours) | raw manifest read | confirmed |
| Odoo CE 18.0 module presence | GitHub contents API, HTTP status per module | `planning` 404, `hr_payroll` 404, `hr_appraisal` 404, `account_accountant` 404; `hr_expense`/`hr_attendance`/`l10n_in`/`survey` 200 |
| Odoo 18 python_requires | raw `setup.py` | `>=3.10` |
| OCA/l10n-india emptiness | GitHub contents API across 6 branches | 0 addons at 15.0–19.0 |
| Open HRMS module licenses | raw manifests, branch `18.0` | LGPL-3 / AGPL-3 set as tabulated; `ent_*` = OPL-1 Enterprise |
| `hr_payroll_community` model surface | GitHub contents API | 17 model files incl. contribution register, payslip input |
| TimeTrex CE availability | HTTP fetch of both download URLs | 403 → request-demo redirect |
| TimeTrex GitHub | GitHub repo API | 2018-11-06, 10 stars, README only |
| TimeTrex tax jurisdictions | vendor tax-formula reference doc | US/Canada only; no India |
| TimeTrex CE SSO | vendor product-comparison page | "Removed (Legacy)" |
| Labour Codes status | MoLE FAQ PDF (16 Mar 2026), KPMG India (22 May 2026), KSMG, LKS tracker, ET (1 Oct 2026), Cyril Amarchand, Fisher Phillips (3 Mar 2026) | as tabulated in §6.1 |