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

from . import settlement_arithmetic as _settlement

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
        # _salary_to_last_day returns a complete _line dict.
        lines.append(_salary_to_last_day(case))

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
        [
            ("company_id", "in", [case.company_id.id, False]),
            "|",
            ("payroll_code", "!=", False),
            ("statutory", "=", True),
        ]
    )
    monthly_wage = float(employee.contract_id.wage or 0.0)
    days_in_month = _days_in_month(case.last_working_day)
    basis_config = ctx.get_json(
        "IN.FNF.ENCASHMENT_WAGE_BASIS",
        case.company_id,
        state_code=employee.hrms_state_code,
        contract_type=employee.contract_type,
        on_date=case.last_working_day,
    ) or {}

    for leave_type in types:
        taken = Leave.search_count(
            [
                ("employee_id", "=", employee.id),
                ("holiday_status_id", "=", leave_type.id),
                ("state", "=", "validate"),
                ("date_from", "<=", case.last_working_day),
            ]
        )
        allocated = _leave_allocated(case, leave_type)
        if allocated is None:
            detail["leave_types"].append(
                {"leave_type": leave_type.name, "taken": taken,
                 "note": "not an accrual-bearing leave type (neither statutory nor "
                         "encashable) and no accrual is configured for it, so "
                         "there is no balance to value or recover"}
            )
            continue
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
            formula = leave_type.encashment_formula
            basis = basis_config.get("basis", "wages")
            try:
                if formula == "daily_wages":
                    # The previous code was ``(employee.hrms_ctc or monthly_wage)
                    # / 365.0``: CTC is not wages, and 365 is a year rather than
                    # the divisor of a month, so the rate was roughly an order of
                    # magnitude too low on the wrong basis.
                    daily = _settlement.daily_wage(
                        monthly_wage=_last_drawn_monthly_wages(case),
                        days_in_month=days_in_month,
                        basis=basis,
                    )
                elif formula == "average_last_m":
                    daily = _settlement.daily_wage(
                        monthly_wage=_average_monthly_wages(
                            case, basis_config.get("average_months", 3)
                        ),
                        days_in_month=days_in_month,
                        basis=basis,
                    )
                elif formula == "not_encashable":
                    daily = 0.0
                else:  # monthly_divisor
                    daily = _settlement.daily_wage(
                        monthly_wage=monthly_wage,
                        days_in_month=days_in_month,
                        basis=basis,
                    )
            except ValueError as exc:
                raise UserError(
                    f"{employee.name}: leave encashment for '{leave_type.name}' "
                    f"cannot be priced: {exc} Configure "
                    f"IN.FNF.ENCASHMENT_WAGE_BASIS and supply the wages figure."
                ) from exc
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
            # Priced at the same rate the encashment used, so the two sides of the
            # same leave type cannot disagree.
            daily = 0.0
            for line in lines:
                if (line["line_type"] == "leave_encashment"
                        and line["computation"].get("leave_type") == leave_type.name):
                    daily = float(line["computation"]["daily_rate"])
                    break
            if not daily:
                try:
                    daily = _settlement.daily_wage(
                        monthly_wage=monthly_wage,
                        days_in_month=days_in_month,
                        basis="wages",
                    )
                except ValueError as exc:
                    raise UserError(
                        f"{employee.name}: excess leave on '{leave_type.name}' "
                        f"cannot be priced: {exc}"
                    ) from exc
            split = _settlement.encashment_for_leave(
                unused_days=0.0,
                daily_rate=daily,
                excess_days=excess,
                carry_forward_days=carry_forward_days,
            )
            if split["recoverable_amount"]:
                entry["excess_note"] = (
                    f"{excess} day(s) beyond the accrual, recovered after the "
                    f"{carry_forward_days} day(s) carry-forward allowance"
                )
                lines.append(
                    _line(
                        "leave_excess",
                        split["recoverable_amount"],
                        is_deduction=True,
                        rule_code="IN.LEAVE.CARRY_FORWARD_DAYS",
                        detail={
                            **entry,
                            "daily_rate": round(daily, 2),
                            "excess_days": excess,
                            "recoverable_days": split["recoverable_days"],
                            "note": f"{excess} day(s) beyond the accrual",
                        },
                        label=f"Excess leave: {leave_type.name} ({excess}d)",
                    )
                )
            else:
                entry["excess_note"] = (
                    f"{excess} day(s) beyond the accrual, all inside the "
                    f"{carry_forward_days} day(s) carry-forward allowance, so "
                    f"nothing is recovered"
                )
    return lines, detail


