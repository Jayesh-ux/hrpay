# -*- coding: utf-8 -*-
"""Self-service summary fields and smart buttons on ``hr.employee``.

These are derived, read-only figures for the "My HR" dashboard. They are
computed defensively: a missing optional module degrades the number to zero
rather than raising, so the dashboard never breaks the employee form.
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    hrms_essm_leave_allocated = fields.Float(
        compute="_compute_essm_leave", digits=(16, 1)
    )
    hrms_essm_leave_taken = fields.Float(
        compute="_compute_essm_leave", digits=(16, 1)
    )
    hrms_essm_leave_remaining = fields.Float(
        compute="_compute_essm_leave", digits=(16, 1)
    )
    hrms_essm_open_requests = fields.Integer(compute="_compute_essm_counts")
    hrms_essm_payslip_count = fields.Integer(compute="_compute_essm_counts")
    hrms_essm_document_count = fields.Integer(compute="_compute_essm_counts")

    @api.depends("name")
    def _compute_essm_leave(self):
        today = fields.Date.context_today(self)
        allocations = self.env["hr.leave.allocation"]
        leaves = self.env["hr.leave"]
        for emp in self:
            allocated = taken = 0.0
            allocs = allocations.sudo().search(
                [
                    ("employee_id", "=", emp.id),
                    ("state", "=", "validate"),
                    ("date_from", "<=", today),
                    "|",
                    ("date_to", "=", False),
                    ("date_to", ">=", today),
                ]
            )
            allocated = sum(allocs.mapped("number_of_days"))
            taken_recs = leaves.sudo().search(
                [
                    ("employee_id", "=", emp.id),
                    ("state", "=", "validate"),
                    ("date_from", ">=", today.replace(month=1, day=1)),
                ]
            )
            taken = sum(taken_recs.mapped("number_of_days"))
            emp.hrms_essm_leave_allocated = allocated
            emp.hrms_essm_leave_taken = taken
            emp.hrms_essm_leave_remaining = allocated - taken

    @api.depends("name")
    def _compute_essm_counts(self):
        Request = self.env["hrms.profile.change.request"]
        Slip = self.env["hr.payslip"]
        Doc = self.env["hrms.employee.document"]
        for emp in self:
            emp.hrms_essm_open_requests = Request.sudo().search_count(
                [
                    ("employee_id", "=", emp.id),
                    ("state", "in", ("draft", "submitted")),
                ]
            )
            emp.hrms_essm_payslip_count = Slip.sudo().search_count(
                [("employee_id", "=", emp.id)]
            )
            emp.hrms_essm_document_count = Doc.sudo().search_count(
                [("employee_id", "=", emp.id)]
            )

    # ─── Smart button actions ───────────────────────────────────────────
    def action_essm_my_requests(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "My Requests",
            "res_model": "hrms.profile.change.request",
            "view_mode": "list,form",
            "domain": [("employee_id", "=", self.id)],
            "context": {"default_employee_id": self.id},
        }

    def action_essm_my_payslips(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "My Payslips",
            "res_model": "hr.payslip",
            "view_mode": "list,form",
            "domain": [("employee_id", "=", self.id)],
        }

    def action_essm_my_leaves(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "My Time Off",
            "res_model": "hr.leave",
            "view_mode": "list,form,calendar",
            "domain": [("employee_id", "=", self.id)],
            "context": {"default_employee_id": self.id},
        }

    def action_essm_my_documents(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "My Documents",
            "res_model": "hrms.employee.document",
            "view_mode": "list,form",
            "domain": [("employee_id", "=", self.id)],
            "context": {"default_employee_id": self.id},
        }
