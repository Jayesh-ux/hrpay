# ADR-0002 — Reject TimeTrex Community Edition; adopt an LGPL payroll engine in Odoo

- **Status:** Proposed (Phase 0, awaiting sign-off)
- **Date:** 2026-10-05

## Context

The brief specifies TimeTrex Community Edition as a separate payroll service with its own
PostgreSQL database, bridged by an integration service, with TimeTrex owning pay calculation.

## Decision

**Reject TimeTrex.** Adopt `hr_payroll_community` (LGPL-3, Open HRMS) inside Odoo as the payroll
engine, with all Indian statutory rules implemented by us as effective-dated configuration.

## Rationale — three independent disqualifiers

1. **CE is sunset and unobtainable.** `portal.timetrex.com/download.php` returns HTTP 403 and
   redirects to a demo request. `github.com/timetrex/timetrex` is a 2018 stub (10 stars,
   README only, no code). No artifact exists at any version, so the platform cannot version-pin
   or patch it — unacceptable for a payroll system of record.
2. **No India tax support.** The documented formula set is US/Canada only (US-Medicare,
   US-Social Security, US-FUTA, US Federal/State/Local income tax, Canada CPP/CPP2/EI).
   No PF, ESI, Professional Tax, TDS (either regime), Form 16, 24Q or ECR.
3. **CE cannot do the required SSO.** Vendor comparison table lists LDAP/SSO as
   "Removed (Legacy)" for Community. Keycloak OIDC is unsatisfiable.

## Consequences

- **Architecture inverts and simplifies.** Odoo becomes system of record for people, payroll and
  accounting. The separate payroll database is eliminated.
- The integration service no longer bridges Odoo⇄TimeTrex; it bridges **Odoo ⇄ Roster ⇄ AI**.
- `/payroll/hours` and `/payroll/hours/push` become in-Odoo orchestration at period lock instead
  of cross-service calls. `/sync/employees/{id}` no longer drives a second payroll system.
- F&F off-cycle payment runs on `hr_payslip_run` with an off-cycle structure.
- One payslip store, one F&F/payslip numbering domain, no double calculation, and a smaller PII
  surface (material for DPDP/Aadhaar/PAN obligations).
- Loses TimeTrex scheduling (3D builds its own CP-SAT solver) and job costing (out of scope).
- **Accepted cost:** we own the India statutory rules layer. This was unavoidable — no
  Community module provides it, and the brief's own "never hardcode statutory rates" rule
  required an owned effective-dated rules layer regardless.
- Deprioritised: scheduling and job costing from TimeTrex.
