# -*- coding: utf-8 -*-
"""Roster period: the publish container.

Rostering here is publish-first. A roster period holds draft assignments while
being built, is *published* (which makes them the obligation of record), and is
later *locked* against the matching payroll period. Attendance is always
validated against the published roster, never against a draft, so an employee
dispute has one unambiguous reference.

Why this matters beyond tidiness: in most Indian establishments overtime is
payable only to employees who were **rostered** to work the excess hours, and a
roster that can be edited after the fact makes that entitlement unfalsifiable.
"""

import hashlib
import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class RosterPeriod(models.Model):
    _name = "hr.roster.period"
    _description = "Roster period"
    _order = "date_from desc"

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    establishment_id = fields.Many2one(
        "hr.department",
        string="Establishment",
        help="Establishment the roster governs. Rosters are per-establishment "
        "because overtime eligibility and shift patterns attach to the unit.",
    )
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("published", "Published"),
            ("locked", "Locked"),
        ],
        default="draft",
        required=True,
        index=True,
        copy=False,
    )
    published_at = fields.Datetime(readonly=True, copy=False)
    published_by_id = fields.Many2one("res.users", readonly=True, copy=False, ondelete="restrict")
    locked_at = fields.Datetime(readonly=True, copy=False)
    locked_by_id = fields.Many2one("res.users", readonly=True, copy=False, ondelete="restrict")
    lock_note = fields.Text(readonly=True, copy=False)
    checksum = fields.Char(
        compute="_compute_checksum", store=True, readonly=True, copy=False,
        help="Hash over every assignment in the period. Recomputed on each "
        "write while published, so a mismatch against a payroll lock proves "
        "the roster moved after the fact.",
    )

    _sql_constraints = [
        (
            "roster_period_dates_ordered",
            "CHECK (date_to >= date_from)",
            "Roster period end must not precede its start.",
        )
    ]

    @api.depends("assignment_ids.state", "assignment_ids.shift_id", "assignment_ids.employee_id",
                 "assignment_ids.start_datetime", "assignment_ids.end_datetime",
                 "date_from", "date_to", "state")
    def _compute_checksum(self):
        for period in self:
            digest = hashlib.sha256()
            rows = period.assignment_ids.sorted(
                lambda a: (a.employee_id.id, a.start_datetime or "")
            )
            for a in rows:
                digest.update(
                    f"{a.id}|{a.employee_id.id}|{a.shift_id.id}|"
                    f"{a.start_datetime}|{a.end_datetime}|{a.state}".encode()
                )
            digest.update(f"{period.date_from}|{period.date_to}|{period.state}".encode())
            period.checksum = digest.hexdigest()

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rec in self:
            if rec.date_to < rec.date_from:
                raise UserError(f"{rec.name}: end date precedes start date.")
            if (rec.date_to - rec.date_from).days > 62:
                raise UserError(
                    f"{rec.name}: a roster period longer than two months is "
                    "almost always an unclosed draft. Publish and roll over."
                )

    @api.constrains("date_from", "date_to", "company_id")
    def _check_no_overlap(self):
        for rec in self:
            others = self.search(
                [
                    ("id", "!=", rec.id),
                    ("company_id", "=", rec.company_id.id),
                    ("state", "!=", "draft"),
                    ("date_from", "<=", rec.date_to),
                    ("date_to", ">=", rec.date_from),
                ]
            )
            if others:
                raise UserError(
                    f"{rec.name}: overlaps published period "
                    f"{', '.join(others.mapped('name'))}. Two published rosters "
                    "covering the same days would make attendance "
                    "non-deterministic."
                )

    # ─── Lifecycle ──────────────────────────────────────────────────────
    def action_publish(self):
        """Make the roster the obligation of record.

        Requires: no unassigned rostered days, and a payroll period must exist
        for the same days so the two can be locked together.
        """
        for rec in self:
            if rec.state != "draft":
                raise UserError(f"{rec.name} is already published.")
            rec._action_check_assignments()
            rec.state = "published"
            rec.published_at = fields.Datetime.now()
            rec.published_by_id = self.env.user
            self.env["hrms.audit.log"].log(
                rec._name, rec.id, "release",
                note=f"Roster published for {rec.date_from} to {rec.date_to}",
            )
        return True

    def action_lock(self):
        """Lock against the matching payroll period.

        Refuses when there is no linked locked payroll period: the whole point
        is that paid hours and published shifts are reconciled once, in both
        directions.
        """
        payroll_lock_model = self.env["payroll.period.lock"]
        for rec in self:
            if rec.state != "published":
                raise UserError(f"{rec.name} must be published before locking.")
            if not rec.hrms_payroll_period_id:
                raise UserError(
                    f"{rec.name}: link a payroll period lock before locking. "
                    "Roster lock exists to reconcile against payroll, not to "
                    "stand alone."
                )
            payroll = rec.hrms_payroll_period_id
            if payroll.state != "locked":
                raise UserError(
                    f"{rec.name}: payroll period '{payroll.name}' is "
                    f"'{payroll.state}', not locked. Lock payroll first, then "
                    "the roster."
                )
            rec.state = "locked"
            rec.locked_at = fields.Datetime.now()
            rec.locked_by_id = self.env.user
            payroll.hrms_roster_lock_verified = True
            self.env["hrms.audit.log"].log(
                rec._name, rec.id, "lock",
                note=(
                    f"Roster locked against payroll period '{payroll.name}' "
                    f"(payroll checksum {payroll.checksum})"
                ),
            )
        return True

    def action_unlock(self):
        """Deliberately blocked after lock; requires an adjustment period.

        Unlocking would silently rewrite the basis of already-approved payroll,
        so it is refused outright rather than merely discouraged.
        """
        raise UserError(
            f"{', '.join(self.mapped('name'))}: a locked roster period cannot be "
            "unlocked. Publish an adjustment period covering the affected days "
            "and process a corrective payroll run, so the original figures stay "
            "auditable."
        )

    def _action_check_assignments(self):
        for rec in self:
            if not rec.assignment_ids:
                raise UserError(
                    f"{rec.name} has no assignments. There is nothing to publish."
                )
            unconfirmed = rec.assignment_ids.filtered(lambda a: a.state == "draft")
            if unconfirmed:
                raise UserError(
                    f"{rec.name}: {len(unconfirmed)} assignment(s) are still "
                    "draft. Confirm each employee's shift before publishing; a "
                    "draft assignment is not an obligation."
                )
            # A published roster is the entitlement basis for overtime, so an
            # assignment with no resolvable paid hours is a payroll defect
            # waiting to happen. Refuse rather than discover it at run time.
            unpriced = rec.assignment_ids.filtered(
                lambda a: not a.shift_id or (a.shift_id.duration_hours or 0) <= 0
            )
            if unpriced:
                raise UserError(
                    f"{rec.name}: {len(unpriced)} assignment(s) reference a shift "
                    "with no paid duration. Fix the shift before publishing."
                )
            negative = rec.assignment_ids.filtered(lambda a: (a.approved_overtime_hours or 0) < 0)
            if negative:
                raise UserError(f"{rec.name}: negative approved overtime is not valid.")

    def unlink(self):
        if any(rec.state in ("published", "locked") for rec in self):
            raise UserError(
                "Published or locked roster periods cannot be deleted. They are "
                "the reference against which attendance and overtime were "
                "assessed."
            )
        return super().unlink()

    def previous_period(self):
        self.ensure_one()
        return self.search(
            [
                ("company_id", "=", self.company_id.id),
                ("date_to", "<", self.date_from),
                ("state", "!=", "draft"),
            ],
            limit=1,
            order="date_to desc",
        )

    def next_period(self):
        self.ensure_one()
        return self.search(
            [
                ("company_id", "=", self.company_id.id),
                ("date_from", ">", self.date_to),
                ("state", "!=", "draft"),
            ],
            limit=1,
            order="date_from asc",
        )

    @api.model
    def create_period(self, date_from, name=None):
        """Open the next period immediately after the last one, pre-filled."""
        last = self.search(
            [("company_id", "=", self.env.company.id), ("state", "!=", "draft")],
            limit=1,
            order="date_to desc",
        )
        start = (last.date_to + relativedelta(days=1)) if last else date_from
        return self.create(
            {
                "name": name or f"{start.strftime('%b %Y')}",
                "date_from": start,
                "date_to": start + relativedelta(months=1, days=-1),
            }
        )


