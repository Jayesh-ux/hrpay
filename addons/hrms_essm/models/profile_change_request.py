# -*- coding: utf-8 -*-
"""Employee self-service profile change requests.

An employee may not edit ``hr.employee`` directly: payroll, statutory and
identity data live there, and a self-edit path would put them inside reach of
every user. Instead an employee raises a *request* naming one field and the
desired value. A second person (the employee's manager or HR) approves it, and
only then is the safe field written. Segregation of duties is enforced: the
approver cannot be the requester.

Sensitive identifiers (PAN, Aadhaar, bank account) are deliberately **never**
captured or written through this path. The request only records that a change is
needed; HR applies the real value through the audited employee form so the
ciphertext and the reveal audit trail stay intact.
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class HrmsProfileChangeRequest(models.Model):
    _name = "hrms.profile.change.request"
    _description = "Employee profile change request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    # Fields an employee is trusted to propose a new value for. Written to
    # hr.employee on approval.
    SAFE_FIELDS = (
        "work_email",
        "work_phone",
        "mobile_phone",
        "private_email",
        "private_phone",
    )
    # Fields that must be applied by HR via the audited reveal path. The request
    # records the intent only; the value is never stored here.
    SENSITIVE_FIELDS = (
        "pan_number",
        "aadhaar_number",
        "bank_account_number",
    )

    name = fields.Char(
        default="New", copy=False, readonly=True, required=True, index=True
    )
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        index=True,
        ondelete="cascade",
        default=lambda self: self._default_employee(),
        help="The employee whose record would change. Defaults to you.",
    )
    requested_by = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        readonly=True,
        required=True,
        ondelete="restrict",
    )
    field_name = fields.Selection(
        selection=[
            ("work_email", "Work email"),
            ("work_phone", "Work phone"),
            ("mobile_phone", "Mobile"),
            ("private_email", "Personal email"),
            ("private_phone", "Personal phone"),
            ("pan_number", "PAN (handled by HR)"),
            ("aadhaar_number", "Aadhaar (handled by HR)"),
            ("bank_account_number", "Bank account (handled by HR)"),
        ],
        required=True,
    )
    is_sensitive = fields.Boolean(compute="_compute_is_sensitive", store=True)
    old_value = fields.Char(
        compute="_compute_old_value",
        help="Current value, or a masked value for a restricted identifier.",
    )
    new_value = fields.Char(help="The value you want set.")
    reason = fields.Text()
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("applied", "Applied"),
        ],
        default="draft",
        required=True,
        index=True,
        tracking=True,
    )
    approver_id = fields.Many2one(
        "res.users", readonly=True, copy=False, ondelete="restrict"
    )
    decision_date = fields.Datetime(readonly=True, copy=False)
    approver_note = fields.Text()
    request_date = fields.Datetime(
        string="Created on",
        default=fields.Datetime.now,
        readonly=True,
        copy=False,
    )

    # ─── Defaults / computes ────────────────────────────────────────────
    @api.model
    def _default_employee(self):
        return self.env.user.employee_id or self.env["hr.employee"].search(
            [("user_id", "=", self.env.uid)], limit=1
        )

    @api.depends("field_name")
    def _compute_is_sensitive(self):
        for rec in self:
            rec.is_sensitive = rec.field_name in self.SENSITIVE_FIELDS

    @api.depends("field_name", "employee_id")
    def _compute_old_value(self):
        for rec in self:
            rec.old_value = rec._current_value_display()

    def _current_value_display(self):
        self.ensure_one()
        if not self.employee_id or not self.field_name:
            return ""
        if self.field_name in self.SENSITIVE_FIELDS:
            display = "%s_display" % self.field_name
            if display in self.employee_id._fields:
                return self.employee_id[display] or "(not set)"
            return "(restricted)"
        return self.employee_id[self.field_name] or ""

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code(
                        "hrms.profile.change.request"
                    )
                    or "New"
                )
        records = super().create(vals_list)
        for rec in records:
            rec._apply_requester_scope()
        return records

    def _apply_requester_scope(self):
        """A non-HR user may only raise a request for their own record."""
        self.ensure_one()
        own = self._default_employee()
        if not self.env.user.has_group("hr.group_hr_user"):
            if not own:
                raise UserError(
                    "Your user is not linked to an employee record, so a profile "
                    "change request cannot be attributed. Ask HR to link your user."
                )
            if self.employee_id != own:
                raise AccessError(
                    "You may only raise a change request for yourself."
                )
            self.requested_by = self.env.user

    # ─── Constraints ────────────────────────────────────────────────────
    @api.constrains("new_value", "field_name", "is_sensitive")
    def _check_new_value(self):
        for rec in self:
            if not rec.is_sensitive and not (rec.new_value or "").strip():
                raise UserError(
                    "A new value is required for '%s'." % rec.field_name
                )
            if rec.is_sensitive and rec.new_value:
                if sum(c.isdigit() for c in rec.new_value) >= 8:
                    raise UserError(
                        "Do not enter the full number for a sensitive identifier. "
                        "Describe the change instead; HR captures the value "
                        "through the audited employee form."
                    )

    # ─── Workflow ───────────────────────────────────────────────────────
    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError("%s is already %s." % (rec.name, rec.state))
            rec.state = "submitted"
            rec.message_post(body="Request submitted for approval.")
        return True

    def _assert_approver_is_second_person(self):
        self.ensure_one()
        if self.env.user == self.requested_by:
            raise AccessError(
                "Segregation of duties: you cannot approve your own change "
                "request. Another person must approve it."
            )
        if self.env.user._is_superuser():
            raise AccessError(
                "Approve as a named manager or HR user, not as the system "
                "superuser, so the decision is attributable."
            )

    def action_approve(self):
        for rec in self:
            if rec.state != "submitted":
                raise UserError("%s is %s, not submitted." % (rec.name, rec.state))
            rec._assert_approver_is_second_person()
            rec.approver_id = self.env.user
            rec.decision_date = fields.Datetime.now()
            if rec.is_sensitive:
                rec.state = "approved"
                rec.message_post(
                    body="Approved. HR must apply this identifier change through "
                    "the audited employee form; it is never written from here."
                )
            else:
                rec._apply_safe_value()
                rec.state = "applied"
                rec.message_post(body="Approved and applied.")
            self.env["hrms.audit.log"].log(
                rec._name,
                rec.id,
                "approve",
                changes={rec.field_name: "***"},
                note="Profile change approved",
            )
        return True

    def _apply_safe_value(self):
        self.ensure_one()
        if self.field_name not in self.SAFE_FIELDS:
            raise UserError(
                "Only non-identifier fields can be applied automatically."
            )
        self.employee_id.sudo().write({self.field_name: self.new_value})
        self.env["hrms.audit.log"].log(
            self._name,
            self.id,
            "read_sensitive" if self.is_sensitive else "create",
            changes={self.field_name: "***"},
            note="Profile field updated from an approved request",
        )

    def action_reject(self):
        for rec in self:
            if rec.state not in ("submitted", "approved"):
                raise UserError("Only a submitted request can be refused.")
            rec._assert_approver_is_second_person()
            rec.approver_id = self.env.user
            rec.decision_date = fields.Datetime.now()
            rec.state = "rejected"
            rec.message_post(body="Request refused.")
            self.env["hrms.audit.log"].log(rec._name, rec.id, "reject")
        return True

    def action_mark_applied(self):
        for rec in self:
            if not (rec.state == "approved" and rec.is_sensitive):
                raise UserError(
                    "Only an approved identifier request can be marked applied."
                )
            if not self.env.user.has_group("hr.group_hr_user"):
                raise AccessError("Only HR may mark an identifier change applied.")
            rec.state = "applied"
            rec.message_post(body="Marked applied by HR after capture.")
        return True
