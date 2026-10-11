# HRMS Payroll Suite — API Test Plan

> Written 2026-10-09 against HEAD `8d44c5a`. Companion to `docs/api-inventory.md`.
> Results are recorded separately in `docs/api-test-results.md`.

## 1. Scope and approach

The suite exposes **no HTTP/REST controllers** (see `api-inventory.md` §0). Its API is the **Odoo
remote ORM protocol** (XML-RPC / JSON-RPC) plus the in-process ORM used by the app's own tests.
Therefore "API testing" here means three complementary layers:

| Layer | What it proves | Tool |
|---|---|---|
| **A. Pure arithmetic** | The extracted calculation modules (PF/ESI/PT, TDS, gratuity, F&F, solver) are numerically correct against developer-derived vectors. No Odoo. | `tests/standalone/*.py` |
| **B. In-app integration** | The models, security gates, state machines and method behaviour run correctly **inside Odoo**, including as different user roles (`with_user`). | `ops/run_odoo_tests.sh` (Odoo test runner) |
| **L. Live wire surface** | The actual XML-RPC endpoint at `localhost:8069` authenticates, enumerates models, enforces ACLs, exposes the seeded catalog, and rejects unauthorised calls. | `xmlrpc.client` script |

A green result here is a **narrow** claim: it proves the code behaves as written and the ACLs
enforce. It does **not** validate any statutory rate (none are configured), and it does not prove
correctness of payroll amounts (no professional sign-off). See §6 of the results file.

---

## 1. Test methods (what each pack exercises)

### T1 — Pure arithmetic suites (`tests/standalone`, no Odoo, no DB)
| File | Methods/behaviour | Prior green count |
|---|---|---|
| `test_solver_constraints.py` | mirror of the roster solver's hard constraints | 14 |
| `test_tds_arithmetic_DEV.py` | `tds_projection.*` (slabs, surcharge, cess, relief, rebate, split) | 45 |
| `test_statutory_arithmetic_DEV.py` | PF/ESI/PT (contribution_arithmetic) + gratuity arithmetic | 81 |
| `test_fnf_arithmetic_DEV.py` | `settlement_arithmetic.*` (net settlement, encashment, notice) | 50 |

### 2. Odoo integration suite (`hrms_*/tests/`)

Runs as a real Odoo DB install + `--test-enable`. Covers every module's models, state machines,
ACLs (`with_user`), computes and SQL constraints. 105 tests total (§ results).

### 3. XML-RPC API smoke (read-only)

Authenticates over the wire and exercises the externally documented surface without mutating data.

| # | Call | Model / method | Expectation |
|---|---|---|---|
| T1 | `common.version` | — | server version string |
| T2 | `common.authenticate` | — | non-zero uid |
| T3 | `search_count` | 24 HRMS models | 0/current count, or `AccessError` where the caller lacks the group |
| T4 | `catalog_codes` | `hrms.statutory.catalog` | 50 codes |
| T5 | `coverage_report` | `hrms.statutory.catalog` | report dict (or `AccessError` when it reads gated rows) |
| T6 | `search_read` | `hrms.statutory.rule` | rows, or `AccessError` |
| T7 | bad-credential `execute_kw` | `hrms.statutory.rule` | fault (rejected) |
| T8 | `value()` on empty recordset | `hrms.statutory.rule.version` | fault (sign-off enforced) |

**Note on access denials:** the built-in `admin` user is **not** a member of the HR Payroll groups,
so group-gated models correctly return `AccessError` over RPC. This is *expected* evidence of the
ACL model, not a defect; see results §3.

---

## 4. Method-coverage matrix (API method → test)

