# -*- coding: utf-8 -*-
"""Statement lines: leave encashment, gratuity, notice shortfall, dues and clawback.

Each line is computed from a snapshot of its inputs and carries the rule version
that produced it, then frozen into the case's ``statement_json``. The engine is
called once per calculation; after that the statement is a historical document
and never recomputes.
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SettlementLine(models.Model):
    """One itemised line of a final statement.

    Persisted so the employee can be shown the statement as rows rather than as
    JSON, and so an auditor can filter by line type.
    """

    _name = "hrms.fnf.line"
    _description = "Final settlement line"
    _order = "case_id, sequence, id"

    case_id = fields.Many2one("hrms.fnf.case", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(
        [
            ("salary_to_last_day", "Salary to last working day"),
            ("leave_encashment", "Leave encashment"),
            ("leave_excess", "Excess leave recovery"),
            ("gratuity", "Gratuity"),
            ("bonus", "Statutory bonus"),
            ("notice_shortfall", "Notice shortfall recovery"),
            ("advance_recovery", "Advance recovery"),
            ("asset_recovery", "Asset recovery"),
            ("loan_recovery", "Loan recovery"),
            ("overpayment_recovery", "Overpayment recovery"),
            ("notice_pay", "Notice pay"),
            ("other_payable", "Other payable"),
            ("other_deduction", "Other deduction"),
            ("statutory_dues", "Statutory dues shortfall"),
        ],
        required=True,
        index=True,
    )
    label = fields.Char(required=True)
    amount = fields.Monetary(currency_field="currency_id")
    is_deduction = fields.Boolean(required=True, default=False)
    currency_id = fields.Many2one(related="case_id.currency_id")
    rule_code = fields.Char(
        help="Statutory rule code that produced this line, for traceability.",
    )
    computation_json = fields.Text(
        help="Frozen inputs and workings for this line. Read at dispute time "
        "when the underlying record has moved on.",
    )
    is_negative = fields.Boolean(
        help="Amount owed by the employee. These lines are governed by the "
        "reason's recovery permission, not merely netted off.",
    )

    @api.model
    def _build_lines(self, case):
        """Return (payable_lines, deduction_lines, details) as plain dicts.

        Kept as a model method returning plain data rather than creating rows
        directly, so the whole statement can be built and checksummed as one
        atomic unit before anything is persisted.
        """
        employee = case.employee_id
        lines = []
        details = {}

        # ── Salary to the last working day ──────────────────────────────
        lines.append(
            _line(
                "salary_to_last_day",
                _salary_to_last_day(case),
                is_deduction=False,
                rule_code=None,
                detail={"basis": "pro-rated to the last working day"},
            )
        )

        # ── Leave encashment and excess leave ───────────────────────────
        encashment, encashment_detail = _leave_encashment(case)
        details["leave"] = encashment_detail
        for item in encashment:
            lines.append(item)

        # ── Gratuity ────────────────────────────────────────────────────
        if case.reason_id.gratuity_eligible:
            gratuity, gratuity_detail = _gratuity(case)
            if gratuity:
                lines.append(gratuity)
            details["gratuity"] = gratuity_detail

        # ── Notice shortfall ────────────────────────────────────────────
        shortfall, shortfall_detail = _notice_shortfall(case)
        if shortfall:
            lines.append(shortfall)
        details["notice"] = shortfall_detail

        payable = [l for l in lines if not l["is_deduction"]]
        deductions = [l for l in lines if l["is_deduction"]]
        return payable, deductions, details


def _line(line_type, amount, is_deduction, rule_code, detail, label=None):
    return {
        "line_type": line_type,
        "label": label or dict(LINE_LABELS).get(line_type, line_type),
        "amount": round(float(amount), 2),
        "is_deduction": is_deduction,
        "is_negative": amount < 0,
        "rule_code": rule_code,
        "computation": detail,
    }


LINE_LABELS = [
    ("salary_to_last_day", "Salary to last working day"),
    ("leave_encashment", "Leave encashment"),
    ("leave_excess", "Excess leave recovery"),
    ("gratuity", "Gratuity"),
    ("bonus", "Statutory bonus"),
    ("notice_shortfall", "Notice shortfall recovery"),
    ("advance_recovery", "Advance recovery"),
    ("asset_recovery", "Asset recovery"),
    ("loan_recovery", "Loan recovery"),
    ("overpayment_recovery", "Overpayment recovery"),
    ("notice_pay", "Notice pay"),
    ("other_payable", "Other payable"),
    ("other_deduction", "Other deduction"),
    ("statutory_dues", "Statutory dues shortfall"),
]


def _salary_to_last_day(case):
    """Days actually worked in the final month, prorated.

    Uses the roster where available, because a machine operator whose last day
    falls mid-shift is paid for the shift, not for a calendar day. Falls back to
    calendar days when the employee was never rostered in the period.
    """
    employee = case.employee_id
    last = case.last_working_day
    month_start = last.replace(day=1)
    worked = 0.0
    source = "calendar"

    Assignment = case.env["hr.roster.assignment"].sudo()
    assignments = Assignment.search(
        [
            ("employee_id", "=", employee.id),
            ("start_datetime", ">=", f"{month_start} 00:00:00"),
            ("start_datetime", "<=", f"{last} 23:59:59"),
            ("state", "in", ("confirmed", "published", "relieved")),
        ]
    )
    if assignments:
        worked = sum(assignments.mapped("paid_hours") or assignments.mapped("actual_hours"))
        source = "roster"
    else:
        worked = (last - month_start).days + 1

    contract = employee.contract_id
    monthly_wage = float(contract.wage or 0.0)
    if not monthly_wage:
        return _line(
            "salary_to_last_day",
            0.0,
            is_deduction=False,
            rule_code=None,
            detail={
                "error": "no contract wage",
                "message": f"{employee.name} has no contract wage, so salary to "
                "the last working day cannot be computed. Fix the contract.",
            },
        )
    days_in_month = _days_in_month(last)
    amount = monthly_wage / days_in_month * worked if source == "calendar" else \
        monthly_wage / (days_in_month * 8.0) * worked
    return _line(
        "salary_to_last_day",
        amount,
        is_deduction=False,
        rule_code=None,
        detail={
            "basis": source,
            "monthly_wage": monthly_wage,
            "days_in_month": days_in_month,
            "worked_units": worked,
            "formula": (
                "monthly_wage / days_in_month * days_worked"
                if source == "calendar"
                else "monthly_wage / (days_in_month * 8) * rostered_hours"
            ),
        },
    )


def _leave_encashment(case):
    """Encash unused statutory leave; recover excess leave taken.

    Uses the pay code on each leave type rather than guessing, and refuses to
    price a leave that has no pay code, because an unpriced encashment is a
    silent zero the employee will dispute.
    """
    employee = case.employee_id
    ctx = case.env["hrms.statutory.context"]
    carry_forward_days = ctx.get_json(
        "IN.LEAVE.CARRY_FORWARD_DAYS",
        case.company_id,
        state_code=employee.hrms_state_code,
        contract_type=employee.contract_type,
        on_date=case.last_working_day,
    )
    lines = []
    detail = {"leave_types": [], "carry_forward_limit": carry_forward_days}

    Leave = case.env["hr.leave"].sudo()
    types = case.env["hr.leave.type"].sudo().search(
        [("employee_type", "=", "employee")]
    )
    monthly_wage = float(employee.contract_id.wage or 0.0)
    days_in_month = _days_in_month(case.last_working_day)

    for leave_type in types:
        taken = Leave.search_count(
            [
                ("employee_id", "=", employee.id),
                ("holiday_status_id", "=", leave_type.id),
                ("state", "=", "validate"),
                ("date_from", "<=", case.last_working_day),
            ]
        )
        allocated = _leave_allocated(case, leave_type, days_in_month)
        if not allocated:
            detail["leave_types"].append(
                {"leave_type": leave_type.name, "taken": taken,
                 "note": "no accrual configured; carry-forward rules come from "
                         "statutory config, so nothing was valued"}
            )
            continue
        unused = max(allocated - taken, 0)
        excess = max(taken - allocated, 0)
        entry = {
            "leave_type": leave_type.name,
            "statutory": leave_type.statutory,
            "allocated": allocated,
            "taken": taken,
            "unused": unused,
            "excess": excess,
            "payroll_code": leave_type.payroll_code,
        }
        detail["leave_types"].append(entry)

        if unused and leave_type.encashable:
            if not leave_type.payroll_code:
                raise UserError(
                    f"{employee.name}: leave type '{leave_type.name}' has "
                    f"{unused} day(s) to encash but no payroll pay code, so the "
                    "amount cannot be priced. Assign a pay code to the leave type."
                )
            divisor = days_in_month
            formula = leave_type.encashment_formula
            if formula == "daily_wages":
                daily = (employee.hrms_ctc or monthly_wage) / 365.0
            elif formula == "average_last_m":
                daily = _average_daily_wage(case, monthly_wage)
            elif formula == "not_encashable":
                daily = 0.0
            else:  # monthly_divisor
                daily = monthly_wage / divisor if divisor else 0.0
            lines.append(
                _line(
                    "leave_encashment",
                    daily * unused,
                    is_deduction=False,
                    rule_code="IN.LEAVE.ENCRASHMENT_FREQUENCY",
                    detail={
                        **entry,
                        "daily_rate": round(daily, 2),
                        "formula": formula,
                    },
                    label=f"Leave encashment: {leave_type.name} ({unused}d)",
                )
            )
        if excess:
            daily = monthly_wage / days_in_month if days_in_month else 0.0
            if carry_forward_days and excess > float(carry_forward_days):
                lines.append(
                    _line(
                        "leave_excess",
                        daily * excess,
                        is_deduction=True,
                        rule_code="IN.LEAVE.CARRY_FORWARD_DAYS",
                        detail={
                            **entry,
                            "daily_rate": round(daily, 2),
                            "note": f"{excess} day(s) beyond the accrual",
                        },
                        label=f"Excess leave: {leave_type.name} ({excess}d)",
                    )
                )
    return lines, detail


def _leave_allocated(case, leave_type, days_in_month):
    """Days of a leave type accrued up to the last working day.

    Deliberately not hardcoded. Statutory accrual for annual leave varies by
    category and State; where it is not configured, the line is skipped and the
    reason recorded rather than a 30-day default being assumed.
    """
    ctx = case.env["hrms.statutory.context"]
    try:
        value = ctx.get_json(
            f"IN.LEAVE.ACCRUAL_DAYS.{leave_type.code or leave_type.id}",
            case.company_id,
            state_code=case.employee_id.hrms_state_code,
            contract_type=case.employee_id.contract_type,
            on_date=case.last_working_day,
        )
    except UserError:
        return 0.0
    if not value:
        return 0.0
    months = value.get("annual_days", 0) / 12.0 if value.get("annual_days") else 0
    if value.get("monthly_days"):
        months = float(value["monthly_days"])
    service_months = _months(case.employee_id.hrms_service_start or case.employee_id.join_date,
                             case.last_working_day)
    return round(months * months, 2)


def _average_daily_wage(case, fallback):
    slips = case.env["hr.payslip"].sudo().search(
        [
            ("employee_id", "=", case.employee_id.id),
            ("date_from", "<=", case.last_working_day),
            ("state", "in", ("done", "paid")),
        ],
        limit=3,
        order="date_to desc",
    )
    if not slips:
        return fallback / _days_in_month(case.last_working_day)
    totals = [sum(l.total for l in s.line_ids) for s in slips]
    return (sum(totals) / len(totals)) / _days_in_month(case.last_working_day)


def _gratuity(case):
    try:
        result = case.env["hrms.gratuity.engine"].sudo().compute(
            case.employee_id,
            case.last_working_day,
            case.reason_id.code,
            wage_basis=float(case.employee_id.hrms_ctc or 0.0) / 12.0
            if case.employee_id.hrms_ctc
            else float(case.employee_id.contract_id.wage or 0.0),
        )
    except UserError as exc:
        return None, {"error": str(exc)}
    detail = {
        "eligible": result.eligible,
        "reason": result.ineligibility_reason,
        "service_months": result.total_service_months,
        "wage_basis": result.wage_basis,
        "days_per_year": result.days_per_year,
        "rule_versions": result.rule_versions_json,
    }
    if not result.eligible or not result.gratuity_amount:
        return None, detail
    line = _line(
        "gratuity",
        result.gratuity_amount,
        is_deduction=False,
        rule_code="IN.GRATUITY.ELIGIBILITY",
        detail=detail,
    )
    return line, detail


def _notice_shortfall(case):
    shortfall_days = case.notice_shortfall_days
    detail = {
        "notice_period_days": case.notice_period_days,
        "notice_served_days": case.notice_served_days,
        "shortfall_days": shortfall_days,
        "recovery_permitted": case.reason_id.permits_recovery,
    }
    if not shortfall_days:
        return None, detail
    if not case.reason_id.permits_recovery:
        detail["note"] = (
            f"Shortfall of {shortfall_days} day(s) exists but "
            f"'{case.reason_id.name}' does not permit recovery, so no deduction "
            "was made. Recovering it without authority would itself be "
            "unlawful."
        )
        return None, detail
    daily = float(case.employee_id.contract_id.wage or 0.0) / _days_in_month(
        case.last_working_day
    )
    line = _line(
        "notice_shortfall",
        daily * shortfall_days,
        is_deduction=True,
        rule_code="IN.FNF.NOTICE_SHORTFILL_DAYS",
        detail={**detail, "daily_rate": round(daily, 2)},
    )
    return line, detail


def _days_in_month(day):
    from calendar import monthrange

    return monthrange(day.year, day.month)[1]


def _months(start, end):
    if not start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)