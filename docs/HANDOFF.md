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

- 105 Odoo test functions exist. Zero have been executed.
- 190 standalone tests exist (14 solver + 45 TDS + 81 statutory + 50 F&F
  arithmetic). **These have been executed**, because they need no Odoo — see §4.
- Some basic Odoo screens **do** exist and have never been loaded: `hrms_fnf`
  (case list, form, line tree, filters), `hrms_payroll_run` (run list and form) and
  the roster/solver screens in `hrms_roster`. `hrms_core_ext` and `hrms_statutory`
  have **no views at all** — they are engine and model code. "No UI exists" is not
  true; "no UI has ever been rendered" is.
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
| `hrms_statutory` | 2772 | Effective-dated sign-off-gated rule engine, legal basis per establishment, wages composition, India PF/ESI/PT/LWF/TDS, gratuity, 50-code catalog + post-init seeder |
| `hrms_roster` | 2066 | Roster periods/shifts/assignments/demand, publish-first lifecycle, attendance validation, **staffing solver**, availability, security, UI |
| `hrms_fnf` | 1239 | Final settlement cases, itemised lines, leave encashment, gratuity, notice shortfall, recovery, frozen statements |
| `hrms_helpdesk` | 261 | Statutory ticket deadlines, confidentiality groups/rules, AI triage review fields |
| `hrms_payroll_run` | 934 | Payroll run lifecycle, coverage/integrity gates, checksums, SoD approval |

Also present:

- 9 ADRs (`docs/adr/`), including ADR-0008 on why the solver is a greedy
  heuristic and what would trigger a CP-SAT rewrite, and ADR-0009 on trimming the
  OCA helpdesk dependencies.
- Phase 0 go/no-go, statutory config register (all 50 codes keyed to the catalog),
  `versions/lock.txt` (exact upstream SHAs), and the CA sign-off request.
- Dev stack: `docker-compose.yml` (Odoo 18 CE + PostgreSQL 16), `ops/`.
- Static checkers: `tools/check_addons.py`, `tools/check_views.py`.

Everything in this document is true as of the commit it is read at; check
`git log --oneline -1` before trusting a step below.

Two commits matter. `75e7cc0` pinned the upstream dependencies by exact SHA, replaced
the TDS arithmetic with a tested pure module, and realigned the statutory register to
its catalog. The commit after it did the same for every other statutory calculation:
PF, ESI, Professional Tax, gratuity, leave accrual and encashment, notice shortfall
and settlement netting, each moved into a pure Python module with standalone tests and
a structural guard against the arithmetic returning inline. **§4a records every defect
that changed, with the number before and after.**

## 3. What is written but has not been run

Read this list before assuming anything works.

| Area | State |
|---|---|
| All 105 Odoo tests | authored, never executed |
| `post_init_hook` seeder | authored; the assertion that nothing resolves is untested in practice |
| Roster solver inside Odoo | logic verified standalone; ORM path untested |
| All views | cross-referenced against models statically; never rendered. Basic screens exist in `hrms_fnf`, `hrms_payroll_run` and `hrms_roster`; `hrms_core_ext` and `hrms_statutory` have none |
| Docker stack | never started; the image internals the entrypoint depends on are assumptions |
| `make test-odoo` end to end | never run |
| Encryption key rotation | implemented, never exercised |
| TDS projection and monthly split | rewritten, 45 standalone tests pass, **developer-derived expected values only**. The Odoo path (reading config off an employee, writing back YTD) is untested. See §5. |
| PF / ESI / PT / gratuity / F&F arithmetic | rewritten into four pure modules, **131 standalone tests pass**, expected values developer-derived. See §4a. The Odoo caller paths (config resolution, payslip queries, `create()` of the result records) are untested. |
| New config codes added 2026-10-05 | `IN.PF.EMPLOYER_RATE`, `IN.PF.EMPLOYER_EPS_RATE`, `IN.PF.EPS_MONTHLY_CAP` (renamed), `IN.PF.EPS_ANNUAL_CEILING`, `IN.ESI.CONTRIBUTION_SCHEDULE`, `IN.LEAVE.ACCRUAL_DAYS_PER_YEAR`, `IN.FNF.ENCASHMENT_WAGE_BASIS`. All skeletons, all unvalidated, six with no figure at all. |
| `hrms.employee.hrms_pf_eps_ytd` | **new field, no writer.** The annual EPS ceiling needs EPS contributed so far this financial year. Nothing populates it, so `compute_pf` passes `None` and **PF refuses to compute** rather than assume month one and let EPS run past the ceiling all year. The field's help says so. This is deliberate: the alternative is silent over-contribution for twelve months. |
| Statutory register alignment | all 50 codes now have a register row; values remain unvalidated |

