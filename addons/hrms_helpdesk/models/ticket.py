# -*- coding: utf-8 -*-
"""``helpdesk.ticket`` extensions for statutory and HR service cases.

A ticket here is not just support: several ticket categories carry a statutory
clock. A grievance filed under the Code on Industrial Relations 2020 must be
addressed within the statutory period, an ESI or PF claim must be lodged before
it lapses, and a POSH complaint has its own confidentiality regime. Modelling
the deadline as a field on the ticket means the SLA is visible, reportable and
cannot be quietly relaxed by an agent.
"""

import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TicketCategory(models.Model):
    _inherit = "helpdesk.ticket.type"

    hrms_statutory_code = fields.Char(
        string="Statutory rule code",
        help="Code in the hrms.statutory.rule catalog that governs the "
        "deadline for this category, e.g. IN.ESI.CLAIM.WINDOW. Blank means the "
        "category has no statutory clock and the ordinary SLA applies.",
    )
    hrms_confidential_by_default = fields.Boolean(
        help="Mark cases in this category confidential. Used for grievances, "
        "POSH complaints and disciplinary matters, where the identity of the "
        "person raising the case is itself protected information.",
    )
    hrms_statutory_retention_months = fields.Integer(
        help="Retention period after closure. Employment records have statutory "
        "minimum retention that is longer than the support SLA.",
    )
    hrms_employee_required = fields.Boolean(
        default=True,
        help="Whether a ticket in this category must identify the employee it "
        "concerns. A statutory claim with no employee attached cannot be "
        "reported to the authority.",
    )


