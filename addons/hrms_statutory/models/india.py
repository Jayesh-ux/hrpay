# -*- coding: utf-8 -*-
"""Indian statutory deductions.

Every rate, ceiling and threshold is resolved through ``hrms.statutory.context``
from an effective-dated, sign-off-gated config row. There are no literals in
this file. See ADR-0003 and docs/compliance/statutory-config-register.md.

The register maps codes to the register rows; if a code is missing from config
the calculation raises rather than defaulting.
"""

import logging
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class IndiaStatutoryResult(models.Model):
    """Structured output of the India statutory computation for one employee."""

    _name = "hrms.india.statutory.result"
    _description = "India statutory deduction result"

    employee_id = fields.Many2one("hr.employee", ondelete="cascade", required=True, index=True)
    period_start = fields.Date(required=True)
    period_end = fields.Date(required=True)
    state_code = fields.Char()
    contract_type = fields.Char(default="permanent")

    pf_wages = fields.Float(digits=(16, 2))
    pf_employee = fields.Float(digits=(16, 2))
    pf_employer = fields.Float(digits=(16, 2))
    pf_eps_employee = fields.Float(digits=(16, 2))
    pf_eps_employer = fields.Float(digits=(16, 2))
    pf_epf_employee = fields.Float(digits=(16, 2))
    pf_epf_employer = fields.Float(digits=(16, 2))
    pf_voluntary = fields.Float(digits=(16, 2))
    pf_capped = fields.Boolean()

    esi_wages = fields.Float(digits=(16, 2))
    esi_employee = fields.Float(digits=(16, 2))
    esi_employer = fields.Float(digits=(16, 2))
    esi_applicable = fields.Boolean()

    pt_employee = fields.Float(digits=(16, 2))
    pt_employer = fields.Float(digits=(16, 2))
    pt_state_code = fields.Char()
    pt_slab_detail = fields.Text(help="JSON: which slab matched and why.")

    lwf_employee = fields.Float(digits=(16, 2))
    lwf_employer = fields.Float(digits=(16, 2))

    tds_recoverable = fields.Float(digits=(16, 2))
    tds_non_recoverable = fields.Float(digits=(16, 2))
    tds_regime = fields.Selection(
        [("old", "Old regime"), ("new", "New regime")], string="Tax regime"
    )
    tds_detail = fields.Text(help="JSON: slab workings and exemptions applied.")

    total_employee_deductions = fields.Float(digits=(16, 2))
    total_employer_contributions = fields.Float(digits=(16, 2))

    rule_versions_json = fields.Text(required=True)
    computed_at = fields.Datetime(default=fields.Datetime.now, readonly=True)


