# Statutory Validation Request — hrpay HRMS Platform

**To:** Chartered Accountant / statutory compliance consultant
**From:** hrpay engineering
**Date:** 2026-10-05
**Response needed by:** before any pilot payroll is processed
**Status of this document:** complete per-code worksheet, 44 codes, no values validated

---

## 0. What we are asking for, in one paragraph

We have written payroll software for an Indian establishment. The software refuses
to compute anything until a statutory value has been signed off by a qualified
professional, so this is not a request for confirmation of code that is already
live — **no statutory value in our system is active, and no payroll has been
processed.** What we need is for each of the 44 codes listed in §2 to be either
confirmed or corrected against the **primary instrument** (the gazette
notification, circular, or the bare Act/rule), together with an effective date.

Where our research disagrees with the primary source, **the primary source wins and
we will change the code**, not the other way round.

## 1. Why primary sources, specifically

Our own research used secondary sources — firm alerts, law-firm client notes,
newspaper summaries. We are not asking you to validate our reading of those
notes. We are asking you to go to the instrument itself.

Where our row cites a secondary source, please treat the value as **unevidenced**
until you have checked the instrument. In three cases below (rows 12, 16, 17) the
secondary sources we found disagree with each other or are silent, and those are
the three we most need help with.

## 2. Priority items — the three that block a settlement run

These three come first because they change what the employee receives, and because
each of them blocks a specific piece of arithmetic from being written at all.

### `IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS` — original row 12, now #33

| | |
|---|---|
| **Our claim** | 2 working days from the last working day, for **all** exit types including resignation |
| **Our source** | Bar & Bench (2026-09-12); Cyril Amarchand |
| **Why we need you** | This determines the deadline on every separation settlement. Our reading is that it covers resignation, which is a broader claim than most summaries state. We could not find a notification confirming the scope, and we could not rule out that the requirement differs for notice-abandoned exits. |
| **What we need** | The instrument and clause setting the deadline, the **exact scope of exit types** it covers, whether the count is in working or calendar days, and the day-count convention (is the last working day day 0 or day 1?). |
| **Effect if wrong** | Every separation settlement gets the wrong due date. Employees lose a statutory entitlement with no error raised anywhere. |

### `IN.GRATUITY.PAYMENT_DEADLINE_DAYS` — original row 16, now #23

| | |
|---|---|
| **Our claim** | 30 days, with interest for payment beyond that |
| **Our source** | Fisher Phillips |
| **Why we need you** | The 30-day figure is widely reported but we have not seen the rule text. The **interest** component is the part we cannot implement from a summary: we need the rate, whether it is simple or compounded, and from which date it runs. |
| **What we need** | The rule/notification for the 30-day period, plus the interest provision in full: rate, basis, start date. |
| **Effect if wrong** | Gratuity is paid late, or under-compensated for delay. This is a debt owed to the employee. |

### `IN.GRATUITY.WAGES_DIVISOR` — original row 17, now #21

| | |
|---|---|
| **Our claim** | "Central Government may specify the wage-baseline divisor" — **we have no figure** |
| **Our source** | Fisher Phillips |
| **Why we need you** | This is the single item that stops the gratuity formula from being written. The statutory formula is 15/26 × last-drawn wages × completed years, where "wages" is defined by a **notification we have not located**. Without the divisor, any number we produce is invented. |
| **What we need** | The notification specifying the wage baseline and its divisor, with its effective date, and confirmation of whether it is still in force. If no notification exists, please say so — that is a valid and useful answer, because it tells us to use the statutory definition directly. |
| **Effect if wrong** | Gratuity is calculated on the wrong wage base. |

## 3. TDS — the two items we are least confident about

Both TDS slab tables (codes 17 and 18) are blank in our register. We are not asking
you to supply the slab tables from memory; §4 asks for them from the Finance Act.

What we **have** implemented is the projection method, and three specific points in
it are our own derivation. They are marked in the code and in
`addons/hrms_statutory/models/tds_projection.py`, and we would like them confirmed
or corrected before they reach a payslip.

### 3.1 The projection method

Our method, per employee per month:

```
projected annual taxable income
    = taxable income received this financial year so far
    + (recurring monthly pay × months remaining after this one)

annual tax  = slabs applied marginally to projected annual income
             + surcharge (highest matching band only)
             + cess

TDS for this month
    = (annual tax − TDS already deducted this financial year)
      ÷ months remaining including this one
```

Three deliberate choices:

1. **We do not annualise by a run rate.** Income so far is added to the months
   ahead; we do not divide income so far by months elapsed and multiply by twelve.
   A run rate is wrong for a mid-year joiner, a mid-year salary revision and a
   bonus month.
