# HRMS Payroll Suite — API Inventory

> Generated 2026-10-09 from a read-only source audit (HEAD `8d44c5a`). Every model/method below is
> traced to source (`file:line`) and cross-checked against a generated list of every `def` in
> `addons/**/*.py` (386 methods). This is the complete **external interface surface**.

## 0. What "API" means here

**There are no HTTP/JSON controllers (`@http.route`) in any HRMS module.** The suite exposes no
REST/GraphQL endpoints and defines no `ir.actions.server` RPC endpoints. The entire API surface is
**Odoo's built-in remote ORM protocol**:

- **XML-RPC:** `POST /xmlrpc/2/common` (`authenticate`), `POST /xmlrpc/2/object` (`execute_kw`)
- **JSON-RPC:** `POST /web/dataset/call_kw` (session-based)
- **Authentication:** `db` + `login` + `password` (or an API key), or a web session cookie.

Any public method on a `models.Model` is callable over these protocols, subject to ACLs, record rules
and Python gates. `models.AbstractModel` methods (solver, statutory context, India engine, catalog)
are callable too but have no persistent records.

Call the surface with `execute_kw(db, uid, password, model, method, [args], {kwargs})`.

### Conventions

| Column | Meaning |
|---|---|
| Model | Odoo model (`_name`) |
| Method | Python method name (public) |
| Args / Returns | Positional args and return shape |
| Gate | ACL group / record rule / Python rule that limits it |
| Source | `file:line` of definition |

`create` / `write` / `read` / `search_read` / `unlink` exist on every persistent model but are listed
only where they carry **custom behaviour** (sign-off gates, append-only locks, state guards).

---

## 1. Session / auth

| Model | Method | Notes |
|---|---|---|
| — | `common.authenticate(db, login, password, {})` | Returns `uid`. No HRMS override. |
| — | `object.execute_kw(db, uid, pw, model, method, args, kwargs)` | Dispatch to any method below. |

No custom auth, MFA, SSO or token endpoint is added by any HRMS module.

---

## 2. `hrms_core_ext` — models & methods

### 2.1 `hrms.audit.log` (`models/base.py`, model at :282)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `log` | `(model, res_id, action, changes=None, note=None)` → int id; writes row | append-only | `base.py:363` |
| `_redact` | `(values)` → redacted dict | internal | `base.py:349` |
| `check_sod` | `(record, action_label, extra_condition=None)` → raises on conflict | SoD control | `base.py:409` |
| `write` | — | **raises** (append-only) | `base.py:402` |
| `unlink` | — | **raises** (append-only) | `base.py:405` |

`_sensitive_fragments` (`:328`) drives redaction. Action enum: `create/write/unlink/read_sensitive/approve/reject/release/override/lock/unlock/auth/ai_action`.
Module-level crypto helpers (not RPC): `encrypt_value` (`:79`), `decrypt_value` (`:96`), `hmac_sign` (`:233`), `hmac_verify` (`:249`). Mixin helpers: `_enc_write` (`:191`), `_enc_read` (`:198`), `_enc_masked` (`:206`).

### 2.2 `hr.employee` (`models/hr_employee.py`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `_hrms_get_enc` | `(field_name)` → plaintext | field group | `hr_employee.py:218` |
| `_hrms_set_enc` | `(field_name, value)` → writes ciphertext | field group | `:223` |
| `_hrms_encrypted_fields` | `()` → tuple of names | internal | `:229` |
| `_hrms_reveal` | `(field_name, reason=None)` → plaintext **+ audit row** | field group | `:232` |
| `action_view_pan` | `()` → action dict | `hr.group_hr_user` | `:252` |
| `action_view_aadhaar` | `()` → action dict | `hr.group_hr_manager` | `:261` |
| `action_reveal_secret` | `()` → `display_notification` action; field via ctx `hrms_reveal_field` | field group (via `_hrms_reveal`) | `:272` |
| `canonical_sync_payload` | `(emp)` → dict | internal | `:353` |
| `sync_hash_for` | `(emp)` → SHA-256 | internal | `:371` |
| `action_recompute_sync_hash` | `()` → writes `sync_hash` | payroll admin | `:375` |
| `action_mark_synced` | `()` → `sync_status=Synced` | payroll admin | `:380` |
| `action_mark_failed` | `(error)` → `sync_status=Failed` | payroll admin | `:392` |

