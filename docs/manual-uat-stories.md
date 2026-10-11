# Manual UAT Stories — HRMS Payroll Suite

> For the **human** verifier. Automated suites live in `docs/api-test-results.md`; this file is the
> click-through checklist that must be performed by a person in the running app.
>
> **Rule:** only **you** may change a story's result to **MANUALLY VERIFIED**. The assistant has
> pre-filled every result as `NOT RUN`. Do not treat the automated green run as a substitute.
>
> Written 2026-10-09 against HEAD `8d44c5a`. App: `http://localhost:8069`, DB `hrpay`.

## 0. Before you start

1. **Start the app** (from WSL, repo root): `make up`, then open http://localhost:8069
   (login `admin` / `admin`, database `hrpay`).
2. **Give your user the right groups.** A bare `admin` is *not* in the payroll groups, so the
   `Payroll → Payroll Runs` and `Payroll → Final Settlements` menus are **hidden**. Via
   `Settings → Users → (Administrator)`, add:
   `HR Payroll/Payroll Admin`, `HR Payroll/Statutory Config Admin`, `HR Payroll/Finance Approver`,
   `Human Resources/Roster Manager`, `Human Resources/Auditor`, and (for the roster solver)
   `Roster Solver: propose`. Reload the page.
   *The `Employees → Rostering` menus are visible to `admin` without any change.*
   *(Adding groups is a dev-only convenience; a production user would be granted these deliberately.)*
3. **Seed data is thin on purpose:** 1 employee, 50 statutory rule definitions, **0 rule versions**,
   0 rosters, 0 runs. Some stories require you to create data; steps say so.
4. **A retry is not a fix.** If a step fails, record the exact error text; do not work around it.