def _leave_allocated(case, leave_type):
    """Days of a leave type accrued by the last working day.

    The previous implementation resolved
    ``IN.LEAVE.ACCRUAL_DAYS.<leave type>`` -- a code that never existed in the
    catalog -- swallowed the resulting ``UserError`` and returned ``0.0``. So
    every leave encashment was silently zero: a statutory payment that is always
    wrong, raises nothing, and leaves a clean payslip.

    It then computed ``months * months``, having rebound ``months`` from the
    per-month accrual to the count of service months. Eighteen months of service
    produced **324** days of leave.

    Accrual is linear: per-month accrual times months of service. Both halves come
    from the single catalog code ``IN.LEAVE.ACCRUAL_DAYS_PER_YEAR``, keyed by
    leave type code. A leave type with no configured accrual raises rather than
    being valued at zero, because zero is indistinguishable from a genuine nil.
    """
    ctx = case.env["hrms.statutory.context"]
    employee = case.employee_id
    config = ctx.get_json(
        "IN.LEAVE.ACCRUAL_DAYS_PER_YEAR",
        case.company_id,
        state_code=employee.hrms_state_code,
        contract_type=employee.contract_type,
        on_date=case.last_working_day,
    )
    by_type = (config or {}).get("by_leave_type", {})
    key = leave_type.code or str(leave_type.id)
    entry = by_type.get(key)
    if entry is None:
        entry = (config or {}).get("default")
    if entry is None:
        # A leave type that is neither statutory nor encashable is not an
        # accrual-bearing balance: a sick-leave or casual-leave type with no
        # accrual rule is a legitimate configuration, and refusing the whole
        # settlement over it would be wrong. A leave type we are going to *pay*
        # for or *recover* is a different matter, and is refused.
        if not (leave_type.statutory or leave_type.encashable):
            return None
        raise UserError(
            f"{employee.name}: no accrual configured for leave type "
            f"'{leave_type.name}' (code {key!r}) in IN.LEAVE.ACCRUAL_DAYS_PER_YEAR. "
            f"It is marked statutory or encashable, so its accrual has to exist "
            f"before it can be valued or recovered. Accrual differs by category "
            f"and by State, so it is not guessed. See CA request section 4.4."
        )

    months = _months(
        employee.hrms_service_start or employee.join_date, case.last_working_day
    )
    try:
        return _settlement.accrued_leave_days(
            annual_days=entry.get("annual_days"),
            monthly_days=entry.get("monthly_days"),
            months_of_service=months,
        )
    except ValueError as exc:
        raise UserError(
            f"{employee.name}: leave accrual for '{leave_type.name}' is "
            f"unusable: {exc}"
        ) from exc


def _gross_earnings(slip):
    """Gross earnings on one payslip: earnings only, no employer burden.

    The previous code summed ``l.total for l in s.line_ids``, which added the
    employer's PF and other contributions to the basis and netted employee
    deductions off it.
    """
    lines = slip.line_ids
    rule_model = slip.env["hr.salary.rule"]
    if "is_employer_contribution" in rule_model._fields:
        lines = lines - lines.filtered(
            lambda line: line.salary_id.is_employer_contribution
        )
    total = sum(float(line.total or 0.0) for line in lines
                if float(line.total or 0.0) > 0)
    return total


def _last_drawn_monthly_wages(case):
    """Wages on the most recent paid payslip.

    Refuses when there is none, rather than falling back to the contract wage.
    """
    employee = case.employee_id
    slip = case.env["hr.payslip"].sudo().search(
        [
            ("employee_id", "=", employee.id),
            ("date_from", "<=", case.last_working_day),
            ("state", "in", ("done", "paid")),
        ],
        limit=1,
        order="date_to desc",
    )
    if not slip:
        raise ValueError(
            f"no paid payslip for {employee.name} on or before "
            f"{case.last_working_day}; the contract wage is refused as a wage "
            f"basis because it is not last-drawn wages"
        )
    total = _gross_earnings(slip)
    if total <= 0:
        raise ValueError(
            f"payslip {slip.display_name or slip.id} has no gross earnings lines"
        )
    return total


def _average_monthly_wages(case, months):
    """Average gross earnings over the last ``months`` paid payslips.

    :raises ValueError: when there are no payslips. The previous version fell
        back to the contract wage divided by the day count of the exit month, and
        divided a three-month average by the length of one month, so the same
        employee encashing in February was paid a daily rate 25% lower than in
        March.
    """
    employee = case.employee_id
    slips = case.env["hr.payslip"].sudo().search(
        [
            ("employee_id", "=", employee.id),
            ("date_from", "<=", case.last_working_day),
            ("state", "in", ("done", "paid")),
        ],
        limit=months,
        order="date_to desc",
    )
    if not slips:
        raise ValueError(
            f"no paid payslips for {employee.name} to average over {months} "
            f"month(s); the contract wage is refused as a wage basis"
        )
    totals = [_gross_earnings(slip) for slip in slips]
    if not any(totals):
        raise ValueError(
            f"the last {months} payslip(s) for {employee.name} have no gross "
            f"earnings lines"
        )
    return sum(totals) / len(totals)


def _gratuity(case):
    try:
        result = case.env["hrms.gratuity.engine"].sudo().compute(
            case.employee_id,
            case.last_working_day,
            case.reason_id.code,
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
    try:
        recovery = _settlement.notice_shortfall_recovery(
            shortfall_days=_settlement.notice_shortfall_days(
                contractual_days=case.notice_period_days,
                served_days=case.notice_served_days,
            ),
            daily_rate=_settlement.daily_wage(
                monthly_wage=float(case.employee_id.contract_id.wage or 0.0),
                days_in_month=_days_in_month(case.last_working_day),
                basis="wages",
            ),
            permits_recovery=bool(case.reason_id.permits_recovery),
            max_recoverable=(
                case.notice_recovery_cap if case.notice_recovery_cap else None
            ),
        )
    except ValueError as exc:
        raise UserError(
            f"{case.employee_id.name}: notice shortfall cannot be valued: {exc}"
        ) from exc
    detail.update(recovery["notes"] and {"notes": recovery["notes"]} or {})
    detail["uncapped_amount"] = recovery["uncapped_amount"]
    detail["recovery_suppressed"] = recovery["recovery_suppressed"]
    if recovery["notes"]:
        detail["notes"] = recovery["notes"]
    if not recovery["recovery_amount"]:
        return None, detail
    line = _line(
        "notice_shortfall",
        recovery["recovery_amount"],
        is_deduction=True,
        rule_code="IN.FNF.NOTICE_SHORTFILL_DAYS",
        detail=detail,
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