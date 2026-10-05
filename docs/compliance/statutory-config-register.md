# Statutory Configuration Register

**Purpose:** the single place where statutory rates, caps, slabs, ceilings and deadlines are recorded so that they can be reviewed, signed off, and loaded as **effective-dated configuration** — never hardcoded.

**Status: ⚠️ NOT VALIDATED. DO NOT USE FOR PRODUCTION.**

Every row below is unverified research gathered during the Phase 0 spike. Each must be
confirmed or corrected by a **qualified Indian payroll / tax professional** before it may be
loaded into any environment.

## How this register relates to the code

The **`Rule code`** column is the identifier that actually runs. It matches
`RULE_CATALOG` in `addons/hrms_statutory/models/catalog.py` exactly, one row per code, all
50 of them. Earlier revisions of this document used descriptive names like
`IN.GRATUITY.DAYS_DIVISOR` where the code reads `IN.GRATUITY.WAGES_DIVISOR`, which meant
30 of the 44 codes at that time had no research row at all and several register keys could not be loaded
without editing them by hand. The code is the contract: it is what `compute_all` resolves
and what `ops/check_statutory_gate.py` verifies.

`tools/check_addons.py` cross-checks this table against the catalog, so a code that exists
in one and not the other is an error rather than a silent gap.

## Sign-off protocol

1. Payroll/tax professional reviews each row.
2. Profession supplies the **authoritative source** (gazette notification, circular, or statute
   section) — replacing our research citation.
3. Profession records their name, credentials, and date in the `signed_off_by` / `signed_off_at`
   columns of the configuration table.
4. Row status moves `unvalidated → validated → active`.
5. A new `statutory_rule_version` row is created on **every** change. Existing calculations keep
   the version they were computed under (see ADR-0006).

No row may be marked `active` without a completed sign-off.

## Register

Figures are recorded as *claims to verify*, not as authoritative values. `—` in the claimed
value column means the Phase 0 spike never researched this code; it is listed so the gap is
visible, not because we have a figure to offer.

