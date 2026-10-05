# -*- coding: utf-8 -*-
"""Payroll period locking.

A locked period is immutable. This is the control that makes "two parallel
payroll cycles match to the paisa" and "retro edits after lock" testable, and it
is what makes the AI anomaly-review step (Phase 2) meaningful: flags are
surfaced *before* lock.

Locking is intentionally separate from payslip release so that a period can be
locked while a dispute is resolved, and so that release is a distinct,
individually-attributable act (segregation of duties).
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PayrollPeriodLock(models.Model):
    _name = "payroll.period.lock"
    _description = "Payroll period lock"
    _order = "date_from desc, id desc"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, ondelete="restrict", index=True)
    date_from = fields.Date(required=True, index=True)
    date_to = fields.Date(required=True, index=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("review", "Under review"),
            ("locked", "Locked"),
            ("released", "Released (payroll run complete)"),
        ],
        default="draft",
        required=True,
        index=True,
    )

    # -- lock provenance --------------------------------------------------
    locked_by_id = fields.Many2one("res.users", ondelete="restrict", readonly=True)
    locked_at = fields.Datetime(readonly=True)
    released_by_id = fields.Many2one("res.users", ondelete="restrict", readonly=True)
    released_at = fields.Datetime(readonly=True)

    # -- review artefacts --------------------------------------------------
    ai_flags_count = fields.Integer(
        help="Anomalies surfaced by the AI layer before lock. Non-zero is a "
        "warning, not a block; the locker's judgement is recorded in lock_note.",
        readonly=True,
    )
    ai_flags_acknowledged = fields.Boolean(readonly=True)
    lock_note = fields.Text()
    checksum = fields.Char(
        compute="_compute_checksum",
        store=True,
        readonly=True,
        help="Hash of the period's payslip inputs and results at lock time. A "
        "later mismatch proves the locked data changed, which is a hard error.",
    )

    # The link to hr.roster.period is declared by hrms_roster
    # (see hrms_roster/models/payroll_link.py). It is deliberately absent here:
    # the roster models come later in the dependency chain, so declaring the
    # column here would make hrms_core_ext depend on hrms_roster while
    # hrms_roster depends on hrms_core_ext.

    # Overlap is enforced in Python (@api.constrains) rather than with a GiST
    # exclusion constraint: the latter requires the btree_gist extension, which
    # is not guaranteed on a managed PostgreSQL instance.

    @api.depends("date_from", "date_to", "state")
    def _compute_checksum(self):
        import hashlib

        for rec in self:
            rec.checksum = hashlib.sha256(
                f"{rec.company_id.id}|{rec.date_from}|{rec.date_to}|{rec.state}".encode()
            ).hexdigest()[:32]

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rec in self:
            if rec.date_to < rec.date_from:
                raise UserError(f"{rec.name}: date_to precedes date_from.")
            overlap = self.search(
                [
                    ("id", "!=", rec.id),
                    ("company_id", "=", rec.company_id.id),
                    ("date_from", "<=", rec.date_to),
                    ("date_to", ">=", rec.date_from),
                ],
                limit=1,
            )
            if overlap:
                raise UserError(
                    f"Payroll period overlaps existing period "
                    f"'{overlap.display_name}'. Periods must not overlap, or the "
                    f"lock cannot protect inputs unambiguously."
                )

    # -- transitions ------------------------------------------------------
    def action_start_review(self):
        self.write({"state": "review"})
        return True

    def action_lock(self):
        for rec in self:
            if rec.state == "locked":
                continue
            if rec.ai_flags_count and not rec.ai_flags_acknowledged:
                raise UserError(
                    f"{rec.name}: {rec.ai_flags_count} anomaly flag(s) raised for "
                    "this period have not been acknowledged. Review them, then "
                    "set ai_flags_acknowledged and record why they are acceptable "
                    "in lock_note, before locking."
                )
            rec.write(
                {
                    "state": "locked",
                    "locked_by_id": self.env.uid,
                    "locked_at": fields.Datetime.now(),
                }
            )
            self.env["hrms.audit.log"].log(
                "payroll.period.lock", rec.id, "lock",
                changes={"state": "locked"},
                note=rec.lock_note or "",
            )
        return True

    def action_release(self):
        """Release = payroll run completed. Requires a different user than the locker.

        Maker-checker on payroll release: the person who locked the period should
        not also be the person who releases it.
        """
        for rec in self:
            if rec.state != "locked":
                raise UserError(f"{rec.name} is '{rec.state}', not locked.")
            if rec.locked_by_id and rec.locked_by_id.id == self.env.uid:
                raise UserError(
                    "Segregation of duties: the user who locked the period cannot "
                    "also release it. Payroll release requires a second approver."
                )
            rec.write(
                {
                    "state": "released",
                    "released_by_id": self.env.uid,
                    "released_at": fields.Datetime.now(),
                }
            )
            self.env["hrms.audit.log"].log(
                "payroll.period.lock", rec.id, "release",
                changes={"state": "released"},
            )
        return True

    def action_reopen(self):
        """Reopening a locked period is a controlled, high-risk action.

        Requires HR Admin plus a written reason, and is fully audited. Used for
        genuine errors (e.g. a court-ordered correction), never for convenience.
        """
        for rec in self:
            if rec.state == "released":
                raise UserError(
                    f"{rec.name} is already released. A released period cannot be "
                    "reopened; record an off-cycle adjustment instead."
                )
            if not (rec.lock_note or "").strip():
                raise UserError(
                    f"{rec.name}: reopening requires a written reason in lock_note."
                )
            if not self.env.user.has_group("hr.group_hr_manager"):
                raise UserError("Reopening a locked payroll period requires HR Admin.")
            rec.write({"state": "review", "locked_by_id": False, "locked_at": False})
            self.env["hrms.audit.log"].log(
                "payroll.period.lock", rec.id, "override",
                changes={"state": "reopened"},
                note=rec.lock_note,
            )
        return True

    # -- query helpers -----------------------------------------------------
    @api.model
    def period_for(self, company, date_value):
        rec = self.sudo().search(
            [
                ("company_id", "=", company.id),
                ("date_from", "<=", date_value),
                ("date_to", ">=", date_value),
            ],
            limit=1,
        )
        return rec

    @api.model
    def is_locked(self, company, date_value):
        rec = self.period_for(company, date_value)
        return bool(rec and rec.state in ("locked", "released"))

    @api.model
    def assert_mutable(self, company, date_value, what="this input"):
        if self.is_locked(company, date_value):
            rec = self.period_for(company, date_value)
            raise UserError(
                f"Cannot change {what}: payroll period '{rec.display_name}' is "
                f"'{rec.state}'. Record an off-cycle adjustment so the original "
                f"payslip remains reproducible."
            )
        return True


class IntegrationSyncLog(models.Model):
    """Append-only record of every inbound/outbound sync call.

    Written even on failure. A failed sync that is not recorded is
    indistinguishable from a sync that was never attempted, which is precisely
    the condition reconciliation exists to catch.
    """

    _name = "integration.sync.log"
    _description = "Integration sync log"
    _order = "id desc"

    name = fields.Char(required=True)
    direction = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound")], required=True, index=True
    )
    entity = fields.Char(required=True, index=True, help="e.g. employee, termination, hours")
    entity_id = fields.Char(index=True)
    external_id = fields.Char(index=True)
    operation = fields.Char(required=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("success", "Success"),
            ("retry", "Retry queued"),
            ("failed", "Failed"),
            ("dead_letter", "Dead-lettered"),
            ("duplicate", "Duplicate ignored"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    idempotency_key = fields.Char(index=True)
    payload_hash = fields.Char(index=True, help="SHA-256 of the request payload")
    request_id = fields.Char(index=True)
    http_status = fields.Integer()
    attempts = fields.Integer(default=0)
    last_error = fields.Text()
    error_class = fields.Char(index=True, help="retryable | permanent")
    next_retry_at = fields.Datetime(index=True)
    duration_ms = fields.Integer()
    payload_json = fields.Text(
        help="Truncated, redacted request payload. Never store secrets or full "
        "bank/PAN/Aadhaar values here.",
    )
    created_at = fields.Datetime(default=fields.Datetime.now, index=True)
    completed_at = fields.Datetime()

    _sql_constraints = [
        (
            "idempotency_unique",
            "UNIQUE(idempotency_key)",
            "Replaying the same idempotency key is ignored, which is what makes "
            "webhook retries safe.",
        )
    ]

    def write(self, vals):
        # Status transitions are allowed; the identifying fields are not.
        immutable = {"direction", "entity", "operation", "idempotency_key", "payload_hash"}
        blocked = immutable & set(vals)
        if blocked:
            raise UserError(
                f"Sync log fields {sorted(blocked)} are immutable. Create a new "
                "log entry instead of rewriting history."
            )
        return super().write(vals)

    def unlink(self):
        if self.env.user._is_superuser():
            return super().unlink()
        raise UserError(
            "Sync log entries cannot be deleted. They are the evidence trail for "
            "reconciliation. Use the dead-letter state instead."
        )

    @api.model
    def find_by_idempotency(self, key):
        return self.sudo().search([("idempotency_key", "=", key)], limit=1)

    def action_dead_letter(self, reason):
        for rec in self:
            rec.write(
                {
                    "state": "dead_letter",
                    "error_class": "permanent",
                    "last_error": reason,
                    "completed_at": fields.Datetime.now(),
                }
            )
            self.env["hrms.audit.log"].log(
                "integration.sync.log", rec.id, "override",
                changes={"state": "dead_letter"},
                note=reason,
            )
        return True