# Statutory Validation Request — hrpay HRMS Platform

**To:** Chartered Accountant / statutory compliance consultant
**From:** hrpay engineering
**Date:** 2026-10-05
**Response needed by:** before any pilot payroll is processed
**Status of this document:** complete per-code worksheet, 50 codes, no values validated

---

## 0. What we are asking for, in one paragraph

We have written payroll software for an Indian establishment. The software refuses
to compute anything until a statutory value has been signed off by a qualified
professional, so this is not a request for confirmation of code that is already
live — **no statutory value in our system is active, and no payroll has been
processed.** What we need is for each of the 50 codes listed in §5 to be either
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

## 2. Priority items — what blocks a settlement run

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

### Gratuity wage components — the second, separate question

This is a **second, separate question** from the divisor, and it may matter more.

Our code, where it cannot find a payslip, falls back to `CTC ÷ 12` as the gratuity
wage basis. We now believe that is wrong, and we want your ruling before we rely on
it either way. CTC is not the same thing as statutory "wages": it normally includes
employer PF and gratuity accruals, insurance and other benefits that are not part
of the wage base. Using CTC ÷ 12 would **overstate** gratuity, and an employee
who is overpaid now is over-recovered if it is corrected at final settlement.

Please answer specifically:

1. Which components are included in "wages" for the gratuity calculation — basic,
   dearness allowance, house rent allowance, special allowance, overtime, bonuses,
   arrears, any others?
2. Which are expressly **excluded**, in particular employer PF, gratuity accrual,
   insurance or any welfare benefit?
3. Is the basis the **last drawn** wage, and if so, for which components is it
   measured — and is a perquisite valued at its actual value or at a notified
   valuation?
4. Does the answer change for an employee who joined mid-year, where "last drawn"
   covers a partial first period?

Until you answer, our code will **raise an error rather than fall back to CTC**,
because a wrong number that looks right is worse than a stop.

### Our policy on missing inputs, so you know what you are reviewing

While we wait for answers, no statutory computation may fall back to a guess, a
contract figure or zero. Where an input the law requires is absent or unconfigured,
**the system raises an error and the payroll stops.** We would rather process no
payroll than process one with a plausible-looking wrong number, because a silent
zero is the thing an employee discovers on their own payslip and disputes.

If that makes the platform unusable in the interim, that is the correct interim
state: it is visible, it is safe, and it becomes usable the moment you sign off.

## 3. TDS — the items we are least confident about

Both TDS slab tables (codes 17 and 18) are blank in our register. We are not asking
you to supply the slab tables from memory; §5 asks for them from the Finance Act.

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

## 4. Other questions our own code review raised

These came out of reviewing our own arithmetic, not out of a specific requirement.
We would rather ask than leave a wrong formula in place.

### 4.1 ESI — is the contribution a percentage or a scheduled amount?

Our code applies a flat 0.75% employee and 3.25% employer to gross wages. We now
think that is wrong: our understanding is that ESIC contributions are **scheduled by
wage band, with a fixed rupee amount per band**, which is why a person earning
around the lower bands owes a specific small amount rather than that amount times a
rate.

For a typical salary the two readings differ substantially — a flat percentage on
₹6,000 gives ₹45, where we believe the scheduled amount is ₹21. Please confirm:

1. Is the contribution within each band a **percentage of wages**, or a **fixed
   amount for the whole band**?
2. Please give the **current schedule**, band by band, with its effective date.
3. Does the schedule change when the wage crosses ₹21,000 mid-month, and how is a
   part-month apportioned when the threshold is crossed?
4. Is the base gross wages, or a defined subset?

Until you answer, our code will raise on a missing schedule rather than apply a
guessed rate.

### 4.2 Professional Tax — band edges and States that levy nothing

1. Where a band boundary applies, is the boundary **inclusive** of the upper figure
   or exclusive of it? Our code takes the first matching band, so the two readings
   differ by one rupee at each edge. This is now a configured setting rather than
   fixed behaviour, but it needs a correct default.
2. Is the band applied to **gross wages**, or to a defined subset?
3. Please confirm which States currently levy **no** PT at all. Our code used to
   treat a State with no configured band table as owing nothing, which silently
   produced a zero that nobody noticed was a configuration gap. A State levying no
   PT must now be configured with an explicit all-zero band, so a missing table
   raises instead.
4. For States that levy PT **once a year** rather than monthly, how is the month of
   levy determined — by our choosing it, or is it fixed?

### 4.3 Provident fund — employer split and the EPS ceiling

Until 2026-10-05 our code set the employer's total contribution equal to the
employee's rate by writing the same expression twice, and read a **monthly** EPS cap
from a code named `IN.PF.EPS_ANNUAL_CAP`. It therefore had **no mechanism to stop EPS
once an employee's EPS for the financial year had reached the ceiling**. Six new
config codes exist because of this review; four carry no figure at all:

`IN.PF.EMPLOYER_RATE`, `IN.PF.EMPLOYER_EPS_RATE`, `IN.PF.EPS_MONTHLY_CAP`,
`IN.PF.EPS_ANNUAL_CEILING`

