# -*- coding: utf-8 -*-
"""Self-service read helpers on ``hr.payslip``.

The payslip history is *gate-aware*: a payslip is only "final" once it has
reached the Done state. Anything earlier is shown but labelled provisional, so
the employee never mistakes a not-yet-validated figure for a settled one.
"""

from odoo import api, fields, models


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    hrms_essm_net = fields.Float(
        string="Net pay (inferred)", compute="_compute_essm_net", digits=(16, 2)
    )
    hrms_essm_is_final = fields.Boolean(
        string="Final", compute="_compute_essm_final", store=True
    )
    hrms_essm_gate = fields.Selection(
        [("final", "Final"), ("provisional", "Provisional - not sign-off validated")],
        string="Sign-off status",
        compute="_compute_essm_final",
        store=True,
    )

    @api.depends("line_ids.total")
    def _compute_essm_net(self):
        for slip in self:
            slip.hrms_essm_net = sum(slip.line_ids.mapped("total"))

    @api.depends("state")
    def _compute_essm_final(self):
        for slip in self:
            final = slip.state == "done"
            slip.hrms_essm_is_final = final
            slip.hrms_essm_gate = "final" if final else "provisional"