The Docker entrypoint (`ops/odoo-entrypoint.sh`) deliberately derives the core
addons path from the installed Odoo package rather than hardcoding it, because
the correct value differs between Odoo releases and install methods. That
derivation has never been executed. If the first `make test-odoo` fails at
container start, that file is the first place to look.

## 4. What has actually been verified

Only two things, and they are worth separating clearly.

**Executed: 190 standalone tests (14 solver + 45 TDS + 81 statutory + 50 F&F).**
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

**Executed: 131 statutory and F&F arithmetic tests.**
`test_statutory_arithmetic_DEV.py` (81) imports the real production modules
`contribution_arithmetic.py` and `gratuity_arithmetic.py`.
`test_fnf_arithmetic_DEV.py` (50) imports `settlement_arithmetic.py`. Neither the
modules nor the tests import Odoo, so they run with plain Python on a host with no
database.

Six of those tests are **structural guards** rather than arithmetic checks, and they
are the reason this batch was safe to do without a database:

- `test_no_mirrored_copies` fails if `india.py` or `gratuity.py` stops importing the
  extracted module. Without it, a green suite would prove nothing about payroll,
  because the tests could be exercising a module payroll no longer runs.
- `test_inline_pf_and_esi_arithmetic_is_gone` scans live code (comments and docstrings
  stripped, so the fix descriptions do not trip it) for the exact expressions that
  were replaced.
- `test_leave_accrual_square_is_gone` fails if `months * months` returns.
- `test_dynamic_invented_config_codes_are_gone` fails if a config code is built at
  runtime, which is how accrual silently read as zero.
- `test_the_accrual_code_is_in_the_catalog` fails if a code the engine resolves is
  missing from `RULE_CATALOG`.
- `test_ctc_wage_basis_does_not_survive` fails if `hrms_ctc` reappears in any of the
  three callers.

Every expected number is ours, not a professional's. See §4a for what that buys.

**Executed: static cross-reference checks.** `make check-static` currently
reports 0 errors: every manifest data file exists, every XML reference resolves
to something declared or auto-generated, no addon references a module that loads
later, every ACL row is 8 columns and points at a real model, and every field
named in a view exists on the model it renders.

These checks have already earned their keep. They caught a genuine
install-time bug: `hrms_core_ext` declared an `ir.rule` on
`hrms_fnf.model_hrms_fnf_case`, but core loads before fnf, so that XML id does
not exist when the rule is created.

## 4a. Defects fixed in the arithmetic extraction, with before and after

Every number below is **ours**, not a professional's. They are what the code now does,
recorded so a reviewer can see the size of each change and argue with it.

Where a "before" is described rather than a figure, that is because the old code
returned a figure that was not obviously wrong — a zero, or a value with no error
anywhere. Those are the most dangerous kind.

### Provident fund

