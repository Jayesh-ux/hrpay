# ADR-0004 — Constrain accounting scope on Odoo Community

- **Status:** ✅ **Accepted** (Phase 0 sign-off, 2026-10-05)
- **Date:** 2026-10-05

## Context

The brief assigns Odoo responsibility for "accounting postings" and Phase 3B requires posting
travel and expense claims with GST tax lines. Verified: `addons/account_accountant` is absent
from Odoo Community 18.0; only `account` (Invoicing) is available.

## Decision

**For Phase 1, build on Community Invoicing** (`account`, plus `l10n_in` for India GST).
Defer general-ledger reporting and bank reconciliation.

## Rationale

- Payslip, expense and loan journals post correctly against Invoicing, including GST tax lines
  and analytic accounting. `hr_payroll_account_community` depends on `account`, not
  `account_accountant`, so the posting path works on Community.
- GL reporting, bank reconciliation, consolidation and accrual tooling are Enterprise-only.
- Building a GL/reconciliation layer would compete for budget with F&F and rostering, which are
  the actual differentiators.

## Consequences

- Available: chart of accounts, journal entries, GST, vendor bills, analytic, payslip journals.
- Not available: GL reporting, bank statement reconciliation, consolidation, deferred/accrual.
- Finance owns GL close externally or manually for now.
- Revisit before Phase 3B needs GST input-credit reconciliation at scale. Options then:
  license Odoo Enterprise for `account_accountant` (breaks the no-Enterprise rule, adds cost),
  or build on CE `account` + OCA `mis_builder` (18.0 branch last commit 2026-08-11 — usable but
  slow-moving; note `OCA/account-financial-report` has no 18.0 branch).
- The no-Enterprise-code rule is about *code*, not licence. Licensing Enterprise while running
  only Community addons would not breach it, but would breach the budget constraint.
