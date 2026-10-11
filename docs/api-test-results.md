# HRMS Payroll Suite — API Test Results

> Recorded 2026-10-09 against HEAD `8d44c5a`. Plan: `docs/api-test-plan.md`.
> Environment: Docker `hrpay-odoo` + `hrpay-postgres`, DB `hrpay`, Odoo 18.0 CE,
> PostgreSQL 16, server `18.0-20260926`, started 15:16 UTC.
>
> **Scope reminder:** these results show the code behaves as written and the access gates
> enforce. They are **not** a statutory validation — no India rate is configured, and no
> professional has signed off a calculation. See §6.

## 1. Summary

| Layer | Command | Result |
|---|---|---|
| L-A Pure arithmetic | `python3 tests/standalone/*.py` | **190/190 pass** |
| L-B Odoo integration | `ops/run_odoo_tests.sh --tests-only` | **105 tests, 0 failed, 0 errors** |
| Statutory gate | `ops/check_statutory_gate.py` | **GATE_HOLDING** |
| L-C Live XML-RPC smoke | `api_smoke.py` (read-only) | **19 pass, 12 access-denials-as-designed, 0 real faults** |

Report artefact: `docs/test-runs/20261009T151648Z.md` (+ `.log`).

---

## 2. Layer A — pure arithmetic (standalone)

Run: `python3 tests/standalone/*.py` inside WSL. No Odoo, no database.

```
test_solver_constraints.py            14/14 passed
test_tds_arithmetic_DEV.py            45/45 passed
test_statutory_arithmetic_DEV.py      81/81 passed
test_fnf_arithmetic_DEV.py            50/50 passed
-----------------------------------------------
total                                190/190 passed
```

Each suite prints the banner *"Developer-derived only. Not a substitute for a CA's hand
calculation."* Those vectors are the developer's own; they do not constitute statutory proof.

---

## 3. Layer B — Odoo integration suite

Run: `ops/run_odoo_tests.sh --tests-only` (reuses the existing DB; **no volume drop**, seeded
data preserved).

```
==> Running tests
  summary: 0 failed, 0 error(s) of 105 tests when loading database 'hrpay'

==> Verifying the statutory sign-off gate is still holding
statutory codes in catalog: 50
codes resolving to a value: 0
versions not in draft:      0
versions claiming a signer: 0
GATE_HOLDING
```

This is the same regression baseline recorded in `docs/HANDOFF.md` §1, re-confirmed after the
documentation-only changes in this session (no code changed since `8d44c5a`).

> **Unpinned-dependency caveat:** `docs/test-run-report-template.md` carries a boilerplate claim
> about unpinned dependencies. That claim is **stale** — dependencies are pinned in
> `versions/lock.txt` and the run confirms each is at its locked revision
> (`OpenHRMS -> 22456b9…`, `helpdesk -> 461aa27…`). Do not quote the template's gap line as fact.

---

## 4. Layer C — live XML-RPC smoke (read-only)

Run: `python3 api_smoke.py` against `http://localhost:8069`.

### 4a. Passed (19)

```
[pass] common.version :: 18.0-20260926
[pass] authenticate   :: uid=2
[pass] search_count hr.employee :: 1
[pass] search_count hrms.audit.log :: 0
[pass] search_count hrms.legal.basis :: 0
[pass] search_count hrms.gratuity.service.period :: 0
[pass] search_count hrms.gratuity.result :: 0
[pass] search_count hr.roster.period :: 0
[pass] search_count hr.roster.shift :: 0
[pass] search_count hr.roster.assignment :: 0
[pass] search_count hr.roster.demand :: 0
[pass] search_count hrms.roster.solver.setting :: 0
[pass] search_count hrms.roster.availability :: 0
[pass] search_count hrms.fnf.case :: 0
[pass] search_count helpdesk.ticket :: 0
[pass] search_count helpdesk.ticket.type :: 8
[pass] catalog.catalog_codes :: 50 codes
[pass] unauth rejected :: Fault
[pass] draft value refused :: Fault
```

Observations that match the seeded state recorded in `HANDOFF.md`:

- `hr.employee` = 1, `helpdesk.ticket.type` = 8 — matches the seed.
- `hrms.statutory.catalog.catalog_codes()` returns **50** codes over the wire.
- A bad-credential call is **rejected** (fault), and `hrms.statutory.rule.version.value()` on an
  empty recordset **raises** — the sign-off gate holds at the wire level too.

## 4. Access-denials that are *designed behaviour*, not faults

The built-in `admin` user (uid 2) is **not** a member of the HR Payroll / Statutory / Roster-Solver
groups, so `search_count` on the following models correctly returns `AccessError`. This is the ACL
model working; the operations themselves are exercised inside Odoo by the Layer-B suite running as
the appropriate roles.

```
payroll.period.lock            -> AccessError (needs HR Payroll/Payroll Admin)
integration.sync.log           -> AccessError (needs Payroll Admin / AI Service)
hrms.statutory.rule            -> AccessError (needs Payroll Admin / Statutory Config Admin)
hrms.statutory.rule.version    -> AccessError (needs Statutory Config Admin / Auditor)
hrms.india.statutory.result    -> AccessError (needs Payroll Admin / Auditor)
hrms.roster.solver.result      -> AccessError (needs Roster Solver: propose)
hrms.fnf.reason                -> AccessError (needs Payroll Admin / Auditor)
hrms.fnf.line                  -> AccessError (needs Payroll Admin / Auditor)
hrms.payroll.run               -> AccessError (needs Finance Approver / Payroll Admin)
hrms.statutory.catalog.coverage_report -> AccessError (reads gated version rows)
```

> To exercise these over RPC, authenticate as a user holding the relevant group (or add `admin`
> to the group first). This smoke uses the untouched seed on purpose so it stays read-only.

## 4c. Real finding from this layer

- **`hrms.wage.composition` is not a model.** The correct `_name` is **`hrms.wages.composition`**
  (`addons/hrms_statutory/models/wages.py`). This was corrected in `docs/api-inventory.md` §3.4 and
  the callable quick reference. No code defect — a documentation error.

---

## 5. Coverage gaps (not tested, tracked)

| Item | Why untested |
|---|---|
| `hr.attendance._compute_deviation` | Defect G10 — reads non-existent `shift_start_datetime`/`shift_end_datetime`; there is no passing test, and one should not be written until the field mismatch is resolved. |
| `hr.employee.action_view_pan/aadhaar` reveal audit | **Now covered** by `hrms_core_ext/tests/test_core_ext_security.py` (added later; was uncovered, which is why defect F-01 shipped). |
| `payroll.period.lock` release/reopen paths | Happy paths covered by Layer B; the two-person release authorisation is not exercised end-to-end over RPC. |
| AI enrichment (`action_ai_*`) | Defect G11 — no AI model/credential is configured; would fail if invoked. |
| Reports / PDF | Defect G12 — none exist. |
| Roster `unlock` | Intentionally always raises (roster lock is irreversible by design). |

---

## 6. What these results do NOT prove

1. **No statutory correctness.** Zero `hrms.statutory.rule.version` rows exist, so every engine
   path is exercised only against test fixtures. India PF/ESI/PT/LWF/TDS/gratuity figures are
   unvalidated until a CA signs off (`docs/compliance/CA-SIGNOFF-REQUEST.md`).
2. **No payroll amounts.** The payroll run refuses to compute without sign-off (by design); no
   end-to-end payroll figure has ever been produced.
3. **No UI/HTTP surface.** There are no controllers or web routes to test.
4. **Nothing is marked MANUALLY VERIFIED** — only the user may do that.