class Ticket(models.Model):
    _inherit = "helpdesk.ticket"

    hrms_employee_id = fields.Many2one(
        "hr.employee",
        string="Employee concerned",
        index=True,
        help="Employee this case concerns. Not the requester: the requester may "
        "be reporting on someone else's behalf.",
    )
    hrms_employee_department_id = fields.Many2one(
        related="hrms_employee_id.department_id", string="Employee department", store=True
    )
    hrms_category_id = fields.Many2one(
        related="ticket_type_id", string="Category", store=True
    )

    hrms_confidential = fields.Boolean(
        string="Confidential",
        compute="_compute_hrms_confidential", store=True, readonly=True,
        help="Set from the category. Locked once the ticket leaves draft, "
        "because declassifying a POSH complaint after the fact is not "
        "reversible.",
    )
    hrms_clearance_group_ids = fields.Many2many(
        "res.groups",
        string="Clearance groups",
        help="Groups beyond the assigned team that may read a confidential "
        "case. Left empty, only the assigned team can.",
    )

    hrms_statutory_deadline = fields.Datetime(
        string="Statutory deadline",
        compute="_compute_statutory_deadline", store=True, readonly=True,
        copy=False,
        help="Derived from the statutory rule version for this category on the "
        "date the ticket was created. Recomputed never; a statutory clock is "
        "fixed by when the case arose, not by when someone opened it.",
    )
    hrms_deadline_code = fields.Char(compute="_compute_statutory_deadline", store=True, readonly=True)
    hrms_deadline_locked_by = fields.Boolean(
        compute="_compute_statutory_deadline", store=True, readonly=True,
        help="True once the ticket is past draft. Agents cannot move a "
        "statutory deadline; only a corrective case with an explanation can.",
    )
    hrms_days_to_deadline = fields.Integer(
        compute="_compute_hrms_days_to_deadline", store=False,
    )
    hrms_breached = fields.Boolean(
        compute="_compute_hrms_breached", store=True,
        help="Open ticket past its statutory deadline. Reported daily, because "
        "a missed statutory deadline is a compliance failure, not a backlog "
        "metric.",
    )

    hrms_escalation_note = fields.Text()
    hrms_ai_triage = fields.Text(
        readonly=True, copy=False,
        help="Machine-generated suggestion. Never applied automatically: it is "
        "a reading of the text, not a decision, and acting on it unverified "
        "would launder a guess into a record.",
    )
    hrms_ai_confidence = fields.Float(digits=(4, 3), readonly=True, copy=False)
    hrms_ai_reviewed_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    hrms_ai_reviewed_at = fields.Datetime(readonly=True, copy=False)
    hrms_ai_accepted = fields.Boolean(readonly=True, copy=False)
    hrms_ai_review_note = fields.Text(readonly=True, copy=False)

    # ─── Computes ───────────────────────────────────────────────────────
    @api.depends("ticket_type_id", "hrms_confidential")
    def _compute_hrms_confidential(self):
        for ticket in self:
            if ticket.hrms_confidential:
                continue  # already locked true
            ticket.hrms_confidential = ticket.ticket_type_id.hrms_confidential_by_default

    @api.depends("create_date", "ticket_type_id")
    def _compute_statutory_deadline(self):
        """Anchor the clock to create_date and keep it fixed.

        The deadline is stored so a later re-configuration of the rule cannot
        retroactively make an overdue case look timely, and so a report of
        overdue statutory cases stays true as the rules are amended.
        """
        for ticket in self:
            ticket.hrms_deadline_locked_by = ticket.create_date is not False
            code = ticket.ticket_type_id.hrms_statutory_code
            ticket.hrms_deadline_code = code
            if not code or not ticket.create_date:
                ticket.hrms_statutory_deadline = False
                continue
            try:
                days = int(
                    self.env["hrms.statutory.context"].get(
                        code,
                        self.env.company,
                        on_date=ticket.create_date.date(),
                    )
                )
            except UserError as exc:
                _logger.warning(
                    "hrms_helpdesk: no configured deadline for %s: %s", code, exc
                )
                ticket.hrms_statutory_deadline = False
                continue
            ticket.hrms_statutory_deadline = ticket.create_date + relativedelta(days=days)

    @api.depends("hrms_statutory_deadline", "stage_id")
    def _compute_hrms_days_to_deadline(self):
        now = fields.Datetime.now()
        for ticket in self:
            if not ticket.hrms_statutory_deadline:
                ticket.hrms_days_to_deadline = 0
                continue
            delta = ticket.hrms_statutory_deadline - now
            ticket.hrms_days_to_deadline = int(delta.total_seconds() // 86400)

    @api.depends("hrms_statutory_deadline", "stage_id", "closed_date")
    def _compute_hrms_breached(self):
        now = fields.Datetime.now()
        for ticket in self:
            closed = bool(ticket.stage_id and ticket.stage_id.fold)
            deadline = ticket.hrms_statutory_deadline
            if not deadline or closed:
                ticket.hrms_breached = False
            else:
                ticket.hrms_breached = now > deadline

    # ─── Guards ─────────────────────────────────────────────────────────
    @api.onchange("ticket_type_id")
    def _onchange_category(self):
        for ticket in self:
            if ticket.hrms_deadline_locked_by:
                continue
            if ticket.ticket_type_id.hrms_employee_required and not ticket.hrms_employee_id:
                ticket.hrms_escalation_note = (
                    f"{ticket.ticket_type_id.name} requires the employee it "
                    "concerns. A statutory claim cannot be reported without one."
                )

    def action_confidential(self):
        """Toggle confidentiality. Forward-only after draft."""
        for ticket in self:
            if ticket.hrms_deadline_locked_by and not ticket.hrms_confidential:
                raise UserError(
                    f"Ticket {ticket.name or ticket.id}: confidentiality cannot be "
                    "removed once the case has left draft. Open a corrected case "
                    "if the classification was wrong; the original trail has to "
                    "stay readable by the people who legitimately saw it."
                )
            ticket.hrms_confidential = True
        return True

    def action_review_ai_triage(self, accepted, note=None):
        """Record a human decision on the machine suggestion.

        The decision is recorded either way, because the failure mode of an AI
        assist is silence: later nobody can tell whether a suggestion was seen
        and dismissed, or never surfaced at all.
        """
        for ticket in self:
            if not ticket.hrms_ai_triage:
                raise UserError("There is no suggestion to act on.")
            if ticket.hrms_ai_reviewed_by_id:
                raise UserError(
                    f"Ticket {ticket.name or ticket.id}: the suggestion was "
                    f"already reviewed by {ticket.hrms_ai_reviewed_by_id.name}. "
                    "One review per suggestion, so the record stays honest."
                )
            if self.env.user._is_superuser():
                raise UserError(
                    "Review the suggestion as a named agent. A superuser "
                    "decision is not attributable to a person."
                )
            ticket.hrms_ai_reviewed_by_id = self.env.user
            ticket.hrms_ai_reviewed_at = fields.Datetime.now()
            ticket.hrms_ai_accepted = bool(accepted)
            ticket.hrms_ai_review_note = note
            self.env["hrms.audit.log"].log(
                ticket._name,
                ticket.id,
                "approve" if accepted else "reject",
                note=f"AI triage suggestion {'accepted' if accepted else 'rejected'}"
                     + (f": {note}" if note else ""),
            )
        return True

    def action_reopen_with_note(self, note):
        """Reopen with a mandatory explanation.

        Reopening is how a closed statutory case gets re-opened, which is
        legitimate (an authority asks for more) but must leave a trail.
        """
        if not note or not note.strip():
            raise UserError("Reopening a ticket requires a note explaining why.")
        for ticket in self:
            self.env["hrms.audit.log"].log(
                ticket._name, ticket.id, "override", note=f"Reopened: {note}",
            )
        self.action_reopen()
        return True