Legend: `[UI]` clickable today · `[SHELL]` backend-only (no view — see the story's shell command) ·
`[BLOCKED]` cannot be verified yet.

---

## Story index

| ID | Workflow | Surface | Result |
|---|---|---|---|
| UAT-01 | Employee PAN/Aadhaar encryption + reveal audit | SHELL | NOT RUN |
| UAT-02 | Audit log is append-only | SHELL | NOT RUN |
| UAT-03 | Statutory sign-off gate blocks resolution | SHELL | NOT RUN |
| UAT-04 | Statutory rule → version → human sign-off → resolve | SHELL | NOT RUN |
| UAT-05 | Payroll period lock: review → lock → refuse edit | SHELL | NOT RUN |
| UAT-05b | Roster period publish/lock | UI | NOT RUN |
| UAT-06 | Roster: period, shift, demand, assignment, publish | UI | NOT RUN |
| UAT-07 | Roster solver proposes without double-booking | UI | NOT RUN |
| UAT-08 | Roster assignment immutability after publish | UI | NOT RUN |
| UAT-09 | Payroll run lifecycle + segregation of duties | UI | NOT RUN |
| UAT-10 | Payroll coverage gate refuses an incomplete run | UI | NOT RUN |
| UAT-11 | F&F case end-to-end and 2-working-day clock | UI | NOT RUN |
| UAT-12 | F&F negative settlement separation | UI/SHELL | NOT RUN |
| UAT-13 | Helpdesk statutory-deadline ticket | UI | NOT RUN |
| UAT-14 | Helpdesk confidentiality record rule | UI | NOT RUN |
| UAT-15 | AI triage review is review-only (no auto-action) | UI | NOT RUN |

---

## UAT-01 · `[SHELL]` Employee PAN/Aadhaar encryption + reveal audit

- **Persona:** Payroll Admin granting itself a reveal.
- **Why shell:** the reveal path was broken (defect F-01, since fixed) and
  `hrms_core_ext` had no views. It now has an **Employee form → HR Security** page
  with masked values and **Reveal** buttons (`action_reveal_secret`); this story
  still uses the shell so the ciphertext-at-rest can be inspected directly.
  The fields are group-restricted and encrypted at rest.
- **Steps (Odoo shell):**
  ```bash
  make odoo-shell
  ```
  ```python
  import base64, os
  env['ir.config_parameter'].sudo().set_param(
      'hrms.field_encryption_key', base64.b64encode(os.urandom(32)).decode())
  e = env['hr.employee'].search([], limit=1)
  e._hrms_set_enc('pan_number', 'ABCDE1234F')
  e._hrms_set_enc('aadhaar_number', '123412341234')
  env.cr.execute("select pan_number_enc, aadhaar_number_enc from hr_employee where id=%s", [e.id])
  print('raw on disk:', env.cr.fetchall())          # expect ciphertext, not the plaintext
  # reveal decrypts for an authorised user AND writes an audit row:
  print(e._hrms_reveal('pan_number', reason='UAT-01'))
  env['hrms.audit.log'].search([('model','=','hr.employee')], order='id desc', limit=1).read(['action','user_id','res_id'])
  ```
  (The public field is `pan_number_enc`/`aadhaar_number_enc` for storage and `pan_number_display` /
  `aadhaar_number_display` for masked output; plaintext is only via `_hrms_reveal`/`action_view_pan`.)
- **Expected:** the `*_enc` columns hold ciphertext (not `ABCDE1234F`); `_hrms_reveal`/
  `action_view_pan` returns the plaintext **and** writes an `hrms.audit.log` row naming the user and
  the action.
- **Note (found while preparing this pass):** encryption is **not configured** in the seeded DB —
  `_hrms_set_enc` raises `UserError: field encryption key is not configured`. Generate and set the
  key first (step above). Expected: no keys/rotation have ever been exercised.
- **Result:** ✅ **EVIDENCE CAPTURED (assistant), F-01 fixed** — originally failed
  (`self.user_has_groups` on `hr.employee` → `AttributeError`). Fixed; the shell probe
  now shows `reveal equals plaintext: True` and `audit rows before/after: 0 1`. A human
  should still re-run and mark this MANUALLY VERIFIED. See
  `docs/manual-verification-findings.md` F-01/F-03. · **Evidence:** shell run 2026-10-09.

## UAT-02 · `[SHELL]` Audit log is append-only

- **Steps:** in `make odoo-shell`, ensure at least one audit row exists (e.g. run UAT-01's reveal
  first), then attempt both mutations in a `try/except`:
  ```python
  A = env['hrms.audit.log']
  log = A.search([], limit=1) or A.log(
      'hr.employee', 1, 'read_sensitive', changes={'pan_number': '***'}, note='UAT-02 probe')
  for op in ('write', 'unlink'):
      try:
          log.write({'action': 'tampered'}) if op == 'write' else log.unlink()
          print(op, 'ALLOWED (bad)')
      except Exception as exc:
          print(op, 'refused ->', type(exc).__name__)
  env.cr.rollback()
  ```
- **Expected:** both `write` and `unlink` raise; the log cannot be altered or deleted.
- **Result:** ✅ **EVIDENCE CAPTURED** (assistant, 2026-10-09): `log()` created a row;
  `write` → `AccessError`, `unlink` → `AccessError`. Awaiting your `MANUALLY VERIFIED`.

## UAT-03 · `[SHELL]` Statutory sign-off gate blocks resolution

- **Steps:** `make odoo-shell`, then:
  ```python
  cat = env['hrms.statutory.catalog']
  ctx = env['hrms.statutory.context']
  n = 0
  for code in cat.catalog_codes():
      try: ctx.resolve(code, env.company)
      except Exception: n += 1
  print('blocked:', n, 'of', len(cat.catalog_codes()))
  ```
- **Expected:** **every** code raises (50 of 50 blocked) while no rule version exists. This is the
  core safety property: an unconfigured database must not compute payroll.
- **Result:** ✅ **EVIDENCE CAPTURED** (assistant, 2026-10-09): catalog 50, blocked 50, resolved 0.
  Awaiting your `MANUALLY VERIFIED`.

## UAT-04 · `[SHELL]` Rule → version → human sign-off → resolve

- **Persona:** two different people (a version's author may **not** be its validator).
- **Steps:** in `make odoo-shell`:
  ```python
  rule = env['hrms.statutory.rule'].search([('code','=','IN.PF.EMPLOYEE_RATE')], limit=1)
  v = env['hrms.statutory.rule.version'].create({'rule_id': rule.id, 'value': 12.0, 'valid_from': '2026-01-01'})
  print('state after create:', v.state)          # expect: draft -> still not usable
  try:
      print(env['hrms.statutory.context'].resolve('IN.PF.EMPLOYEE_RATE', env.company))
  except Exception as e:
      print('still blocked:', e)
  ```
  Then sign off **as a different user** (set an approver id / use the intended API; see
  `models/rule.py` `_check_signoff`), and re-resolve.
- **Expected:** a bare `create` leaves the version unusable; resolution only succeeds **after** a
  distinct validator signs off; self-sign-off is refused.
- **Result:** NOT RUN · **Evidence:** ______ · **Notes:** D6 (per-establishment legal basis) is
  formally unapproved — record whether that blocks you.

## UAT-05 · `[SHELL]` Payroll period lock refuses an edit

- **Steps:** `make odoo-shell`:
  ```python
  L = env['payroll.period.lock']
  p = env['hr.roster.period']  # or create a period for the company/month per the model
  # create/find the lock for the current month, move review -> lock, then attempt a mutation
  print(env['payroll.period.lock'].is_locked(env.company, '2026-10-01'))
  ```
  Then attempt to write a time/leave value dated inside a **locked** period.
- **Expected:** `is_locked` is False in draft, `True` after `action_lock`; `assert_mutable` raises for
  any write inside a locked period; `action_reopen` requires elevated authorisation.
- **Result:** NOT RUN · **Evidence:** ______

## UAT-05b · `[UI]` Roster period publish/lock (roster side)

- **Menu:** *Employees → Rostering → Roster periods*.
- **Steps:** create a period (dates within one month), `Publish`, then `Lock`, then try to edit an
  assignment inside it.
- **Expected:** publish stamps a checksum; after lock, edits are refused; `action_unlock` always
  raises (irreversible by design).
- **Result:** NOT RUN · **Evidence:** ______

## UAT-06 · `[UI]` Roster: shift, demand, assignment, publish

- **Menu:** *Employees → Rostering* → **Roster configuration** (Shifts, Staffing demand,
  Availability, Solver proposals), plus **Roster periods** and **Assignments**.
- **Steps:** create a shift (e.g. 09:00–18:00); create a demand for a date needing N staff; create a
  period covering that date; create an assignment of the seeded employee to a shift; publish.
- **Expected:** records save; `publish` sets the published flag/checksum; the assignment appears on
  the period.
- **Result:** NOT RUN · **Evidence:** ______ · **Notes:** `actual_hours` is never populated (gap G9).

## UAT-07 · `[UI]` Roster solver proposes without double-booking

- **Persona:** Roster Manager + Roster Solver user.
- **Steps:** with demand and availability loaded, open a **period** and run the solver from the
  solver-result view (`menu_hrms_roster_solver_result`). Inspect the proposal.
- **Expected:** a proposal is created; no employee is double-booked; unfilled demand is reported as a
  **shortfall**, not silently closed. *(A known greedy-heuristic limitation, ADR-0008, may decline an
  arrangement a backtracking solver would find — that is documented, not a failure.)*
- **Result:** NOT RUN · **Evidence:** ______

## UAT-08 · `[UI]` Assignment immutability after publish

- **Steps:** publish a roster period, then attempt to edit a field on an assignment inside it from the
  UI.
- **Expected:** the write is refused (checksum mismatch / published guard).
- **Result:** NOT RUN · **Evidence:** ______

## UAT-09 · `[UI]` Payroll run lifecycle + segregation of duties

- **Persona:** Payroll Admin creates; a **different** user with Finance Approver approves.
- **Steps:** `Payroll → Payroll Runs`, create a run for the period, `Compute` (expect refusal while
  statutory values are absent), then walk `review → lock`. Try to approve the run **as its creator**.
- **Expected:** compute refuses because no statutory code resolves (UAT-03); the state machine
  advances only in order; **the creator cannot approve their own run** (SoD enforced in the model).
- **Result:** NOT RUN · **Evidence:** ______

## UAT-10 · `[UI]` Coverage gate refuses an incomplete run

- **Steps:** create a run scoped to an establishment/month with an employee but **no** published
  roster/attendance; attempt to advance it.
- **Expected:** the run reports the coverage gap and refuses to proceed (empty snapshot counts as a
  gap — HANDOFF §5 "Fixed by the first Odoo run", item 6).
- **Result:** NOT RUN · **Evidence:** ______

## UAT-11 · `[UI]` F&F case end-to-end and the 2-working-day clock

- **Persona:** Payroll Admin.
- **Steps:** `Payroll → Final Settlements`, create a case (set last working day, reason), add lines,
  run the settlement, then transition through the documented states.
- **Expected:** the statutory wage deadline is computed as **2 working days** from the last working
  day for the wages component (per-component deadlines); a shortfall (unserved notice) shows as a
  recovery subject to `permits_recovery`/`notice_recovery_cap`; negative net settlement separates
  `amount_payable` from `recovery_due`.
- **Result:** NOT RUN · **Evidence:** ______

## UAT-12 · `[UI/SHELL]` Negative settlement separation

- **Steps:** create a case whose recoveries exceed payables; inspect the fields.
- **Expected:** `amount_payable = 0` and `recovery_due > 0` (never a single negative number).
- **Result:** NOT RUN · **Evidence:** ______

## UAT-13 · `[UI]` Helpdesk statutory-deadline ticket

- **Steps:** open a ticket (OCA helpdesk menu) of a statutory type; set the relevant dates.
- **Expected:** the statutory deadline field is populated from the ticket type; the ticket shows as
  breached when the deadline passes. *(`hrms_helpdesk` is the thinnest addon — expect rough edges.)*
- **Result:** NOT RUN · **Evidence:** ______

## UAT-14 · `[UI]` Helpdesk confidentiality record rule

- **Persona:** two users, one with `group_hrms_confidential_case_handler`, one without.
- **Steps:** mark a ticket confidential; log in as each user and list tickets.
- **Expected:** the non-handler cannot see the confidential ticket; the handler can.
- **Result:** NOT RUN · **Evidence:** ______

## UAT-15 · `[UI]` AI triage review is review-only

- **Steps:** if a ticket exposes the AI-triage review fields, attempt any "apply"/"enrich" action.
- **Expected:** there is **no AI model configured** (known gap G11); the action must not silently
  fabricate a result. Record what happens.
- **Result:** NOT RUN · **Evidence:** ______

---

## Deferred — cannot be manually verified yet

| Item | Why |
|---|---|
| TDS monthly projection on real payslips | Write-back of `hrms_ytd_taxable` etc. not built (`HANDOFF §5` blocking-2). |
| PF/ESI/PT/gratuity producing real numbers | No validated statutory values (by design). |
| Reports / Form 16 / payslip PDF | None exist (gap G12). |
| Roster statutory overtime caps in the solver | Not enforced in solver (`HANDOFF §5` blocking-5, ADR-0008). |
| Integration service / RAG chat / webhooks | Phase 3/4, not built. |
| UI for `hrms_core_ext` and `hrms_statutory` | ~~No views~~ Views added (gaps G1/G2 resolved); the UI itself has still not been visually inspected. |

---

## Sign-off

| Story | Verified by (name) | Date | Result |
|---|---|---|---|
| UAT-01 | | | |
| UAT-02 | | | |
| UAT-03 | | | |
| UAT-04 | | | |
| UAT-05 | | | |
| UAT-05b | | | |
| UAT-06 | | | |
| UAT-07 | | | |
| UAT-08 | | | |
| UAT-09 | | | |
| UAT-10 | | | |
| UAT-11 | | | |
| UAT-12 | | | |
| UAT-13 | | | |
| UAT-14 | | | |
| UAT-15 | | | |

**Overall manual verdict:** ____________________  **User approval to proceed to UI phase:**
☐ APPROVED ☐ REJECTED — signed ____________________ date ____________
