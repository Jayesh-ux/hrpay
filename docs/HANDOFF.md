# HANDOFF

Written 2026-10-05 at the end of the authoring session on the development host.
Read this before touching the code, and read
[`docs/test-run-report-template.md`](test-run-report-template.md)'s "Not covered"
section before quoting any test result.

## 1. The single most important thing to know

**Nothing in this repository has ever been executed inside Odoo.** The
development host had no Docker, no PostgreSQL and no Odoo, and the project rule
is that runtime testing happens on the target laptop (Gate 1A). Every Odoo test
in this repo is *authored and statically checked, never run*.

What that means practically:

- 101 Odoo test functions exist. Zero have been executed.
- 14 standalone solver tests exist. **These have been executed**, because they
  need no Odoo — see §4.
- The static checkers (`make check-static`) prove internal consistency: manifests
  resolve, XML references exist, no addon references a module that loads later,
  and every field named in a view exists on the model. They say nothing about
  whether Odoo accepts the code.

So the first thing to do on the new machine is `make test-odoo`, and expect it
to find problems. That is the plan working, not the plan failing.

## 2. What is built

Six Odoo addons under `addons/`, in dependency order. This order is verified by
`tools/check_addons.py`, not asserted by hand.

| Addon | Lines | What it does |
|---|---|---|
| `hrms_core_ext` | 1398 | Employee statutory/separation fields, AES-GCM encryption, HMAC helpers, audit log, payroll period locking, leave/attendance/contract/department extensions, security groups |
| `hrms_statutory` | 2772 | Effective-dated sign-off-gated rule engine, legal basis per establishment, wages composition, India PF/ESI/PT/LWF/TDS, gratuity, 44-code catalog + post-init seeder |
| `hrms_roster` | 2066 | Roster periods/shifts/assignments/demand, publish-first lifecycle, attendance validation, **staffing solver**, availability, security, UI |
| `hrms_fnf` | 1239 | Final settlement cases, itemised lines, leave encashment, gratuity, notice shortfall, recovery, frozen statements |
| `hrms_helpdesk` | 261 | Statutory ticket deadlines, confidentiality groups/rules, AI triage review fields |
| `hrms_payroll_run` | 934 | Payroll run lifecycle, coverage/integrity gates, checksums, SoD approval |

Also present:

- 8 ADRs (`docs/adr/`), including ADR-0008 on why the solver is a greedy
  heuristic and what would trigger a CP-SAT rewrite.
- Phase 0 go/no-go, statutory config register, version manifest.
- Dev stack: `docker-compose.yml` (Odoo 18 CE + PostgreSQL 16), `ops/`.
- Static checkers: `tools/check_addons.py`, `tools/check_views.py`.

## 3. What is written but has not been run

Read this list before assuming anything works.

| Area | State |
|---|---|
| All 101 Odoo tests | authored, never executed |
| `post_init_hook` seeder | authored; the assertion that nothing resolves is untested in practice |
| Roster solver inside Odoo | logic verified standalone; ORM path untested |
| All views | cross-referenced against models statically; never rendered |
| Docker stack | never started; the image internals the entrypoint depends on are assumptions |
| `make test-odoo` end to end | never run |
| Encryption key rotation | implemented, never exercised |
| TDS annualisation / cumulative deduction | **written and never reviewed even by reading it closely.** See §5. |

The Docker entrypoint (`ops/odoo-entrypoint.sh`) deliberately derives the core
addons path from the installed Odoo package rather than hardcoding it, because
the correct value differs between Odoo releases and install methods. That
derivation has never been executed. If the first `make test-odoo` fails at
container start, that file is the first place to look.

## 4. What has actually been verified

Only two things, and they are worth separating clearly.

**Executed: 14 standalone solver tests.**
`python3 tests/standalone/test_solver_constraints.py` (or `make test-standalone`)
runs with no dependencies. It re-implements the solver's constraint arithmetic
with plain dataclasses and checks it. It found two real problems:

1. A 16-hour default `rest_after_hours` on a 09:00–18:00 shift made consecutive
   day shifts impossible (the next start would have to be 10:00 or later), and it
   failed *silently* by just producing a short roster. Default is now 12.
2. The contractual weekly hour ceiling binds before the weekly day cap: 5 × 8.5h
   = 42.5h, and a 6th day would reach 51h against a 48h ceiling. Knowing which
   limit actually binds is what a manager needs to see in the unfilled list.

This file is a **mirror** of `solver.py`, not the implementation, so it can
drift. `test_mirror_is_in_sync_with_the_odoo_solver` parses `solver.py` and
fails if a default, a blocking reason or a constraint disappears. That guard was
tested by deliberately changing a default and watching it fail. If you change
the solver, run this suite.

**Executed: static cross-reference checks.** `make check-static` currently
reports 0 errors: every manifest data file exists, every XML reference resolves
to something declared or auto-generated, no addon references a module that loads
later, every ACL row is 8 columns and points at a real model, and every field
named in a view exists on the model it renders.

These checks have already earned their keep. They caught a genuine
install-time bug: `hrms_core_ext` declared an `ir.rule` on
`hrms_fnf.model_hrms_fnf_case`, but core loads before fnf, so that XML id does
not exist when the rule is created.

## 5. Open bugs and known gaps

Ordered by how much they should worry you.

### Blocking

1. **TDS annualisation and cumulative deduction has never been reviewed.** The
   code exists in `addons/hrms_statutory/models/india.py`. Correct cumulative
   TDS across a year is the single most error-prone thing in this codebase, and
   it was written and never re-read. Treat as unverified code.