Please confirm:

1. The required employer **EPS and EPF split**, and whether it differs from the
   employee's split. We are no longer assuming it matches.
2. Whether the employer's EPS portion is subject to the same **monthly wage
   ceiling** and the same **annual EPS ceiling** as the employee's.
3. **What the annual EPS ceiling is a ceiling on.** Our reading is that the ₹15,000
   monthly wage ceiling is what produces the ₹1,250 monthly EPS figure, and that
   the annual limit follows arithmetically rather than being a separate rupee
   ceiling. If that is right, `IN.PF.EPS_ANNUAL_CEILING` is redundant and we should
   delete it rather than configure a figure. Please confirm, and give the figure if
   a separate rupee ceiling exists.
4. Whether the annual ceiling applies per employee per **financial year**, and the
   **month in which it stops applying** once reached.
5. Whether an employee who crosses the annual EPS ceiling part-way through a month
   has that month's EPS reduced pro rata, or stops from the following month.

Until this is answered our code refuses to compute PF at all: an unconfigured
employer rate raises rather than defaulting to the employee's rate.

### 4.4 Leave accrual and encashment — two codes we had to invent

Two further codes were added on 2026-10-05 because the code was reading a
configuration key that never existed:

`IN.LEAVE.ACCRUAL_DAYS_PER_YEAR` (accrual per year, by leave type) and
`IN.FNF.ENCASHMENT_WAGE_BASIS` (the wage basis and averaging window for
encashment). We have **no figures for either**.

1. Please give **accrual per year by employee category** (permanent, probation,
   contractual) and by State where it differs, with the instrument. Our
   understanding is that accrual varies by category rather than being uniform.
2. For **leave encashment**, which pay components form the daily wage, and over
   what averaging window is a long-service employee's monthly wage taken when they
   exit mid-month? Our previous code used the contract wage and, where a payslip
   existed, the sum of *every* payslip line including employer contributions.
3. Is the monthly divisor the **actual days in the exit month**, or a fixed 30? Our
   previous code divided by 365, which understated the daily rate by roughly an
   order of magnitude.

Until these are configured our code raises rather than paying a zero encashment.

## 5. Per-code worksheet

Every code in the runtime catalog, so nothing can be silently skipped. Codes marked
**no research row** are ones we never researched; an explicit "no such requirement
exists" is a complete and acceptable answer for any of them.

Fill in what you can and return the sheet; we will chase the rest.

