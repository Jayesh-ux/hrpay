# Enterprise HR & Payroll Platform

Open-source, AI-native HR and payroll platform. Replicates the functional scope and workflows of
enterprise HRMS products. No proprietary branding, UI assets or content is copied.

## Status: Phase 0 complete — awaiting sign-off

No platform code has been written. Phase 0 was a validation spike.

| Phase | Scope | Status |
|---|---|---|
| **0** | Validation spike + go/no-go | ✅ **Complete** — [report](docs/phase0/go-no-go.md) |
| 1 | Core loop: schema, integration service, RBAC | ⛔ Blocked pending 6 decisions |
| 2 | AI management layer | ⛔ Blocked |
| 3A | Full & final settlement engine | ⛔ Blocked |
| 3B | Tax-linked travel & expense engine | ⛔ Blocked |
| 3C | SLA-based enterprise helpdesk | ⛔ Blocked |
| 3D | Complex shift auto-rostering | ⛔ Blocked |
| 4 | Recruitment, bots, surveys, org chart, succession, UAE/US payroll | ⛔ Blocked |

## Verdict: CONDITIONAL GO — the target stack is not buildable as specified

Phase 0 changed the architecture in three ways:

1. **TimeTrex is out.** Community Edition is sunset and unobtainable (download returns HTTP 403;
   the GitHub repo is a 2018 stub with no code). Its tax engine is US/Canada only with zero
   India support, and CE removed LDAP/SSO so Keycloak cannot integrate. Replaced by the LGPL-3
   engine `hr_payroll_community` in Odoo, with all Indian statutory logic built by us.
2. **Odoo Community has no full accounting.** `account_accountant` is Enterprise. Payroll and
   expense journals post fine against Invoicing, but GL close and reconciliation do not.
3. **The F&F deadline assumption was wrong.** India's Labour Codes require **all wages to be paid
   within 2 working days of the last working day, for every exit type including voluntary
   resignation.** Deadlines are per-component, not one global deadline.

Also established: the **new statutory definition of "wages"** (effective 2025-11-21, with a 50%
anti-subterfuge add-back) now drives PF, ESI and gratuity, and applicable law resolves **per
State** — only ~10 of 36 States/UTs have notified their rules.

## Architecture

```
                    ┌─────────────────────────────┐
   users ──OIDC──► │  Keycloak                   │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
      ┌──────────────┐  ┌──────────────┐  ┌────────────┐
      │  Odoo CE 18  │  │    Roster    │  │  AI layer  │
      │  (records:   │◄─┤   solver     │  │  (RAG, OCR)│
      │   people,    │  │  OR-Tools    │  │            │
      │   payroll,   │  │  CP-SAT      │  │            │
      │   expenses)  │  └──────────────┘  └────────────┘
      └──────┬───────┘
             │  reads/writes via RBAC-checked APIs, as the logged-in user
      ┌──────▼───────────────────────────────────────┐
      │  Integration service: FastAPI + RabbitMQ     │
      │  + Redis, HMAC-signed webhooks, DLQ,         │
      │  nightly reconciliation, audit logging       │
      └──────────────────────────────────────────────┘
```

**Ownership:** Odoo owns people data, workflows and the payroll record. The rules engine
(ours) owns pay calculation. The AI layer is strictly read-only on payroll and acts only as the
logged-in user through RBAC-checked APIs, with explicit confirmation for actions.

**Country-pluggable, effective-dated** by design: India first (PF, ESI, PT, TDS both regimes,
Form 16, gratuity, LWF), then UAE (WPS, EOSB), then US (federal/state).

## Non-negotiable engineering rules

- **Never hardcode a statutory rate, cap, slab or deadline.** All live as effective-dated
  configuration with a source reference, and require sign-off by a qualified payroll/tax
  professional before go-live. Register: [statutory-config-register.md](docs/compliance/statutory-config-register.md)
- **No Odoo Enterprise code.** `ent_*` Open HRMS modules and Enterprise-only addons are excluded.
  See [versions/pinned.env](versions/pinned.env).
- **Segregation of duties.** No one approves their own leave, claim, ticket or F&F. Maker-checker
  on F&F release and high-value expenses.
- **Payroll data is read-only to the AI layer.** Every query and action is logged.
- Tests with every module; an ADR for every major decision; a README per service.

## Decisions pending sign-off

| ID | Decision |
|---|---|
| D1 | Drop TimeTrex; adopt `hr_payroll_community` in Odoo |
| D2 | Accept Odoo 18.0 as the pinned version |
| D3 | Accounting scope on Community: accept Invoicing-only for Phase 1 |
| D4 | Goals/OKR has no Community module — build custom in Phase 4, or drop |
| D5 | Run the payroll engine bake-off (Gate 1A) before committing |
| D6 | Adopt per-establishment legal-basis resolution |

## Architecture decision records

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-pin-odoo-18-community.md) | Pin Odoo 18.0 Community Edition |
| [0002](docs/adr/0002-reject-timetrex.md) | Reject TimeTrex; adopt LGPL payroll engine in Odoo |
| [0003](docs/adr/0003-statutory-rules-are-bespoke.md) | Statutory rules are bespoke, effective-dated, sign-off gated |
| [0004](docs/adr/0004-accounting-scope-on-community.md) | Constrain accounting scope on Community |
| [0005](docs/adr/0005-legal-basis-resolves-per-establishment.md) | Applicable law resolves per establishment |
| [0006](docs/adr/0006-immutable-versioned-calculations.md) | Every calculation is immutable and versioned |
| [0007](docs/adr/0007-helpdesk-on-oca-with-custom-extensions.md) | Helpdesk on OCA helpdesk_mgmt; extend |

## Licensing

Odoo Community (LGPL-3) · Open HRMS (`hr_payroll_community`, `hr_resignation`,
`hr_employee_shift`, `ohrms_core` LGPL-3; `oh_appraisal` AGPL-3) · OCA/helpdesk (AGPL-3).
Our extensions: LGPL-3. Enterprise addons excluded by policy.

## Phase 0 evidence

Every claim in the go/no-go report was verified directly against upstream git, PyPI or the
vendor's own documentation on 2026-10-05 rather than inferred from marketing pages. See the
[evidence log](docs/phase0/go-no-go.md#appendix--evidence-log-verified-2026-10-05).