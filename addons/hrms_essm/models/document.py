# -*- coding: utf-8 -*-
"""Employee document vault (self-service).

A lightweight store for employee-held documents (ID proofs, certificates,
contracts). It is separate from the encrypted identity columns: a scanned
document is an attachment, not a decrypted identifier, and access is limited to
the employee and HR.
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class HrmsEmployeeDocument(models.Model):
    _name = "hrms.employee.document"
    _description = "Employee document"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True)
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        index=True,
        ondelete="cascade",
        default=lambda self: self.env.user.employee_id,
    )
    doc_type = fields.Selection(
        [
            ("id_proof", "Identity proof"),
            ("address_proof", "Address proof"),
            ("education", "Education certificate"),
            ("contract", "Contract / letter"),
            ("payslip", "Payslip / tax document"),
            ("other", "Other"),
        ],
        default="other",
        required=True,
    )
    file = fields.Binary(string="File", attachment=True)
    file_name = fields.Char()
    issue_date = fields.Date()
    expiry_date = fields.Date()
    notes = fields.Text()
    state = fields.Selection(
        [("valid", "Valid"), ("expiring", "Expiring soon"), ("expired", "Expired")],
        compute="_compute_state",
        store=True,
    )

    @api.depends("expiry_date")
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.expiry_date:
                rec.state = "valid"
            elif rec.expiry_date < today:
                rec.state = "expired"
            elif (rec.expiry_date - today).days <= 60:
                rec.state = "expiring"
            else:
                rec.state = "valid"