Implicit computes/constraints: `_compute_enc_display` (`:301`), `_compute_hrms_state_code` (`:308`),
`_check_contract_dates` (`:315`), `_check_prior_service` (`:329`).

### 2.2 `payroll.period.lock` (`models/payroll_period.py:22`) — model name has **no `hrms.` prefix**

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `action_start_review` | `()` → `draft → review` | — | `payroll_period.py:106` |
| `action_lock` | `()` → `review → locked`; requires AI flags acknowledged | — | `:110` |
| `action_release` | `()` → `locked → released`; **must differ from locker** | SoD | `:135` |
| `action_reopen` | `()` → `→ review`; requires written reason + HR manager | `hr.group_hr_manager` | `:162` |
| `period_for` | `(company, date_value)` → record | internal | `:190` |
| `is_locked` | `(company, date_value)` → bool | internal | `:202` |
| `assert_mutable` | `(company, date_value, what)` → raises if locked | internal | `:207` |
| `_compute_checksum` | `()` → str | internal | `:76` |
| `_check_dates` | `()` → raises on overlap | constrains | `:85` |

States: `draft, review, locked, released`. This is the control the payroll run depends on.

### 2.3 `integration.sync.log` (`models/payroll_period.py:218`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `find_by_idempotency` | `(key)` → record | internal | `payroll_period.py:296` |
| `action_dead_letter` | `(reason)` → marks dead-letter | internal | `:299` |
| `write` / `unlink` | append-only enforcement | — | `:276` / `:287` |

**External integration interface:** no outbound HTTP client, no webhook receiver. The suite only
manages integration state on `hr.employee` (`payroll_external_id`, `sync_status`, `sync_hash`) and
records sync calls here.

### 2.4 `hr.leave` / `hr.attendance` / `hr.contract` extensions (`models/hr_core_ext.py`)

| Model | Method | Source |
|---|---|---|
| `hr.leave` | `action_validate` (`:61`), `action_refuse` (`:71`) | `hr_core_ext.py` |
| `hr.attendance` | `_compute_deviation` (`:107`) — **reads non-existent `shift_start_datetime`/`shift_end_datetime`** | `:107` |
| `hr.contract` | `_check_fixed_term` (`:156`) | `:156` |

---

## 3. `hrms_statutory` — models & methods

### 3.1 `hrms.statutory.rule` (`models/rule.py:47`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `create` | standard | statutory admin | `rule.py:101` |
| `_compute_scope_key` | `()` → scope key | internal | `:112` |
| `action_open_versions` | `()` → action dict | — | `:131` |

### 3.2 `hrms.statutory.rule.version` — the sign-off gate (`models/rule.py`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `create` | runs `_check_signoff` + `_check_value_shape_at_create` | statutory admin | `rule.py:307` |
| `write` | runs `_check_signoff`; blocks value edits once validated; auto-supersedes prior | statutory admin | `:313` |
| `unlink` | only `draft` deletable | statutory admin | `:346` |
| `value` | `()` → typed value; refuses if not validated/active/superseded | — | `:356` |
| `_check_signoff` | `(vals)` → raises unless `validated_by` set and ≠ author | Python gate | `:246` |
| `_check_value_shape` | `()` → type/shape validation | constrains | `:216` |
| `_check_dates` | `()` → effective dating | constrains | `:238` |
| `_check_value_shape_at_create` | `(vals)` | internal | `:285` |
| `action_validate` | `()` → `draft → validated`; passes `validated_by` in the same write (form button) | sign-off gate | `:313` |

States: `draft → validated → superseded`. `action_validate` is a thin UI wrapper over `write`; it does
**not** bypass `_check_signoff` (named validator required, author ≠ validator). There is still no
`action_supersede` — superseding happens automatically inside `write`.

### 3.3 `hrms.legal.basis` (`models/rule.py:380`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `create` / `write` | standard | statutory admin | `rule.py` |
| `_compute_scope_key` | `()` | internal | `:450` |
| `action_confirm` | `()` → sign off the basis | statutory admin | `:469` |
| `resolve` | `(company, state_code, contract_type, on_date)` → basis | internal | `:485` |

### 3.4 `hrms.wages.composition` (`models/wages.py`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `compute` | `(employee, period_start, period_end, contract_type=None, payslip=None)` → composition | payroll admin | `wages.py:214` |
| `_apply_basis_rule` | `(statutory, rule, total_rem, code)` | internal | `:402` |
| `_collect_lines` | `(employee, p_start, p_end, payslip=None)` | internal | `:424` |
| `name_get` | `()` | internal | `:120` |

