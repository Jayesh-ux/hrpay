# -*- coding: utf-8 -*-
"""Gratuity computation.

As at 2026-10-05, under the Code on Social Security 2020:

- Permanent employees: gratuity payable after five years continuous service, at
  15 days' last-drawn wages per completed year **or part thereof in excess of
  six months**.
- Fixed-term employees: **pro-rata** gratuity after one year of continuous
  service under the contract, triggered on expiry of the term. A subsequent
  fixed-term period of more than six months but less than one year may be
  rounded off as one additional year.
- Payment is due within 30 days, with interest for delay.
- The Central Government may specify a ceiling and the wage-baseline divisor.
- Piece-rated workers: average wages of the three months preceding termination.
- Seasonal workers: 7 days per season.

Every one of those parameters comes from statutory config. The only thing this
module decides is *how* they combine, and the combination is versioned so a
change of law never rewrites a historical calculation.
"""

import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from . import gratuity_arithmetic as _gratuity

_logger = logging.getLogger(__name__)


class GratuityServicePeriod(models.Model):
    """One spell of continuous service.

    Modelled as separate rows rather than a single date range because a
    fixed-term employee may have successive contracts, and successive periods
    combine differently under the rules.
    """

    _name = "hrms.gratuity.service.period"
    _description = "Gratuity service period"
    _order = "start_date"

    employee_id = fields.Many2one("hr.employee", required=True, ondelete="cascade", index=True)
    start_date = fields.Date(required=True)
    end_date = fields.Date()
    contract_type = fields.Selection(
        [
            ("permanent", "Permanent"),
            ("fixed_term", "Fixed-term"),
            ("contractor", "Contractor"),
            ("intern", "Intern"),
            ("trainee", "Trainee"),
            ("consultant", "Consultant"),
        ],
        required=True,
        default="permanent",
    )
    recognised = fields.Boolean(
        default=True,
        help="Uncheck to exclude a spell from eligibility (e.g. a break in "
        "continuous service). Excluded spells remain visible for audit.",
    )
    note = fields.Text()

    _sql_constraints = [
        (
            "period_dates_ordered",
            "CHECK (end_date IS NULL OR end_date >= start_date)",
            "Service period end must not precede its start.",
        )
    ]


class GratuityResult(models.Model):
    """Immutable gratuity outcome for an employee at a point in time."""

    _name = "hrms.gratuity.result"
    _description = "Gratuity computation result"
    _order = "id desc"

    employee_id = fields.Many2one("hr.employee", required=True, ondelete="restrict", index=True)
    as_of_date = fields.Date(required=True, index=True)
    exit_reason = fields.Selection(
        [
            ("resignation", "Resignation"),
            ("termination", "Termination"),
            ("retrenchment", "Retrenchment"),
            ("retirement", "Retirement"),
            ("death", "Death / disablement"),
            ("fixed_term_expiry", "Fixed-term contract expiry"),
        ],
        required=True,
    )

    eligible = fields.Boolean(required=True)
    ineligibility_reason = fields.Text()

    completed_years = fields.Float(digits=(8, 2))
    completed_months = fields.Float(digits=(8, 2))
    total_service_months = fields.Integer()

    wage_basis = fields.Float(digits=(16, 2), help="Last-drawn wages used as the basis.")
    wage_basis_method = fields.Selection(
        [
            ("last_drawn", "Last drawn wages"),
            ("average_3m", "Average of preceding 3 months (piece-rated)"),
            ("seasonal", "Seasonal"),
        ],
        default="last_drawn",
    )
    days_per_year = fields.Float(digits=(8, 2))
    divisor = fields.Float(digits=(8, 2), help="Days-per-month divisor for the daily wage.")
    gratuity_amount = fields.Float(digits=(16, 2))
    ceiling = fields.Float(digits=(16, 2))
    ceiling_applied = fields.Boolean()
    capped_amount = fields.Float(digits=(16, 2))

    payment_deadline = fields.Date()
    deadline_days = fields.Integer()

    rule_versions_json = fields.Text(required=True)
    detail_json = fields.Text(help="JSON: period-by-period workings.")
    computed_at = fields.Datetime(default=fields.Datetime.now, readonly=True)


