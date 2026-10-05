# ADR-0001 — Pin Odoo 18.0 Community Edition as the platform core

- **Status:** ✅ **Accepted** (Phase 0 sign-off, 2026-10-05)
- **Date:** 2026-10-05

## Context

The brief requires a system of record for employee master, attendance, leave, recruitment,
surveys and expenses, with Odoo Enterprise code explicitly prohibited. Planning and Helpdesk
are Enterprise-only, so substitutes are required.

## Decision

Pin **Odoo Community Edition 18.0**, Python 3.12, PostgreSQL 16.

## Rationale

- `odoo/odoo@18.0` last commit 2026-10-03 — actively maintained.
- OCA/helpdesk `18.0` last commit 2026-10-01 — the only branch where the helpdesk stack is
  actively maintained (17.0 migration issue #523 still open).
- Open HRMS ships a Community-safe LGPL/AGPL module family at `18.0`.
- Community at 18.0 contains: hr, hr_attendance, hr_expense, hr_holidays, hr_contract,
  hr_recruitment, hr_skills, hr_timesheet, survey, resource, account, l10n_in.
- 17.0 rejected (stale OCA branches). 19.0 rejected (no l10n-in, ecosystem unsettled).
  20.0 rejected (pre-release).

## Consequences

- Planning is unavailable → Phase 3D builds custom `hr_roster` (already planned).
- `account_accountant` unavailable → accounting scope constrained; see ADR-0004.
- India payroll localization unavailable → entire statutory layer is bespoke; see ADR-0003.
- Lockfile the exact Odoo commit SHA, not just "18.0", at build time.
