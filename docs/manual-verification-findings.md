# Manual Verification Findings

> Produced 2026-10-09 during the guided manual-verification pass on HEAD `8d44c5a`.
> These are defects and doc errors found **while preparing** the manual stories, before any UI work.
> They are recorded here rather than silently fixed, per the "no false claims" rule.
>
> **Update 2026-10-09 (later):** the user waived the manual-verification gate and
> authorised "fix defects + start UI". F-01, F-02 and F-03 below are now **fixed**
> in code, with regression tests, and the suite is green (114 tests, 0 failed,
> statutory sign-off gate still holding). The UI work (Phase Five) is also done —
> see the last section.

## F-01 — PAN/Aadhaar reveal path is broken (functional defect) · **FIXED**

- **Where:** `addons/hrms_core_ext/models/hr_employee.py:238` `_hrms_reveal` and
  `:263` `action_view_aadhaar`.
- **What:** both called `self.user_has_groups(...)` on an `hr.employee` recordset,
  which does not exist, so every reveal raised `AttributeError`.
- **Fix:** now `self.env.user.has_group(...)` (matching every other call in the
  codebase, e.g. `payroll_period.py:178`).
- **Regression coverage:** `addons/hrms_core_ext/tests/test_core_ext_security.py`
  (new for this addon) covers encrypt→reveal→audit-row as an HR manager and
  AccessError for an unauthorised user.
- **Re-verified:** shell probe `uat_shell_evidence.py` — `reveal equals plaintext:
  True`, `audit rows before/after: 0 1`, `last audit: read_sensitive hr.employee`.

## F-02 — Encryption key source contradicted its own documentation (defect) · **FIXED**

- **Where:** `addons/hrms_core_ext/models/base.py` `_field_key()`.
- **What:** it read only `tools.config`/`os.environ`, while the `UserError` message
  and `data/ir_config_data.xml:5-9` told operators to set
  `ir.config_parameter 'hrms.field_encryption_key'` — so following the instruction
  did nothing.
- **Fix (option 1, reconcile to the documented design):** `_field_key(env=None)` now
  reads `ir.config_parameter 'hrms.field_encryption_key'` first, then falls back to
  Odoo config / env `FIELD_ENCRYPTION_KEY`. `encrypt_value`/`decrypt_value` take an
  `env` and thread it through `_enc_write`/`_enc_read`. Both the message and the
  `ir_config_data.xml` comment are now true.
- **Re-verified:** the reveal probe now succeeds with the key set **only** via
  `ir.config_parameter` (no env var passed to the container).

## F-03 — Decryption returned bytes, not text (defect found by the new test) · **FIXED**

- **Where:** `addons/hrms_core_ext/models/base.py` `decrypt_value()`.
- **What:** it returned `AESGCM(...).decrypt(...)`, which is `bytes`, so
  `_hrms_reveal` handed back `b'ABCDE1234F'` instead of `'ABCDE1234F'`. Any caller
  that compared or displayed the value would have shown the `b'...'` form.
- **Fix:** decode the AEAD plaintext (`.decode()`), returning `str`.
- **Regression coverage:** `test_reveal_returns_plaintext_and_writes_audit` fails on
  the old code and passes on the fixed code.

## Documentation corrections made during this pass (no code affected)

- Model name is `hrms.wages.composition`, not `hrms.wage.composition` (`api-inventory.md` fixed).
- Encrypted employee fields are `pan_number_enc` / `aadhaar_number_enc` (with
  `*_display` masked readers); there is no `hrms_pan` field (`manual-uat-stories.md` UAT-01 fixed).
- Roster menus live under **Employees → Rostering**; `Payroll → Payroll Runs` and
  `Payroll → Final Settlements` are hidden until the user holds the payroll groups
  (`manual-uat-stories.md` fixed).
- `hrms.audit.log.log` signature is `log(model, res_id, action, changes=?, note=?)`
  (`manual-uat-stories.md` UAT-02 fixed).

## Not a defect (checked)

- A startup traceback mentioning `hr_payroll_account_community` is a **third-party
  `DeprecationWarning`** (old single-record `create` override in the OCA module), not our code; it is
  non-fatal and the module works.
- `admin` not being in the payroll groups is correct access control, not a bug; the RPC smoke showed
  the gated models deny as designed.

## New UI added (Phase Five) · 2026-10-09

Two addons had **no views or menus at all**; those gaps are now closed.

- `hrms_statutory/views/statutory_views.xml`:
  - **Statutory → Statutory Rules** (list/form, button to open versions, "no version
    yet" warning).
  - **Statutory → Statutory Rule Versions** (list/form; `state` status bar; a
    **Sign off** button that calls the new `action_validate`, which still enforces
    the named-validator + segregation-of-duties gate).
  - **Statutory → Legal Basis** (list/form; **Confirm** button calling the existing
    `action_confirm`).
- `hrms_core_ext/views/core_ext_views.xml`:
  - **Compliance → Payroll Period Locks** (list/form; review→lock→release→reopen
    buttons with the maker-checker guards already in the model).
  - **Compliance → Audit Log** (read-only list/form; the append-only log).
  - **Compliance → Integration Sync Log** (list/form).
  - **Employee form → new "HR Security" page** (sync metadata, statutory/engagement
    fields, and masked PAN/Aadhaar/bank values each with a **Reveal** button that
    calls the new `action_reveal_secret` — access-checked and audit-logged via
    `_hrms_reveal`).

New model methods backing the UI (both thin wrappers over existing, tested gates):
`hrms.statutory.rule.version.action_validate` and `hr.employee.action_reveal_secret`.

### Viewing the new menus as `admin`

`admin` holds none of the custom HRMS groups, so the **Compliance** and
**Statutory** menus are hidden from it by design (that is the access model, not a
bug). To click through the new screens, grant the relevant groups to your QA user,
e.g.:

```sql
-- run against the hrpay database, or do it from Settings → Users & Companies
INSERT INTO res_groups_users_rel (gid, uid)
SELECT id, 2 FROM res_groups
WHERE name IN ('Payroll Admin', 'Auditor', 'Statutory Config Admin', 'Statutory Validator')
ON CONFLICT DO NOTHING;
```

(or in the UI: **Settings → Users → Administrator → Other groups**).

## Status

F-01, F-02 and F-03 are **fixed** and covered by tests; `tools/check_views.py`
reports 0 errors and the full Odoo suite is green with the sign-off gate holding.
The manual-verification gate was waived by the user, who authorised the fixes and
the UI work in the same instruction. UAT-01 can now pass; the remaining UAT
stories still need a human to run them and mark the traceability matrix.