| Defect | Before | After |
|---|---|---|
| Employer's total PF rate | the same expression as the employee's, `base * (emp_rate / 100.0)`, so the employer rate was silently the employee's | separate required config `IN.PF.EMPLOYER_RATE`; the calculation **raises** if it is absent |
| Employer's EPS rate | followed the employee's | separate required config `IN.PF.EMPLOYER_EPS_RATE` |
| The EPS annual ceiling | **could not exist.** The code documented that capping EPS "requires a YTD figure" and then read a *monthly* amount from a code named `IN.PF.EPS_ANNUAL_CAP`. An employee who crossed the annual ceiling kept paying EPS for the rest of the financial year | `IN.PF.EPS_MONTHLY_CAP` (renamed) plus a new `IN.PF.EPS_ANNUAL_CEILING`, and `hrms_pf_eps_ytd` is **required** when the ceiling is configured. At ₹15,000 wages with a ₹15,000 ceiling: EPS **₹833.00 → ₹0.00** once reached, the total employee contribution stays **₹1,200.00** and becomes entirely EPF |
| Voluntary PF | the employer paid the employee's voluntary contribution whenever the config key was absent-and-truthy; `total_employer += voluntary` unconditionally | `counted_in_employee` and `counted_in_employer` are **required** keys. At ₹10,000 wages with 5% voluntary: employer **₹1,700.00 → ₹1,200.00** |
| Wage ceiling boundary | `min(wages, ceiling)` — right by luck, undocumented and untested | same bound, tested at below, exactly at, one rupee above and far above: at ₹15,000 exactly, not capped; at ₹15,000.01, basis **₹15,000** and contribution **₹1,800.00** |
| Negative wages | `min(abs(wages), ceiling)` with no test | tested: −₹20,000 contributes as ₹20,000 and caps at ₹15,000 |

### ESI

| Defect | Before | After |
|---|---|---|
| Contribution basis | a flat percentage of wages, unconditionally. A band *amount* was not representable at all, so the question could not be put to the code | the schedule carries its own `mode`; a `band_amount` schedule gives the band's own amount, and a percentage schedule must be marked `provisional` or the code refuses |
| Example at ₹6,000 wages | 0.75% of 6,000 = **₹45.00** employee, 3.25% = ₹195.00 employer | against a band schedule it is the band's fixed amount — our reading of the schedule is ₹21.00 employee, ₹175.00 employer. **This is the single most material change in the batch and it is unvalidated** (§4.1 of the CA request) |
| Coverage ceiling | `gross <= threshold`, so anything above the threshold produced two zeros and looked identical to a genuine exemption | `coverage_ceiling` must be explicit and the bands must reach it; above it the result says `above_coverage_ceiling: true` |
| Schedule shape | a bare list, so a missing table and a malformed table looked alike | a mapping with `mode`, `coverage_ceiling`, `bands`; gaps, overlaps, open-ended bands and a ceiling the bands do not reach all raise |

### Professional Tax

| Defect | Before | After |
|---|---|---|
| State with no PT table | returned `{"pt_employee": 0.0, ... "reason": "no PT configured for this state"}` and **no error** — a silent non-deduction | refused. A State that genuinely levies nothing must be configured with an explicit all-zero band, which then really does produce zero |
| Band edge | `amount <= hi` with nothing written down, so every band edge was undocumented behaviour | `boundary` is configuration (`inclusive` by default) and an unknown value raises. At ₹5,000: **₹0.00** inclusive, **₹175.00** exclusive |
| Annual cap | `if annual_cap and (ytd_pt + pt_employee) > annual_cap` — a configured cap of **zero** was treated as no cap at all, and the case where the cap was already reached before this month could not be reported | `annual_cap is not None`. Cap ₹2,500 with ₹2,400 already paid: **₹175.00 → ₹100.00**, noted. Already at the cap: **₹175.00 → ₹0.00**, noted "annual cap already reached" |
| Table with a gap | matched nothing and returned nothing useful | a gap, an overlap, a table not starting at zero, and a closed top band each raise |

### Gratuity