> **Gap:** `compute` requires rule `IN.GRATUITY.WAGE_BASIS_RULE`, which is **not** in the 50-entry
> catalog — it raises unless created manually (the catalog has `IN.PF/ESI.WAGE_BASIS_RULE` only).

### 3.5 `hrms.india.statutory.engine` (AbstractModel, `models/india.py:82`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `compute_pf` | `(employee, wages, period_end, ctx, composition=None)` → PF dict | payroll admin | `india.py:87` |
| `compute_esi` | `(employee, wages, period_end, ctx)` → ESI dict | payroll admin | `:161` |
| `compute_pt` | `(employee, taxable_salary, period_end, ctx)` → PT dict | payroll admin | `:189` |
| `compute_lwf` | `(employee, period_end, ctx)` → LWF dict | payroll admin | `:256` |
| `compute_tds` | `(employee, period_end, ctx, ytd=None)` → TDS dict | payroll admin | `:274` |
| `compute_all` | `(employee, composition, period_start, period_end, ytd=None)` → all + persists result | payroll admin | `:373` |

Persists to `hrms.india.statutory.result` (`india.py:26`, no custom methods).

### 3.5 `hrms.gratuity.engine` (AbstractModel, `models/gratuity.py`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `compute` | `(employee, as_of_date, exit_reason, wage_basis=None, wage_basis_method=None)` → gratuity dict | payroll admin | `gratuity.py:136` |
| `_default_periods` / `_wage_basis` / `_gross_earnings` / `_refuse_wage_basis` | helpers | internal | `:319` / `:346` / `:396` / `:423` |

### 3.6 `hrms.statutory.context` (AbstractModel, `models/rule.py`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `_snapshot` | `(company, state_code, contract_type, on_date)` → **list** of active version dicts (raises if no signed basis) | payroll admin | `rule.py:537` |
| `resolve` | `(code, company, state_code=None, contract_type, on_date=None)` → version | internal | `:574` |
| `get` | `(code, company, state_code=None, contract_type, on_date=None)` → scalar rate | — | `:625` |
| `get_json` | `(code, ...)` → dict | — | `:632` |

> `_snapshot` is what the payroll run calls. It **returns a list**; an empty/unconfigured result is
> turned into a blocking coverage gap upstream, not a single value.

### 3.7 `hrms.statutory.catalog` (AbstractModel, `models/catalog.py:94`)

| Method | Args / Returns | Source |
|---|---|---|
| `seed` | `()` → idempotent skeletons (called by `post_init_hook`) | `catalog.py:98` |
| `catalog_codes` | `()` → list of codes | `:139` |
| `coverage_report` | `()` → go-live readiness report | `:144` |

---

## 4. `hrms_roster` — models & methods

### 4.1 `hr.roster.period` (`models/roster_period.py:26`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `action_publish` | `()` → `draft → published` | — | `roster_period.py:123` |
| `action_lock` | `()` → `published → locked`; requires linked payroll locked | — | `:142` |
| `action_unlock` | `()` → **always raises** | — | `:179` |
| `_action_check_assignments` | `()` → raises on unpaid shift / negative overtime | internal | `:192` |
| `unlink` | guarded by state | — | `:220` |
| `previous_period` / `next_period` / `create_period` | helpers | — | `:229` / `:241` / `:254` |

### 4.2 `hr.roster.shift` (`models/roster_period.py:271`)

`_compute_overnight` (`:316`), `_compute_duration` (`:321`), `_check_times` (`:329`).

### 4.3 `hr.roster.assignment` (`models/roster_assignment.py:29`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `action_confirm` | `()` → `draft → confirmed` | — | `roster_assignment.py:220` |
| `action_set_published` | `()` → `confirmed → published` | — | `:233` |
| `action_approve_overtime` | `(hours=None, note=None)` | SoD (no self/superuser) | `:237` |
| `action_reject_overtime` | `(reason)` | — | `:274` |
| `_check_window` / `_check_no_self_overlap` / `_check_approved_overtime` / `_check_actual_hours` | constrains | `:163` / `:173` / `:194` / `:205` |
| `unlink` / `write` | guarded by state | `:291` / `:300` |