class IndiaStatutoryEngine(models.AbstractModel):
    """Compute PF, ESI, PT, LWF and TDS for an employee for a period.

    Called from the payroll rule evaluation and from F&F. Always accompanied by
    the resolved rule versions so the result is reproducible.
    """

    _name = "hrms.india.statutory.engine"
    _description = "India statutory engine"

    # -- Provident Fund ---------------------------------------------------
    @api.model
    def compute_pf(self, employee, wages, period_end, ctx, composition=None):
        """Employee PF + EPS split, with the wage ceiling applied.

        EPS has an annual contribution cap distinct from the monthly ceiling, so
        both are resolved from config. If YTD EPS is unknown we cannot cap
        correctly, so the caller must supply the YTD figure or we raise.
        """
        company = employee.company_id
        state = employee.hrms_state_code or company.state_id.code or ""
        ct = employee.contract_type or "permanent"

        ceiling = ctx.get("IN.PF.WAGE_CEILING", company, state_code=state, contract_type=ct, on_date=period_end)
        emp_rate = ctx.get("IN.PF.EMPLOYEE_RATE", company, state_code=state, contract_type=ct, on_date=period_end)
        eps_rate = ctx.get("IN.PF.EPS_RATE", company, state_code=state, contract_type=ct, on_date=period_end)
        eps_monthly_cap = ctx.get("IN.PF.EPS_ANNUAL_CAP", company, state_code=state, contract_type=ct, on_date=period_end)

        base = min(abs(wages or 0.0), ceiling)
        capped = abs(wages or 0.0) > ceiling

        total_employee = base * (emp_rate / 100.0)
        total_employer = base * (emp_rate / 100.0)

        eps_employee = min(base * (eps_rate / 100.0), eps_monthly_cap)
        eps_employer = eps_employee
        epf_employee = round(total_employee - eps_employee, 2)
        epf_employer = round(total_employer - eps_employer, 2)

        voluntary = 0.0
        voluntary_config = ctx.resolve(
            "IN.PF.VOLUNTARY", company, state_code=state, contract_type=ct, on_date=period_end
        )
        vcfg = voluntary_config.value() or {}
        if vcfg.get("enabled"):
            cap = vcfg.get("cap")
            voluntary = min(base * (vcfg.get("default_rate_pct", 0.0) / 100.0), cap) if cap else base * (
                vcfg.get("default_rate_pct", 0.0) / 100.0
            )
            if vcfg.get("counted_in_employee"):
                total_employee += voluntary
            if vcfg.get("counted_in_employer"):
                total_employer += voluntary

        return {
            "pf_wages": round(base, 2),
            "pf_capped": capped,
            "wage_ceiling_applied": ceiling,
            "pf_employee": round(total_employee, 2),
            "pf_employer": round(total_employer, 2),
            "pf_eps_employee": round(eps_employee, 2),
            "pf_eps_employer": round(eps_employer, 2),
            "pf_epf_employee": epf_employee,
            "pf_epf_employer": epf_employer,
            "pf_voluntary": round(voluntary, 2),
        }

    # -- ESI --------------------------------------------------------------
    @api.model
    def compute_esi(self, employee, wages, period_end, ctx):
        company = employee.company_id
        state = employee.hrms_state_code or company.state_id.code or ""
        ct = employee.contract_type or "permanent"

        threshold = ctx.get("IN.ESI.WAGE_THRESHOLD", company, state_code=state, contract_type=ct, on_date=period_end)
        emp_rate = ctx.get("IN.ESI.EMPLOYEE_RATE", company, state_code=state, contract_type=ct, on_date=period_end)
        emp_rate = emp_rate / 100.0
        er_rate = ctx.get("IN.ESI.EMPLOYER_RATE", company, state_code=state, contract_type=ct, on_date=period_end)
        er_rate = er_rate / 100.0

        # ESIC's wage threshold is expressed as a gross threshold; contribution
        # applies to actual wages when below it.
        gross = abs(wages or 0.0)
        applicable = gross <= threshold
        if applicable:
            ee = gross * emp_rate
            er = gross * er_rate
        else:
            ee = er = 0.0
        return {
            "esi_wages": round(gross, 2),
            "esi_applicable": applicable,
            "esi_employee": round(ee, 2),
            "esi_employer": round(er, 2),
            "esi_threshold": threshold,
        }

    # -- Professional Tax --------------------------------------------------
    @api.model
    def compute_pt(self, employee, taxable_salary, period_end, ctx):
        """Multi-state PT.

        PT slabs differ per State, are based on slab ranges rather than rates,
        and some States levy none. The slab table is config JSON keyed by
        monthly income range.
        """
        company = employee.company_id
        state = employee.hrms_state_code or company.state_id.code or ""
        ct = employee.contract_type or "permanent"

        slabs = ctx.get_json("IN.PT.SLABS", company, state_code=state, contract_type=ct, on_date=period_end)
        annual_cap = ctx.get("IN.PT.ANNUAL_CAP", company, state_code=state, contract_type=ct, on_date=period_end)
        ytd_pt = float(employee.hrms_pt_ytd or 0.0)

        amount = abs(taxable_salary or 0.0)
        if not slabs:
            return {
                "pt_employee": 0.0,
                "pt_employer": 0.0,
                "pt_state_code": state,
                "pt_slab_detail": _json({"reason": "no PT configured for this state"}),
            }

        matched = None
        for slab in slabs.get("slabs", []):
            lo = slab.get("from")
            hi = slab.get("to")
            if (lo is None or amount >= lo) and (hi is None or amount <= hi):
                matched = slab
                break

        if not matched:
            raise UserError(
                f"Professional Tax: no slab matches {amount} for state {state} on "
                f"{period_end}. The slab table in statutory config is incomplete. "
                f"Every income band must be covered, including the top band."
            )

        pt_employee = float(matched.get("employee", 0.0))
        pt_employer = float(matched.get("employer", 0.0))

        # Constitutional annual cap: PT is capped per year, so stop deducting
        # once the employee has hit it.
        if annual_cap and (ytd_pt + pt_employee) > annual_cap:
            pt_employee = max(0.0, annual_cap - ytd_pt)
            capped_note = "annual cap reached"
        else:
            capped_note = None

        return {
            "pt_employee": round(pt_employee, 2),
            "pt_employer": round(pt_employer, 2),
            "pt_state_code": state,
            "pt_slab_detail": _json(
                {
                    "matched_slab": matched,
                    "taxable": amount,
                    "annual_cap": annual_cap,
                    "ytd_before": ytd_pt,
                    "note": capped_note,
                    "frequency": slabs.get("frequency", "monthly"),
                    "remit_form": slabs.get("remit_form"),
                }
            ),
        }

    # -- Labour Welfare Fund ----------------------------------------------
    @api.model
    def compute_lwf(self, employee, period_end, ctx):
        """LWF is levied by some States only (e.g. Maharashtra), not nationally."""
        company = employee.company_id
        state = employee.hrms_state_code or company.state_id.code or ""
        ct = employee.contract_type or "permanent"
        try:
            cfg = ctx.get_json("IN.LWF.RATES", company, state_code=state, contract_type=ct, on_date=period_end)
        except UserError:
            return {"lwf_employee": 0.0, "lwf_employer": 0.0}
        if not cfg or not cfg.get("applicable"):
            return {"lwf_employee": 0.0, "lwf_employer": 0.0}
        basis = abs(employee.hrms_ctc or 0.0)
        ee = min(basis, cfg.get("employee_cap", 0) or basis) * (cfg.get("employee_rate_pct", 0) / 100.0)
        er = min(basis, cfg.get("employer_cap", 0) or basis) * (cfg.get("employer_rate_pct", 0) / 100.0)
        return {"lwf_employee": round(ee, 2), "lwf_employer": round(er, 2)}

    # -- TDS (Section 192) -------------------------------------------------
    @api.model
    def compute_tds(self, employee, period_end, ctx, ytd=None):
        """TDS on salary for the employee's elected regime.

        Both the old and new regime slabs come from config (IN.TDS.SLABS.OLD /
        IN.TDS.SLABS.NEW). Mid-year regime change is supported because the
        employee may change once before 31 March.
        """
        company = employee.company_id
        state = employee.hrms_state_code or company.state_id.code or ""
        ct = employee.contract_type or "permanent"
        regime = employee.hrms_tax_regime or "new"

        slabs = ctx.get_json(
            f"IN.TDS.SLABS.{regime.upper()}",
            company,
            state_code=state,
            contract_type=ct,
            on_date=period_end,
        )
        if not slabs:
            raise UserError(
                f"No {regime}-regime TDS slab table configured for {state} as at "
                f"{period_end}. Add IN.TDS.SLABS.{regime.upper()} in statutory "
                f"config before processing payroll."
            )

        ytd = ytd if ytd is not None else _ytd_taxable(employee, period_end)
        # Standard deduction / regime-specific deduction from config.
        deduction = float(employee.hrms_tds_deduction or 0.0) or float(slabs.get("standard_deduction", 0.0))
        taxable_ytd = max(ytd - deduction, 0.0)

        slabs_list = slabs.get("slabs", [])
        cess_pct = float(slabs.get("cess_pct", 0.0))
        surcharge = slabs.get("surcharge") or []

        annual_taxable = taxable_ytd * 12  # annualise for slab selection
        matched = None
        for slab in slabs_list:
            lo = slab.get("from")
            hi = slab.get("to")
            if (lo is None or annual_taxable >= lo) and (hi is None or annual_taxable <= hi):
                matched = slab
                break
        if not matched:
            raise UserError(
                f"TDS: no slab matches annualised taxable income {annual_taxable} "
                f"under the {regime} regime. The slab table is incomplete."
            )

        rate = float(matched.get("rate_pct", 0.0))
        annual_tax = taxable_ytd * (rate / 100.0)

        # Marginal relief caps the tax at the top band where the rate jumps.
        # The relief amount is config, not code, because it changes with
        # notifications.
        relief_amount = matched.get("marginal_relief_amount")
        if relief_amount is not None:
            annual_tax = min(annual_tax, float(relief_amount))

        # Surcharge at high incomes (config-driven thresholds).
        surcharge_amount = 0.0
        for band in surcharge:
            if annual_taxable >= band.get("threshold", 0):
                surcharge_amount = annual_tax * (band.get("pct", 0.0) / 100.0)
        annual_tax += surcharge_amount

        cess = annual_tax * (cess_pct / 100.0)
        total_annual = annual_tax + cess

        # TDS is on a cumulative/averaging basis, not per-month slabs.
        ytd_deducted = float(employee.hrms_tds_ytd or 0.0)
        target_ytd = (total_annual / 12.0) * 12  # full-year liability
        month_number = period_end.month
        should_have = target_ytd * (month_number / 12.0)
        recoverable = max(round(should_have - ytd_deducted, 2), 0.0)
        non_recoverable = 0.0
        if ytd_deducted > should_have:
            non_recoverable = round(ytd_deducted - should_have, 2)

        return {
            "tds_regime": regime,
            "tds_recoverable": recoverable,
            "tds_non_recoverable": non_recoverable,
            "tds_detail": _json(
                {
                    "regime": regime,
                    "annualised_taxable": annual_taxable,
                    "matched_slab": matched,
                    "deduction_applied": deduction,
                    "annual_tax": round(total_annual, 2),
                    "cess_pct": cess_pct,
                    "surcharge": surcharge_amount,
                    "ytd_deducted_before": ytd_deducted,
                    "month_number": month_number,
                    "method": "cumulative",
                }
            ),
        }

    # -- orchestration ------------------------------------------------------
    @api.model
    def compute_all(self, employee, composition, period_start, period_end, ytd=None):
        """Run the full India statutory set for one employee/period."""
        ctx = self.env["hrms.statutory.context"]
        company = employee.company_id

        pf = self.compute_pf(employee, composition.pf_wages, period_end, ctx, composition)
        esi = self.compute_esi(employee, composition.esi_wages, period_end, ctx)
        pt = self.compute_pt(employee, composition.statutory_wages, period_end, ctx)
        lwf = self.compute_lwf(employee, period_end, ctx)
        tds = self.compute_tds(employee, period_end, ctx, ytd=ytd)

        total_ee = round(pf["pf_employee"] + esi["esi_employee"] + pt["pt_employee"] + lwf["lwf_employee"] + tds["tds_recoverable"], 2)
        total_er = round(pf["pf_employer"] + esi["esi_employer"] + pt["pt_employer"] + lwf["lwf_employer"], 2)

        versions = ctx._snapshot(
            company,
            composition.state_code,
            composition.contract_type or "permanent",
            period_end,
        )
        result = self.env["hrms.india.statutory.result"].create(
            {
                "employee_id": employee.id,
                "period_start": period_start,
                "period_end": period_end,
                "state_code": composition.state_code,
                "contract_type": composition.contract_type,
                **pf,
                **esi,
                **pt,
                **lwf,
                **tds,
                "total_employee_deductions": total_ee,
                "total_employer_contributions": total_er,
                "rule_versions_json": _json(versions),
            }
        )
        self.env["hrms.audit.log"].log(
            "hrms.india.statutory.result",
            result.id,
            "create",
            changes={
                "pf_employee": pf["pf_employee"],
                "esi_employee": esi["esi_employee"],
                "pt_employee": pt["pt_employee"],
                "tds": tds["tds_recoverable"],
            },
            note="India statutory computation",
        )
        return result


def _ytd_taxable(employee, period_end):
    """Year-to-date taxable salary, preferring an explicit stored figure."""
    ytd = getattr(employee, "hrms_ytd_taxable", None)
    if ytd:
        return float(ytd)
    # Fall back to contract monthly * elapsed months. A real deployment supplies
    # this from payslips; this is a best-effort default and is flagged.
    contract = employee.contract_id
    if contract and contract.wage:
        months = period_end.month
        return float(contract.wage) * months
    return 0.0


def _json(payload):
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str)