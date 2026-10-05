# ADR-0007 — Build the helpdesk on OCA helpdesk_mgmt; extend rather than replace

- **Status:** Proposed (Phase 0, awaiting sign-off)
- **Date:** 2026-10-05

## Context

Odoo Enterprise Helpdesk is prohibited. The brief asks for SLA-based helpdesk with
business-hours calendars, escalation, pause, breach alerts, auto-assignment, confidentiality,
CSAT and AI triage.

## Decision

Base Phase 3C on `OCA/helpdesk` at branch 18.0 and build custom modules for the gaps.

## Rationale — verified available at 18.0

| Module | Version | Provides |
|---|---|---|
| `helpdesk_mgmt` | 18.0.1.18.0 | ticket core, teams, categories, portal |
| `helpdesk_mgmt_sla` | 18.0.2.1.0 | SLA policies; depends on `resource` → **per-country business-hours calendars** |
| `helpdesk_type` | 18.0.1.2.1 | ticket types |
| `helpdesk_type_sla` | 18.0.1.0.0 | **SLA per ticket type** → payroll/grievance/escape SLAs |
| `helpdesk_mgmt_rating` | 18.0.1.0.2 | **CSAT** |
| `helpdesk_portal_restriction` | 18.0.1.1.0 | portal scoping |
| `helpdesk_mgmt_merge` | 18.0.1.0.2 | duplicate merge |

Repository last commit 2026-10-01 — actively maintained.

## Consequences

Build on top:
- escalation matrix (L1 → L2 → HR head) — not provided
- SLA **pause** while awaiting employee — not provided
- breach alerting and SLA dashboards — not provided
- auto-assignment (round-robin, skill, load) — not provided
- reopen rules — not provided
- **confidential-ticket record rules** locking payroll/grievance tickets to the assigned team
- knowledge base ↔ AI deflection, with auto ticket creation on deflection failure
- AI triage and reply drafts only; never auto-resolve payroll or confidential tickets

Copyright note: OCA/helpdesk is AGPL-3. Compliance obligations are unchanged for internal
deployment, but network use and distribution require attention. Our own extensions should be
LGPL-3 to keep the combined work distributable.
