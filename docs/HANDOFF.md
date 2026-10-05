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
- 59 standalone tests exist (14 solver + 45 TDS arithmetic). **These have been
  executed**, because they need no Odoo — see §4.
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

- 9 ADRs (`docs/adr/`), including ADR-0008 on why the solver is a greedy
  heuristic and what would trigger a CP-SAT rewrite, and ADR-0009 on trimming the
  OCA helpdesk dependencies.
- Phase 0 go/no-go, statutory config register (all 44 codes keyed to the catalog),
  `versions/lock.txt` (exact upstream SHAs), and the CA sign-off request.
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
| TDS projection and monthly split | rewritten, 45 standalone tests pass, **developer-derived expected values only**. The Odoo path (reading config off an employee, writing back YTD) is untested. See §5. |
| Statutory register alignment | all 44 codes now have a register row; values remain unvalidated |

The Docker entrypoint (`ops/odoo-entrypoint.sh`) deliberately derives the core
addons path from the installed Odoo package rather than hardcoding it, because
the correct value differs between Odoo releases and install methods. That
derivation has never been executed. If the first `make test-odoo` fails at
container start, that file is the first place to look.

## 4. What has actually been verified

Only two things, and they are worth separating clearly.

**Executed: 59 standalone tests (14 solver + 45 TDS).**
`make test-standalone` runs both files with no dependencies. It re-implements the solver's constraint arithmetic
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

**Executed: 45 TDS arithmetic tests.**
`python3 tests/standalone/test_tds_arithmetic_DEV.py` imports the real production
module `addons/hrms_statutory/models/tds_projection.py` — not a copy — and walks
whole financial years month by month for both regimes: mid-year joiners, salary
revisions, bonuses, month 1/6/12 positions, surcharge, cess, rebate and relief. A
structural guard fails if anyone reintroduces a multiplication of income-so-far by
anything but 1, which is the original annualisation defect; that guard was verified
by injecting `income_to_date * 12` and watching the suite go red.

These tests are **developer-derived**. They prove the code matches our reading of
the rules. They do not prove the reading is right.

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

1. **TDS slab tables, relief and rebate are unvalidated.** The projection
   arithmetic is now separated into `tds_projection.py`, tested by 45 standalone
   tests, and the two defects it shipped with (annualising YTD income by ×12, and
   a dividing-then-multiplying step that cancelled and withheld the whole year's
   tax in month 1) are fixed and guarded against. **Every expected number in the
   tests is our own reading of the rules.** Marginal relief's cap rate, whether
   relief is recomputed, and the order of relief versus rebate are all unresolved.
   See `docs/compliance/CA-SIGNOFF-REQUEST.md` §3.2.
2. **The TDS inputs are not written by anything.** `hrms_ytd_taxable`,
   `hrms_tds_ytd`, `hrms_current_month_pay` and
   `hrms_tds_scheduled_future_pay` have no writer yet, so payroll falls back to
   the contract wage and the joining date. That fallback is now joining-date aware
   (a mid-year joiner is not credited with months they were not here), but the
   write-back that should own these figures is not built.
3. **No F&F golden files exist.** `make golden` is a stub. Nothing has been
   compared against a payroll professional's hand calculation. The F&F arithmetic
   is entirely unvalidated against an authority.
4. **No statutory value is configured or validated.** By design — all 44 catalog
   codes are skeletons. No payroll can actually be processed. This is correct
   behaviour, not a bug, but it means "the platform computes payroll" is not yet a
   true statement.
5. **The roster solver does not enforce statutory overtime caps.** Its limits
   come from `hrms.roster.solver.setting`, which a manager fills in. If a
   statutory limit is stricter, the payroll-time statutory engine is what catches
   it, not the solver. Documented in ADR-0008; not yet fixed.

### Non-blocking but known

6. The solver is greedy and does not backtrack, so it can decline an assignment
   a different arrangement would have allowed (ADR-0008).
7. `hrms_helpdesk` is the thinnest addon (261 lines) and the least reviewed.
8. `addons/hrms_api/` and `addons/hrms_expense/` exist on disk as empty
   placeholder directories. They are untracked by git and contain nothing. The
   old Makefile referenced them by name, which is why they are mentioned here.
9. `ops/compliance_report.py` is not written, so `make compliance-report` and
   `make compliance-block` fail loudly. The interim gate is
   `ops/check_statutory_gate.py`, run by `make test-odoo`.
10. Several Makefile targets are deliberate loud failures (`test-e2e`,
   `test-load`, `golden`, `scan`, `zap-scan`, `k8s-build`, `dr-drill`, `backup`,
   `compliance-report`, `compliance-block`). They are unimplemented, not broken.
11. Dependencies are now pinned by exact SHA in `versions/lock.txt` and verified
    on every fetch, so this one is *closed* — see §6 Step 1. Note the two
    corrections: payroll modules come from **CybroOdoo/OpenHRMS**, not
    OCA/payroll, and OCA/helpdesk 18.0 uses **`helpdesk_type`** for
    `helpdesk.ticket.type`. The earlier manifest depended on
    `helpdesk_mgmt_type`, which does not exist on that branch.
12. **OpenHRMS ships an Enterprise module on the same branch.** `ent_uae_wps_report`
    (OPL-1) sits next to the LGPL payroll modules. `fetch_deps.sh` uses a sparse
    checkout limited to the locked module directories, so it is never fetched. If
    anyone widens that sparse set, the script stops on it.
13. D6 — per-establishment legal basis — is formally unapproved. The
    implementation exists; the approval does not.
14. The CA request is drafted (`docs/compliance/CA-SIGNOFF-REQUEST.md`) but **has
    not been sent**. Nothing statutory can be configured until it comes back.

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

`make test-standalone` should print 14 and 45 passing tests and needs no Docker. If
it does not, the repository is broken before Odoo is even involved, and that is the
cheapest possible failure to diagnose.

### Step 1 — dependencies

```bash
make oca
```

Clones **CybroOdoo/OpenHRMS** and **OCA/helpdesk** into `.oca/`, each checked out at
the exact SHA in `versions/lock.txt` — not the branch head. It fails if a module
directory is missing (catching an upstream rename), if a module's version or
licence differs from the lock, or if any Odoo Enterprise module is present.

```bash
make pin          # re-verifies every pin and prints the module inventory
```

`make pin` deliberately does **not** rewrite `versions/lock.txt`. A lock the build
regenerates is not a lock: it would let an upstream change enter a commit
unreviewed. To move a pin, edit the file by hand, run `make pin`, and review the
diff.

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
3. Install: a dependency of an OCA module we pin differs on this machine (the
   pins are verified at fetch time, but transitive dependencies are not pinned).
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