| # | Rule code | Claimed value | Applies to | Research source | Status |
|---|---|---|---|---|---|
| 1 | `IN.COW.WAGES.PROVISO_SHARE_PCT` | **50%** of total remuneration is a permissible deduction ceiling | Code on Wages definition of wages | MoLE FAQ 16 Mar 2026 | unvalidated |
| 2 | `IN.COW.WAGES.OVERTIME_SHARE_PCT` | OT allowance **excess over 50%** of wages added back | Code on Wages — MoLE FAQ on overtime allowance | secondary | unvalidated |
| 3 | `IN.COW.WAGES.IN_KIND_CAP_PCT` | remuneration in kind counted up to **15%** of total wages | Code on Wages — in-kind explanation | Trilegal CHRO | unvalidated |
| 4 | `IN.PF.WAGE_CEILING` | ₹15,000/month | PF contribution ceiling | secondary | unvalidated |
| 5 | `IN.PF.EMPLOYEE_RATE` | 12% | PF | secondary | unvalidated |
| 6 | `IN.PF.EMPLOYER_RATE` | — | employer PF share | Code on Social Security 2020 - PF schedule | **no research row — added 2026-10-05 because the code was assuming the employee's rate** |
| 7 | `IN.PF.EPS_RATE` | 8.33% | EPS share of the employee contribution | secondary | unvalidated |
| 8 | `IN.PF.EMPLOYER_EPS_RATE` | — | employer share to EPS | Code on Social Security 2020 - PF schedule | **no research row — added 2026-10-05 because the code was assuming the employee's rate** |
| 9 | `IN.PF.EPS_MONTHLY_CAP` | ₹1,250/month | monthly ceiling on the EPS contribution | secondary | unvalidated — **renamed from `IN.PF.EPS_ANNUAL_CAP` on 2026-10-05: the code was named annual and held a monthly figure** |
| 10 | `IN.PF.EPS_ANNUAL_CEILING` | — | ceiling on EPS for the whole financial year | Code on Social Security 2020 - annual EPS ceiling | **no research row — added 2026-10-05; without it EPS could never stop** |
| 11 | `IN.PF.VOLUNTARY` | — | voluntary PF contribution config | — | **no research row** |
| 12 | `IN.PF.WAGE_BASIS_RULE` | — | rule for which wages form the PF basis | — | **no research row** |
| 13 | `IN.ESI.WAGE_THRESHOLD` | ₹21,000/month | ESI applicability | MoLE FAQ 16 Mar 2026 ("₹21,000 per month wages notified for ESI coverage will apply") | unvalidated |
| 14 | `IN.ESI.EMPLOYEE_RATE` | 0.75% | ESI | secondary | unvalidated |
| 15 | `IN.ESI.EMPLOYER_RATE` | 3.25% | ESI | secondary | unvalidated |
| 16 | `IN.ESI.CONTRIBUTION_SCHEDULE` | — | banded ESI contribution, with mode and coverage ceiling | Code on Social Security 2020 - ESI schedule | **no research row — added 2026-10-05; CA request 4.1** |
| 17 | `IN.ESI.WAGE_BASIS_RULE` | — | rule for which wages form the ESI basis | — | **no research row** |
| 18 | `IN.PT.SLABS` | per State; Constitution caps annual PT at ₹2,500 | Professional Tax | secondary | unvalidated |
| 19 | `IN.PT.ANNUAL_CAP` | ₹2,500/year | Professional Tax | Constitution of India Art. 276(2) | unvalidated |
| 20 | `IN.LWF.RATES` | per State (e.g. Maharashtra applicable) | Labour Welfare Fund | secondary | unvalidated |
| 21 | `IN.TDS.SLABS.OLD` | — | old-regime slab table | — | **no research row — tax-professional scope** |
| 22 | `IN.TDS.SLABS.NEW` | — | new-regime slab table | — | **no research row — tax-professional scope** |
| 23 | `IN.GRATUITY.ELIGIBILITY` | 5 years continuous (permanent); **1 year pro-rata (fixed-term)** | SS Code s.53; r.33(1)(a); IR Code s.2(o)(c) | MoLE FAQ; KPMG 2026-05-22 | unvalidated |
| 24 | `IN.GRATUITY.DAYS_PER_YEAR` | 15 days' last-drawn wages per completed year **or part thereof in excess of 6 months** | SS Code | MoLE FAQ; Fisher Phillips 2026-03-03 | unvalidated |
| 25 | `IN.GRATUITY.WAGES_DIVISOR` | Central Government may specify wage-baseline divisor | SS Code | Fisher Phillips | unvalidated — **blocks the formula** |
| 26 | `IN.GRATUITY.CEILING` | ₹20,00,000 (Central Government may specify) | SS Code | Fisher Phillips; Cyril Amarchand | unvalidated |
| 27 | `IN.GRATUITY.PAYMENT_DEADLINE_DAYS` | **30 days**, with interest for delay | SS Code | Fisher Phillips | unvalidated — **blocks settlement** |
| 28 | `IN.BONUS.THRESHOLD` | ₹21,000/month | Code on Wages bonus threshold | Cyril Amarchand (Jan 2026) | unvalidated |
| 29 | `IN.COW.CH3_WAGE_CEILING` | ₹25,000 from 2026-09-17 (S.O. 5109(E)) | Wage Code Chapter III ceiling | KSMG | unvalidated |
| 30 | `IN.MINWAGE.DAILY_TO_HOURLY_DIVISOR` | daily ÷ 8 = hourly | Wages (Central) Rules | KPMG 2026-05-22 | unvalidated |
| 31 | `IN.MINWAGE.HOURLY_TO_MONTHLY_FACTOR` | hourly × 26 = monthly | Wages (Central) Rules | KPMG 2026-05-22 | unvalidated |
| 32 | `IN.OT.WEEKLY_CAP_HOURS` | 15 hours/week | OSH Code | secondary | unvalidated |
| 33 | `IN.OT.MONTHLY_PERIOD_HOURS` | 26 days × 8 hours = 208 hours / 3 months | OSH Code | secondary | unvalidated |
| 34 | `IN.OT.CONSENT_REQUIRED` | explicit employee consent required | Code on Wages / OSH | Cyril Amarchand | unvalidated |
| 35 | `IN.LEAVE.CARRY_FORWARD_DAYS` | 30 days under Codes; State Shops & Establishment Acts differ (Maharashtra 45 days) | Code on Wages / State Acts | Trilegal; ET 2026-10-01 | unvalidated — **State-dependent** |
| 36 | `IN.LEAVE.ENCRASHMENT_FREQUENCY` | permitted **annually** under Codes | Code on Wages | Trilegal | unvalidated |
| 37 | `IN.LEAVE.ACCRUAL_DAYS_PER_YEAR` | — | leave accrual per year, by leave type | Code on Wages 2019; Factories Act / State Acts | **no research row — added 2026-10-05; the per-type code the engine used never existed** |
| 38 | `IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS` | **2 working days** from last working day, **all exit types incl. resignation** | Code on Wages | Bar & Bench (2026-09-12); Cyril Amarchand | unvalidated — **highest impact item** |
| 39 | `IN.RESKILL.EMPLOYER_DEPOSIT_DAYS` | 15 days' last-drawn wages per retrenched worker, **within 10 days** | OSH/SS Code | KPMG 2026-05-22 | unvalidated |
| 40 | `IN.RESKILL.DAYS_WAGES` | 15 days' last-drawn wages per retrenched worker | OSH/SS Code | KPMG 2026-05-22 | unvalidated |
| 41 | `IN.RESKILL.DISBURSEMENT_DAYS` | to worker within **45 days** | OSH/SS Code | KPMG 2026-05-22 | unvalidated |
| 42 | `IN.FNF.NOTICE_SHORTFILL_DAYS` | contractual; per-company | notice shortfall recovery basis | — | **no research row — contractual** |
| 43 | `IN.FNF.ENCASHMENT_WAGE_BASIS` | — | leave encashment wage basis and averaging window | Code on Wages 2019 - wages definition; State Acts | **no research row — added 2026-10-05; the code used CTC/365** |
| 44 | `IN.GRIEVANCE.RESPONSE_DEADLINE_DAYS` | — | IR Code grievance redressal | — | **no research row** |
| 45 | `IN.POSH.INTERNAL_COMMITTEE_DEADLINE_DAYS` | — | POSH Act 2013 Internal Committee timeline | — | **no research row** |
| 46 | `IN.PF.CLAIM.WINDOW_DAYS` | — | PF claim lodgement period | — | **no research row** |
| 47 | `IN.ESI.CLAIM.WINDOW_DAYS` | — | ESI benefit claim period | — | **no research row** |
| 48 | `IN.LWF.CLAIM.WINDOW_DAYS` | — | LWF refund/benefit claim period | — | **no research row** |
| 49 | `IN.FNF.DISPUTE_RESPONSE_DEADLINE_DAYS` | — | settlement dispute response window | — | **no research row** |
| 50 | `IN.WAGES.DISPUTE_RESPONSE_DEADLINE_DAYS` | — | wages claim / authority response window | — | **no research row** |