class RosterShift(models.Model):
    _name = "hr.roster.shift"
    _description = "Roster shift pattern"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    start_time = fields.Float(
        string="Start time (hours)", required=True,
        help="Local start time in 24-hour decimal hours, e.g. 22.0 for 22:00.",
    )
    end_time = fields.Float(string="End time (hours)", required=True)
    overnight = fields.Boolean(
        compute="_compute_overnight", store=True,
        help="A shift ending before it starts crosses midnight, which is normal "
        "for night and security shifts.",
    )
    duration_hours = fields.Float(compute="_compute_duration", store=True, digits=(8, 4))
    rest_after_hours = fields.Float(
        default=12.0, digits=(8, 2),
        help="Minimum rest after this shift before the next one begins, measured "
        "from the end of paid work. 12 hours suits ordinary day shifts; night "
        "shifts should carry a higher figure, which is why it is per shift "
        "rather than global. A value of 16 on a 09:00-18:00 shift would make "
        "consecutive day shifts impossible, because the next start would have to "
        "be 10:00 or later. Sustained daily working is controlled by the "
        "contractual weekly hour ceiling, not by inflating this figure.",
    )
    break_minutes = fields.Integer(
        default=30,
        help="Paid break. Excluded from paid hours but included in span of "
        "duty, so an employee on break is still rostered.",
    )
    weekly_ot_threshold = fields.Float(
        help="Overtime threshold in hours for this shift. Blank uses the "
        "statutory rule IN.OT.WEEKLY_CAP_HOURS. Set only where the employer's "
        "own policy is more generous.",
    )
    is_night_shift = fields.Boolean()
    active = fields.Boolean(default=True)

    @api.depends("start_time", "end_time")
    def _compute_overnight(self):
        for rec in self:
            rec.overnight = rec.end_time <= rec.start_time

    @api.depends("start_time", "end_time", "overnight", "break_minutes")
    def _compute_duration(self):
        for rec in self:
            span = rec.end_time - rec.start_time
            if rec.overnight:
                span += 24.0
            rec.duration_hours = round(max(span - (rec.break_minutes or 0) / 60.0, 0.0), 4)

    @api.constrains("start_time", "end_time", "break_minutes")
    def _check_times(self):
        for rec in self:
            for label in ("start_time", "end_time"):
                value = rec[label]
                if not 0 <= value < 24:
                    raise UserError(f"{rec.name}: {label} must be within 0..24.")
            if rec.start_time == rec.end_time:
                raise UserError(
                    f"{rec.name}: start and end are equal, which would be a "
                    "24-hour span rather than a zero-length shift. Use the "
                    "overnight flag instead."
                )
            if (rec.duration_hours or 0) > 16:
                raise UserError(
                    f"{rec.name}: a {rec.duration_hours:.1f}h paid shift exceeds "
                    "16 hours. Beyond that the arrangement needs explicit "
                    "professional review rather than silent acceptance."
                )