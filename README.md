# Enterprise HR & Payroll Platform

Open-source, AI-native HR and payroll platform. Replicates the functional scope and workflows of
enterprise HRMS products. No proprietary branding, UI assets or content is copied.

## Status: backend written, Odoo never run — Gate 1A pending

Phase 0 was a validation spike. The code that followed it is written but has never
executed inside Odoo: the authoring host had no Docker, PostgreSQL or Odoo, so only
the 190 Odoo-free tests have ever run (14 solver, 45 TDS, 81 statutory, 50 F&F).
All 105 Odoo test functions, every view and the Docker stack are unexecuted.
Read [docs/HANDOFF.md](docs/HANDOFF.md) §3 before assuming anything works.

| Phase | Scope | Status |
|---|---|---|
| **0** | Validation spike + go/no-go | ✅ **Complete** — [report](docs/phase0/go-no-go.md) |
| **1A** | Payroll engine bake-off | 🟡 Next. Code written; **needs your machine**, the authoring host had no Docker |
| 1 | Core loop: schema, integration service, RBAC | ⛔ Blocked on Gate 1A + D6 |
| 2 | AI management layer | ⛔ Blocked |
| 3A | Full & final settlement engine | ⛔ Blocked |
| 3B | Tax-linked travel & expense engine | ⛔ Blocked |
| 3C | SLA-based enterprise helpdesk | ⛔ Blocked |
| 3D | Complex shift auto-rostering | ⛔ Blocked |
| 4 | Recruitment, bots, surveys, org chart, succession, UAE/US payroll | ⛔ Blocked |

## Quickstart

Ordered. Do not skip step 1 and trust a later step — `make test-standalone` is the
cheapest failure to diagnose. Full detail and expected failure modes are in
[docs/HANDOFF.md](docs/HANDOFF.md) §6.

Prerequisites: Docker with Compose v2, Git 2.25+, Python 3.12, and `make`.
On Windows, do this inside **WSL2 (Ubuntu)** — the Makefile is bash and
`make` is not installed by Git for Windows.

```bash
git clone https://github.com/Jayesh-ux/hrpay.git && cd hrpay

# 1. config + the tests that need no Docker at all (expect 190 passing)
make env               # creates .env — EDIT the passwords
make test-standalone

# 2. pinned dependencies, exact SHAs from versions/lock.txt
make oca && make pin

# 3. cross-reference addons and views (expect 0 errors / 105 authored tests)
make check-static

# 4. the real run: fresh DB, install six addons, run every test, write a report
make test-odoo
```

**Expect `make test-odoo` to fail.** The Docker entrypoint, the Odoo field and API
assumptions, and the 105 authored tests have never executed. Report the failure
honestly rather than working around it; `docs/test-runs/<timestamp>.md` has a
"Not covered by this run" section that must be answered, not left blank.

To run the UI instead of tests:

```bash
make up                # Odoo → http://localhost:8069
make install-addons    # install the six addons into the hrpay database
make down              # stop, keeping data
```

Statutory values are intentionally **absent**: all 50 catalog codes are unvalidated
skeletons, so PF/ESI/PT/gratuity/F&F calculations refuse to produce a number until
each is signed off. `docs/compliance/CA-SIGNOFF-REQUEST.md` must be sent to a
qualified professional by hand — nothing has been sent for you.

## Verdict: CONDITIONAL GO — approved 2026-10-05 (D1, D3, D5); D6 open

**Decisions signed off:** D1 drop TimeTrex · D2 pin Odoo 18.0 · D3 Invoicing-only accounting ·
D5 Gate 1A bake-off. **Still open:** D6 per-establishment legal basis (affects Phase 1 schema),
D4 goals/OKR (Phase 4, no schema impact).

The target stack is not buildable as specified:

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

| ID | Decision | Outcome |
|---|---|---|
| D1 | Drop TimeTrex; adopt `hr_payroll_community` in Odoo | ✅ approved |
| D2 | Accept Odoo 18.0 as the pinned version | ✅ accepted |
| D3 | Accounting scope on Community: accept Invoicing-only for Phase 1 | ✅ approved |
| D4 | Goals/OKR has no Community module — build custom in Phase 4, or drop | 🟡 open, low stakes |
| D5 | Run the payroll engine bake-off (Gate 1A) before committing | ✅ approved |
| D6 | Adopt per-establishment legal-basis resolution | 🟡 **open — blocks Phase 1 schema** |

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