class GratuityEngine(models.AbstractModel):
    _name = "hrms.gratuity.engine"
    _description = "Gratuity engine"

    @api.model
    def compute(self, employee, as_of_date, exit_reason, wage_basis=None, wage_basis_method=None):
        ctx = self.env["hrms.statutory.context"]
        company = employee.company_id
        state = employee.hrms_state_code or company.state_id.code or ""
        ct = employee.contract_type or "permanent"

        periods = employee.hrms_gratuity_service_period_ids.filtered(lambda p: p.recognised)
        if not periods:
            periods = self._default_periods(employee)

        eligibility = ctx.get_json(
            "IN.GRATUITY.ELIGIBILITY", company, state_code=state, contract_type=ct, on_date=as_of_date
        )
        if not eligibility:
            raise UserError(
                "IN.GRATUITY.ELIGIBILITY is not configured. Gratuity eligibility "
                "cannot be determined without it, and it must not be assumed. "
                "Add the rule version with a source reference and professional "
                "sign-off."
            )

        params = eligibility.get(ct) or eligibility.get("default")
        if not params:
            raise UserError(
                f"No gratuity eligibility parameters for contract type '{ct}'. "
                f"Configure IN.GRATUITY.ELIGIBILITY with a 'default' entry or a "
                f"'{ct}' entry."
            )

        min_years = float(params.get("min_years", 0))
        min_months = int(params.get("min_months", 0))
        partial_month_threshold = int(params.get("partial_year_month_threshold", 6))
        pro_rata = bool(params.get("pro_rata", False))
        trigger_on_expiry = bool(params.get("trigger_on_term_expiry", False))

        def cfg(code):
            return ctx.get(code, company, state_code=state, contract_type=ct, on_date=as_of_date)

        total_months = 0
        per_period = []
        for period in sorted(periods, key=lambda p: p.start_date):
            start = max(period.start_date, employee.hrms_service_start or period.start_date)
            end = min(period.end_date or as_of_date, as_of_date)
            if end < start:
                continue
            # A fixed-term contract obliges service to the last day of its term,
            # so the final month counts as served in full. Without this a contract
            # running 1 Jan to 31 Dec measures as 11 months and a one-year
            # pro-rata threshold would wrongly deny gratuity on expiry.
            inclusive_end = end + relativedelta(days=1) if (
                trigger_on_expiry and period.end_date and period.end_date <= as_of_date
            ) else end
            months = _months_between(start, inclusive_end)
            total_months += months
            per_period.append(
                {
                    "start": str(start),
                    "end": str(end),
                    "contract_type": period.contract_type,
                    "months": months,
                }
            )

        completed_years = total_months // 12
        completed_months = total_months % 12
        # ---- eligibility -------------------------------------------------
        reason = None
        eligible = True
        if exit_reason == "fixed_term_expiry" and trigger_on_expiry:
            # Fixed-term: eligible on expiry after the minimum service.
            required_months = min_years * 12 + min_months
            if total_months < required_months:
                eligible = False
                reason = (
                    f"Fixed-term gratuity requires at least {required_months} months "
                    f"of service; {total_months} completed."
                )
        else:
            required_months = min_years * 12 + min_months
            if total_months < required_months:
                eligible = False
                reason = (
                    f"Gratuity requires at least {required_months} months of "
                    f"continuous service; {total_months} completed."
                )

        # ---- computation -------------------------------------------------
        days_per_year = float(cfg("IN.GRATUITY.DAYS_PER_YEAR"))
        # Every one of these must be configured. A default divisor would silently
        # produce a wrong gratuity liability, so absence is an error, not zero.
        divisor = float(cfg("IN.GRATUITY.WAGES_DIVISOR"))
        ceiling = float(cfg("IN.GRATUITY.CEILING"))
        deadline_days = int(cfg("IN.GRATUITY.PAYMENT_DEADLINE_DAYS"))

        method = wage_basis_method or params.get("wage_basis_method", "last_drawn")
        if wage_basis is None:
            wage_basis = self._wage_basis(employee, method, as_of_date)

        # Countable service and the amount itself live in gratuity_arithmetic.py,
        # where they are tested without Odoo. Two defects came out of the inline
        # version: a remainder of exactly six months was counted as a full year
        # even though the statute says *in excess of* six months, and
        # ``if ceiling and amount > ceiling`` treated a ceiling of zero as no
        # ceiling at all. Both now raise or apply as configured.
        boundary = params.get("partial_month_boundary", "exclusive")
        try:
            countable_years, rounding_note = _gratuity.countable_years(
                total_months,
                pro_rata=pro_rata,
                partial_threshold_months=partial_month_threshold,
                boundary=boundary,
            )
            figures = _gratuity.compute_gratuity(
                wage_basis=wage_basis,
                days_per_year=days_per_year,
                countable_years_value=countable_years,
                wages_divisor=divisor,
                ceiling=ceiling,
            )
        except ValueError as exc:
            raise UserError(
                f"{employee.name}: gratuity cannot be computed as at {as_of_date}: "
                f"{exc} See docs/compliance/CA-SIGNOFF-REQUEST.md section 2."
            ) from exc

        daily_wage = figures["daily_wage"]
        amount = figures["uncapped_amount"]
        ceiling_applied = figures["ceiling_applied"]
        capped = figures["excess_over_ceiling"]

        # Reported service: a remainder that does not clear the partial-year
        # boundary is not counted, so it must not appear in the completed months
        # or in the total the result reports (the raw span is kept for
        # eligibility, above).
        remainder = total_months % 12
        counted_remainder = remainder
        if not pro_rata and partial_month_threshold > 0:
            if remainder > partial_month_threshold or (
                remainder == partial_month_threshold and boundary == "inclusive"
            ):
                counted_remainder = remainder
            else:
                counted_remainder = 0
        completed_months = counted_remainder
        counted_service_months = completed_years * 12 + counted_remainder

        versions = ctx._snapshot(company, state, ct, as_of_date)
        rule_versions_by_code = {}
        for row in versions:
            rule_versions_by_code.setdefault(row["code"], []).append(row)
        return self.env["hrms.gratuity.result"].create(
            {
                "employee_id": employee.id,
                "as_of_date": as_of_date,
                "exit_reason": exit_reason,
                "eligible": eligible,
                "ineligibility_reason": reason,
                "completed_years": completed_years,
                "completed_months": completed_months,
                "total_service_months": counted_service_months,
                "wage_basis": round(wage_basis, 2),
                "wage_basis_method": method,
                "days_per_year": days_per_year,
                "divisor": divisor,
                "gratuity_amount": figures["payable"],
                "ceiling": ceiling,
                "ceiling_applied": ceiling_applied,
                "capped_amount": round(capped, 2),
                "payment_deadline": as_of_date + relativedelta(days=deadline_days),
                "deadline_days": deadline_days,
                "rule_versions_json": _json(rule_versions_by_code),
                "detail_json": _json(
                    {
                        "periods": per_period,
                        "countable_years": countable_years,
                        "rounding": rounding_note,
                        "daily_wage": round(daily_wage, 2),
                        "eligibility_params": params,
                    }
                ),
            }
        )

    def _default_periods(self, employee):
        """Derive service periods from contracts when none are recorded."""
        start = employee.hrms_service_start or employee.join_date
        if not start:
            raise UserError(
                f"{employee.name}: no service start date. Set hrms_service_start "
                "or join_date so gratuity service can be established."
            )
        # The end date matters: it is what tells the engine the contractual term
        # actually ran to its last day, which is the trigger for fixed-term
        # gratuity. Leaving it open would make a completed 12-month term measure
        # as 11 months.
        end = False
        if employee.contract_type == "fixed_term" and employee.hrms_contract_end:
            end = employee.hrms_contract_end
        return [
            self.env["hrms.gratuity.service.period"].new(
                {
                    "employee_id": employee.id,
                    "start_date": start,
                    "end_date": end,
                    "contract_type": employee.contract_type or "permanent",
                    "recognised": True,
                }
            )
        ]

    def _wage_basis(self, employee, method, as_of_date):
        """Last-drawn wages for gratuity.

        Three defects in the previous version, all of which overstate or
        misstate the basis:

        1. ``sum(l.total for l in slip.line_ids)`` summed **every** payslip line,
           so employer contributions such as the employer's PF were added to the
           basis and employee deductions were netted off it. Only gross earnings
           count, and employer contributions are not wages at all.
        2. With no payslip found it fell back to ``hrms_ctc / 12``. CTC includes
           employer PF, a gratuity accrual and insurance, none of which are
           wages, so the gratuity was overstated by construction.
        3. The ``seasonal`` method returned CTC outright, for the same reason.

        There is no fallback now. Absence of a payslip raises, because the two
        figures we do have (CTC and the contract wage) are both the wrong kind of
        number and guessing between them silently is how an overpayment becomes a
        liability. Which components are wages is CA request section 2.
        """
        months = 3
        if method == "average_3m":
            slips = self.env["hr.payslip"].search(
                [
                    ("employee_id", "=", employee.id),
                    ("date_from", "<=", as_of_date),
                    ("date_to", ">=", (as_of_date - relativedelta(months=months))),
                    ("state", "in", ("done", "paid")),
                ],
                limit=months,
                order="date_to desc",
            )
            if not slips:
                return self._refuse_wage_basis(employee, method, as_of_date)
            return round(sum(self._gross_earnings(slip) for slip in slips)
                         / len(slips), 2)

        slip = self.env["hr.payslip"].search(
            [
                ("employee_id", "=", employee.id),
                ("date_from", "<=", as_of_date),
                ("state", "in", ("done", "paid")),
            ],
            limit=1,
            order="date_to desc",
        )
        if not slip:
            return self._refuse_wage_basis(employee, method, as_of_date)
        return self._gross_earnings(slip)

    def _gross_earnings(self, slip):
        """Gross earnings on one payslip: earnings only, no employer burden.

        Payslip lines are positive for earnings and negative for deductions, so
        ``total > 0`` separates them. Employer contributions are positive too and
        must be excluded; whether a rule is an employer contribution is a field on
        the salary rule in recent Odoo versions, and is checked for rather than
        assumed, because this addon has never been loaded against a database.
        """
        lines = slip.line_ids
        rule_model = self.env["hr.salary.rule"]
        if "is_employer_contribution" in rule_model._fields:
            excluded = lines.filtered(
                lambda line: line.salary_id.is_employer_contribution
            )
            lines = lines - excluded
        total = sum(float(line.total or 0.0) for line in lines
                    if float(line.total or 0.0) > 0)
        if total <= 0:
            raise UserError(
                f"Payslip {slip.display_name or slip.id} has no gross earnings "
                f"lines, so last-drawn wages cannot be established. Refusing to "
                f"substitute CTC or the contract wage for the gratuity basis; see "
                f"docs/compliance/CA-SIGNOFF-REQUEST.md section 2."
            )
        return total

    def _refuse_wage_basis(self, employee, method, as_of_date):
        """No payslip means no wages figure, and this is not a recoverable gap."""
        raise UserError(
            f"{employee.name}: gratuity wage basis method '{method}' needs a paid "
            f"payslip on or before {as_of_date} and there is none. CTC and the "
            f"contract wage are both refused, because neither is statutory 'wages' "
            f"(CTC includes employer contributions). Resolve CA request section 2 "
            f"to know which components count, then supply a payslip."
        )


def _months_between(start, end):
    """Complete months between two dates."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def _json(payload):
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str)

class HrEmployee(models.Model):
    """Service periods live on the employee so gratuity survives a contract change."""

    _inherit = "hr.employee"

    hrms_gratuity_service_period_ids = fields.One2many(
        "hrms.gratuity.service.period",
        "employee_id",
        string="Service periods",
        help="Spells of continuous service. Multiple rows where service was "
        "broken and restarted, or where successive fixed-term contracts ran. "
        "Uncheck 'recognised' to exclude a spell from eligibility without "
        "deleting the record.",
    )
