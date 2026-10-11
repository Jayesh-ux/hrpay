# Manual Testing Guide

> Entry point for a human to click through the application, including the UI added
> in Phase Five. Pairs with `docs/manual-uat-stories.md` (the full 16-story script)
> and `docs/manual-verification-findings.md` (what changed). Nothing here has been
> marked verified by the assistant — only a human may do that.

## 0. Start

```bash
# in WSL (Ubuntu), from the repo root
make up          # starts hrpay-odoo + hrpay-postgres
# open http://localhost:8069  ·  login admin / admin  ·  database: hrpay
```

Health check: `make ps` should show both containers healthy; `make logs` shows the
server on 8069.

## 1. Give yourself the groups (required)

`admin` holds **none** of the custom HRMS groups, so the Payroll/Compliance/Statutory
menus are hidden by design (that is the access model, not a bug). For manual QA, add
your user to the groups you want to exercise. Easiest via **Settings → Users &
Companies → Users → Administrator → Other groups** (tick *Payroll Admin*,
*Statutory Config Admin*, *Statutory Validator*, *Auditor*, *Finance Approver*, then
save), or in SQL:

```sql
INSERT INTO res_groups_users_rel (gid, uid)
SELECT id, 2 FROM res_groups
WHERE name IN ('Payroll Admin','Auditor','Statutory Config Admin',
               'Statutory Validator','Finance Approver','Roster Manager')
ON CONFLICT DO NOTHING;
```

## 2. Where the new screens live

The backend now wears a **dark** Bitrix24-style skin (dark canvas, blue accents,
flat rounded cards, left-hand navigation) and the HRMS sections are consolidated
under a single **HRMS** app in the app switcher, so nothing is buried inside
Employees/Payroll:

```
HRMS ▸ Rostering     (Roster periods, Assignments, Roster configuration)
     ▸ Payroll Runs
     ▸ Final Settlements
     ▸ Compliance    (Payroll Period Locks, Audit Log, Integration Sync Log)
     ▸ Statutory     (Statutory Rules, Rule Versions, Legal Basis)
```

| Menu path | Model | What to try |
|---|---|---|
| **HR → Employees → (open one) → HR Security tab** | `hr.employee` | masked PAN/Aadhaar/bank + **Reveal** buttons |
| **HRMS → Compliance → Payroll Period Locks** | `payroll.period.lock` | create a period, Start review → Lock → Release → Reopen |
| **HRMS → Compliance → Audit Log** | `hrms.audit.log` | read-only; confirm no Create/Edit/Delete |
| **HRMS → Compliance → Integration Sync Log** | `integration.sync.log` | read-only |
| **HRMS → Statutory → Statutory Rules** | `hrms.statutory.rule` | 50 seeded skeletons; open "Versions" |
| **HRMS → Statutory → Statutory Rule Versions** | `hrms.statutory.rule.version` | draft → **Sign off** |
| **HRMS → Statutory → Legal Basis** | `hrms.legal.basis` | draft → **Confirm** |
| **HRMS → Payroll Runs** | `hrms.payroll.run` | Compute → Record review → Approve → Lock |
| **HRMS → Final Settlements** | `hrms.fnf.case` | Calculate → Acknowledge → Approve → Mark paid |

### 2a. Login & sign-up screens
The skin also covers `/web/login`, `/web/signup` and `/web/reset_password` (a
dark card on the dark canvas, blue primary button). Log out to see it; the
sign-up link is the *"Don't have an account?"* link under the login form.

### Accessibility check (text contrast)
Every screen was audited by driving headless Chrome and computing the WCAG
contrast ratio (alpha-composited) of every visible text element. Result: **0
elements below AA** (4.5:1 normal text / 3:1 large text) on: login, sign-up,
backend landing, app dashboard, settings, payroll-run/statutory-rule/audit-log
lists, employee kanban and employee form — and on the interactive overlays the
app menu / burger sidebar (**HRMS** app-toggle, also opened from inside an app)
and the systray user-menu dropdown. White-text buttons use the Bitrix blue
`#0b66c3` (~5.7:1); the cyan `#2fc6f6` is used for links/accents/borders on the
dark canvas (~7.3:1). Re-run for yourself:

