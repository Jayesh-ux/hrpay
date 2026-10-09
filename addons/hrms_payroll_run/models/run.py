# -*- coding: utf-8 -*-
"""Payroll run: the thing that either produces a defensible month or refuses to.

The run exists because "compute the payroll and save it" is too weak a unit of
work for statutory payroll. A run is a single attempt over a closed period, and
it carries four gates that must each be passed explicitly by a named person:

  draft -> computed -> reviewed -> approved -> locked

Two rules are enforced in the database rather than the interface:

* **Coverage.** A run cannot be computed while any employee in scope lacks a
  signed-off statutory configuration. Computing a month in which one employee
  silently receives no PF is worse than not computing at all, because it looks
  finished.

* **Immutability.** Once computed, the result set is frozen by checksum. A later
  edit to a salary component, a rule version or an attendance record cannot
  silently change what was paid; it produces a checksum mismatch, which blocks
  the lock.

Anomaly flags from the AI layer are advisory. They count, they are shown, and
the locker must record a judgement, but they never block by themselves: a
machine's suspicion is not an authority, and letting it stop payroll hands
control of the payroll calendar to a scoring function.
"""

import hashlib
import json
import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PayrollRun(models.Model):
    _name = "hrms.payroll.run"
    _description = "Payroll run"
    _order = "period_start desc, id desc"

    name = fields.Char(
        compute="_compute_name", store=True,
        help="Always includes the establishment and period, because a run for "
        "'March' is ambiguous the moment there is more than one establishment.",
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    establishment_id = fields.Many2one(
        "hr.department",
        string="Establishment",
        required=True,
        index=True,
        help="Statutory rules are resolved per establishment, so a run is "
        "per-establishment. A combined run would have to choose one State's "
        "rules for all of them.",
    )
    period_lock_id = fields.Many2one("payroll.period.lock", ondelete="restrict", copy=False)
    period_start = fields.Date(required=True, index=True)
    period_end = fields.Date(required=True, index=True)

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("computed", "Computed"),
            ("reviewed", "Reviewed"),
            ("approved", "Approved"),
            ("locked", "Locked"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        index=True,
        copy=False,
    )

    employee_count = fields.Integer(compute="_compute_counts", store=True)
    slip_count = fields.Integer(compute="_compute_counts", store=True)
    gross_total = fields.Monetary(compute="_compute_counts", store=True, currency_field="currency_id")
    net_total = fields.Monetary(compute="_compute_counts", store=True, currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    company_currency_id = fields.Many2one(related="company_id.currency_id")

    result_checksum = fields.Char(
        readonly=True, copy=False,
        help="Hash of every payslip amount in the run. Recomputed at lock time; "
        "a mismatch means a figure changed after the run was computed, which "
        "blocks the lock rather than silently paying the new number.",
    )
    input_checksum = fields.Char(
        compute="_compute_input_checksum", readonly=True, copy=False,
        help="Hash of the inputs: attendance, roster, contracts and the statutory "
        "rule versions in force. Detects that the basis changed, even when the "
        "outputs happen to be identical.",
    )
    rule_versions_json = fields.Text(readonly=True, copy=False)
    coverage_json = fields.Text(
        readonly=True, copy=False,
        help="Which statutory codes were resolved for this period and "
        "establishment. Empty for any employee means the run cannot proceed.",
    )

    ai_flags_count = fields.Integer(
        readonly=True, copy=False,
        help="Anomalies raised by the advisory layer. Never blocks the run; the "
        "reviewer records a judgement in review_note.",
    )
    ai_flags_json = fields.Text(readonly=True, copy=False)
    ai_flags_acknowledged = fields.Boolean(readonly=True, copy=False)

    blocking_issues = fields.Text(
        compute="_compute_blocking_issues",
        help="Why this run cannot proceed, if it cannot. Empty means it can.",
    )

    computed_at = fields.Datetime(readonly=True, copy=False)
    computed_by_id = fields.Many2one("res.users", readonly=True, copy=False, ondelete="restrict")
    reviewed_by_id = fields.Many2one("res.users", readonly=True, copy=False, ondelete="restrict")
    reviewed_at = fields.Datetime(readonly=True, copy=False)
    review_note = fields.Text(
        readonly=True, copy=False,
        help="Required. Records what the reviewer considered, including whether "
        "anomaly flags were accepted or dismissed and why.",
    )
    approved_by_id = fields.Many2one("res.users", readonly=True, copy=False, ondelete="restrict")
    approved_at = fields.Datetime(readonly=True, copy=False)
    locked_by_id = fields.Many2one("res.users", readonly=True, copy=False, ondelete="restrict")
    locked_at = fields.Datetime(readonly=True, copy=False)

    _sql_constraints = [
        (
            "one_run_per_establishment_period",
            "UNIQUE(establishment_id, period_start, period_end)",
            "Only one run per establishment and period. Two concurrent runs "
            "would produce two conflicting sets of payslips for the same people.",
        ),
        (
            "period_dates_ordered",
            "CHECK (period_end >= period_start)",
            "Run period end must not precede its start.",
        ),
    ]

    # ─── Computes ───────────────────────────────────────────────────────
    @api.depends("establishment_id", "period_start", "period_end")
    def _compute_name(self):
        for run in self:
            run.name = (
                f"{run.establishment_id.name or ''} "
                f"{run.period_start} to {run.period_end}"
            ).strip()

    @api.depends("period_start", "period_end", "state", "establishment_id")
    def _compute_counts(self):
        Slip = self.env["hr.payslip"]
        for run in self:
            slips = Slip.search(run._slip_domain())
            run.slip_count = len(slips)
            run.employee_count = len({s.employee_id.id for s in slips})
            run.gross_total = sum(sum(l.total for l in s.line_ids) for s in slips)
            run.net_total = sum(
                s.net_amount if "net_amount" in s._fields else sum(l.total for l in s.line_ids)
                for s in slips
            )

    @api.depends("period_start", "period_end", "establishment_id", "state")
    def _compute_input_checksum(self):
        for run in self:
            payload = run._input_payload()
            run.input_checksum = hashlib.sha256(
                json.dumps(payload, sort_keys=True, default=str).encode()
            ).hexdigest()

    @api.depends("state", "coverage_json", "ai_flags_count", "ai_flags_acknowledged")
    def _compute_blocking_issues(self):
        for run in self:
            issues = []
            if run.state in ("draft",):
                missing = _coverage_gaps(run)
                if missing:
                    issues.append(
                        f"{len(missing)} employee(s) in scope have no signed-off "
                        "statutory configuration. A run must not compute while "
                        "one employee would silently receive no statutory "
                        "deduction. Codes missing: "
                        + ", ".join(sorted({m for gaps in missing.values() for m in gaps})[:12])
                    )
                unrostered = run._unrostered_employees()
                if unrostered:
                    issues.append(
                        f"{len(unrostered)} employee(s) in scope have no roster "
                        "assignments for this period. Their hours are unknown, "
                        "so the run would either pay nothing or guess."
                    )
                missing_wage = run._employees_without_wage()
                if missing_wage:
                    issues.append(
                        f"{len(missing_wage)} employee(s) have no contract wage: "
                        + ", ".join(missing_wage[:5])
                    )
            if run.ai_flags_count and not run.ai_flags_acknowledged:
                issues.append(
                    f"{run.ai_flags_count} advisory anomaly flag(s) are "
                    "unacknowledged. They do not block the run, but a reviewer "
                    "must record a judgement before approval."
                )
            run.blocking_issues = "\n".join(issues)

    # ─── Domain helpers ─────────────────────────────────────────────────
    def _slip_domain(self):
        self.ensure_one()
        return [
            ("employee_id.company_id", "=", self.company_id.id),
            ("date_from", ">=", self.period_start),
            ("date_to", "<=", self.period_end),
        ]

    def _scope_employees(self):
        """Employees this run must cover: everyone active at any point in it."""
        self.ensure_one()
        Employee = self.env["hr.employee"]
        domain = [("company_id", "=", self.company_id.id)]
        if self.establishment_id.hrms_is_establishment:
            domain += [
                "|",
                ("hrms_establishment_id", "=", self.establishment_id.id),
                ("department_id", "=", self.establishment_id.id),
            ]
        domain += [
            "|",
            ("join_date", "<=", self.period_end),
            ("join_date", "=", False),
        ]
        if self.period_start:
            domain += [
                "|",
                ("hrms_last_working_day", ">=", self.period_start),
                ("hrms_last_working_day", "=", False),
            ]
        return Employee.search(domain)

    def _input_payload(self):
        """Inputs that determine the run's figures, hashed for tamper evidence."""
        self.ensure_one()
        employees = self._scope_employees()
        assignments = self.env["hr.roster.assignment"].sudo().search(
            [
                ("company_id", "=", self.company_id.id),
                ("start_datetime", ">=", f"{self.period_start} 00:00:00"),
                ("start_datetime", "<=", f"{self.period_end} 23:59:59"),
            ]
        )
        versions = {}
        ctx = self.env["hrms.statutory.context"]
        for employee in employees:
            try:
                versions[employee.id] = ctx._snapshot(
                    self.company_id,
                    employee.hrms_state_code,
                    employee.contract_type,
                    self.period_end,
                )
            except UserError as exc:
                versions[employee.id] = {"error": str(exc)}
        return {
            "period": [str(self.period_start), str(self.period_end)],
            "establishment": self.establishment_id.id,
            "employees": sorted(
                (
                    e.id,
                    e.join_date and str(e.join_date),
                    e.contract_id.wage,
                    e.contract_type,
                    e.hrms_tax_regime,
                )
                for e in employees
            ),
            "assignments": sorted(
                (a.id, a.employee_id.id, a.shift_id.id, str(a.start_datetime),
                 str(a.end_datetime), a.actual_hours, a.approved_overtime_hours)
                for a in assignments
            ),
            "rule_versions": versions,
        }

    def _unrostered_employees(self):
        self.ensure_one()
        rostered = {
            a.employee_id.id
            for a in self.env["hr.roster.assignment"].sudo().search(
                [
                    ("company_id", "=", self.company_id.id),
                    ("start_datetime", ">=", f"{self.period_start} 00:00:00"),
                    ("start_datetime", "<=", f"{self.period_end} 23:59:59"),
                ]
            )
        }
        return [
            e.name
            for e in self._scope_employees()
            if e.id not in rostered and self.establishment_id.hrms_rostered
        ]

    def _employees_without_wage(self):
        self.ensure_one()
        return [
            e.name
            for e in self._scope_employees()
            if not e.contract_id or not e.contract_id.wage
        ]

    # ─── Lifecycle ──────────────────────────────────────────────────────
    def action_compute(self):
        """Compute the run. Refuses while coverage is incomplete."""
        for run in self:
            if run.state != "draft":
                raise UserError(
                    f"{run.name}: cannot compute a run in state '{run.state}'."
                )
            issues = _issues_list(run)
            blocking = [i for i in issues if "advisory" not in i]
            if blocking:
                raise UserError(
                    f"{run.name} cannot be computed:\n\n"
                    + "\n".join(f"- {i}" for i in blocking)
                )
            run._action_create_payslips()
            run.result_checksum = run._result_checksum()
            run.rule_versions_json = json.dumps(
                run._rule_version_summary(), indent=2, sort_keys=True, default=str
            )
            run.coverage_json = json.dumps(
                run._coverage_summary(), indent=2, sort_keys=True, default=str
            )
            run.computed_at = fields.Datetime.now()
            run.computed_by_id = self.env.user
            run.state = "computed"
            self.env["hrms.audit.log"].log(
                run._name, run.id, "create",
                changes={"result_checksum": run.result_checksum},
                note=f"Payroll computed: {run.employee_count} employees, "
                     f"gross {run.gross_total:,.2f}",
            )
        return True

    def _action_create_payslips(self):
        """Create one draft payslip per employee in scope.

        Draft, never confirmed: this stage records what the engine produced.
        Confirmation is a separate human act after review.
        """
        Slip = self.env["hr.payslip"].sudo()
        Structure = self.env["hr.payroll.structure"].sudo()
        existing = Slip.search(self._slip_domain())
        if existing:
            existing.unlink()
        structures = Structure.search(
            [("company_id", "in", (False, self.company_id.id))]
        )
        if not structures:
            raise UserError(
                f"{self.name}: no salary structure is configured. The run "
                "cannot be computed, and guessing a structure would produce a "
                "payroll nobody intended."
            )
        structure = structures[0]
        slips = self.env["hr.payslip"]
        for employee in self._scope_employees():
            slips |= Slip.create(
                {
                    "employee_id": employee.id,
                    "date_from": self.period_start,
                    "date_to": self.period_end,
                    "name": f"{self.period_start} - {self.period_end} ({employee.name})",
                    "struct_id": structure.id,
                    "state": "draft",
                }
            )
        # compute_sheet runs the component lines. Failures must stop the run,
        # not leave a half-computed payslip set behind.
        try:
            slips._compute_sheet()
        except Exception as exc:
            _logger.error("hrms_payroll_run: compute_sheet failed for %s: %s", self.name, exc)
            raise UserError(
                f"{self.name}: payslip computation failed ({exc}). Nothing has "
                "been saved; fix the salary structure and recompute."
            ) from exc
        return slips

    def _result_checksum(self):
        self.ensure_one()
        digest = hashlib.sha256()
        for slip in self.env["hr.payslip"].sudo().search(self._slip_domain()):
            digest.update(
                f"{slip.employee_id.id}|{slip.date_from}|{slip.date_to}|"
                f"{round(sum(l.total for l in slip.line_ids), 2)}".encode()
            )
        return digest.hexdigest()

    def _rule_version_summary(self):
        self.ensure_one()
        ctx = self.env["hrms.statutory.context"]
        out = {}
        for employee in self._scope_employees():
            out[str(employee.id)] = ctx._snapshot(
                self.company_id,
                employee.hrms_state_code,
                employee.contract_type,
                self.period_end,
            )
        return out

    def _coverage_summary(self):
        self.ensure_one()
        gaps = _coverage_gaps(self)
        return {
            "employees_in_scope": len(self._scope_employees()),
            "employees_with_gaps": {
                emp.name: codes for emp, codes in gaps.items()
            },
        }

    def action_review(self, note):
        """Record a human review. Note is mandatory, flags must be acknowledged."""
        for run in self:
            if run.state != "computed":
                raise UserError(
                    f"{run.name}: only a computed run can be reviewed; this one "
                    f"is '{run.state}'."
                )
            if self.env.user._is_superuser():
                raise UserError(
                    f"{run.name}: review as a named Payroll Admin. A superuser "
                    "review cannot be attributed to a person."
                )
            if run.computed_by_id == self.env.user:
                raise UserError(
                    f"{run.name}: you computed this run, so you cannot also "
                    "review it. Segregation of duties requires a second person."
                )
            if run.ai_flags_count and not note:
                raise UserError(
                    f"{run.name} carries {run.ai_flags_count} anomaly flag(s). "
                    "Record what you concluded about them before approving."
                )
            if not note or not note.strip():
                raise UserError("A review must record what was checked.")
            run.review_note = note
            run.ai_flags_acknowledged = True
            run.reviewed_by_id = self.env.user
            run.reviewed_at = fields.Datetime.now()
            run.state = "reviewed"
            self.env["hrms.audit.log"].log(
                run._name, run.id, "approve", note=f"Reviewed: {note}",
            )
        return True

    def action_approve(self):
        """Finance approval. Cannot be the same person who computed or reviewed."""
        for run in self:
            if run.state != "reviewed":
                raise UserError(
                    f"{run.name}: only a reviewed run can be approved; this one "
                    f"is '{run.state}'."
                )
            if self.env.user._is_superuser():
                raise UserError(
                    f"{run.name}: approve as a named Finance Approver."
                )
            if run.computed_by_id == self.env.user:
                raise UserError("You cannot approve a run you computed.")
            if run.reviewed_by_id == self.env.user:
                raise UserError("You cannot approve a run you reviewed.")
            if run._current_result_checksum() != run.result_checksum:
                raise UserError(
                    f"{run.name}: the payslips changed after this run was "
                    "computed. Recompute so the approved figures match the "
                    "current data, or investigate what moved."
                )
            run.approved_by_id = self.env.user
            run.approved_at = fields.Datetime.now()
            run.state = "approved"
            self.env["hrms.audit.log"].log(
                run._name, run.id, "approve",
                note=f"Approved {run.slip_count} payslips, net {run.net_total:,.2f}",
            )
        return True

    def action_lock(self):
        """Freeze the run and its period. The point of no return."""
        for run in self:
            if run.state != "approved":
                raise UserError(
                    f"{run.name}: only an approved run can be locked; this one "
                    f"is '{run.state}'."
                )
            current = run._current_result_checksum()
            if current != run.result_checksum:
                raise UserError(
                    f"{run.name}: refusing to lock. The payslips no longer match "
                    "the computed checksum. Locking would make the record "
                    "internally inconsistent."
                )
            slips = self.env["hr.payslip"].sudo().search(self._slip_domain())
            draft = slips.filtered(lambda s: s.state == "draft")
            if draft:
                raise UserError(
                    f"{run.name}: {len(draft)} payslip(s) are still draft. A "
                    "locked run cannot contain unconfirmed figures."
                )
            period = run.period_lock_id
            if not period:
                raise UserError(
                    f"{run.name}: link a payroll period lock before locking."
                )
            if period.state == "locked":
                raise UserError(
                    f"{run.name}: payroll period '{period.name}' is already "
                    "locked. A period may only be locked once."
                )
            period.action_lock()
            for slip in slips:
                if slip.state in ("draft", "confirm"):
                    slip.action_sheet_confirm()
                if slip.state == "confirm":
                    slip.action_sheet_done()
            run.locked_by_id = self.env.user
            run.locked_at = fields.Datetime.now()
            run.state = "locked"
            self.env["hrms.audit.log"].log(
                run._name, run.id, "lock",
                note=f"Locked against period '{period.name}'",
            )
        return True

    def _current_result_checksum(self):
        return self._result_checksum()

    def action_cancel(self):
        """Cancel a run that has not been locked.

        Refused after lock, always. A locked month is the reference for what was
        actually paid; reversing it means an adjustment, not a cancellation.
        """
        for run in self:
            if run.state == "locked":
                raise UserError(
                    f"{run.name} is locked and cannot be cancelled. Process an "
                    "adjustment run for the affected period instead, so both "
                    "figures remain auditable."
                )
            if not run.review_note and not run.ai_flags_count:
                reason = run.env.context.get("cancel_reason")
                if not reason:
                    raise UserError(
                        "Cancelling a computed run requires a recorded reason."
                    )
                run.review_note = f"cancelled: {reason}"
            run.state = "cancelled"
            self.env["hrms.audit.log"].log(
                run._name, run.id, "reject",
                note=run.review_note or "cancelled",
            )
        return True

    def action_record_ai_flags(self, flags_json):
        """Advisory flags from the AI layer. Recorded, never blocking."""
        for run in self:
            if run.state in ("locked", "cancelled"):
                raise UserError(
                    f"{run.name}: flags cannot be attached to a "
                    f"'{run.state}' run."
                )
            try:
                flags = json.loads(flags_json)
            except ValueError as exc:
                raise UserError(f"flags are not valid JSON: {exc}") from exc
            run.ai_flags_json = flags_json
            run.ai_flags_count = len(flags) if isinstance(flags, list) else 1
            run.ai_flags_acknowledged = False
        return True

    @api.model
    def create_run(self, establishment, period_end):
        """Open a run for the month ending ``period_end``."""
        return self.create(
            {
                "establishment_id": establishment.id,
                "period_start": date(period_end.year, period_end.month, 1),
                "period_end": period_end,
            }
        )

    # ─── Guards ─────────────────────────────────────────────────────────
    def write(self, vals):
        if "period_start" in vals or "period_end" in vals or "establishment_id" in vals:
            for run in self:
                if run.state != "draft":
                    raise UserError(
                        f"{run.name}: the period cannot be changed after the run "
                        "leaves draft. The figures were computed against those "
                        "dates."
                    )
        return super().write(vals)

    def unlink(self):
        if any(run.state != "cancelled" for run in self):
            raise UserError(
                "Only a cancelled run can be deleted. A computed or locked run is "
                "a financial record."
            )
        return super().unlink()


def _issues_list(run):
    return [i for i in (run.blocking_issues or "").split("\n") if i.strip()]


def _coverage_gaps(run):
    """Employees in scope missing a signed-off statutory configuration.

    A gap is not "this particular code is absent" but "resolving statutory
    context for this employee raises", because that is the condition that would
    actually break a run.
    """
    ctx = run.env["hrms.statutory.context"]
    gaps = {}
    for employee in run._scope_employees():
        missing = []
        try:
            rows = ctx._snapshot(
                run.company_id,
                employee.hrms_state_code,
                employee.contract_type,
                run.period_end,
            )
        except UserError as exc:
            missing.append(str(exc).split(".")[0])
        else:
            if not rows:
                missing.append("no signed-off statutory configuration in scope")
        if missing:
            gaps[employee] = missing
    return gaps
