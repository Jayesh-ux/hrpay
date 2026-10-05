# ADR-0003 — All Indian statutory payroll rules are bespoke, effective-dated, and sign-off gated

- **Status:** Proposed (Phase 0, awaiting sign-off)
- **Date:** 2026-10-05

## Context

Phase 1 requires PF, ESI, Professional Tax, TDS (old and new regime), Form 16, gratuity and LWF.
The working rules forbid hardcoding statutory rates, caps or slabs and require professional
sign-off before go-live.

Phase 0 established that **no Community module supplies any of this**: OCA/l10n-india has zero
addons at 15.0–19.0; Odoo's `l10n_in_hr_payroll` is Enterprise; TimeTrex has no India support.

## Decision

Build a dedicated rules subsystem in our own code, configured entirely from
effective-dated data. No statutory rate, cap, slab, ceiling or deadline appears as a literal in
code, XML, or seed files.

## Rationale

- The Labour Codes changed the *definition* of "wages" effective 2025-11-21, with a 50%
  anti-subterfuge add-back. This requires a per-employee, per-period classification and
  threshold test — no off-the-shelf module does this.
- Gratuity is now conditional on a service model that must handle fixed-term contracts
  (pro-rata after 1 year) — again bespoke.
- Deadlines are per-component (2 working days for wages on any exit; 30 days for gratuity;
  10/45 days for the re-skilling fund), not a single global F&F deadline.
- "Applicable law" resolves per State and ~26 of 36 States/UTs have not yet notified rules.

## Consequences

- Configuration model: `country → state → establishment → contract type → effective_from`,
  with a `source_reference`, `validated_by`, `validated_at` on every rule version.
- A rule version may not reach `active` without recorded professional sign-off.
  See `docs/compliance/statutory-config-register.md`.
- Each calculation snapshots the rule versions used, so historical payslips and F&F statements
  remain defensible after a State notifies new rules.
- A statutory-change watch process becomes a go-live prerequisite, tracking the six instrument
  classes that can change what binds.
- Realistically the highest-value and highest-risk logic in the platform. Budget and staff for
  it explicitly, and validate every row with a payroll specialist before go-live.
