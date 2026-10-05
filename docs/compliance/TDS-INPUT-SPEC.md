# Spec: TDS input capture and write-back

- **Status:** Specification only. **Nothing in section 4 is implemented.**
- **Date:** 2026-10-05
- **Why this exists:** `hrms_ytd_taxable`, `hrms_tds_ytd`, `hrms_current_month_pay` and
  `hrms_tds_scheduled_future_pay` currently have **no writer**. Income so far is
  derived from the contract wage and the joining date, which is wrong for bonuses,
  arrears, loss-of-pay months, prior-employer income and any declaration.
- **Explicitly out of scope on this host:** the write-back itself. It cannot be
  tested without Odoo, and shipping untested payroll state changes is worse than
  shipping none.

---

## 1. What is wrong today

| Situation | What the code does | What is required |
|---|---|---|
| Bonus paid this month | invisible — not in income so far, not in forward projection | counted once, in the month received |
| Arrears payment | invisible | counted once, in the month received |
| Loss-of-pay month | counted as a full month of pay | counted at the actual amount, zero if unpaid |
| Worked for a previous employer this FY | **not captured at all** | added to annual income; see §3 |
| Employee declared old/new regime | not captured | regime recorded and used |
| Declared exemptions or losses | not captured | reduce annual taxable income |
| Mid-year joiner | handled: service months from joining date | unchanged |

The prior-employer case is the most dangerous. If an employee's income for the
financial year is under-stated, the projected annual income is too low, the monthly
deduction is too low, and **nothing later in the year collects the shortfall** —
because the balance is recalculated each month against the same under-stated income.
The employee keeps less than the Act requires and there is no error anywhere.

## 2. Inputs the computation needs

### 2.1 Declaration (`hrms.tds.declaration`)

One record per employee per financial year. Not a field on the employee: it is
periodic, versioned, and must be retained so a past computation can be explained.

| Field | Notes |
|---|---|
| `financial_year` | Apr–Mar, derived from the company's FY start |
| `regime` | `old` / `new` / `not_declared`. **`not_declared` must not default to either.** See §3.2 |
| `regime_declared_on` | required when `regime` is set |
| `previous_employer_income` | income reported for this FY by earlier employers |
| `previous_employer_tds` | tax already reported as deducted by earlier employers |
| `income_underreport_by_prev_employer` | Form 12B style declaration, if used |
| `exemptions` | JSON, each with an amount, a section, and **a statutory instrument reference** |
| `deductions` | same shape |
| `evidence_attachment` | the signed declaration, mandatory |
| `verified_by` / `verified_at` | **must differ from `submitted_by`** |

Provenance matters more than the numbers: a declared exemption with no instrument
behind it is an assertion by the employee, not a deduction, and the audit trail has
to show which it is.

### 2.2 The four fields that need a writer

| Field | Owner | Written when |
|---|---|---|
| `hrms_ytd_taxable` | payroll run, per employee per period | after payslips for the period are final |
| `hrms_tds_ytd` | payroll run, same point | same transaction as the above, or they disagree |
| `hrms_current_month_pay` | payroll run, from payslip earnings lines | per period |
| `hrms_tds_scheduled_future_pay` | **a human**, not the payroll run | only when an approved increment letter or bonus schedule fixes the future |

All four must be written together or not at all. Writing `hrms_tds_ytd` without
`hrms_ytd_taxable` in the same transaction is the failure mode that produces a
plausible wrong number.

## 3. Rules the writer must follow

### 3.1 Income-so-far is built from payslip earnings, never from the contract

`hrms_ytd_taxable` = sum of **earnings** lines for periods in the financial year,
plus declared previous-employer income, minus any amount already reported as taxed
by a previous employer per the declaration.

Three exclusions, each of which the current code gets wrong by omission:

1. **Reimbursements** are not income. They must be excluded by line code, not by
   name, or a renamed code silently starts being taxed.
2. **Employer contributions** (PF employer, gratuity accrual) are not employee
   income. Summing *all* payslip lines, as the gratuity and leave-encashment code
   currently does, picks these up and inflates the basis.
3. **Employee deduction lines** have negative totals in Odoo. Summing every line
   nets them off, so "gross" comes out as gross-minus-deductions. Filter by
   `is_salary`/line side, not by sign.

### 3.2 Regime defaults must be explicit

If `regime` is `not_declared`, the computation must either raise or fall back to a
value that is **configured and recorded as a default**, not to whichever regime the
code happens to prefer. A silent default regime is a silent tax liability.

### 3.3 Never write back from a payslip that is not final

Only payslips in a final state may contribute. A later correction to a payslip must
trigger recomputation of the affected months, not a single overwrite, or the YTD
figure and the individual payslips disagree permanently.

### 3.4 Idempotence and restart

Re-running a period must produce the same YTD figure. That means the writer has to
be able to rebuild the financial year from payslips, not increment a running total.
Incrementing is how a failed run leaves the field permanently wrong.

### 3.5 A correction is a new version, not an edit

If a payslip is corrected, the prior computation stands. `statutory_rule_version` and
the payslip snapshot keep the old number explainable (ADR-0006).

## 4. Work items — **not started**

| # | Item | Size |
|---|---|---|
| 1 | `hrms.tds.declaration` model, security, access rules | medium |
| 2 | Separation-of-duties enforcement on verification | small |
| 3 | Earnings-line selector shared by TDS, gratuity and encashment | medium, and it fixes three defects at once |
| 4 | `hrms_ytd_taxable` write-back, rebuild-from-payslips | medium |
| 5 | `hrms_tds_ytd` write-back in the same transaction | small |
| 6 | `hrms_current_month_pay` from earnings lines, bonuses separated | medium |
| 7 | Regime default policy and its config | small |
| 8 | Prior-employer income merged into annual income | small |
| 9 | Correction/recompute path | medium |
| 10 | Tests — Odoo tests, plus standalone tests for the pure selector | medium |

Item 3 is the one to do first. Three separate modules currently sum *all* payslip
lines for a "gross" figure, which is wrong in the same way each time: it picks up
employer contributions and nets off employee deductions. One selector, tested
standalone, removes that class of defect rather than patching it three times.

## 5. Acceptance criteria

A payroll run is correct for TDS only when:

- every payslip line that feeds income is traceable to a line code in the selector;
- a bonus appears once, in the month received, and never in the forward projection;
- a month with no payslip contributes zero, not a contract wage;
- previous-employer income appears in annual income and its TDS is subtracted from
  the balance before this employer's deduction is split;
- re-running the same period twice yields identical YTD figures;
- an unverified declaration blocks the run rather than defaulting silently;
- a mid-year joiner with prior-employer income is taxed on the **whole** financial
  year's income, not only on this employer's portion.

The last one is the regression test to write first.
