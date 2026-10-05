# -*- coding: utf-8 -*-
"""Final settlement: the itemised statement and the payable-by clock.

Three things this gets right that a naive implementation does not:

1. **The statutory clock starts at the last working day**, not at the date HR
   happens to open the case. An open case silently restarting that clock is how
   employers miss a statutory payment date, and the miss is invisible until an
   inspection finds it.

2. **Negative settlements are a different animal.** An employee can be a net
   debtor (overpaid advance, unreturned asset, notice shortfall). Deducting that
   from the final month's pay without authority is itself unlawful, so the case
   records whether recovery is permitted and from what, configured per company
   rather than assumed.

3. **Every line is a snapshot, not a live reference.** The statement must stay
   reproducible after the underlying salary component, rule version or attendance
   record changes, because the employee may dispute it months later.
"""

import hashlib
import logging
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Payable-within deadline per exit type, keyed to the statutory rule code that
# must hold the signed-off number of days. No number appears here.
REASON_RULE = {
    "resignation": "IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS",
    "termination": "IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS",
    "retrenchment": "IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS",
    "retirement": "IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS",
    "death": "IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS",
    "fixed_term_expiry": "IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS",
}


class SeparationReason(models.Model):
    """Exit reason, with the settlement behaviour it implies.

    Configured rather than hardcoded because the treatment of notice shortfall,
    gratuity and the payment clock differs by exit type, and because a company
    may only be permitted to recover in some cases.
    """

    _name = "hrms.fnf.reason"
    _description = "Full and final settlement reason"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    code = fields.Char(required=True, help="Stable code used on reports and exports.")
    active = fields.Boolean(default=True)

    requires_notice = fields.Boolean(
        default=False,
        help="Contractual notice applies, so a shortfall against the notice "
        "period is computed and may be recovered.",
    )
    gratuity_eligible = fields.Boolean(
        default=True,
        help="Whether the gratuity rule applies to this exit type. Death and "
        "retrenchment are treated differently from resignation.",
    )
    permits_recovery = fields.Boolean(
        default=False,
        help="Whether amounts owed by the employee may be recovered from final "
        "wages. Deducting without authority is not lawful, so this is explicit.",
    )
    payroll_deadline_rule = fields.Char(
        required=True,
        help="Statutory rule code holding the number of days within which wages "
        "must be paid. Resolved on the last working day, never on the case date.",
    )
    notice = fields.Text(
        help="Shown to the employee on the statement, so the reason and its "
        "consequences are never a surprise discovered at settlement.",
    )