2. **The forward-looking figure excludes one-offs.** A bonus is added once, to
   income so far. If a bonus were used as the monthly run rate it would be
   projected across every remaining month.
3. **Over-deduction in an earlier month is surfaced**, not silently ignored: it is
   returned as a non-recoverable amount for the next salary.

### 3.2 The three points we need confirmed

**(a) Marginal relief — cap rate.** Where income crosses a threshold and the rate
jumps, we cap the **total** tax at:

```
tax at the threshold  +  (income above the threshold × cap rate)
```

We need to know whether the cap rate is the threshold band's own rate, or the lower
of the two adjacent bands. Our reading is the threshold band's rate.

**(b) Marginal relief — is it recomputed?** We apply relief once, to the total tax
computed from full income. We need to confirm relief is not a two-stage computation
where the reduced income is itself re-taxed and re-tested against the threshold.

**(c) Order of relief and the Section 87A rebate.** **We currently cap first, then
apply the rebate.** This is the point we are least sure of. Applying a lower
marginal-relief cap before the rebate can produce a different liability from the
reverse order, and the statute settles it. Please state the required order
explicitly, including where the two interact.

### 3.3 A note on what we need for the rebate

For Section 87A we have implemented a ceiling (`max_income`, `max_rebate`) and a
rate. We need the current figures, their effective dates, and confirmation of
whether the rebate is computed on total tax or on tax before cess, and whether it
is limited by a per-eligibility condition we have not modelled.

## 4. Per-code worksheet

Every code in the runtime catalog, so nothing can be silently skipped. Codes marked
**no research row** are ones we never researched; an explicit "no such requirement
exists" is a complete and acceptable answer for any of them.

Fill in what you can and return the sheet; we will chase the rest.

| # | Rule code | Our claimed value | Primary instrument (citation) | Confirmed / corrected value | Effective from | Your name & date |
|---|---|---|---|---|---|---|
| 1 | `IN.COW.WAGES.PROVISO_SHARE_PCT` | 50% | | | | |
| 2 | `IN.COW.WAGES.OVERTIME_SHARE_PCT` | OT excess over 50% | | | | |
| 3 | `IN.COW.WAGES.IN_KIND_CAP_PCT` | 15% | | | | |
| 4 | `IN.PF.WAGE_CEILING` | ₹15,000/month | | | | |
| 5 | `IN.PF.EMPLOYEE_RATE` | 12% | | | | |
| 6 | `IN.PF.EPS_RATE` | 8.33% | | | | |
| 7 | `IN.PF.EPS_ANNUAL_CAP` | ₹1,250/month | | | | |
| 8 | `IN.PF.VOLUNTARY` | no research row | | | | |
| 9 | `IN.PF.WAGE_BASIS_RULE` | no research row | | | | |
| 10 | `IN.ESI.WAGE_THRESHOLD` | ₹21,000/month | | | | |
| 11 | `IN.ESI.EMPLOYEE_RATE` | 0.75% | | | | |
| 12 | `IN.ESI.EMPLOYER_RATE` | 3.25% | | | | |
| 13 | `IN.ESI.WAGE_BASIS_RULE` | no research row | | | | |
| 14 | `IN.PT.SLABS` | per State; ₹2,500 annual cap | | | | |
| 15 | `IN.PT.ANNUAL_CAP` | ₹2,500/year | | | | |
| 16 | `IN.LWF.RATES` | per State | | | | |
| 17 | `IN.TDS.SLABS.OLD` | **no research row** — see §3 | | | | |
| 18 | `IN.TDS.SLABS.NEW` | **no research row** — see §3 | | | | |
| 19 | `IN.GRATUITY.ELIGIBILITY` | 5 yrs permanent; 1 yr pro-rata fixed-term | | | | |
| 20 | `IN.GRATUITY.DAYS_PER_YEAR` | 15 days per year or part > 6 months | | | | |
| 21 | `IN.GRATUITY.WAGES_DIVISOR` | **no figure** — see §2 row 17 | | | | |
| 22 | `IN.GRATUITY.CEILING` | ₹20,00,000 | | | | |
| 23 | `IN.GRATUITY.PAYMENT_DEADLINE_DAYS` | 30 days + interest — see §2 row 16 | | | | |
| 24 | `IN.BONUS.THRESHOLD` | ₹21,000/month | | | | |
| 25 | `IN.COW.CH3_WAGE_CEILING` | ₹25,000 from 2026-09-17 (S.O. 5109(E)) | | | | |
| 26 | `IN.MINWAGE.DAILY_TO_HOURLY_DIVISOR` | daily ÷ 8 | | | | |
| 27 | `IN.MINWAGE.HOURLY_TO_MONTHLY_FACTOR` | hourly × 26 | | | | |
| 28 | `IN.OT.WEEKLY_CAP_HOURS` | 15 hours/week | | | | |
| 29 | `IN.OT.MONTHLY_PERIOD_HOURS` | 208 hours per 3 months | | | | |
| 30 | `IN.OT.CONSENT_REQUIRED` | explicit written consent | | | | |
| 31 | `IN.LEAVE.CARRY_FORWARD_DAYS` | 30 (Codes); State Acts differ | | | | |
| 32 | `IN.LEAVE.ENCRASHMENT_FREQUENCY` | annually | | | | |
| 33 | `IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS` | 2 working days — see §2 row 12 | | | | |
| 34 | `IN.RESKILL.EMPLOYER_DEPOSIT_DAYS` | 10 days | | | | |
| 35 | `IN.RESKILL.DAYS_WAGES` | 15 days per retrenched worker | | | | |
| 36 | `IN.RESKILL.DISBURSEMENT_DAYS` | 45 days | | | | |
| 37 | `IN.FNF.NOTICE_SHORTFILL_DAYS` | no research row (contractual) | | | | |
| 38 | `IN.GRIEVANCE.RESPONSE_DEADLINE_DAYS` | no research row | | | | |
| 39 | `IN.POSH.INTERNAL_COMMITTEE_DEADLINE_DAYS` | no research row | | | | |
| 40 | `IN.PF.CLAIM.WINDOW_DAYS` | no research row | | | | |
| 41 | `IN.ESI.CLAIM.WINDOW_DAYS` | no research row | | | | |
| 42 | `IN.LWF.CLAIM.WINDOW_DAYS` | no research row | | | | |
| 43 | `IN.FNF.DISPUTE_RESPONSE_DEADLINE_DAYS` | no research row | | | | |
| 44 | `IN.WAGES.DISPUTE_RESPONSE_DEADLINE_DAYS` | no research row | | | | |