```bash
node /mnt/c/Users/hsing/AppData/Local/Temp/opencode/contrast.mjs login
node "C:/Users/hsing/AppData/Local/Temp/opencode/contrast.mjs" signup
node "C:\Users\hsing\AppData\Local\Temp\opencode\contrast.mjs" backend
# open overlays before auditing (click selector as 4th arg):
node "C:\Users\hsing\AppData\Local\Temp\opencode\contrast.mjs" backend "http://localhost:8069/web?db=hrpay" "a.o_menu_toggle"
# sweep every menu/action in one pass (crawl mode):
node "C:\Users\hsing\AppData\Local\Temp\opencode\contrast.mjs" crawl "C:\Users\hsing\AppData\Local\Temp\opencode\urls.txt" "C:\Users\hsing\AppData\Local\Temp\opencode\crawl_results.json"
```


## 3. Click-through highlights

**A. Secret reveal + audit (covers former F-01/F-03).**
Open an employee → **HR Security** → note PAN/Aadhaar show masked last-4 → click a
**Reveal** button → a sticky notification shows the full value → open **Compliance →
Audit Log**, filter *Sensitive reads*: a new `read_sensitive` row names you and the
field. (Reveal of Aadhaar requires *HR Manager*.)

**B. Statutory sign-off gate (must still refuse).**
**Statutory → Statutory Rule Versions → New**: pick e.g. `IN.PF.WAGE_CEILING`, set a
value and `effective_from`, leave `validated_by` empty → **Sign off** refuses. Set
`validated_by` to a **different** user than the author, save, **Sign off** → state
becomes *Validated* and the value fields lock. There is **no way** to make a value
live without a named validator who is not the author.

**C. Payroll period lock (maker-checker).**
**Compliance → Payroll Period Locks → New** (name, company, dates) → **Start review**
→ **Lock period** (records you as locker) → **Release** as the *same* user is refused
("segregation of duties"); log in as a second user (or reopen) to release.

**D. Payroll run refuses to compute.**
**Payroll → Payroll Runs → New** (establishment + period) → **Compute** should stop
and show **blocking issues / statutory coverage gap**, because no statutory code has
a signed-off value. That refusal is the **expected, correct** behaviour, not a bug.

## 4. Shell-based stories

UAT-01/02/03 intentionally inspect storage (ciphertext columns, append-only log) and
belong in the shell:

```bash
make odoo-shell
```
```python
env['ir.config_parameter'].sudo().set_param(
    'hrms.field_encryption_key',
    __import__('base64').b64encode(__import__('os').urandom(32)).decode())
e = env['hr.employee'].search([], limit=1)
e._hrms_set_enc('pan_number', 'ABCDE1234F')
print(e._hrms_reveal('pan_number', reason='manual'))
# then try (expect AccessError):
#   env['hrms.audit.log'].create({'name':'x','model':'hr.employee','action':'write'})
```

## 5. Re-run the automated evidence

```bash
make test-standalone                      # expect 190 passing
./ops/run_odoo_tests.sh --tests-only      # expect 114 tests, 0 failed, GATE_HOLDING
python3 tools/check_views.py              # expect 0 errors
```

> **Do not run `make test-odoo`** without `--tests-only`: the plain form drops the
> database volume and would erase the seeded data.

## 6. Marking results

Work the stories in `docs/manual-uat-stories.md`, replace `NOT RUN` with
**MANUALLY VERIFIED** (or a failure note) in your own review, and update
`docs/requirement-traceability.md`. The assistant will not do this for you.

## 7. What you will **not** see (by design, not defects)

- Real PF/ESI/PT/TDS/gratuity numbers — all 50 catalog codes are value-less
  skeletons; the sign-off gate holds (GATE_HOLDING). This is the safe state.
- Reports / Form 16 / payslip PDF, REST API/webhooks, AI chat — not built
  (gaps G11/G12, Phase 3/4).
- The 3 remaining known code gaps G3–G10 documented in `application-flow.md` §19.
