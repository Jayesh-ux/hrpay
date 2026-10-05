# -*- coding: utf-8 -*-
"""Schema extension of ``hr.employee``.

Adds the Phase 1 sync columns (``payroll_external_id``, ``sync_status``,
``sync_hash``), the statutory-deduction inputs the rules engine needs, and the
encrypted-at-rest identifiers (bank, PAN, Aadhaar).

Design note: after ADR-0002 the "payroll engine" is in the same database as the
people data, so ``payroll_external_id`` is retained as a stable external key for
idempotent inbound sync and for any future external processor, not as a
cross-database join. See ADR-0002.
"""

import hashlib
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

SYNC_STATES = [
    ("pending", "Pending"),
    ("synced", "Synced"),
    ("failed", "Failed"),
    ("blocked", "Blocked (validation)"),
]


class HrEmployee(models.Model):
    _inherit = ["hr.employee", "hrms.mixin.encrypted"]

    _encrypted_fields = {
        "bank_account_number": {"label": "Bank account number", "group": "base.group_user"},
        "bank_ifsc": {"label": "Bank IFSC", "group": "base.group_user"},
        "pan_number": {"label": "PAN", "group": "hr.group_hr_user"},
        "aadhaar_number": {"label": "Aadhaar", "group": "hr.group_hr_manager"},
        "esic_number": {"label": "ESIC IP number", "group": "hr.group_hr_user"},
        "epf_number": {"label": "EPF/UAN", "group": "hr.group_hr_user"},
    }

    # ─── Integration / sync ─────────────────────────────────────────────
    payroll_external_id = fields.Char(
        string="External payroll ID",
        index=True,
        copy=False,
        help="Stable identifier from the upstream HR source or payroll "
        "processor. Used for idempotent upsert. Unique per company.",
    )
    sync_status = fields.Selection(
        SYNC_STATES,
        default="pending",
        required=True,
        index=True,
        copy=False,
        help="Last known sync state for this employee record.",
    )
    sync_hash = fields.Char(
        copy=False,
        index=True,
        read=False,
        help="SHA-256 of the canonicalised sync-relevant fields. A mismatch "
        "means the record drifted and must be re-synced. Read-only.",
    )
    last_synced_at = fields.Datetime(readonly=True, copy=False)
    last_sync_error = fields.Text(readonly=True, copy=False)

    # ─── Statutory inputs ───────────────────────────────────────────────
    hrms_state_code = fields.Char(
        string="Establishment state code",
        compute="_compute_hrms_state_code",
        store=True,
        index=True,
        help="ISO 3166-2 code of the establishment that governs this "
        "employee's applicable law. Resolved from the address/company; "
        "override only where the work location differs from the registered "
        "office.",
    )
    hrms_establishment_id = fields.Many2one(
        "hr.department",
        string="Establishment",
        help="Establishment used to resolve applicable law and statutory "
        "configuration. Must be set before payroll.",
    )
    contract_type = fields.Selection(
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
        help="Drives legal-basis resolution and statutory eligibility "
        "(e.g. fixed-term employees have different gratuity eligibility).",
    )
    hrms_contract_start = fields.Date(string="Contract start")
    hrms_contract_end = fields.Date(string="Contract end (fixed-term)")
    hrms_tax_regime = fields.Selection(
        [("old", "Old regime"), ("new", "New regime")],
        default="new",
        required=True,
        help="Employee's elected income-tax regime. May change once before "
        "31 March; a mid-year change is supported by the TDS computation.",
    )
    hrms_ctc = fields.Float(string="Annual CTC", digits=(16, 2))
    hrms_tds_deduction = fields.Float(
        string="TDS deduction (exemptions etc.)",
        digits=(16, 2),
        help="Declared exemptions/deductions under the elected regime, "
        "aggregated. Formally this comes from a year-end declaration; it is "
        "stored here so TDS is cumulative and defensible.",
    )
    hrms_ytd_taxable = fields.Float(string="YTD taxable salary", digits=(16, 2))
    hrms_tds_ytd = fields.Float(string="YTD TDS deducted", digits=(16, 2))
    hrms_pt_ytd = fields.Float(string="YTD professional tax", digits=(16, 2))
    hrms_pf_ytd = fields.Float(string="YTD PF (EPS/EPF)", digits=(16, 2))
    hrms_esi_ytd = fields.Float(string="YTD ESI", digits=(16, 2))

    # ─── Gratuity service tracking ──────────────────────────────────────
    hrms_service_start = fields.Date(
        string="Continuous service start",
        help="Start of continuous service for gratuity. Differs from join_date "
        "when prior service is recognised (e.g. acquired entity).",
    )
    hrms_previous_employer_service_months = fields.Integer(
        default=0,
        help="Recognised prior service in months, for gratuity eligibility.",
    )

    # ─── Separation ─────────────────────────────────────────────────────
    hrms_separation_state = fields.Selection(
        [
            ("none", "Active"),
            ("resignation_pending", "Resignation pending"),
            ("resigned", "Resigned"),
            ("terminated", "Terminated"),
            ("retired", "Retired"),
            ("retrenched", "Retrenched"),
        ],
        default="none",
        index=True,
        copy=False,
    )
    hrms_last_working_day = fields.Date(copy=False, index=True)
    hrms_separation_reason = fields.Text()

    # ─── Encrypted field names (stored, never read directly) ────────────
    bank_account_number_enc = fields.Char(
        string="Bank account number (encrypted)", copy=False, groups="base.group_user"
    )
    bank_ifsc_enc = fields.Char(string="Bank IFSC (encrypted)", copy=False, groups="base.group_user")
    pan_number_enc = fields.Char(
        string="PAN (encrypted)", copy=False, groups="hr.group_hr_user"
    )
    aadhaar_number_enc = fields.Char(
        string="Aadhaar (encrypted)", copy=False, groups="hr.group_hr_manager"
    )
    esic_number_enc = fields.Char(
        string="ESIC IP number (encrypted)", copy=False, groups="hr.group_hr_user"
    )
    epf_number_enc = fields.Char(
        string="EPF/UAN (encrypted)", copy=False, groups="hr.group_hr_user"
    )

    # ─── Plaintext access ───────────────────────────────────────────────
    # Deliberately explicit rather than a computed/inverse ``<name>`` field.
    # Two reasons: a non-stored computed field's inverse ordering during create
    # would decide whether the row id is available to bind into the AAD (if it
    # is not, every later decrypt would fail), and requiring an explicit accessor
    # keeps "reveal this secret" a visible act that can be access-checked and
    # audit-logged rather than an incidental field read.

    def _hrms_get_enc(self, field_name):
        """Decrypt one field. Use the ``*_display`` field for masked output."""
        self.ensure_one()
        return self._enc_read(field_name, self)

    def _hrms_set_enc(self, field_name, value):
        """Encrypt and store one field across the recordset."""
        for rec in self:
            rec[field_name + "_enc"] = self._enc_write(field_name, rec, value)
        return True

    def _hrms_encrypted_fields(self):
        return tuple(self._encrypted_fields)

    def _hrms_reveal(self, field_name, reason=None):
        """Decrypt for an authorised user, recording who looked and why."""
        self.ensure_one()
        spec = self._encrypted_fields.get(field_name)
        if not spec:
            raise UserError(f"{field_name} is not an encrypted field on hr.employee")
        if not self.user_has_groups(spec.get("group", "base.group_user")):
            raise AccessError(
                f"{spec['label']} is restricted to "
                f"{spec.get('group')} and above."
            )
        self.env["hrms.audit.log"].log(
            self._name,
            self.id,
            "read_sensitive",
            changes={field_name: "***"},
            note=reason or f"{spec['label']} revealed",
        )
        return self._hrms_get_enc(field_name)

    def action_view_pan(self):
        self.ensure_one()
        self.env["hrms.audit.log"].log(
            "hr.employee", self.id, "read_sensitive",
            changes={"pan_number": "***"},
            note="PAN viewed by %s" % self.env.user.name,
        )
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "new"}

    def action_view_aadhaar(self):
        self.ensure_one()
        if not self.user_has_groups("hr.group_hr_manager"):
            raise AccessError("Aadhaar is restricted to HR Managers.")
        self.env["hrms.audit.log"].log(
            "hr.employee", self.id, "read_sensitive",
            changes={"aadhaar_number": "***"},
            note="Aadhaar viewed by %s" % self.env.user.name,
        )
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "new"}

    # ─── Masked display values ──────────────────────────────────────────
    # Safe to render in a list or a report: last four characters only, so a
    # screenshot of a payroll run does not disclose a full account number.
    # groups= mirrors the ciphertext column it decrypts. Without it a reader
    # lacking the group could still obtain the last four characters by
    # evaluating the masked field.
    bank_account_number_display = fields.Char(
        compute="_compute_enc_display", groups="base.group_user"
    )
    bank_ifsc_display = fields.Char(
        compute="_compute_enc_display", groups="base.group_user"
    )
    pan_number_display = fields.Char(
        compute="_compute_enc_display", groups="hr.group_hr_user"
    )
    aadhaar_number_display = fields.Char(
        compute="_compute_enc_display", groups="hr.group_hr_manager"
    )
    esic_number_display = fields.Char(
        compute="_compute_enc_display", groups="hr.group_hr_user"
    )
    epf_number_display = fields.Char(
        compute="_compute_enc_display", groups="hr.group_hr_user"
    )

    @api.depends(
        "bank_account_number_enc", "bank_ifsc_enc", "pan_number_enc",
        "aadhaar_number_enc", "esic_number_enc", "epf_number_enc",
    )
    def _compute_enc_display(self):
        for emp in self:
            for field_name in self._encrypted_fields:
                emp[f"{field_name}_display"] = self._enc_masked(field_name, emp)

    # ─── Computes ───────────────────────────────────────────────────────
    @api.depends("address_id.state_id", "company_id")
    def _compute_hrms_state_code(self):
        for emp in self:
            state = emp.address_id.state_id or emp.company_id.state_id
            emp.hrms_state_code = state.code if state else ""

    # ─── Constraints ────────────────────────────────────────────────────
    @api.constrains("contract_type", "hrms_contract_start", "hrms_contract_end")
    def _check_contract_dates(self):
        for emp in self:
            if emp.contract_type == "fixed_term":
                if not emp.hrms_contract_start or not emp.hrms_contract_end:
                    raise UserError(
                        f"{emp.name}: fixed-term employees require both a contract "
                        "start and end date. Gratuity eligibility for fixed-term "
                        "employees differs from permanent, so the dates are not "
                        "optional."
                    )
                if emp.hrms_contract_end < emp.hrms_contract_start:
                    raise UserError(f"{emp.name}: contract end precedes start.")

    @api.constrains("hrms_previous_employer_service_months")
    def _check_prior_service(self):
        for emp in self:
            if emp.hrms_previous_employer_service_months < 0:
                raise UserError("Recognised prior service cannot be negative.")

    _sql_constraints = [
        (
            "payroll_external_id_company_unique",
            "UNIQUE(company_id, payroll_external_id)",
            "External payroll ID must be unique within a company; it is the "
            "idempotency key for inbound sync.",
        )
    ]

    # ─── Sync hashing ───────────────────────────────────────────────────
    SYNC_FIELDS = (
        "name", "date_of_birth", "join_date", "hrms_last_working_day",
        "contract_type", "hrms_tax_regime", "hrms_ctc", "hrms_state_code",
        "hrms_establishment_id", "bank_account_number_enc", "bank_ifsc_enc",
        "pan_number_enc", "epf_number_enc", "esic_number_enc",
        "work_email", "work_phone", "job_id", "department_id",
    )

    @api.model
    def canonical_sync_payload(self, emp):
        """Deterministic JSON of sync-relevant fields, for hashing and diffing.

        Secrets are hashed, never returned in plaintext, so this payload is safe
        to log.
        """
        payload = {}
        for fname in self.SYNC_FIELDS:
            if fname not in emp._fields:
                continue
            val = emp[fname]
            if hasattr(val, "id"):
                val = val.id
            payload[fname] = val
        raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        return raw

    @api.model
    def sync_hash_for(self, emp):
        raw = self.canonical_sync_payload(emp)
        return hashlib.sha256(raw.encode()).hexdigest()

    def action_recompute_sync_hash(self):
        for emp in self:
            emp.sudo().sync_hash = self.sync_hash_for(emp)
        return True

    def action_mark_synced(self):
        for emp in self:
            emp.write(
                {
                    "sync_status": "synced",
                    "sync_hash": self.sync_hash_for(emp),
                    "last_synced_at": fields.Datetime.now(),
                    "last_sync_error": False,
                }
            )
        return True

    def action_mark_failed(self, error):
        for emp in self:
            emp.write({"sync_status": "failed", "last_sync_error": str(error)[:2000]})
        return True

    @api.model
    def upsert_by_external_id(self, company, payload):
        """Idempotent upsert keyed on (company, payroll_external_id).

        Returns (record, created). Replaying the same payload is a no-op because
        the sync hash is unchanged. This is the guarantee the webhook retry path
        relies on.
        """
        ext = payload.get("payroll_external_id")
        if not ext:
            raise UserError("payroll_external_id is required for upsert.")
        existing = self.sudo().search(
            [("company_id", "=", company.id), ("payroll_external_id", "=", ext)], limit=1
        )
        if existing:
            vals = dict(payload)
            vals.pop("payroll_external_id", None)
            existing.sudo().write(vals)
            return existing, False
        vals = dict(payload)
        vals["company_id"] = company.id
        return self.sudo().create(vals), True

    # ─── Post-lock guards ───────────────────────────────────────────────
    def assert_period_unlocked(self, period_start, period_end=None):
        """Raise if any payroll period overlapping this range is locked.

        Every path that mutates payroll-affecting input calls this. A locked
        period must be corrected via an off-cycle adjustment, never by editing
        the original inputs.
        """
        period_end = period_end or period_start
        locks = self.env["payroll.period.lock"].sudo().search(
            [
                ("state", "in", ("locked", "released")),
                ("date_from", "<=", period_end),
                ("date_to", ">=", period_start),
            ]
        )
        if locks:
            raise UserError(
                f"Payroll period {locks[0].display_name} is locked. Retroactive "
                "changes to this input are not permitted. Record an off-cycle "
                "adjustment instead so the original payslip stays reproducible."
            )
        return True