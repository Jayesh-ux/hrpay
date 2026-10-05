# ADR-0006 — Every payroll and F&F calculation is an immutable, versioned record

- **Status:** ✅ **Accepted** (Phase 0 sign-off, 2026-10-05) — required by the brief; no standalone signature required
- **Date:** 2026-10-05

## Context

The brief requires that "every calculation is an immutable, versioned record. Recalculation
creates a new version," and requires retro-edit behaviour after period lock to be tested. The
Labour Codes make this mandatory rather than optional: a State may notify new rules that
invalidate a prior interpretation.

## Decision

Persist every calculation as an append-only versioned record capturing: inputs, the exact
statutory rule versions applied, the resolved legal basis, and the computed result. Recalculation
appends a new version and never mutates a prior one.

## Rationale

- Period locking, two parallel cycles matching to the paisa, payroll reruns after retro edits,
  and F&F recalculation versioning all depend on immutability.
- Audit and defensibility: a payslip issued in 2026 must remain reproducible after a State
  notifies a rule in 2027.
- Immutable records make the reconciliation and golden-file test strategy tractable — a test
  asserts on a stored version, not on a recomputation.

## Consequences

- `payroll_period_lock` gates mutation of any input feeding a locked period; retro edits against
  a locked period must be rejected or routed to an off-cycle adjustment.
- `fnf_calculation_version` follows the same pattern: append-only, with a reason code for each
  new version.
- Storage grows. Retention and archival policy required for payslips under Indian labour and
  tax-record retention expectations — confirm with counsel.
- Deterministic replay becomes testable: golden files assert on stored versions.
