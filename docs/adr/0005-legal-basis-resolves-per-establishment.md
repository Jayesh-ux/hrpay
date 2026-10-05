# ADR-0005 — Applicable law resolves per establishment, not globally

- **Status:** 🟡 Proposed — Decision D6 still OPEN, not yet signed off
- **Date:** 2026-10-05

## Context

India's four Labour Codes came into force nationally on 2025-11-21 and the final Central Rules
were notified 2026-05-08. But labour is a Concurrent List subject: as of 2026-10-01 only about
10 of 36 States/UTs have notified their own rules, and the largest industrial and GCC clusters
(Karnataka, Tamil Nadu, Maharashtra, Telangana, Haryana, Punjab) have not, more than ten months
in. Where a State has not notified, pre-Codes rules continue insofar as they are not
inconsistent with the Codes.

## Decision

Model the applicable legal basis as a first-class, per-establishment, per-component,
effective-dated configuration object. Never assume national uniformity.

## Rationale

- Commencement is national; rules are not. A single global "India" ruleset would be wrong for
  the majority of States today and would silently become wrong as States notify.
- State Shops & Establishment Acts diverge materially from the Codes on leave carry-forward
  (30 days under the Codes versus 45 in Maharashtra) and on casual-leave lapse.
- F&F outcomes, gratuity entitlement and payroll cost differ by establishment and change over
  time. Without this model, recomputation and audit trails are indefensible.

## Consequences

- Add a legal-basis resolution chain to the Phase 1 schema:
  `country → state → establishment → contract type → effective_from`.
- The resolved legal basis is snapshotted into each immutable calculation version.
- Every F&F component carries the legal basis that produced it.
- A statutory-change watch process is a go-live prerequisite, monitoring the six instrument
  classes that can change what binds.
- Requires the payroll specialist to map establishments to their correct State rules as they are
  notified — an ongoing operational commitment, not a one-off.
