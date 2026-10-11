# Phase Four Handover — Manual Verification Gate

> Produced 2026-10-09 · HEAD `8d44c5a` · **Gate WAIVED by the user** ("fix defects + start UI"), so
> defects F-01/F-02/F-03 were fixed and Phase Five UI work was carried out. See the update at the
> bottom. The original gate statement is kept for the record.

## 1. What this engagement delivered

Audit, documentation, and — after the user waived the gate — targeted fixes and UI. Originally the
engagement was audit/docs only. Three defects were then fixed in code (F-01, F-02, F-03) and views
were added for the two addons that had none; see §7 for exactly what changed.

| Artefact | What it is |
|---|---|
| `docs/application-flow.md` | How the app works: stack, module map, per-workflow diagrams, clickable happy path, known-gaps table |
| `docs/api-inventory.md` | Every callable ORM/RPC method with `file:line`; confirms there are **no HTTP controllers** |
| `docs/api-test-plan.md` | The three-layer test approach and the method→test coverage matrix |
| `docs/api-test-results.md` | Real captured results of the suites that were actually run |
| `docs/manual-uat-stories.md` | 16 click/shell stories for **you** to verify; only you may mark them verified |
| `docs/requirement-traceability.md` | Requirement → implementation → evidence → status matrix (13 done, 13 partial, 5 not started) |

One documentation bug was found and fixed while testing: the wage-composition model is
`hrms.wages.composition` (was written `hrms.wage.composition` in the inventory).

## 2. Test evidence from this session (fresh)

| Layer | Command | Result |
|---|---|---|
| Pure arithmetic | `python3 tests/standalone/*.py` | **190/190 pass** (14 solver, 45 TDS, 81 statutory, 50 F&F) |
| Odoo integration | `ops/run_odoo_tests.sh --tests-only` | **114 tests, 0 failed, 0 errors** (was 105; +9 regression tests for the fixes/UI) |
| Statutory gate | `ops/check_statutory_gate.py` | **GATE_HOLDING** (50 codes, 0 resolve) |
| Live XML-RPC smoke | `api_smoke.py` (read-only) | auth OK; 24 models probed; gated models **correctly deny**; 0 real faults |

Report: `docs/test-runs/20261009T151648Z.md` (`.log` beside it).

**What this does not prove:** that any payroll amount or statutory rate is *correct*. All 50 catalog
codes are unvalidated skeletons, so the engines refuse to compute. That is the designed safe state,
not a defect. No CA/statutory sign-off has occurred.

## 3. Exact steps for you

```bash
# from the repo root in WSL (Ubuntu)
make up                      # start Odoo + PostgreSQL (http://localhost:8069, admin/admin)

# reproduce the automated evidence
make test-standalone         # expect 190 passing
./ops/run_odoo_tests.sh --tests-only   # expect 105 tests, 0 failed, 0 errors, GATE_HOLDING

# the on-the-wire smoke (read-only)
python3 /mnt/c/Users/hsing/AppData/Local/Temp/opencode/api_smoke.py

# manual click-through
#   open docs/manual-uat-stories.md and work the stories in order
```

To see the payroll menus you must add your user to the groups in
`manual-uat-stories.md` §0 step 2.

> **Do not run `make test-odoo` without `--tests-only`** on this machine: the plain form drops the
> database volume (`docker compose down -v`) and would erase the seeded database. Use
> `./ops/run_odoo_tests.sh --tests-only` to preserve data.

## 4. The approval gate — WAIVED

The delivery brief forbids any UI modernization (Phase Five/Six) until a human has
manually verified the application and approved. **The user waived this gate** and
instructed "fix defects + start UI", which was carried out. The original gate text
follows for the record:

To pass the gate you must, in your own review:

1. Run the manual stories in `docs/manual-uat-stories.md` and change each `NOT RUN` you are satisfied
   with to **MANUALLY VERIFIED** (only you may do this).
2. Confirm the statutory gate is holding (it must — no rates may be signed off by the assistant).
3. Decide the open items: **D6** (per-establishment legal basis) and **D4** (goals/OKR), plus whether
   to send `docs/compliance/CA-SIGNOFF-REQUEST.md`.

The stories have **not** been marked verified — that remains a human action; only the
gate *precondition* to start UI work was waived.

## 5. Known limitations (updated)

- ~~No UI for `hrms_core_ext` / `hrms_statutory`~~ — **now added** (see §7). Those UAT
  stories are no longer `[SHELL]`-only.
- TDS output is not production-usable (no input write-back).
- Roster overtime consent artefact and statutory caps in the solver are not implemented.
- Worker re-skilling fund is catalog-only, not an F&F component.
- No reports/PDF, no REST API, no AI layer.

These are catalogued with line references in `application-flow.md` §19 and tracked in
`requirement-traceability.md`.

## 6. Repo state

All new/edited files are **uncommitted** (nothing was committed or pushed in this engagement),
matching the instruction not to commit without an explicit request:

```
 M docs/HANDOFF.md
 M addons/hrms_core_ext/models/base.py
 M addons/hrms_core_ext/models/hr_employee.py
 M addons/hrms_core_ext/__manifest__.py
 M addons/hrms_statutory/models/rule.py
 M addons/hrms_statutory/__manifest__.py
?? addons/hrms_core_ext/tests/__init__.py
?? addons/hrms_core_ext/tests/test_core_ext_security.py
?? addons/hrms_core_ext/views/core_ext_views.xml
?? addons/hrms_statutory/views/statutory_views.xml
?? docs/application-flow.md
?? docs/api-inventory.md
?? docs/api-test-plan.md
?? docs/api-test-results.md
?? docs/manual-uat-stories.md
?? docs/manual-verification-findings.md
?? docs/requirement-traceability.md
?? docs/test-runs/20261009T154645Z.{md,log}   (and later runs)
```

## 7. What changed in code (post-waiver)

- **F-01** `hr_employee.py`: reveal path uses `self.env.user.has_group(...)`.
- **F-02** `base.py`: `_field_key` reads `ir.config_parameter` first, then config/env;
  `encrypt_value`/`decrypt_value` take and thread `env`.
- **F-03** `base.py`: `decrypt_value` decodes AEAD plaintext to `str`.
- **Tests** `hrms_core_ext/tests/`: new suite (was absent) — encrypt/reveal/audit,
  denied paths, the new reveal action. `hrms_statutory/tests`: two tests for the new
  sign-off action.
- **UI** `hrms_statutory/views/statutory_views.xml`,
  `hrms_core_ext/views/core_ext_views.xml`: statutory rules/versions/legal-basis
  screens with a sign-off button; payroll-period locks, audit log, integration sync
  log; and an "HR Security" page on the employee form with reveal buttons.
  Backing methods: `hrms.statutory.rule.version.action_validate`,
  `hr.employee.action_reveal_secret` (both wrap existing, tested gates).

`tools/check_views.py` → 0 errors; `tools/check_addons.py` → 0 errors, 114 tests.
