# -*- coding: utf-8 -*-
"""Employee tax investment declarations.

The employee declares exemptions/deductions for a financial year. HR or Finance
approves the declaration. Nothing here changes a statutory rate: the declared
figure is an *input*, and it is only copied onto the employee's payroll input
(``hrms_tds_deduction``) by an explicit, audited HR action, never automatically.
This keeps unvalidated payroll configuration behind the existing sign-off gate.
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class HrmsTaxDeclaration(models.Model):
    _name = "hrms.tax.declaration"
    _description = "Employee tax investment declaration"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "financial_year desc, id desc"

    name = fields.Char(default="New", copy=False, readonly=True, required=True, index=True)
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        index=True,
        ondelete="cascade",
        default=lambda self: self.env.user.employee_id,
    )
    financial_year = fields.Char(
        required=True,
        help="Financial year, e.g. 2026-2027. India runs April to March.",
        default=lambda self: self._default_financial_year(),
    )
    regime = fields.Selection(
        [("old", "Old regime"), ("new", "New regime")],
        default="new",
        required=True,
    )
    amount = fields.Monetary(
        currency_field="currency_id",
        help="Total exemptions/deductions declared for the year.",
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )
    note = fields.Text()
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "hrms_tax_declaration_attachment_rel",
        "declaration_id",
        "attachment_id",
        string="Proof documents",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="draft",
        required=True,
        index=True,
        tracking=True,
    )
    approver_id = fields.Many2one("res.users", readonly=True, copy=False, ondelete="restrict")
    decision_date = fields.Datetime(readonly=True, copy=False)
    approver_note = fields.Text()
    applied_to_payroll = fields.Boolean(readonly=True, copy=False)

    @api.model
    def _default_financial_year(self):
        today = fields.Date.context_today(self)
        start = self.env.company.hrms_fiscal_year_start_month or 4
        year = today.year if today.month >= start else today.year - 1
        return "%d-%d" % (year, year + 1)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("hrms.tax.declaration")
                    or "New"
                )
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError("Only a draft declaration can be submitted.")
            rec.state = "submitted"
            rec.message_post(body="Declaration submitted.")
        return True

    def _assert_second_person(self):
        self.ensure_one()
        if self.env.user == self.employee_id.user_id:
            raise AccessError(
                "Segregation of duties: you cannot approve your own declaration."
            )
        if self.env.user._is_superuser():
            raise AccessError("Approve as a named HR or Finance user.")

    def action_approve(self):
        for rec in self:
            if rec.state != "submitted":
                raise UserError("Only a submitted declaration can be approved.")
            if not (
                self.env.user.has_group("hr.group_hr_user")
                or self.env.user.has_group("hrms_core_ext.group_hrms_finance_approver")
            ):
                raise AccessError("Only HR or Finance may approve a declaration.")
            rec._assert_second_person()
            rec.approver_id = self.env.user
            rec.decision_date = fields.Datetime.now()
            rec.state = "approved"
            rec.message_post(body="Declaration approved.")
            self.env["hrms.audit.log"].log(rec._name, rec.id, "approve")
        return True

    def action_reject(self):
        for rec in self:
            if rec.state not in ("submitted", "approved"):
                raise UserError("Only a submitted declaration can be refused.")
            rec._assert_second_person()
            rec.approver_id = self.env.user
            rec.decision_date = fields.Datetime.now()
            rec.state = "rejected"
            rec.message_post(body="Declaration refused.")
        return True

    def action_apply_to_payroll_input(self):
        """Copy the approved total onto the employee payroll input (audited).

        Explicit HR/Finance action only. It writes an *input*, not a rate, and
        is recorded, so an unvalidated declaration cannot silently change TDS.
        """
        for rec in self:
            if rec.state != "approved":
                raise UserError("Approve the declaration before applying it.")
            if not self.env.user.has_group("hr.group_hr_user"):
                raise AccessError("Only HR may apply a declaration to payroll.")
            rec.employee_id.sudo().write({"hrms_tds_deduction": rec.amount})
            rec.applied_to_payroll = True
            rec.message_post(
                body="Applied to payroll input hrms_tds_deduction: %s" % rec.amount
            )
            self.env["hrms.audit.log"].log(
                rec._name,
                rec.id,
                "override",
                changes={"hrms_tds_deduction": "***"},
                note="Declaration applied to employee payroll input",
            )
        return True