| Defect | Before | After |
|---|---|---|
| A remainder of exactly six months | **counted as a full year**, although the statute says *in excess of* six months. 5 years 6 months (66 months) paid as **6 years** | not counted by default: **66 months → 5.0 years**, with the note recording that the remainder does not exceed the threshold. `boundary: inclusive` gives 6.0 for anyone who reads it the other way, and it is a CA request item |
| Wage basis when no payslip exists | fell back to `hrms_ctc / 12` | refused. CTC includes employer PF, a gratuity accrual and insurance, none of which are wages, so the liability was overstated by construction |
| Wage basis from a payslip | `sum(l.total for l in slip.line_ids)` — **every** line, so employer contributions were added to the basis and employee deductions netted off it | gross earnings only, employer contributions excluded where the salary rule identifies them |
| Ceiling of zero | `if ceiling and amount > ceiling` — a ceiling of zero was treated as no ceiling | `ceiling is not None` |
| Notice pay versus recoverable shortfall | a negative shortfall was clamped to zero upstream | `notice_shortfall_days` returns the negative value so over-served notice reads as a payment to the employee, not a recovery |
| Fixed-term service end | a completed 12-month term could measure as 11 | `service_months(..., inclusive_end=True)`; 1 Jan–31 Dec is 12 months, and a leap 31 Jan–29 Feb is 2 |

### Leave accrual and encashment

| Defect | Before | After |
|---|---|---|
| Accrual | `round(months * months, 2)` after `months` had been rebound from the per-month accrual to the **count of service months**. **18 months of service gave 324 days of leave** — 12× too many, in the employee's favour, so it would have been paid without complaint | linear: accrual per month × months of service. 18 days a year over 18 months: **324.00 → 27.00 days** |
| Accrual source | `IN.LEAVE.ACCRUAL_DAYS.<leave type>` — **not a code in the catalog** — and the resulting `UserError` was swallowed into `0.0`, so every encashment was silently zero | `IN.LEAVE.ACCRUAL_DAYS_PER_YEAR`, keyed by leave type. A leave type with no configured accrual raises; an all-zero accrual still means zero and is distinguishable |
| Daily wage | `(hrms_ctc or monthly_wage) / 365.0` — CTC is not wages, and 365 is a year rather than the divisor of a month | last-drawn gross earnings ÷ the days in the month, with the basis and the averaging window from `IN.FNF.ENCASHMENT_WAGE_BASIS`. ₹30,000 over 28 days: **₹82.19 → ₹1,071.43** a day |
| Three-month average | `sum(l.total for l in s.line_ids)` over three slips, divided by the **day count of the exit month** — so the same employee was paid a daily rate 25% lower for a February exit than a March one | gross earnings per slip, averaged, divided by the days in the month the rate is used for |
| No payslips to average | fell back to contract wage ÷ days in month | refused |
| Excess leave | recovered on the *full* excess whenever a carry-forward cap existed, ignoring the cap: with a 30-day cap and 40 excess days it recovered all 40 | `recoverable_days = excess − carry_forward`: 40 excess days against a 30-day cap recovers **10 days**, and excess inside the cap recovers nothing and says so |
| Shortfall pricing | excess leave was priced from the contract wage while the encashment for the same leave type was priced from CTC/365 | both sides use the same daily rate |

### Notice shortfall and settlement netting

| Defect | Before | After |
|---|---|---|
| Recovery authority | correct — `permits_recovery` was already honoured | unchanged, but now recorded: `recovery_suppressed: true` with the reason, and `uncapped_amount` still reported so the shortfall is visible |
| Contractual recovery ceiling | not modelled, so a contract limiting recovery could not be applied | `hrms.fnf.case.notice_recovery_cap` caps the recovery and records both figures: 45 shortfall days at ₹2,000 = ₹90,000, capped at the contract → **₹30,000** |
| Unreadable statement | `except Exception: statement = {}` — a corrupted or half-written `statement_json` displayed a settlement of **₹0.00** with nothing wrong | raises. A settlement figure that cannot be read is not a zero figure |
| Deduction amounts | `sum(abs(l["amount"]))`, so a negative payable and a deduction netted off each other invisibly and a negative payable line read as a positive deduction | deductions must be positive magnitudes; a negative line is refused with the reason, so a shortfall cannot hide inside a payment |
| Negative settlement | `net_payable` could go negative with no separate figure, so "we owe the employee" and "the employee owes us" looked alike | `amount_payable` and `recovery_due` are separate fields, so the −₹25,000 case shows as zero payable and ₹25,000 due from the employee |

