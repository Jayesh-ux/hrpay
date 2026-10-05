# -*- coding: utf-8 -*-
"""Leave, attendance, contract and establishment extensions.

Small, targeted extensions to core Odoo models rather than new models, so that
core workflows (leave approval, attendance sheets) keep working while gaining the
fields the platform needs.
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrLeaveType(models.Model):
    """``payroll_code`` maps an approved leave to a payroll pay code.

    Required so that leave encashment in F&F, and paid-leave hours in the
    payroll hours push, resolve to a real pay code rather than a guess.
    """

    _inherit = "hr.leave.type"

    payroll_code = fields.Char(
        string="Payroll pay code",
        required=False,
        help="Pay code credited when this leave is taken, and used to value "
        "encashment at exit. Must match a configured pay code or leave "
        "encashment will be unpriceable.",
    )
    encashable = fields.Boolean(
        default=True,
        help="Whether unused balance of this leave type is encashable at exit. "
        "Statutory leave types must be encashable; discretionary types may not be.",
    )
    statutory = fields.Boolean(
        default=False,
        help="This is a statutory leave type. Statutory accrual and carry-forward "
        "rules come from statutory configuration, not company policy.",
    )
    max_carry_forward = fields.Integer(
        help="Blank = read from statutory config. Set only where company policy "
        "is more generous than the statutory minimum.",
    )
    encashment_formula = fields.Selection(
        [
            ("daily_wages", "Daily wages x days"),
            ("monthly_divisor", "Monthly salary / divisor x days"),
            ("average_last_m", "Average of last M months"),
            ("not_encashable", "Not encashable"),
        ],
        default="monthly_divisor",
    )


class HrLeave(models.Model):
    _inherit = "hr.leave"

    def action_validate(self):
        """Segregation of duties: nobody approves their own leave."""
        for rec in self:
            if rec.user_id and rec.user_id.id == self.env.uid:
                raise UserError(
                    "You cannot approve your own leave request. Route it to your "
                    "manager or HR (segregation of duties)."
                )
        return super().action_validate()

    def action_refuse(self):
        for rec in self:
            if rec.user_id and rec.user_id.id == self.env.uid:
                raise UserError("You cannot action your own leave request.")
        return super().action_refuse()


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    roster_assignment_id = fields.Many2one(
        "hr.roster.assignment",
        string="Roster assignment",
        ondelete="set null",
        index=True,
        help="Shift this attendance was validated against, when the employee "
        "was rostered.",
    )
    hrms_deviation_type = fields.Selection(
        [
            ("on_time", "On time"),
            ("late", "Late"),
            ("early", "Early departure"),
            ("absent", "Absent"),
            ("missing_checkout", "Missing check-out"),
            ("unrostered", "Worked outside roster"),
        ],
        compute="_compute_deviation",
        store=True,
        help="Derived from the roster shift, not from a policy threshold, so "
        "the comparison is always against the published shift.",
    )
    hrms_rostered_start = fields.Datetime(compute="_compute_deviation", store=True)
    hrms_rostered_end = fields.Datetime(compute="_compute_deviation", store=True)

    @api.depends("check_in", "check_out", "roster_assignment_id")
    def _compute_deviation(self):
        for rec in self:
            start = end = False
            kind = "on_time"
            if rec.roster_assignment_id:
                start = rec.roster_assignment_id.shift_start_datetime
                end = rec.roster_assignment_id.shift_end_datetime
                rec.hrms_rostered_start = start
                rec.hrms_rostered_end = end
                if not rec.check_in:
                    kind = "absent"
                elif start and rec.check_in > start:
                    kind = "late"
                elif end and rec.check_out and rec.check_out < end:
                    kind = "early"
                elif end and not rec.check_out:
                    kind = "missing_checkout"
            else:
                rec.hrms_rostered_start = False
                rec.hrms_rostered_end = False
            rec.hrms_deviation_type = kind


class HrContract(models.Model):
    _inherit = "hr.contract"

    hrms_contract_type = fields.Selection(
        [
            ("permanent", "Permanent"),
            ("fixed_term", "Fixed-term"),
            ("contractor", "Contractor"),
            ("intern", "Intern"),
            ("trainee", "Trainee"),
            ("consultant", "Consultant"),
        ],
        default="permanent",
        required=True,
        help="Mirrors the employee's contract_type and drives gratuity "
        "eligibility. Kept on the contract because eligibility is a property of "
        "the contract, not of the person.",
    )
    notice_period_days = fields.Integer(
        default=0,
        help="Notice period in days. F&F shortfall recovery or buyout is "
        "computed from this.",
    )
    hrms_probation_months = fields.Integer(default=0)

    @api.constrains("date_start", "date_end", "hrms_contract_type")
    def _check_fixed_term(self):
        for rec in self:
            if rec.hrms_contract_type == "fixed_term":
                if not rec.date_end:
                    raise UserError(
                        f"{rec.name or rec.employee_id.name}: a fixed-term contract "
                        "requires an end date. Gratuity eligibility and expiry "
                        "triggers depend on it."
                    )


class HrDepartment(models.Model):
    """Establishment = the unit that applicable law resolves against."""

    _inherit = "hr.department"

    hrms_is_establishment = fields.Boolean(
        default=False,
        help="Mark as an establishment for statutory resolution. Each "
        "establishment needs its own confirmed legal basis because Labour Code "
        "rules are notified per State, and only some States have notified.",
    )
    hrms_state_code = fields.Char(string="Establishment state code")
    hrms_estab_code = fields.Char(
        string="Establishment code",
        help="Statutory establishment identifier used on PF and ESI remittances.",
    )
    hrms_gstin = fields.Char(string="GSTIN", help="For GST input-credit tracking on expenses.")
    hrms_lwf_applicable = fields.Boolean(
        default=False,
        help="Labour Welfare Fund is levied only by some States. Drives the LWF "
        "rule and the F&F/LWF remittance decision.",
    )
    hrms_rostered = fields.Boolean(
        default=False,
        help="This establishment runs published rosters. Payroll for a rostered "
        "establishment cannot be computed while an employee has no roster "
        "assignments, because their hours are then unknown.",
    )


class ResCompany(models.Model):
    _inherit = "res.company"

    hrms_default_tax_regime = fields.Selection(
        [("old", "Old regime"), ("new", "New regime")], default="new"
    )
    hrms_fiscal_year_start_month = fields.Integer(
        default=4,
        help="Month the payroll year starts. India is April, but this is "
        "configuration because UAE and the US differ.",
    )
    hrms_wage_ceiling_notified_on = fields.Date(
        help="Date the latest wage-ceiling notification took effect. Recorded so "
        "a mid-month ceiling change can be applied pro-rata rather than "
        "silently using the wrong ceiling.",
    )
    hrms_notice_board_id = fields.Many2one(
        "hr.employee", string="Notice board employee",
        help="Employee responsible for displaying notices on the establishment "
        "notice board. Required by the Code on Social Security for certain "
        "establishments.",
    )