2. **No F&F golden files exist.** `make golden` is a stub. Nothing has been
   compared against a payroll professional's hand calculation. The F&F arithmetic
   is entirely unvalidated against an authority.
3. **No statutory value is configured or validated.** By design — all 44 catalog
   codes are skeletons. No payroll can actually be processed. This is correct
   behaviour, not a bug, but it means "the platform computes payroll" is not yet a
   true statement.
4. **The roster solver does not enforce statutory overtime caps.** Its limits
   come from `hrms.roster.solver.setting`, which a manager fills in. If a
   statutory limit is stricter, the payroll-time statutory engine is what catches
   it, not the solver. Documented in ADR-0008; not yet fixed.

### Non-blocking but known

5. The solver is greedy and does not backtrack, so it can decline an assignment
   a different arrangement would have allowed (ADR-0008).
6. `hrms_helpdesk` is the thinnest addon (261 lines) and the least reviewed.
7. `addons/hrms_api/` and `addons/hrms_expense/` exist on disk as empty
   placeholder directories. They are untracked by git and contain nothing. The
   old Makefile referenced them by name, which is why they are mentioned here.
8. `ops/compliance_report.py` is not written, so `make compliance-report` and
   `make compliance-block` fail loudly. The interim gate is
   `ops/check_statutory_gate.py`, run by `make test-odoo`.
9. Several Makefile targets are deliberate loud failures (`test-e2e`,
   `test-load`, `golden`, `scan`, `zap-scan`, `k8s-build`, `dr-drill`, `backup`,
   `compliance-report`, `compliance-block`). They are unimplemented, not broken.
10. OCA dependencies are fetched at the `18.0` branch, not pinned by SHA.
    `ops/fetch_deps.sh` writes `.oca/*.sha` and `make pin` collects them into
    `versions/lock.txt`, but **`versions/lock.txt` does not exist yet**. Until it
    does, a test failure upstream is not reproducible.
11. D6 — per-establishment legal basis — is formally unapproved. The
    implementation exists; the approval does not.

## 6. First steps on the new machine

Ordered. Do not skip step 2 and trust a later step.

### Step 0 — prerequisites

- Docker with Compose v2 (`docker compose version`).
- Python 3.12 available for the standalone tests. No other Python deps.
- Free disk: PostgreSQL volume, Odoo filestore, and the Odoo image.

```bash
git clone <this repo> && cd hrpay
make env          # creates .env from .env.example — EDIT the passwords
make test-standalone
```

`make test-standalone` should print 14 passing tests and needs no Docker. If it
does not, the repository is broken before Odoo is even involved, and that is the
cheapest possible failure to diagnose.

### Step 1 — dependencies

```bash
make oca
```

Clones OCA/payroll and OCA/helpdesk at `18.0` into `.oca/`. It fails if any
expected module directory is missing (catching an upstream rename) and it
**refuses to continue if any Odoo Enterprise module directory is present**.
Record the SHAs:

```bash
make pin          # writes versions/lock.txt — commit this
```

### Step 2 — static checks

```bash
make check-static
```

Expect `0 error(s)` and `0 view field error(s)`. If these fail, the working tree
is broken; fix it before spending time on Docker.

### Step 3 — the first real run

```bash
make test-odoo
```

This is the one command that does everything: fetches deps, starts the stack on
a fresh database, installs all six addons in dependency order, runs the tests,
verifies the statutory sign-off gate is still holding, and writes a report to
`docs/test-runs/<timestamp>.md` with the log beside it.

Expect this to fail. The most likely first failures, in order of probability:

1. Container start: the entrypoint cannot locate the core addons directory.
2. Install: an Odoo 18 field or API differs from what the code assumes.
3. Install: an OCA module name or dependency differs from `versions/pinned.env`.
4. Tests: assertions that encode a wrong assumption about Odoo behaviour.

Useful while debugging:

```bash
docker compose logs -f odoo
docker compose exec odoo odoo shell -d hrpay
./ops/run_odoo_tests.sh --tests-only     # re-run tests without reinstalling
./ops/run_odoo_tests.sh --addon hrms_roster   # narrow it down
```

### Step 4 — report honestly

Fill in `docs/test-runs/<timestamp>.md`. The template has a "Not covered by this
run" section that must be answered, not left blank — a blank there is
indistinguishable from a pass. It also refuses to render if placeholders are
unfilled.

Then update this file: §3 and §5 are only true if you update them.

## 7. Working rules that are not obvious from the code

- **Never hardcode a statutory rate, cap, slab or deadline.** Values require an
  effective-dated version signed off by a named professional, and the author of a
  row cannot be its validator. The `post_init_hook` asserts that no catalog code
  resolves to a usable value and fails the install if one does.
- **No Enterprise code, ever.** `ops/fetch_deps.sh` and the static checks both
  look for it.
- **Segregation of duties is enforced in the model layer**, not in views: nobody
  signs off their own leave, their own statutory value, or their own payroll.
- **Published rosters are immutable.** Checksums on assignments and periods are
  recomputed on validation; payroll refuses to consume a mismatch.
- **A shortfall the manager can explain beats an optimal schedule that cannot
  be.** The solver refuses to double-book to close a gap, and a proposal with
  unfilled demand cannot be applied at all.
- **Comment the *why*, never the *what*.** Several comments record a rejected
  approach and the reason; do not delete them because the code "looks obvious".
  The 16-hour rest-window default is commented because it failed silently and
  nobody would otherwise know it was ever wrong.
- **Do not run the API, integration service or AI service.** They are Phase 3/4
  and not built. `services/` contains scaffolding only.