### Codes with no research row

Twenty of the 50 codes have **no claimed value at all**. Some were listed in the catalog
during Phase 1 and never researched; seven were added on 2026-10-05 by reading the arithmetic
and finding that it was guessing. They are not low-priority filler:

- **Both TDS slab tables.** These block payroll outright for every employee. The projection
  arithmetic in `addons/hrms_statutory/models/tds_projection.py` is covered by 45
  developer-derived tests, but every figure in those tests is our own reading and none of it
  is validated. See `CA-SIGNOFF-REQUEST.md`.
- **The seven added 2026-10-05**, each because the code had no alternative to guessing:
  `IN.PF.EMPLOYER_RATE` and `IN.PF.EMPLOYER_EPS_RATE` (the employer share was assumed equal
  to the employee's), `IN.PF.EPS_ANNUAL_CEILING` (EPS could never stop within a year),
  `IN.ESI.CONTRIBUTION_SCHEDULE` (a banded contribution could not be represented at all),
  `IN.LEAVE.ACCRUAL_DAYS_PER_YEAR` (the per-leave-type code the engine resolved never existed
  in the catalog, so accrual silently read as zero), and `IN.FNF.ENCASHMENT_WAGE_BASIS`
  (the encashment used CTC/365).
- **Six claim and response windows.** Each one produces a wrong number silently — a deadline
  that is too short means an employee loses a statutory right; too long means the employer is
  exposed. They need the professional's attention even though they look minor.
- **Wage-basis rules.** These decide *which* wages form the PF and ESI base, and which pay
  components form the gratuity and leave-encashment base, which changes each amount
  materially.
- **Voluntary PF** and **notice shortfall basis** are configuration rather than statute.

### One code was renamed rather than added

`IN.PF.EPS_ANNUAL_CAP` held a **monthly** figure (₹1,250/month) while its name said annual.
`compute_pf` read it as a monthly cap and had no way to stop EPS at an annual ceiling. It is
now `IN.PF.EPS_MONTHLY_CAP`, with `IN.PF.EPS_ANNUAL_CEILING` added separately. No value row
existed for the old code — only the skeleton is seeded — so nothing was carried over.

## TDS arithmetic: developer-derived, pending validation

`compute_tds` projects annual income as **income so far this financial year plus the current
month's recurring pay times the months that follow**. It deliberately does not extrapolate
from a run-rate average, because a run rate is wrong for a mid-year joiner, a salary revision
and a bonus month — the three cases that matter most.

Two defects in the earlier inline implementation were found by reading, not by a test, since
the logic had no test coverage: annual income was computed as `taxable_ytd * 12` on a figure
that was already year-to-date (up to a 12× overstatement that pushed employees into the top
slab), and `target_ytd = (total_annual / 12) * 12` cancelled to `total_annual`, withholding
the entire annual liability in month 1.

`tests/standalone/test_tds_arithmetic_DEV.py` covers 45 cases including both regimes, a
mid-year joiner, a salary revision and a bonus month. **The expected values in that file are
ours, not a professional's.** A green run means the code matches our reading of the rules. It
does not mean the reading is right.

### Relief and rebate are explicitly unvalidated

Marginal relief and the Section 87A rebate are implemented in
`addons/hrms_statutory/models/tds_projection.py` and both are applied to the **total** tax,
not per slab — relief exists precisely because the jump between adjacent bands is
disproportionate, so a per-slab adjustment would leave the higher rate applied to income above
the threshold, which is the effect relief is meant to remove.

Three specific points need professional confirmation before either is relied on:

1. Whether the relief cap rate is the threshold band's rate or the lower of the two adjacent
   rates.
2. Whether relief is recomputed on reduced income once applied.
3. The **order** of relief and rebate. A lower marginal-relief cap applied before the rebate
   produces a different liability than the reverse order, and the statute settles that. The
   current implementation caps first, then rebates.

Every threshold involved comes from configuration and is effective-dated, so any correction
is a new version row rather than a code change (ADR-0006).

## Per-State legal-basis overlay

State rules are notified **asynchronously** (~10 of 36 States/UTs as of 2026-10-05). Each
establishment resolves its legal basis independently. Track this per State; do not infer.

| State/UT | Wages | IR | OSH | SS | Verified as of |
|---|---|---|---|---|---|
| Andhra Pradesh | draft | draft | draft | draft | 2026-05-11 (LKS tracker) |
| Arunachal Pradesh | ✅ | ✅ | ✅ | ✅ | 2026-05-11 |
| Bihar | ✅ | ✅ | ✅ | ✅ | 2026-05-11 |
| Gujarat | ✅ | ✅ | ✅ | ✅ | 2026-05-11 |
| Karnataka | draft | draft | draft | draft | 2026-05-11 — ⚠️ later ET report (2026-10-01) still reports pending |
| Maharashtra | draft (5 drafts Apr–May 2026, all objection periods expired, none finalized) | draft | draft | draft | 2026-05-11 / 2026-10-01 |
| Tamil Nadu | draft | draft | draft | **no draft published** | 2026-05-11 |
| Telangana | draft | draft | draft | draft | 2026-05-11 |