### What this batch did **not** do

- It did not touch TDS. The four TDS input fields still have no writer, and
  prior-employer income, declarations and regime choice are still uncaptured. TDS
  output is still not production-usable (§5 item 2).
- It did not add any UI, REST API or AI service. There is none to extend yet in
  `hrms_core_ext` or `hrms_statutory`, and the sequence stays: finish the Odoo
  screens, then the API, then AI chat, after Gate 1A.
- It did not make any of these numbers correct. Every "after" figure above is still
  unvalidated, and six of the seven config codes involved have no figure at all.
  They are questions in `docs/compliance/CA-SIGNOFF-REQUEST.md` §4.3 and §4.4.

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
2. **TDS runs on a fallback, not on payslip data.** `hrms_ytd_taxable`,
   `hrms_tds_ytd`, `hrms_current_month_pay` and
   `hrms_tds_scheduled_future_pay` have **no writer at all**. Income so far is
   derived from the contract wage and the joining date. Consequences, all of them
   invisible at runtime:
   - a bonus, arrears payment or reimbursement is not reflected;
   - a loss-of-pay month is counted as a full month of pay;
   - **prior-employer income is not captured at all.** An employee who worked
     elsewhere this financial year has their income under-stated for TDS
     purposes, and because their monthly deduction is too low, the shortfall is
     not collected later in the year either. This is the most dangerous item in
     this list.
   - **no declaration is captured**, so neither the employee's declared regime
     nor declared exemptions or losses reach the computation.

   **Treat TDS output as not production-usable** until the declaration, the
   regime choice and prior-employer income are captured and the write-back
   exists. The design for that is written up in
   `docs/compliance/TDS-INPUT-SPEC.md`; the write-back itself was deliberately
   **not** built on the authoring host, because it cannot be tested without Odoo
   and shipping untested payroll state changes is worse than shipping none.
3. **No F&F golden files exist.** `make golden` is a stub. Nothing has been
   compared against a payroll professional's hand calculation. The F&F arithmetic
   is entirely unvalidated against an authority.
4. **No statutory value is configured or validated.** By design — all 50 catalog
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

### Step 1 — dependencies (do this first)

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

**This has only ever been run against the network from the authoring host.** The
sparse-checkout and SHA-verification logic works there, but GitHub is not a
constant: if `make oca` fails here, check network and `git --version` (sparse
checkout needs git 2.25+) before assuming the lock is wrong. It fails loudly on a
version or licence mismatch, on a missing module, and on any Enterprise directory,
so a broken fetch will not silently produce a wrong payroll.

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
- **A statutory calculation with no configured input raises. It must never fall
  back to zero, to CTC, to the contract wage, or to the other party's rate.** Every
  number that used to be guessed is now an argument with a name, and the refusal
  message says which code to configure. If you add a calculation, it gets a pure
  module and a `_DEV` test file, and the callers import it — the structural guards
  in the two new test files exist to stop the arithmetic quietly moving back inline.
- **Extract arithmetic out of the model layer before you extract anything else.**
  A model method can only be tested with a database, and this host had none. Anything
  that stays in a model method stays untested, and everything found in this batch was
  found by reading untested code.
- **Do not run the API, integration service or AI service.** They are Phase 3/4
  and not built. `services/` contains scaffolding only. The order is: finish the
  Odoo screens, then the REST API, then AI chat — and all three come after the
  backend arithmetic has been validated against a CA's hand calculations (Gate 1A).