Note on numbering: our register was realigned so its rows are keyed by code rather
than by description, which renumbered everything. The three priority items in §2 were
rows 12, 16 and 17 in the earlier draft and are **rows 33, 23 and 21** here. Please
work from the codes, which are unambiguous.

## 5. Golden files — the hand calculations we need

To validate the arithmetic and not just the rates, please work these cases by hand.
**All figures are invented. There is no real employee data in this request**, and
none is needed from you.

### Case A — straightforward full year

- Monthly basic + fixed allowances: ₹1,00,000
- No bonus, no revision, joined before the financial year
- Old regime, resident individual, no other income
- Please give the month-by-month TDS for all twelve months, plus the total withheld

### Case B — mid-year joiner

- Same pay, but joins in **October** (FY month 7 of 12)
- Please give the TDS for each month from October to March
- This is the case our run-rate approach got wrong; we want to confirm ours is right

### Case C — salary revision and a bonus

- ₹1,00,000/month from April
- Revised to ₹1,40,000/month effective **October**
- One-time bonus of ₹3,00,000 paid in **November**
- Please give month-by-month TDS and confirm how you treat the bonus for
  Section 192 purposes — specifically whether it is added to the year's projected
  income once, as we do

### Case D — relief and rebate

- One employee just below a relief threshold, one just above
- Old and new regime
- Please give the total annual liability and confirm §3.2(a), (b) and (c) against
  your figures

## 6. What happens with your answer

1. Each confirmed value is entered as an **effective-dated** statutory version,
   attributed to you by name and date. The system cannot make a row live without a
   validator who is not its author, so your sign-off is what unlocks it.
2. Corrected values replace ours in `docs/compliance/statutory-config-register.md`
   with your citation, not a law-firm summary.
3. The hand calculations in §5 become regression tests. If our arithmetic and your
   arithmetic disagree, **the code is wrong** and we change it.
4. Anything you tell us does not exist gets marked "no requirement" in the register,
   which is a real and useful outcome — it stops someone else re-researching it.

## 7. What we are not asking

- We are not asking you to review the code. We are asking you to validate figures
  and one projection method.
- We are not asking you to supply a compliance certificate or a filing. This is
  input data for an internal control.
- We will not process a payroll on your sign-off alone without a second person
  reviewing the output — the software enforces that separation itself.

---

**Attachments we can send on request:** the register with our full research trail,
the code-level location of each rule, and the test file containing the arithmetic we
currently believe is correct.
