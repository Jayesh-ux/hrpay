# Statutory Configuration Register

**Purpose:** the single place where statutory rates, caps, slabs, ceilings and deadlines are recorded so that they can be reviewed, signed off, and loaded as **effective-dated configuration** — never hardcoded.

**Status: ⚠️ NOT VALIDATED. DO NOT USE FOR PRODUCTION.**

Every row below is unverified research gathered during the Phase 0 spike. Each must be
confirmed or corrected by a **qualified Indian payroll / tax professional** before it may be
loaded into any environment.

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

Figures are recorded as *claims to verify*, not as authoritative values.

| # | Key | Claimed value | Applies to | Research source | Status |
|---|---|---|---|---|---|
| 1 | `IN.PF.WAGE_CEILING` | ₹15,000/month | EPF contribution ceiling | secondary | unvalidated |
| 2 | `IN.PF.EMPLOYEE_RATE` | 12% | EPF | secondary | unvalidated |
| 3 | `IN.PF.EMPLOYER_SPLIT` | 8.33% EPS + 3.67% EPF | EPF | secondary | unvalidated |
| 4 | `IN.PF.EPS_ANNUAL_CAP` | ₹1,250/month | EPS | secondary | unvalidated |
| 5 | `IN.ESI.WAGE_THRESHOLD` | ₹21,000/month | ESI applicability | MoLE FAQ 16 Mar 2026 ("₹21,000 per month wages notified for ESI coverage will apply") | unvalidated |
| 6 | `IN.ESI.EMPLOYEE_RATE` | 0.75% | ESI | secondary | unvalidated |
| 7 | `IN.ESI.EMPLOYER_RATE` | 3.25% | ESI | secondary | unvalidated |
| 8 | `IN.PT.SLABS` | per State; Constitution caps annual PT at ₹2,500 | Professional Tax | secondary | unvalidated |
| 9 | `IN.LWF.RATES` | per State (e.g. Maharashtra applicable) | Labour Welfare Fund | secondary | unvalidated |
| 10 | `IN.BONUS.THRESHOLD` | ₹21,000/month | Code on Wages bonus threshold | Cyril Amarchand (Jan 2026) | unvalidated |
| 11 | `IN.COW.CH3_WAGE_CEILING` | ₹25,000 from 2026-09-17 (S.O. 5109(E)) | Wage Code Chapter III ceiling | KSMG | unvalidated |
| 12 | `IN.FNF.WAGE_PAYMENT_DEADLINE` | **2 working days** from last working day, **all exit types incl. resignation** | Code on Wages | Bar & Bench (2026-09-12); Cyril Amarchand | unvalidated — **highest impact item** |
| 13 | `IN.GRATUITY.ELIGIBILITY_YEARS` | 5 years continuous (permanent); **1 year pro-rata (fixed-term)** | SS Code s.53; r.33(1)(a); IR Code s.2(o)(c) | MoLE FAQ; KPMG 2026-05-22 | unvalidated |
| 14 | `IN.GRATUITY.RATE` | 15 days' last-drawn wages per completed year **or part thereof in excess of 6 months** | SS Code | MoLE FAQ; Fisher Phillips 2026-03-03 | unvalidated |
| 15 | `IN.GRATUITY.CEILING` | ₹20,00,000 (Central Government may specify) | SS Code | Fisher Phillips; Cyril Amarchand | unvalidated |
| 16 | `IN.GRATUITY.PAYMENT_DEADLINE` | **30 days**, with interest for delay | SS Code | Fisher Phillips | unvalidated |
| 17 | `IN.GRATUITY.DAYS_DIVISOR` | Central Government may specify wage-baseline divisor | SS Code | Fisher Phillips | unvalidated — **needed for formula** |
| 18 | `IN.GRATUITY.PIECERATE_BASIS` | average wages of preceding 3 months | SS Code | Fisher Phillips | unvalidated |
| 19 | `IN.GRATUITY.SEASONAL_RATE` | 7 days per season | SS Code | Fisher Phillips | unvalidated |
| 20 | `IN.RESKILL.EMPLOYER_DEPOSIT` | 15 days' last-drawn wages per retrenched worker, **within 10 days** | OSH/SS Code | KPMG 2026-05-22 | unvalidated |
| 21 | `IN.RESKILL.DISBURSEMENT` | to worker within **45 days** | OSH/SS Code | KPMG 2026-05-22 | unvalidated |
| 22 | `IN.WAGES.DEFINITION.EFFECTIVE_FROM` | **2025-11-21**; excludes >50% add-back; OT excess over 50% added back | Code on Wages s.2 | MoLE FAQ 16 Mar 2026 | unvalidated |
| 23 | `IN.WAGES.KIND_REMARKING_CAP` | remuneration in kind counted up to 15% of total wages | Code on Wages | Trilegal CHRO | unvalidated |
| 24 | `IN.LEAVE.CARRY_FORWARD` | 30 days under Codes; State Shops & Establishment Acts differ (Maharashtra 45 days) | Code on Wages / State Acts | Trilegal; ET 2026-10-01 | unvalidated — **State-dependent** |
| 25 | `IN.LEAVE.ENCRASHMENT` | permitted **annually** under Codes | Code on Wages | Trilegal | unvalidated |
| 26 | `IN.OT.WEEKLY_CAP` | 15 hours/week | OSH Code | secondary | unvalidated |
| 27 | `IN.OT.MONTHLY_SPAN` | 26 days × 8 hours = 208 hours / 3 months | OSH Code | secondary | unvalidated |
| 28 | `IN.OT.CONSENT_REQUIRED` | explicit employee consent required | Code on Wages / OSH | Cyril Amarchand | unvalidated |
| 29 | `IN.MINWAGE.DAILY_TO_MONTHLY` | daily ÷ 8 = hourly; hourly × 26 = monthly | Code on Wages r. | KPMG 2026-05-22 | unvalidated |
| 30 | `IN.PERQ.NON_TAXABLE_ITEMS` | HRA exemption, LTA, meal vouchers, telephone reimbursement etc. | Income Tax | secondary | unvalidated — **tax-professional scope** |

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
| Haryana | draft | draft | draft | draft | 2026-05-11 |
| Punjab | ✅ | draft | draft | draft | 2026-05-11 |
| *(remaining 26)* | mixed | mixed | mixed | mixed | see LKS tracker |

**Rule:** where a State has not notified, pre-Codes rules continue *insofar as not inconsistent
with the Codes* (MoLE). This must be an explicit, recorded configuration decision per
establishment — not a code default.

## Watch list — what changes what binds

Six instrument classes require re-review (KSMG):

1. New commencement notification or corrigendum (e.g. S.O. 5936(E), 19 Dec 2025)
2. An Act amending a Code
3. An amendment to the Central Rules
4. A State notifying its own rules
5. An appointment naming an authority
6. A notification under an enabling section fixing a **rate, ceiling or threshold** (e.g. S.O. 5109(E), 17 Sep 2026)

A press release or vendor announcement changes nothing. Only these six do.

## Live sources for the watch process

- MoLE FAQ (as on 16.03.2026): `labour.gov.in/static/uploads/2026/03/a4ccf4c6d97c4f1f36a6d83f8c64213d.pdf`
- MoLE Labour Codes portal (official — authoritative)
- LKS per-jurisdiction tracker: `employmentlaw.lkslaw.com/draft-rules`
- ESIC circulars (Dec 2025 on the new "wages" definition)
- EPFO and state PT portals for rate/slab notifications