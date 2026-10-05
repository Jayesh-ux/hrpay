# -*- coding: utf-8 -*-
"""Cross-module link between payroll period lock and roster period lock.

Lives in ``hrms_roster`` rather than ``hrms_core_ext`` because the payroll lock
model is defined in the earlier addon. Declaring the Many2one here keeps the
dependency direction one-way: ``hrms_roster`` -> ``hrms_core_ext``.
"""

from odoo import fields, models


class PayrollPeriod(models.Model):
    _inherit = "payroll.period.lock"

    hrms_roster_period_id = fields.Many2one(
        "hr.roster.period",
        string="Linked roster period",
        ondelete="set null",
        index=True,
        help="Roster lock is aligned with payroll lock so published shifts and "
        "paid hours cannot diverge. A locked payroll period must reference a "
        "roster period that is itself locked.",
    )
    hrms_roster_lock_verified = fields.Boolean(
        readonly=True,
        copy=False,
        help="Set when the linked roster period was confirmed locked at the "
        "same instant the payroll period was locked. Prevents a roster "
        "revision after payroll lock.",
    )

class RosterPeriod(models.Model):
    """Reverse side of the link, so ``action_lock`` does not re-derive it."""

    _inherit = "hr.roster.period"

    hrms_payroll_period_id = fields.Many2one(
        "payroll.period.lock",
        string="Linked payroll period",
        ondelete="set null",
        index=True,
        help="Payroll period this roster must reconcile against. Set by the "
        "locker, not inferred from dates: two payroll periods can overlap a "
        "draft roster and guessing would lock against the wrong one.",
    )
