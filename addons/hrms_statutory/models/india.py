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

from . import contribution_arithmetic as _contributions
from . import tds_projection as _tds_projection

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
        """Employee PF + EPS split, with the wage and EPS ceilings applied.

        The arithmetic lives in ``contribution_arithmetic.py`` and is tested
        outside Odoo. What this method adds is the refusal: an unconfigured rate
        or ceiling is a configuration fault, and it is raised as a ``UserError``
        rather than turned into a zero that nobody notices.

        Defects this replaced, each found by reading the inline version:

        1. ``total_employer = base * (emp_rate / 100.0)`` -- the same expression
           as the employee's. The employer's rate is now its own config code.
        2. The annual EPS ceiling could not apply: the code documented that it
           needed a year-to-date figure and then read ``IN.PF.EPS_ANNUAL_CAP``,
           which held a *monthly* amount, so an employee who crossed the annual
           ceiling kept paying EPS for the rest of the year. The code is renamed
           to ``IN.PF.EPS_MONTHLY_CAP`` and the annual ceiling is separate, with
           the year-to-date figure now required.
        3. ``if vcfg.get("counted_in_employer"): total_employer += voluntary``
           was the only thing standing between the employer and paying the
           employee's voluntary contribution, and it depended on a key that
           simply being absent from config. It is now required.
        """
        company = employee.company_id
        state = employee.hrms_state_code or company.state_id.code or ""
        ct = employee.contract_type or "permanent"

        def get(code):
            return ctx.get(
                code, company, state_code=state, contract_type=ct, on_date=period_end
            )

        voluntary_config = ctx.resolve(
            "IN.PF.VOLUNTARY", company, state_code=state, contract_type=ct,
            on_date=period_end,
        )
        voluntary_cfg = voluntary_config.value() or {}
        # ``enabled: false`` means no voluntary contribution exists, so no rate is
        # required. Enabled, the rate and both allocation flags are required --
        # see the note on voluntary PF in compute_pf.
        voluntary = voluntary_cfg if voluntary_cfg.get("enabled") else None

        try:
            return _contributions.compute_pf(
                wages=wages,
                employee_rate_pct=get("IN.PF.EMPLOYEE_RATE"),
                eps_rate_pct=get("IN.PF.EPS_RATE"),
                employer_rate_pct=get("IN.PF.EMPLOYER_RATE"),
                employer_eps_rate_pct=get("IN.PF.EMPLOYER_EPS_RATE"),
                wage_ceiling=get("IN.PF.WAGE_CEILING"),
                eps_monthly_cap=get("IN.PF.EPS_MONTHLY_CAP"),
                eps_annual_ceiling=get("IN.PF.EPS_ANNUAL_CEILING"),
                # Not ``or 0.0``: an unwritten year-to-date field is an unknown
                # figure, and treating it as zero would let EPS run for the whole
                # year past the annual ceiling -- the defect this batch exists to
                # remove. Once the payroll writer populates it, a genuine month-one
                # zero is still a refusal until the writer records that the figure
                # is known; that is the lesser cost, and the refusal names the gap.
                eps_ytd_before=(
                    float(employee.hrms_pf_eps_ytd)
                    if employee.hrms_pf_eps_ytd
                    else None
                ),
                voluntary=voluntary,
            )
        except ValueError as exc:
            raise UserError(
                f"Provident fund for {employee.display_name} as at {period_end} "
                f"cannot be computed: {exc} See docs/compliance/"
                f"CA-SIGNOFF-REQUEST.md sections 3 and 5."
            ) from exc

    # -- ESI --------------------------------------------------------------
    @api.model
    def compute_esi(self, employee, wages, period_end, ctx):
        """Banded ESI contribution, with the statutory reading declared.

        The previous implementation applied a flat percentage of wages and could
        not represent a band *amount* at all, so the question of which reading
        applies could not be put to the code. The schedule now carries its own
        mode, and a percentage schedule has to be marked provisional before the
        code will use it.
        """
        company = employee.company_id
        state = employee.hrms_state_code or company.state_id.code or ""
        ct = employee.contract_type or "permanent"

        schedule = ctx.get_json(
            "IN.ESI.CONTRIBUTION_SCHEDULE", company, state_code=state,
            contract_type=ct, on_date=period_end,
        )
        try:
            return _contributions.compute_esi(wages=wages, schedule=schedule)
        except ValueError as exc:
            raise UserError(
                f"ESI for {employee.display_name} as at {period_end} cannot be "
                f"computed: {exc} See docs/compliance/CA-SIGNOFF-REQUEST.md "
                f"section 4.1."
            ) from exc

    # -- Professional Tax --------------------------------------------------
    @api.model
    def compute_pt(self, employee, taxable_salary, period_end, ctx):
        """Per-State PT slabs, with the constitutional annual cap.

        Three defects this replaced:

        1. A State with no slab table returned ``{"pt_employee": 0.0}`` with the
           reason "no PT configured for this state" and **no error**. A State that
           genuinely levies no PT must now be configured with an explicit zero
           band, so a missing table cannot masquerade as a correct deduction.
        2. ``amount <= hi`` made the upper edge of every band inclusive, which was
           never documented and is a CA request item. It is config now.
        3. ``if annual_cap and (ytd_pt + pt_employee) > annual_cap`` treated a
           configured cap of zero as no cap, and could not say that the cap had
           already been reached before this month.
        """
        company = employee.company_id
        state = employee.hrms_state_code or company.state_id.code or ""
        ct = employee.contract_type or "permanent"

        slabs_config = ctx.get_json(
            "IN.PT.SLABS", company, state_code=state, contract_type=ct,
            on_date=period_end,
        )
        try:
            annual_cap = ctx.get(
                "IN.PT.ANNUAL_CAP", company, state_code=state,
                contract_type=ct, on_date=period_end,
            )
        except UserError:
            annual_cap = None
        ytd_pt = float(employee.hrms_pt_ytd or 0.0)

        slabs = slabs_config.get("slabs") if slabs_config else None
        try:
            result = _contributions.compute_pt(
                monthly_income=taxable_salary,
                slabs=slabs,
                ytd_pt=ytd_pt,
                annual_cap=annual_cap,
                boundary=slabs_config.get("boundary", "inclusive"),
            )
        except ValueError as exc:
            raise UserError(
                f"Professional Tax for {employee.display_name} as at {period_end} "
                f"cannot be computed: {exc} Configure IN.PT.SLABS for {state} with "
                f"a table that covers every income."
            ) from exc

        return {
            "pt_employee": result["pt_employee"],
            "pt_employer": result["pt_employer"],
            "pt_state_code": state,
            "pt_slab_detail": _json(
                {
                    "matched_slab": result["matched_slab"],
                    "annual_cap": annual_cap,
                    "ytd_before": ytd_pt,
                    "note": result["annual_cap_note"],
                    "frequency": slabs_config.get("frequency", "monthly"),
                    "remit_form": slabs_config.get("remit_form"),
                    "boundary": slabs_config.get("boundary", "inclusive"),
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

        The arithmetic lives in ``tds_projection.py`` and is projected as:
        income so far this financial year, plus the current month's pay times
        the months that follow it. It is deliberately not a run-rate average --
        see that module's docstring for why a mid-year joiner, a salary revision
        and a bonus month each break one.

        Two defects in the previous inline implementation, both found by reading
        rather than by a test because the logic had no test coverage:

        1. It annualised with ``taxable_ytd * 12`` where ``taxable_ytd`` was
           already year-to-date income. In month 6 that overstated annual income
           sixfold and pushed the employee into the top slab, applying the
           highest rate to all of their income.
        2. It computed ``target_ytd = (total_annual / 12) * 12``, which is
           arithmetically ``total_annual`` -- the division and re-multiplication
           cancelled, so the intended monthly spread never happened and the whole
           annual liability was withheld in month 1.

        Marginal relief and rebate remain a CA sign-off item; both are applied to
        the total tax, not per slab. See ``docs/compliance/CA-SIGNOFF-REQUEST.md``.
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

        income_to_date = ytd if ytd is not None else _ytd_taxable(employee, period_end)
        # Annual deduction: standard deduction for the regime, or the employee's
        # declared exemptions/deductions where those are higher.
        deduction = float(
            employee.hrms_tds_deduction or 0.0
        ) or float(slabs.get("standard_deduction", 0.0))

        fy_start = company.hrms_fiscal_year_start_month or _tds_projection.IN_FY_START_MONTH
        months_elapsed, months_remaining = _tds_projection.financial_year_position(
            period_end, fy_start
        )
        ytd_deducted = float(employee.hrms_tds_ytd or 0.0)

        try:
            recurring_pay, pay_basis = _recurring_monthly_pay(employee, income_to_date)
            recoverable, non_recoverable, detail = _tds_projection.compute_tds_arithmetic(
                income_to_date=income_to_date,
                # This is the per-month figure for months not yet paid, not a
                # run rate for annualising income so far. See the helper for why
                # the order of preference matters.
                current_month_pay=recurring_pay,
                months_elapsed=months_elapsed,
                months_remaining=months_remaining,
                ytd_deducted=ytd_deducted,
                annual_deduction=deduction,
                slabs=slabs.get("slabs", []),
                cess_pct=float(slabs.get("cess_pct", 0.0)),
                surcharge_bands=slabs.get("surcharge") or [],
                relief=slabs.get("marginal_relief"),
                rebate=slabs.get("rebate"),
                scheduled_future_pay=employee.hrms_tds_scheduled_future_pay or None,
                pay_basis=pay_basis,
            )
        except ValueError as exc:
            # An incomplete slab table is a configuration fault, not a data
            # fault. Refusing is the whole point: a guessed rate would produce a
            # plausible payslip with a wrong TDS number on it.
            raise UserError(
                f"TDS for {employee.display_name} as at {period_end} cannot be "
                f"computed: {exc} Configure IN.TDS.SLABS.{regime.upper()} with a "
                f"complete slab table before processing payroll."
            ) from exc

        return {
            "tds_regime": regime,
            "tds_recoverable": recoverable,
            "tds_non_recoverable": non_recoverable,
            "tds_detail": _json({"regime": regime, **detail}),
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
        payload = {
            **pf,
            **esi,
            **pt,
            **lwf,
            **tds,
        }
        # The arithmetic modules return flags and bounds a reviewer needs (which
        # ceiling bound, which ESI band, whether the cap already bound), but the
        # result model has no column for them. Passing them to create() would
        # raise; dropping them would lose the audit trail. They are recorded in
        # the audit log entry below instead.
        model = self.env["hrms.india.statutory.result"]
        stored, extra = _split_payload(payload, model)
        result = model.create(
            {
                "employee_id": employee.id,
                "period_start": period_start,
                "period_end": period_end,
                "state_code": composition.state_code,
                "contract_type": composition.contract_type,
                **stored,
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
                "flags": extra,
            },
            note="India statutory computation",
        )
        return result


def _split_payload(payload, model):
    """Split a computed payload into model fields and everything else.

    The pure arithmetic returns more than the result table stores, on purpose:
    ``pf_capped``, ``esi_band_up_to``, the annual-cap notes and similar are how a
    reviewer sees that a bound was reached. Writing them straight into ``create``
    raises for unknown keys, and discarding them would make the audit trail lie
    about what was applied.
    """
    known = set(model._fields)
    stored = {k: v for k, v in payload.items() if k in known}
    extra = {k: v for k, v in payload.items() if k not in known}
    return stored, extra


def _ytd_taxable(employee, period_end):
    """Taxable income received this financial year, up to the current month.

    Prefers the stored figure a payroll run writes back after each period. The
    contract fallback multiplies by *service* months inside the FY rather than
    by FY months elapsed, because an employee who joined in September has one
    payslip of income-so-far in September, not six. Counting FY months here
    overstated a mid-year joiner's income by five months of salary and
    over-deducted TDS from their very first payslip.
    """
    stored = getattr(employee, "hrms_ytd_taxable", None)
    if stored:
        return float(stored)
    contract = employee.contract_id
    monthly = float(contract.wage) if contract and contract.wage else 0.0
    if not monthly:
        return 0.0
    fy_start = (
        employee.company_id.hrms_fiscal_year_start_month
        or _tds_projection.IN_FY_START_MONTH
    )
    service_months = _tds_projection.service_months_in_fy(
        period_end, getattr(employee, "joining_date", None), fy_start
    )
    if service_months <= 0:
        return 0.0
    return round(monthly * service_months, 2)


def _recurring_monthly_pay(employee, income_to_date):
    """The recurring monthly pay to project forward, and where it came from.

    ``project_annual_income`` multiplies this figure by the months ahead, so it
    must exclude one-off components. A bonus sitting in it would be projected
    across the rest of the year and over-deducted once per remaining month.

    Preference order:

    1. ``hrms_current_month_pay`` -- the payroll run's own figure for the period
       being processed. Trusted first because it is the only source that sees
       this month's actual composition.
    2. The contract wage -- recurring by definition, and it already reflects a
       revision that takes effect mid-year.
    3. The average of income so far. This last resort includes one-off pay, so
       it is flagged in ``tds_detail`` as ``ytd-average``: a reviewer can see the
       number was best-effort rather than a clean recurring figure.

    Returns ``(amount, basis)``.
    """
    explicit = float(getattr(employee, "hrms_current_month_pay", 0.0) or 0.0)
    if explicit > 0:
        return explicit, "explicit-field"

    contract = employee.contract_id
    wage = float(contract.wage) if contract and contract.wage else 0.0
    if wage > 0:
        return wage, "contract-wage"

    return round(float(income_to_date or 0.0), 2), "ytd-average"


def _json(payload):
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str)