States: `draft, confirmed, published, relieved, cancelled` — `relieved`/`cancelled` have **no transition**.

### 4.4 `hr.roster.demand` (`models/roster_assignment.py:314`)

| Method | Args / Returns | Source |
|---|---|---|
| `total_for` | `(establishment, weekday, date=None)` → int | `roster_assignment.py:378` |
| `_compute_name` / `_check_headcount` | — | `:363` / `:372` |

### 4.5 Solver helpers & proposal

| Model | Method | Args / Returns | Gate | Source |
|---|---|---|---|---|
| `hrms.roster.solver.setting` | `_check_limits` | `()` → range checks | — | `solver.py:113` |
| `hrms.roster.availability` | `sync_from_approved_leave` | `(leave)` → availability | — | `solver.py:190` |
| `hrms.roster.solver.result` | `action_apply` | `()` → creates **draft** assignments | solver user | `solver.py:264` |
| `hrms.roster.solver.result` | `_action_apply_proposal` | `()` | internal | `solver.py:293` |

### 4.6 `hrms.roster.solver` (AbstractModel, `models/solver.py:325`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `solve` | `(roster_period, setting=None)` → `hrms.roster.solver.result` proposal | solver user | `solver.py:331` |

`solve` **never writes assignments** — it only writes a proposal row. It is invoked **only from
`hrms_roster/tests/test_solver.py:121`**; no UI/button/cron calls it. `_json` serializer at `solver.py:739`.

---

## 5. `hrms_fnf` — models & methods

### 5.1 `hrms.fnf.reason` / `hrms.fnf.line`

Standard CRUD; `reason` seeded by `data/*.xml` (6 rows). `hrms.fnf.line` has no custom action methods.

### 5.2 `hrms.fnf.case` — the settlement lifecycle (`models/settlement.py`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `action_calculate` | `()` → `→ calculated`; runs the settlement engine | payroll admin | `settlement.py:291` |
| `_action_require_notice_data` | `()` → raises if notice data missing | internal | `:337` |
| `action_acknowledge` | `()` → `→ employee_acknowledged` | — | `:352` |
| `action_approve` | `()` → `→ approved`; refused for calculator; negative needs recovery rule | finance approver | `:...`/`action_approve` |
| `action_mark_paid` | `(reference)` → `→ paid` | finance approver | `:412` |
| `action_raise_dispute` | `(reason)` → `→ disputed` | — | `:425` |

The pure engine lives in `models/settlement_arithmetic.py` (`net_settlement` (`:246`),
`encashment_for_leave` (`:133`), `notice_shortfall_days` (`:174`), `notice_shortfall_recovery` (`:188`),
`service_months` (`:59`), `daily_wage` (`:110`), `accrued_leave_days` (`:71`)) and
`models/encashment.py` (`_build_lines` (`:70`), `_gross_earnings` (`:456`), `_last_drawn_monthly_wages`
(`:474`), `_average_monthly_wages` (`:503`), `_gratuity` (`:536`), `_notice_shortfall` (`:565`)).

States: `draft, under_calculation, calculated, employee_acknowledged, approved, paid, disputed,
withheld` (withheld unreachable).

---

## 6. `hrms_payroll_run` — `hrms.payroll.run` (`models/run.py:41`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `create_run` | `(establishment, period_end)` → run | payroll admin | `run.py:590` |
| `action_compute` | `()` → `draft → computed`; raises on blocking issues | payroll admin | `:318` |
| `action_review` | `(note)` → `computed → reviewed`; must differ from computer | SoD | `:429` |
| `action_approve` | `()` → `reviewed → approved`; differ from computer+reviewer; checksum match | finance approver | `:464` |
| `action_lock` | `()` → `approved → locked`; requires period lock; confirms/dones payslips | finance approver | `:495` |
| `action_cancel` | `()` → `→ cancelled`; reason required; blocked once locked | — | `:545` |
| `action_record_ai_flags` | `(flags_json)` → records advisory flags | — | `:572` |
| `_compute_input_checksum` / `_result_checksum` / `_current_result_checksum` | `()` → str | internal | `:172` / `:396` / `:542` |
| `_compute_blocking_issues` / `_unrostered_employees` / `_action_create_payslips` | `()` | internal | `:180` / `:291` / `:351` |