class SettlementCase(models.Model):
    _name = "hrms.fnf.case"
    _description = "Full and final settlement case"
    _order = "last_working_day desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        ondelete="restrict",
        index=True,
        help="Restricted rather than cascading: a settlement record is a "
        "financial document and deleting the employee must not erase it.",
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    reason_id = fields.Many2one("hrms.fnf.reason", required=True, ondelete="restrict")
    last_working_day = fields.Date(
        required=True, index=True,
        help="Last day of service. The statutory payment clock is anchored here, "
        "so it must be the contractual last working day, not the date this case "
        "was opened.",
    )
    resignation_date = fields.Date(
        help="Date the employee gave notice. Kept distinct from the last working "
        "day so the notice period can be audited.",
    )
    notice_period_days = fields.Integer()
    notice_served_days = fields.Integer(
        help="Days actually worked against the notice period. Shortfall is the "
        "difference, and is only recoverable when the reason permits it.",
    )
    notice_shortfall_days = fields.Integer(compute="_compute_notice", store=True)

    separation_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("under_calculation", "Under calculation"),
            ("calculated", "Calculated"),
            ("employee_acknowledged", "Acknowledged by employee"),
            ("approved", "Approved for payment"),
            ("paid", "Paid"),
            ("disputed", "Disputed"),
            ("withheld", "Withheld pending dispute"),
        ],
        default="draft",
        required=True,
        index=True,
        copy=False,
    )

    payable_by = fields.Date(
        compute="_compute_payable_by", store=True, readonly=True, copy=False,
        help="Statutory payment deadline, resolved from the configured rule on "
        "the last working day. Recomputed never.",
    )
    days_remaining = fields.Integer(compute="_compute_days_remaining")
    overdue = fields.Boolean(compute="_compute_overdue", store=True)
    deadline_rule_code = fields.Char(related="reason_id.payroll_deadline_rule")

    gross_payable = fields.Monetary(currency_field="currency_id", compute="_compute_totals", store=True)
    total_deductions = fields.Monetary(currency_field="currency_id", compute="_compute_totals", store=True)
    net_payable = fields.Monetary(currency_field="currency_id", compute="_compute_totals", store=True)
    is_negative_settlement = fields.Boolean(
        compute="_compute_totals", store=True,
        help="Net owed by the employee rather than to them. Routed to a different "
        "approval path and never settled by silently deducting from wages.",
    )
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    company_currency_id = fields.Many2one(related="company_id.currency_id")

    statement_json = fields.Text(
        readonly=True, copy=False,
        help="Itemised, frozen statement: every line, its inputs and the rule "
        "versions used. This is what the employee is shown and what an auditor "
        "reads a year later.",
    )
    statement_checksum = fields.Char(readonly=True, copy=False)
    rule_versions_json = fields.Text(readonly=True, copy=False)

    prepared_by_id = fields.Many2one("res.users", ondelete="restrict", copy=False)
    acknowledged_by_id = fields.Many2one("hr.employee", ondelete="restrict", copy=False)
    acknowledged_at = fields.Datetime(readonly=True, copy=False)
    approved_by_id = fields.Many2one("res.users", ondelete="restrict", copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    paid_by_id = fields.Many2one("res.users", ondelete="restrict", copy=False)
    paid_at = fields.Datetime(readonly=True, copy=False)
    payment_reference = fields.Char(copy=False)

    dispute_reason = fields.Text()
    dispute_raised_at = fields.Datetime(copy=False, readonly=True)

    _sql_constraints = [
        (
            "one_open_case_per_employee",
            "UNIQUE(employee_id)",
            "An employee may have only one settlement case. A second concurrent "
            "settlement for the same person is double counting their dues.",
        )
    ]

    # ─── Computes ───────────────────────────────────────────────────────
    @api.depends("employee_id", "last_working_day")
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.employee_id.name} ({rec.last_working_day})"

    @api.depends("notice_period_days", "notice_served_days")
    def _compute_notice(self):
        for rec in self:
            rec.notice_shortfall_days = max(
                (rec.notice_period_days or 0) - (rec.notice_served_days or 0), 0
            )

    @api.depends("last_working_day", "reason_id")
    def _compute_payable_by(self):
        ctx = self.env["hrms.statutory.context"]
        for rec in self:
            code = rec.reason_id.payroll_deadline_rule
            if not code or not rec.last_working_day:
                rec.payable_by = False
                continue
            try:
                days = int(
                    ctx.get(
                        code,
                        rec.company_id,
                        state_code=rec.employee_id.hrms_state_code,
                        contract_type=rec.employee_id.contract_type,
                        on_date=rec.last_working_day,
                    )
                )
            except UserError as exc:
                _logger.error(
                    "hrms_fnf: cannot resolve the payment deadline for %s: %s",
                    rec.employee_id.name, exc,
                )
                rec.payable_by = False
                continue
            rec.payable_by = _add_working_days(
                rec.last_working_day, days, rec.employee_id
            )

    @api.depends("payable_by", "separation_state")
    def _compute_days_remaining(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.payable_by or rec.separation_state == "paid":
                rec.days_remaining = 0
            else:
                rec.days_remaining = (rec.payable_by - today).days

    @api.depends("payable_by", "separation_state")
    def _compute_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.overdue = bool(
                rec.payable_by
                and rec.separation_state != "paid"
                and today > rec.payable_by
            )

    @api.depends("statement_json", "currency_id")
    def _compute_totals(self):
        for rec in self:
            try:
                statement = _json_load(rec.statement_json)
            except Exception:
                statement = {}
            payable = sum(l["amount"] for l in statement.get("payable_lines", []))
            deductions = sum(abs(l["amount"]) for l in statement.get("deduction_lines", []))
            rec.gross_payable = payable
            rec.total_deductions = deductions
            rec.net_payable = payable - deductions
            rec.is_negative_settlement = rec.net_payable < 0

    # ─── Lifecycle ──────────────────────────────────────────────────────
    def action_calculate(self):
        """Build the statement from live data, then freeze it.

        Recalculation is refused once the employee has acknowledged or the case
        is approved: the figure they agreed to is the figure they are owed, and
        quietly changing it afterwards is how disputes start.
        """
        for rec in self:
            if rec.separation_state not in ("draft", "under_calculation", "disputed"):
                raise UserError(
                    f"{rec.name}: cannot recalculate a case in state "
                    f"'{rec.separation_state}'. The employee has already seen the "
                    "figure. Raise a dispute to reopen it explicitly."
                )
            rec._action_require_notice_data()
            lines = self.env["hrms.fnf.line"]._build_lines(rec)
            payable_lines, deduction_lines, details = lines
            versions = self.env["hrms.statutory.context"]._snapshot(
                rec.company_id,
                rec.employee_id.hrms_state_code,
                rec.employee_id.contract_type,
                rec.last_working_day,
            )
            statement = {
                "payable_lines": payable_lines,
                "deduction_lines": deduction_lines,
                "details": details,
                "employee_id": rec.employee_id.id,
                "last_working_day": str(rec.last_working_day),
                "reason": rec.reason_id.code,
                "payable_by": str(rec.payable_by or ""),
            }
            rec.statement_json = _json_dump(statement)
            rec.rule_versions_json = _json_dump(versions)
            rec.statement_checksum = hashlib.sha256(
                rec.statement_json.encode()
            ).hexdigest()
            rec.prepared_by_id = self.env.user
            rec.separation_state = "calculated"
            self.env["hrms.audit.log"].log(
                rec._name, rec.id, "create",
                changes={"checksum": rec.statement_checksum},
                note="F&F statement calculated",
            )
        return True

    def _action_require_notice_data(self):
        for rec in self:
            if rec.reason_id.requires_notice and not rec.notice_period_days:
                raise UserError(
                    f"{rec.name}: {rec.reason_id.name} carries a notice period. "
                    "Set notice_period_days on the contract or on the case before "
                    "calculating, otherwise a shortfall cannot be detected and an "
                    "over-recovery is possible."
                )
            if rec.reason_id.requires_notice and not rec.resignation_date:
                raise UserError(
                    f"{rec.name}: set resignation_date so the notice period can be "
                    "audited against the contractual requirement."
                )

    def action_acknowledge(self):
        """Employee confirms they have seen the itemised statement."""
        for rec in self:
            if rec.separation_state != "calculated":
                raise UserError(
                    f"{rec.name}: the statement must be calculated before the "
                    "employee can acknowledge it."
                )
            rec.acknowledged_by_id = rec.employee_id
            rec.acknowledged_at = fields.Datetime.now()
            rec.separation_state = "employee_acknowledged"
        return True

    def action_approve(self):
        """Approve for payment. Segregation of duties and a named approver."""
        for rec in self:
            if rec.separation_state not in ("calculated", "employee_acknowledged"):
                raise UserError(
                    f"{rec.name}: cannot approve a case in state "
                    f"'{rec.separation_state}'."
                )
            if self.env.user._is_superuser():
                raise UserError(
                    f"{rec.name}: approve as a named Finance Approver. A "
                    "superuser approval is not attributable to a person."
                )
            if rec.acknowledged_by_id and rec.acknowledged_by_id.user_id == self.env.user:
                raise UserError("You cannot approve a case you acknowledged.")
            if rec.is_negative_settlement and not rec.reason_id.permits_recovery:
                raise UserError(
                    f"{rec.name}: this is a negative settlement of "
                    f"{rec.company_currency_id.symbol or ''}{abs(rec.net_payable):,.2f} "
                    f"and '{rec.reason_id.name}' does not permit recovery. Get "
                    "authorisation recorded before pursuing an amount owed by the "
                    "employee."
                )
            rec.approved_by_id = self.env.user
            rec.approved_at = fields.Datetime.now()
            rec.separation_state = "approved"
            self.env["hrms.audit.log"].log(
                rec._name, rec.id, "approve",
                note=f"Approved {rec.net_payable:,.2f}",
            )
        return True

    def action_mark_paid(self, reference=None):
        for rec in self:
            if rec.separation_state != "approved":
                raise UserError(
                    f"{rec.name}: only an approved case can be marked paid; this "
                    f"one is '{rec.separation_state}'."
                )
            if rec.overdue:
                _logger.warning(
                    "hrms_fnf: %s paid %d day(s) after the statutory deadline %s",
                    rec.name, abs(rec.days_remaining), rec.payable_by,
                )
            rec.paid_by_id = self.env.user
            rec.paid_at = fields.Datetime.now()
            rec.payment_reference = reference
            rec.separation_state = "paid"
            self.env["hrms.audit.log"].log(
                rec._name, rec.id, "release",
                note=f"Paid {rec.net_payable:,.2f} ref={reference or '-'}",
            )
        return True

    def action_raise_dispute(self, reason):
        if not reason or not reason.strip():
            raise UserError("A dispute must state the reason.")
        for rec in self:
            rec.dispute_reason = reason
            rec.dispute_raised_at = fields.Datetime.now()
            rec.separation_state = "disputed"
            self.env["hrms.audit.log"].log(
                rec._name, rec.id, "reject", note=reason,
            )
        return True

    def write(self, vals):
        """Freeze the money once the employee has seen it."""
        money_keys = {
            "last_working_day", "reason_id", "notice_period_days",
            "notice_served_days", "employee_id",
        }
        if any(k in vals for k in money_keys):
            for rec in self:
                if rec.separation_state in (
                    "employee_acknowledged", "approved", "paid", "withheld"
                ):
                    raise UserError(
                        f"{rec.name}: the inputs to this settlement are locked "
                        "because the employee has already seen the statement. "
                        "Raise a dispute and recompute deliberately."
                    )
        return super().write(vals)

    def unlink(self):
        if any(rec.separation_state != "draft" for rec in self):
            raise UserError(
                "A settlement case that has been calculated is a financial "
                "record and cannot be deleted. Only an untouched draft may be "
                "removed."
            )
        return super().unlink()


def _add_working_days(start, working_days, employee):
    """Advance ``working_days`` working days from ``start``.

    Holidays come from the employee's country, because a public holiday differs
    per establishment and per State. If no holiday calendar is configured the
    count still advances by calendar days with a loud warning, rather than
    silently treating a holiday as a working day.
    """
    calendar = None
    state = employee.company_id.country_id
    if state:
        calendar = state.calendar_id
    if not calendar:
        _logger.warning(
            "hrms_fnf: no public holiday calendar for %s; the payment deadline "
            "is being advanced by calendar days, which may be too generous",
            state.display_name if state else "the country",
        )
        return start + timedelta(days=working_days)
    days = calendar.advance(start, working_days, workday=False)
    return fields.Date.to_date(days)


def _json_dump(payload):
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def _json_load(text):
    import json

    if not text:
        return {}
    return json.loads(text)