| # | Rule code | Our claimed value | Primary instrument (citation) | Confirmed / corrected value | Effective from | Your name & date |
|---|---|---|---|---|---|---|
| 1 | `IN.COW.WAGES.PROVISO_SHARE_PCT` | 50% | | | | 
| 2 | `IN.COW.WAGES.OVERTIME_SHARE_PCT` | OT excess over 50% | | | | 
| 3 | `IN.COW.WAGES.IN_KIND_CAP_PCT` | 15% | | | | 
| 4 | `IN.PF.WAGE_CEILING` | ₹15,000/month | | | | 
| 5 | `IN.PF.EMPLOYEE_RATE` | 12% | | | | 
| 6 | `IN.PF.EMPLOYER_RATE` | **no figure** — see §4.3; we had been assuming the employee's rate | | | | 
| 7 | `IN.PF.EPS_RATE` | 8.33% | | | | 
| 8 | `IN.PF.EMPLOYER_EPS_RATE` | **no figure** — see §4.3 | | | | 
| 9 | `IN.PF.EPS_MONTHLY_CAP` | ₹1,250/month — **see §4.3**, we may have no mechanism to stop it | | | | 
| 10 | `IN.PF.EPS_ANNUAL_CEILING` | **no figure** — see §4.3; we believe it may be redundant | | | | 
| 11 | `IN.PF.VOLUNTARY` | no research row | | | | 
| 12 | `IN.PF.WAGE_BASIS_RULE` | no research row | | | | 
| 13 | `IN.ESI.WAGE_THRESHOLD` | ₹21,000/month — **see §4.1** | | | | 
| 14 | `IN.ESI.EMPLOYEE_RATE` | 0.75% — **may be wrong, see §4.1** | | | | 
| 15 | `IN.ESI.EMPLOYER_RATE` | 3.25% — **may be wrong, see §4.1** | | | | 
| 16 | `IN.ESI.CONTRIBUTION_SCHEDULE` | **no schedule** — see §4.1 | | | | 
| 17 | `IN.ESI.WAGE_BASIS_RULE` | no research row | | | | 
| 18 | `IN.PT.SLABS` | per State; ₹2,500 annual cap — **see §4.2** | | | | 
| 19 | `IN.PT.ANNUAL_CAP` | ₹2,500/year | | | | 
| 20 | `IN.LWF.RATES` | per State | | | | 
| 21 | `IN.TDS.SLABS.OLD` | **no research row** — see §3 | | | | 
| 22 | `IN.TDS.SLABS.NEW` | **no research row** — see §3 | | | | 
| 23 | `IN.GRATUITY.ELIGIBILITY` | 5 yrs permanent; 1 yr pro-rata fixed-term | | | | 
| 24 | `IN.GRATUITY.DAYS_PER_YEAR` | 15 days per year or part > 6 months | | | | 
| 25 | `IN.GRATUITY.WAGES_DIVISOR` | **no figure** — see §2; wage components separately in §2 | | | | 
| 26 | `IN.GRATUITY.CEILING` | ₹20,00,000 | | | | 
| 27 | `IN.GRATUITY.PAYMENT_DEADLINE_DAYS` | 30 days + interest — see §2 row 16 | | | | 
| 28 | `IN.BONUS.THRESHOLD` | ₹21,000/month | | | | 
| 29 | `IN.COW.CH3_WAGE_CEILING` | ₹25,000 from 2026-09-17 (S.O. 5109(E)) | | | | 
| 30 | `IN.MINWAGE.DAILY_TO_HOURLY_DIVISOR` | daily ÷ 8 | | | | 
| 31 | `IN.MINWAGE.HOURLY_TO_MONTHLY_FACTOR` | hourly × 26 | | | | 
| 32 | `IN.OT.WEEKLY_CAP_HOURS` | 15 hours/week | | | | 
| 33 | `IN.OT.MONTHLY_PERIOD_HOURS` | 208 hours per 3 months | | | | 
| 34 | `IN.OT.CONSENT_REQUIRED` | explicit written consent | | | | 
| 35 | `IN.LEAVE.CARRY_FORWARD_DAYS` | 30 (Codes); State Acts differ | | | | 
| 36 | `IN.LEAVE.ENCRASHMENT_FREQUENCY` | annually | | | | 
| 37 | `IN.LEAVE.ACCRUAL_DAYS_PER_YEAR` | **no figure** — see §4.4 | | | | 
| 38 | `IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS` | 2 working days — see §2 row 12 | | | | 
| 39 | `IN.RESKILL.EMPLOYER_DEPOSIT_DAYS` | 10 days | | | | 
| 40 | `IN.RESKILL.DAYS_WAGES` | 15 days per retrenched worker | | | | 
| 41 | `IN.RESKILL.DISBURSEMENT_DAYS` | 45 days | | | | 
| 42 | `IN.FNF.NOTICE_SHORTFILL_DAYS` | no research row (contractual) | | | | 
| 43 | `IN.FNF.ENCASHMENT_WAGE_BASIS` | **no figure** — see §4.4 | | | | 
| 44 | `IN.GRIEVANCE.RESPONSE_DEADLINE_DAYS` | no research row | | | | 
| 45 | `IN.POSH.INTERNAL_COMMITTEE_DEADLINE_DAYS` | no research row | | | | 
| 46 | `IN.PF.CLAIM.WINDOW_DAYS` | no research row | | | | 
| 47 | `IN.ESI.CLAIM.WINDOW_DAYS` | no research row | | | | 
| 48 | `IN.LWF.CLAIM.WINDOW_DAYS` | no research row | | | | 
| 49 | `IN.FNF.DISPUTE_RESPONSE_DEADLINE_DAYS` | no research row | | | | 
| 50 | `IN.WAGES.DISPUTE_RESPONSE_DEADLINE_DAYS` | no research row | | | | 

Note on numbering: our register was realigned so its rows are keyed by code rather
than by description, which renumbered everything. The three priority items in §2 were
rows 12, 16 and 17 in the earlier draft and are **rows 33, 23 and 21** here. Please
work from the codes, which are unambiguous.

**This worksheet now has 50 rows, not 44.** Seven were added on 2026-10-05 during a
review of our own arithmetic: `IN.PF.EMPLOYER_RATE`, `IN.PF.EMPLOYER_EPS_RATE`,
`IN.PF.EPS_ANNUAL_CEILING`, `IN.ESI.CONTRIBUTION_SCHEDULE`,
`IN.LEAVE.ACCRUAL_DAYS_PER_YEAR` and `IN.FNF.ENCASHMENT_WAGE_BASIS` are new, and
`IN.PF.EPS_ANNUAL_CAP` was renamed to `IN.PF.EPS_MONTHLY_CAP` because it held a
monthly figure under an annual name. Each was added because the code had no
alternative to guessing; §4.3 and §4.4 explain why. None of them carries a figure we
can defend.

## 6. Golden files — the hand calculations we need

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

## 7. What happens with your answer

1. Each confirmed value is entered as an **effective-dated** statutory version,
   attributed to you by name and date. The system cannot make a row live without a
   validator who is not its author, so your sign-off is what unlocks it.
2. Corrected values replace ours in `docs/compliance/statutory-config-register.md`
   with your citation, not a law-firm summary.
3. The hand calculations in §6 become regression tests. If our arithmetic and your
   arithmetic disagree, **the code is wrong** and we change it.
4. Anything you tell us does not exist gets marked "no requirement" in the register,
   which is a real and useful outcome — it stops someone else re-researching it.

## 8. What we are not asking

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