States: `draft → computed → reviewed → approved → locked`, plus `cancelled`. Methods named
`action_confirm`/`action_post`/`action_pay`/`_check_roster_published`/`_generate_payslips`
**do not exist** (grep-verified).

---

## 7. `hrms_helpdesk` — inherited Odoo models

### 7.1 `helpdesk.ticket.type` (`models/ticket.py:22`)

Adds `hrms_statutory_code`, `hrms_confidential_by_default`, `hrms_statutory_retention_months`,
`hrms_employee_required`. No custom RPC methods.

### 7.2 `helpdesk.ticket` (`models/ticket.py:48`)

| Method | Args / Returns | Gate | Source |
|---|---|---|---|
| `_compute_hrms_confidential` | `()` | internal | `ticket.py:118` |
| `_compute_statutory_deadline` | `()` → resolves the category statutory code | internal | `:125` |
| `_compute_hrms_days_to_deadline` | `()` | internal | `:156` |
| `_compute_hrms_breached` | `()` | internal | `:166` |
| `_onchange_category` | `()` | internal | `:178` |
| `action_confidential` | `()` → sets confidential (forward-only) | internal | `:188` |
| `action_review_ai_triage` | `(accepted, note=None)` | SoD (no superuser) | `:201` |
| `action_reopen_with_note` | `(note)` → reopen with audit note | — | `:235` |

Record rules `rule_hrms_ticket_confidential_*`; ACLs for `group_hrms_helpdesk_agent` and
`group_hrms_confidential_case_handler`. "AI" is a record/review surface — no producer in-repo.

---

## 8. Non-ORM surfaces

| Surface | Present? | Notes |
|---|---|---|
| HTTP JSON/REST controllers | **No** | no `@http.route`/`http.Controller` anywhere |
| GraphQL | No | — |
| XML-RPC / JSON-RPC | Yes (native Odoo) | the surface described in §0 |
| Cron / scheduled jobs | **No** HRMS cron | no `ir.cron` |
| Server actions (RPC) | No | no `ir.actions.server` |
| Webhooks / message queue | No | integration state only |

---

## 9. Authorisation scope for external callers

External callers must satisfy **both** the group ACL and the record rule. Key groups (defined in
`hrms_core_ext/security/hrms_security.xml`): `group_hrms_payroll_admin`, `group_hrms_finance_approver`,
`group_hrms_auditor`, `group_hrms_statutory_admin`, `group_hrms_roster_manager`,
`group_hrms_roster_solver_manager`/`_user`, `group_hrms_helpdesk_agent`,
`group_hrms_confidential_case_handler`. Full ACL/record-rule tables: `docs/application-flow.md` §3.

---

## 10. Callable-method quick reference

**Persistent models with custom methods:** `hrms.audit.log` (append-only `log`); `hr.employee`
(`_hrms_reveal`, `action_view_pan/aadhaar`, `action_recompute_sync_hash`, `action_mark_synced/failed`);
`payroll.period.lock` (`action_start_review/lock/release/reopen`, `is_locked`, `assert_mutable`);
`integration.sync.log` (`find_by_idempotency`, `action_dead_letter`); `hrms.statutory.rule`
(`action_open_versions`); `hrms.statutory.rule.version` (sign-off via `create`/`write`, `value`);
`hrms.legal.basis` (`action_confirm`); `hrms.wages.composition` (`compute`); `hr.roster.period`
(`action_publish/lock/unlock`); `hr.roster.assignment` (`action_confirm`, `action_set_published`,
`action_approve_overtime`, `action_reject_overtime`); `hr.roster.demand` (`total_for`);
`hrms.roster.availability` (`sync_from_approved_leave`); `hrms.roster.solver.result` (`action_apply`);
`hrms.fnf.case` (`action_calculate/acknowledge/approve/mark_paid/raise_dispute`); `hrms.payroll.run`
(`action_compute/review/approve/lock/cancel`, `action_record_ai_flags`); `helpdesk.ticket`
(`action_confidential`, `action_review_ai_triage`, `action_reopen_with_note`).

**AbstractModels:** `hrms.roster.solver.solve`; `hrms.statutory.context` (`_snapshot`, `resolve`,
`get`, `get_json`); `hrms.statutory.catalog` (`seed`, `catalog_codes`, `coverage_report`);
`hrms.india.statutory.engine` (`compute_pf/esi/pt/lwf/tds/all`); `hrms.gratuity.engine.compute`.

*End of API inventory.*
