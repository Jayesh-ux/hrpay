# -*- coding: utf-8 -*-
"""Roster assignment: one employee, one shift, one date.

Two separate datetimes rather than a date plus a shift template, because night
shifts cross midnight and an overnight shift on the 1st starts on the 1st but
finishes on the 2nd. Storing resolved datetimes keeps the attendance comparison
and the overtime arithmetic unambiguous, and lets the solver move an assignment
to a different date without touching payroll.

``approved_overtime_hours`` is separated from actual attendance because overtime
is a *claim*: the employee worked extra and is entitled to pay. That entitlement
requires approval before payroll, so an unapproved claim is visible as a
pending item rather than being quietly paid.
"""

import hashlib
import logging
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RosterAssignment(models.Model):
    _name = "hr.roster.assignment"
    _description = "Roster assignment"
    _order = "start_datetime, id"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    roster_period_id = fields.Many2one(
        "hr.roster.period",
        string="Roster period",
        required=True,
        ondelete="cascade",
        index=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        ondelete="cascade",
        index=True,
        help="Employee rostered. Restricted to the establishment of the roster "
        "period where a per-establishment establishment rule applies.",
    )
    contract_id = fields.Many2one(
        "hr.contract",
        help="Contract the assignment runs under. Defaults to the employee's "
        "current contract so a mid-contract roster cannot be costed at the "
        "wrong wage.",
    )
    shift_id = fields.Many2one("hr.roster.shift", required=True, ondelete="restrict")

    start_datetime = fields.Datetime(required=True, index=True)
    end_datetime = fields.Datetime(required=True)
    span_of_duty_hours = fields.Float(
        compute="_compute_hours", store=True, digits=(8, 4),
        help="Start to end including the paid break. This is what the employee "
        "was rostered to be present for.",
    )
    paid_hours = fields.Float(
        compute="_compute_hours", store=True, digits=(8, 4),
        help="Span of duty minus the shift's paid break. The denominator for "
        "overtime entitlement.",
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("published", "Published"),
            ("relieved", "Relieved (swap approved)"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        index=True,
        copy=False,
    )
    actual_hours = fields.Float(
        help="Hours actually worked, filled from validated attendance. Never "
        "entered by hand.",
    )
    overtime_hours = fields.Float(
        compute="_compute_hours", store=True, digits=(8, 4),
        help="Hours worked beyond the rostered paid hours. Clamped at zero: "
        "working less than rostered is short time, not negative overtime.",
    )
    approved_overtime_hours = fields.Float(
        default=0.0, digits=(8, 4),
        help="Overtime hours approved for payment. Set by a manager "
        "acknowledging the claim. Only approved hours reach payroll.",
    )
    overtime_approved_by_id = fields.Many2one("res.users", ondelete="restrict", copy=False)
    overtime_approved_at = fields.Datetime(copy=False, readonly=True)
    overtime_rejection_reason = fields.Text(
        help="Required when overtime is declined, so the employee is not left "
        "with an unexplained zero.",
    )

    swap_requested_by_id = fields.Many2one("hr.employee", string="Swap requested by", copy=False)
    swap_with_employee_id = fields.Many2one("hr.employee", string="Swap with", copy=False)
    swap_approved_by_id = fields.Many2one("res.users", copy=False)
    swap_note = fields.Text()

    note = fields.Text()
    checksum = fields.Char(compute="_compute_name_hash", store=True, copy=False)

    _sql_constraints = [
        (
            "assignment_no_overlap",
            "UNIQUE(employee_id, start_datetime)",
            "An employee cannot hold two overlapping rostered assignments.",
        )
    ]

    # ─── Computes ───────────────────────────────────────────────────────
    @api.depends("employee_id", "start_datetime", "shift_id.name")
    def _compute_name(self):
        for rec in self:
            rec.name = (
                f"{rec.employee_id.name or ''} / "
                f"{(rec.start_datetime or datetime(1970, 1, 1)).strftime('%d %b %H:%M')} "
                f"{rec.shift_id.name or ''}"
            ).strip(" /")

    @api.depends(
        "start_datetime", "end_datetime", "shift_id.break_minutes",
        "shift_id.duration_hours", "actual_hours", "approved_overtime_hours",
    )
    def _compute_hours(self):
        for rec in self:
            if rec.start_datetime and rec.end_datetime:
                span = (rec.end_datetime - rec.start_datetime).total_seconds() / 3600.0
            else:
                span = 0.0
            rec.span_of_duty_hours = round(max(span, 0.0), 4)
            if rec.shift_id and rec.shift_id.duration_hours:
                paid = rec.shift_id.duration_hours
            else:
                paid = max(span - (rec.shift_id.break_minutes or 0) / 60.0, 0.0)
            rec.paid_hours = round(min(paid, span), 4) if span else round(paid, 4)
            rec.overtime_hours = round(max((rec.actual_hours or 0.0) - rec.paid_hours, 0.0), 4)

    @api.depends("employee_id", "start_datetime", "end_datetime", "shift_id",
                 "actual_hours", "approved_overtime_hours", "state")
    def _compute_name_hash(self):
        for rec in self:
            rec.checksum = hashlib.sha256(
                f"{rec.employee_id.id}|{rec.start_datetime}|{rec.end_datetime}|"
                f"{rec.shift_id.id}|{rec.actual_hours}|{rec.approved_overtime_hours}|"
                f"{rec.state}".encode()
            ).hexdigest()

    # ─── Constraints ────────────────────────────────────────────────────
    @api.constrains("start_datetime", "end_datetime")
    def _check_window(self):
        for rec in self:
            if rec.end_datetime <= rec.start_datetime:
                raise UserError(
                    f"{rec.employee_id.name or 'Assignment'}: the assignment must "
                    "end after it starts. For an overnight shift, set the end to "
                    "the following day rather than an earlier time."
                )

    @api.constrains("employee_id", "start_datetime", "end_datetime")
    def _check_no_self_overlap(self):
        for rec in self:
            others = self.search(
                [
                    ("id", "!=", rec.id),
                    ("employee_id", "=", rec.employee_id.id),
                    ("state", "in", ("confirmed", "published", "relieved")),
                    ("start_datetime", "<", rec.end_datetime),
                    ("end_datetime", ">", rec.start_datetime),
                ],
                limit=1,
            )
            if others:
                raise UserError(
                    f"{rec.employee_id.name}: this assignment overlaps an "
                    f"existing rostered shift ({others[0].start_datetime} to "
                    f"{others[0].end_datetime}). Two overlapping obligations "
                    "cannot both be the record."
                )

    @api.constrains("approved_overtime_hours", "overtime_hours")
    def _check_approved_overtime(self):
        for rec in self:
            if rec.approved_overtime_hours < 0:
                raise UserError("Approved overtime cannot be negative.")
            if rec.approved_overtime_hours and not rec.overtime_approved_by_id:
                raise UserError(
                    f"{rec.display_name}: approving overtime requires a named "
                    "approver. Segregation of duties and audit both depend on it."
                )

    @api.constrains("actual_hours", "paid_hours", "span_of_duty_hours")
    def _check_actual_hours(self):
        for rec in self:
            if rec.actual_hours and rec.actual_hours < 0:
                raise UserError("Actual hours cannot be negative.")
            # A worked duration far beyond the roster is a missing checkout far
            # more often than real work, so refuse rather than price it.
            if rec.span_of_duty_hours and rec.actual_hours > rec.span_of_duty_hours * 1.5:
                raise UserError(
                    f"{rec.display_name}: actual hours ({rec.actual_hours:.2f}) "
                    f"exceed 150% of the rostered span "
                    f"({rec.span_of_duty_hours:.2f}). This usually means a "
                    "missing check-out. Correct the attendance before payroll."
                )

    # ─── Actions ────────────────────────────────────────────────────────
    def action_confirm(self):
        for rec in self:
            if rec.state != "draft":
                continue
            if rec.roster_period_id.state != "draft":
                raise UserError(
                    f"{rec.display_name}: roster period "
                    f"'{rec.roster_period_id.name}' is published, so its shifts "
                    "cannot be changed. Add an adjustment period instead."
                )
            rec.state = "confirmed"
        return True

    def action_set_published(self):
        self.filtered(lambda r: r.state == "confirmed").state = "published"
        return True

    def action_approve_overtime(self, hours=None, note=None):
        """Record approval of an overtime claim.

        Refuses a superuser approver: the point of approval is an attributable
        human decision.
        """
        for rec in self:
            if self.env.user._is_superuser():
                raise UserError(
                    f"{rec.display_name}: approve overtime as a named manager. A "
                    "superuser approval cannot be attributed to a person and "
                    "would not satisfy an audit."
                )
            if rec.employee_id.user_id == self.env.user:
                raise UserError("You cannot approve your own overtime claim.")
            amount = rec.overtime_hours if hours is None else float(hours)
            if amount < 0:
                raise UserError("Approved overtime cannot be negative.")
            if amount > rec.overtime_hours and not note:
                raise UserError(
                    f"{rec.display_name}: approving {amount:.2f}h against an "
                    f"overtime entitlement of {rec.overtime_hours:.2f}h requires "
                    "a written reason."
                )
            rec.approved_overtime_hours = amount
            rec.overtime_approved_by_id = self.env.user
            rec.overtime_approved_at = fields.Datetime.now()
            if note:
                rec.overtime_rejection_reason = note
            self.env["hrms.audit.log"].log(
                rec._name, rec.id, "approve",
                changes={"overtime_hours": rec.overtime_hours,
                         "approved_overtime_hours": amount},
                note=note or "Overtime approved",
            )
        return True

    def action_reject_overtime(self, reason):
        if not reason or not reason.strip():
            raise UserError(
                "Declining an overtime claim requires a reason. An unexplained "
                "zero is not a decision."
            )
        for rec in self:
            rec.approved_overtime_hours = 0.0
            rec.overtime_rejection_reason = reason
            rec.overtime_approved_by_id = self.env.user
            rec.overtime_approved_at = fields.Datetime.now()
            self.env["hrms.audit.log"].log(
                rec._name, rec.id, "reject",
                note=reason,
            )
        return True

    def unlink(self):
        if any(rec.state in ("published", "relieved") for rec in self):
            raise UserError(
                "Published assignments cannot be deleted; they are the reference "
                "for attendance and overtime already paid. Cancel the "
                "assignment instead, which keeps the record."
            )
        return super().unlink()

    def write(self, vals):
        """Freeze published assignments except for corrections we can explain."""
        if any(k in vals for k in ("start_datetime", "end_datetime", "shift_id", "employee_id")):
            for rec in self:
                if rec.state in ("published", "relieved"):
                    raise UserError(
                        f"{rec.display_name}: a published assignment cannot be "
                        "re-timed or reassigned. Publish an adjustment period "
                        "and process a corrective run, so the original roster "
                        "stays intact."
                    )
        return super().write(vals)


class RosterDemand(models.Model):
    """Required staffing per establishment per weekday.

    Input to the rostering solver. Kept as a simple requirement curve rather than
    a full workforce model because the solver's job is to fill a curve, and the
    curve is what the establishment manager actually knows.
    """

    _name = "hr.roster.demand"
    _description = "Roster staffing demand"
    _order = "establishment_id, weekday, shift_id"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    establishment_id = fields.Many2one("hr.department", string="Establishment", required=True)
    weekday = fields.Selection(
        [
            ("0", "Monday"), ("1", "Tuesday"), ("2", "Wednesday"),
            ("3", "Thursday"), ("4", "Friday"), ("5", "Saturday"),
            ("6", "Sunday"),
        ],
        required=True,
        index=True,
        help="Day of week the requirement applies to, Monday as 0.",
    )
    shift_id = fields.Many2one("hr.roster.shift", string="Shift", required=True)
    required_headcount = fields.Integer(required=True, default=1)
    required_skill_ids = fields.Many2many(
        "hr.skill", string="Required skills",
        help="Employees rostered to this demand must hold at least one of these.",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "demand_unique",
            "UNIQUE(establishment_id, weekday, shift_id)",
            "Only one demand row per establishment, weekday and shift.",
        )
    ]

    _WEEKDAYS = {
        "0": "Monday", "1": "Tuesday", "2": "Wednesday", "3": "Thursday",
        "4": "Friday", "5": "Saturday", "6": "Sunday",
    }

    @api.depends("establishment_id", "weekday", "shift_id")
    def _compute_name(self):
        for rec in self:
            day = self._WEEKDAYS.get(rec.weekday, rec.weekday or "")
            rec.name = (
                f"{rec.establishment_id.name or 'Roster'} / {day or ''} / "
                f"{rec.shift_id.name or ''}"
            ).strip(" /") or "Roster demand"

    @api.constrains("required_headcount")
    def _check_headcount(self):
        for rec in self:
            if rec.required_headcount < 0:
                raise UserError("Required headcount cannot be negative.")

    @api.model
    def total_for(self, establishment, weekday, date=None):
        """Required headcount for an establishment on a given day."""
        wd = str(date.weekday()) if date else weekday
        rows = self.search(
            [
                ("establishment_id", "=", establishment.id),
                ("weekday", "=", wd),
                ("active", "=", True),
            ]
        )
        return sum(rows.mapped("required_headcount"))