| Module | Method (API surface) | Covered by |
|---|---|---|
| core_ext | `hrms.audit.log.log` / append-only `write`,`unlink` | Odoo suite (`test_core_ext`) |
| core_ext | `hr.employee._hrms_reveal`, `action_view_pan/aadhaar`, `_hrms_set_enc` | Odoo suite |
| core_ext | `hr.employee.action_recompute_sync_hash` / `action_mark_synced` / `action_mark_failed` | Odoo suite |
| core_ext | `payroll.period.lock.action_start_review/lock/release/reopen`, `is_locked`, `assert_mutable` | Odoo suite |
| core_ext | `integration.sync.log.find_by_idempotency`, `action_dead_letter` | Odoo suite |
| core_ext | `hr.leave.action_validate` / `action_refuse` | Odoo suite |
| core_ext | `hr.attendance._compute_deviation` | **NOT COVERED — defect G10** (reads missing fields) |
| statutory | `hrms.statutory.rule.create`, `action_open_versions` | `test_statutory`, `test_seed` |
| statutory | `hrms.statutory.rule.version` sign-off (`create`,`write`,`value`) | `test_seed`, `test_statutory` |
| core_ext | `hrms.statutory.legal.basis.action_confirm`, `resolve` | Odoo suite |
| statutory | `hrms.wages.composition.compute` | Odoo suite (limited; needs `IN.GRATUITY.WAGE_BASIS_RULE`) |
| statutory | `india.engine.compute_pf/esi/pt/lwf/tds/all` | Odoo suite + standalone |
| statutory | `hrms.statutory.context._snapshot` / `resolve` / `get` | Odoo suite (`test_statutory`) |
| core_ext | `hrms.statutory.catalog.seed/catalog_codes/coverage_report` | Odoo suite `test_seed` + XML-RPC T4 |
| roster | `hr.roster.period.action_publish/lock/unlock` | Odoo suite |
| roster | `hr.roster.assignment.action_confirm` | Odoo suite |
| roster | `hr.roster.demand.total_for` | Odoo suite |
| roster | `hrms.roster.solver.solve` | Odoo suite (`test_solver`) + standalone |
| roster | `hrms.roster.solver.result.action_apply` | Odoo suite |
| fnf | `hrms.fnf.case.action_calculate/acknowledge/approve/mark_paid/raise_dispute` | Odoo suite + standalone |
| payroll_run | `hrms.payroll.run.action_compute/review/approve/lock/cancel` | Odoo suite |
| helpdesk | `helpdesk.ticket._compute_*`, `action_confidential`, `action_review_ai_triage` | Odoo suite (helpdesk) |

### Methods with **no dedicated test** (known gaps, not silently ignored)

- `hr.employee.action_view_pan` / `action_view_aadhaar` (audit-on-reveal path)
- `payroll.period.lock.action_release` / `action_reopen` (SoD + HR-manager gates)
- `helpdesk.ticket.action_reopen_with_note`
- `hrms.roster.solver.result` `action_apply` failure branches beyond the covered ones
- The external sync path (`integration.sync.log`) has no producer in-repo to test end-to-end.

These are recorded in the results as **not covered**, not as passing.

---

## 5. Negative / security tests

| Test | Expectation |
|---|---|
| Bad password over XML-RPC | Fault |
- Group-gated models over RPC as a non-member | `AccessError`
- `hrms.statutory.rule.version.value()` with no signed version | raises (`UserError`)
- Statutory gate: no catalog code resolves | `GATE_HOLDING` (ops/check_statutory_gate.py)
- Negative F&F settlement without recovery permission | `UserError` (Odoo suite)
- Superuser cannot approve a run / acknowledge AI triage | `UserError` (Odoo suite)

---

## 5. How to run

```bash
# standalone (no stack)
make test-standalone

# Odoo integration (non-destructive: reuses the existing DB)
./ops/run_odoo_tests.sh --tests-only

# full fresh-DB run (DESTROYS the volume — do not use on a data-bearing DB)
# ./ops/run_odoo_tests.sh

# on-the-wire smoke (read-only)
python3 /mnt/c/Users/hsing/AppData/Local/Temp/opencode/api_smoke.py
```

---

## 6. Exit criteria

1. Standalone suites: all pass.
2. Odoo suite: `0 failed, 0 error(s)`.
3. Statutory gate: `GATE_HOLDING`.
4. XML-RPC smoke: authentication succeeds; gated surfaces deny as designed; no unexpected faults.

Results: `docs/api-test-results.md`.

---

## 5b. Test data & isolation

- The **XML-RPC smoke is read-only** and leaves no rows behind.
- The **standalone suites** touch no database.
- The **Odoo suite** runs inside a transaction and rolls back; using `--tests-only` reuses the
  existing `hrpay` database and does **not** drop the volume, so the seeded data survives.
