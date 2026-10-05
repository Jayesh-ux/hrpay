# ADR-0009: OCA helpdesk dependency minimisation

- **Status:** Accepted, with an unmet requirement recorded
- **Date:** 2026-10-05
- **Supersedes:** part of ADR-0007 (the dependency table therein)
- **Related:** ADR-0001 (pin Odoo 18 Community), ADR-0002 (reject TimeTrex)

## Context

ADR-0007 chose OCA `helpdesk` as the ticket base and planned to extend it with
confidentiality groups, statutory deadline categories and AI triage fields. The
dependency list it proposed was:

```
helpdesk_mgmt, helpdesk_mgmt_sla, helpdesk_mgmt_type,
helpdesk_mgmt_rating, helpdesk_mgmt_team
```

Verifying those names against OCA/helpdesk at branch `18.0` on 2026-10-05 found
that two of them do not exist:

| ADR-0007 name | Present at 18.0? | Upstream name |
|---|---|---|
| `helpdesk_mgmt` | yes | `helpdesk_mgmt` |
| `helpdesk_mgmt_sla` | yes | `helpdesk_mgmt_sla` |
| `helpdesk_mgmt_type` | **no** | `helpdesk_type` |
| `helpdesk_mgmt_rating` | yes | `helpdesk_mgmt_rating` |
| `helpdesk_mgmt_team` | **no** | `helpdesk_motive` |

`hrms_helpdesk` therefore could not have installed. `models/ticket.py` inherits
`helpdesk.ticket.type`, which upstream now ships in `helpdesk_type`.

A second, independent problem: an earlier version of `ops/fetch_deps.sh` cloned
`OCA/payroll` for `hr_payroll_community` and `hr_payroll_account_community`.
Neither module exists in that repository — they live in `CybroOdoo/OpenHRMS`,
which `versions/pinned.env` already named as the real source. The clone
succeeded, so nothing warned, and the first install would have failed on a
missing dependency. Both repositories are now pinned by commit in
`versions/lock.txt`.

## Decision

Depend on exactly the two modules the code needs:

```
helpdesk_mgmt, helpdesk_type
```

`helpdesk_mgmt` supplies `helpdesk.ticket`; `helpdesk_type` supplies
`helpdesk.ticket.type`. These two names are the correct current ones at 18.0.

Rationale for dropping the other three:

- **Nothing reads them.** `hrms_helpdesk` contains four Python files and two XML
  views. Grepping for `sla`, `business_hours`, `rating`, `team_id` and `stage_id`
  finds no use of the SLA, business-hours or rating models. `stage_id` is a field
  of the base `helpdesk_mgmt` ticket model, not of a separate team module.
- **A dependency that is not used is a dependency that can break the install.**
  Each extra module is another upstream rename or version constraint that this
  project does not control and does not exercise.
- **The requirement is unmet, not met.** See Consequences.

## Consequences

### The original SLA requirement is not satisfied

ADR-0007 intended per-country business-hours calendars so a statutory deadline
would respect working days. `helpdesk_mgmt_sla` and `helpdesk_mgmt` provide that
machinery and **this project does not use it**. Concretely, as of this ADR:

- There is no business-hours calendar. `hrms_helpdesk` computes statutory
  deadlines from calendar days only.
- There are no SLA policies on ticket categories.
- There is no CSAT capability.

This is recorded here rather than left implicit, because dropping a dependency
makes an unmet requirement easy to mistake for a resolved one. The
`helpdesk_mgmt_sla` capability is still wanted; it is deferred, not rejected.
Deciding when to adopt it is a Gate 1B question, since it depends on the
deployment topology that the integration service review will settle.

The statutory deadline codes that would drive business-hours calculations
(`IN.GRIEVANCE.RESPONSE_DEADLINE_DAYS` and similar) are unaffected by this
decision — they are in `hrms_statutory` and are worked in calendar days
regardless.

### `helpdesk_motive` is not fetched either

It was briefly pinned "so the rename stays visible if upstream moves again". That
is a bad reason to carry a module, and it contradicted the rationale above: an
unused module is an upstream surface this project neither controls nor exercises.
It is now absent from `versions/lock.txt`. If a requirement ever needs it, add it
to the lock at that point, with a test behind it.

### Renames are a recurring hazard on this branch

Two separate dependency lists in this project were wrong in the same week, both
in ways that produced a silent success followed by a failed install. Every
repository is now pinned to an exact commit and every module version and licence
is read from the manifest at fetch time, so a mismatch is reported rather than
discovered during a payroll run.

## Alternatives considered

**Keep all five dependencies and fix the two names.** Rejected: it would keep
three modules the code never reads, each an untested upstream surface. If the
SLA work is picked up in Gate 1B, the dependency can be added back at that point
with a test behind it.

**Vendor the helpdesk addon.** Rejected: it would mean carrying a fork of
AGPL-3 code and taking on the merge burden for a requirement that is deferred.

**Build the ticket model on `mail.thread` directly.** Rejected: reimplements
stage management, portal access and chatter behaviour that OCA already provides
under AGPL-3.