class RosterPeriod(models.Model):
    """Inverse of ``hr.roster.assignment.roster_period_id``.

    Declared here rather than in roster_period.py so the one2many sits beside
    the model it points at.
    """

    _inherit = "hr.roster.period"

    assignment_ids = fields.One2many(
        "hr.roster.assignment",
        "roster_period_id",
        string="Assignments",
    )
    assignment_count = fields.Integer(compute="_compute_assignment_count")

    @api.depends("assignment_ids")
    def _compute_assignment_count(self):
        counts = self.env["hr.roster.assignment"]._read_group(
            [("roster_period_id", "in", self.ids)],
            groupby=["roster_period_id"],
            aggregates=["__count"],
        )
        mapped = {period.id: count for period, count in counts}
        for rec in self:
            rec.assignment_count = mapped.get(rec.id, 0)

    def uncovered_demand(self):
        """Days where confirmed assignments fall short of the demand curve.

        Returned rather than merely warned about, because a short roster is the
        usual cause of unplanned overtime weeks later.
        """
        Demand = self.env["hr.roster.demand"]
        Assignment = self.env["hr.roster.assignment"]
        report = []
        for rec in self:
            day = rec.date_from
            while day and day <= rec.date_to:
                required = Demand.total_for(rec.establishment_id, None, date=day)
                if required:
                    start = fields.Datetime.to_string(
                        datetime.combine(day, datetime.min.time())
                    )
                    end = fields.Datetime.to_string(
                        datetime.combine(day, datetime.max.time())
                    )
                    filled = Assignment.search_count(
                        [
                            ("roster_period_id", "=", rec.id),
                            ("state", "in", ("confirmed", "published", "relieved")),
                            ("start_datetime", ">=", start),
                            ("start_datetime", "<=", end),
                        ]
                    )
                    if filled < required:
                        report.append(
                            {
                                "date": str(day),
                                "required": required,
                                "rostered": filled,
                                "short_by": required - filled,
                            }
                        )
                day += timedelta(days=1)
        return report
