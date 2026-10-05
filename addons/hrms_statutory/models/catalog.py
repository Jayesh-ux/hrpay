# -*- coding: utf-8 -*-
"""Post-install seed.

Creates the *skeleton* of every statutory rule the platform needs: the rule
definition (code, scope, source requirement) but **no value**.

Values are intentionally absent. A version row must be created by a
Statutory Config Admin and signed off by a Validator with a source reference
before any payroll can be processed. This is the enforcement of the working rule
"never hardcode statutory rates, caps or slabs; require sign-off by a qualified
payroll/tax professional before go-live."

Running this twice is safe: rules are matched on their computed scope_key.

The codes below correspond one-to-one with rows in
docs/compliance/statutory-config-register.md.
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# (code, name, component_type, unit, source_hint)
RULE_CATALOG = [
    # ── Wage Code: the definition of wages ────────────────────────────────
    ("IN.COW.WAGES.PROVISO_SHARE_PCT", "Wages: anti-subterfuge proviso share of total remuneration (%)", "threshold", "percent", "Code on Wages 2019, definition of wages - 50% proviso"),
    ("IN.COW.WAGES.OVERTIME_SHARE_PCT", "Wages: overtime allowance add-back share of remuneration (%)", "threshold", "percent", "Code on Wages 2019 - MoLE FAQ on overtime allowance"),
    ("IN.COW.WAGES.IN_KIND_CAP_PCT", "Wages: remuneration in kind cap as share of total wages (%)", "threshold", "percent", "Code on Wages 2019 - explanation to remuneration in kind"),
    # ── Provident fund ───────────────────────────────────────────────────
    ("IN.PF.WAGE_CEILING", "PF: monthly wage ceiling", "threshold", "currency", "Code on Social Security 2020 (replaced EPF Act via S.O. 5936(E) 19 Dec 2025)"),
    ("IN.PF.EMPLOYEE_RATE", "PF: employee contribution rate (%)", "rate", "percent", "Code on Social Security 2020 - PF schedule"),
    ("IN.PF.EPS_RATE", "PF: employee share to EPS (%)", "rate", "percent", "Code on Social Security 2020 - PF schedule"),
    ("IN.PF.EPS_ANNUAL_CAP", "PF: EPS monthly contribution cap", "cap", "currency", "Code on Social Security 2020 - EPS cap"),
    ("IN.PF.VOLUNTARY", "PF: voluntary contribution configuration", "json_value", "json", "Code on Social Security 2020 - voluntary PF"),
    ("IN.PF.WAGE_BASIS_RULE", "PF: wage basis rule", "json_value", "json", "Code on Social Security 2020 - definition applicable to PF"),
    # ── ESI ──────────────────────────────────────────────────────────────
    ("IN.ESI.WAGE_THRESHOLD", "ESI: monthly wage applicability threshold", "threshold", "currency", "Code on Social Security 2020 - ESI; MoLE FAQ 16 Mar 2026"),
    ("IN.ESI.EMPLOYEE_RATE", "ESI: employee contribution rate (%)", "rate", "percent", "Code on Social Security 2020 - ESI schedule"),
    ("IN.ESI.EMPLOYER_RATE", "ESI: employer contribution rate (%)", "rate", "percent", "Code on Social Security 2020 - ESI schedule"),
    ("IN.ESI.WAGE_BASIS_RULE", "ESI: wage basis rule", "json_value", "json", "Code on Social Security 2020 - definition applicable to ESI"),
    # ── Professional tax ─────────────────────────────────────────────────
    ("IN.PT.SLABS", "Professional Tax: slab table by state", "json_value", "json", "State professional tax enactments; Constitution Art. 276 annual cap"),
    ("IN.PT.ANNUAL_CAP", "Professional Tax: annual cap per employee", "cap", "currency", "Constitution of India Art. 276(2)"),
    # ── Labour welfare fund ──────────────────────────────────────────────
    ("IN.LWF.RATES", "Labour Welfare Fund: rates by state", "json_value", "json", "State labour welfare fund acts"),
    # ── TDS ──────────────────────────────────────────────────────────────
    ("IN.TDS.SLABS.OLD", "TDS: salary slab table, old regime", "json_value", "json", "Income-tax Act 1961, Part B / Schedule - old regime"),
    ("IN.TDS.SLABS.NEW", "TDS: salary slab table, new regime", "json_value", "json", "Income-tax Act 1961 - new regime default section"),
    # ── Gratuity ─────────────────────────────────────────────────────────
    ("IN.GRATUITY.ELIGIBILITY", "Gratuity: eligibility parameters by contract type", "json_value", "json", "Code on Social Security 2020 s.53; Social Security (Central) Rules 2026 r.33"),
    ("IN.GRATUITY.DAYS_PER_YEAR", "Gratuity: days' wages per year of service", "formula", "days", "Code on Social Security 2020 - gratuity formula"),
    ("IN.GRATUITY.WAGES_DIVISOR", "Gratuity: monthly divisor for the daily wage", "formula", "days", "Code on Social Security 2020 - Central Government may specify the divisor"),
    ("IN.GRATUITY.CEILING", "Gratuity: statutory ceiling", "cap", "currency", "Code on Social Security 2020 - Central Government may specify"),
    ("IN.GRATUITY.PAYMENT_DEADLINE_DAYS", "Gratuity: payment deadline (days from eligibility)", "deadline", "days", "Code on Social Security 2020 - payment within 30 days"),
    # ── Bonus ────────────────────────────────────────────────────────────
    ("IN.BONUS.THRESHOLD", "Bonus: monthly wage applicability threshold", "threshold", "currency", "Code on Wages 2019 - statutory bonus threshold"),
    # ── Wage ceilings / minimum wages ────────────────────────────────────
    ("IN.COW.CH3_WAGE_CEILING", "Wage Code: Chapter III wage ceiling", "threshold", "currency", "Code on Wages 2019 - Chapter III ceiling notification"),
    ("IN.MINWAGE.DAILY_TO_HOURLY_DIVISOR", "Minimum wages: daily to hourly divisor", "formula", "days", "Wages (Central) Rules 2026"),
    ("IN.MINWAGE.HOURLY_TO_MONTHLY_FACTOR", "Minimum wages: hourly to monthly factor", "formula", "days", "Wages (Central) Rules 2026"),
    # ── Overtime ─────────────────────────────────────────────────────────
    ("IN.OT.WEEKLY_CAP_HOURS", "Overtime: weekly cap (hours)", "cap", "hours", "OSH Code 2020 - overtime limits"),
    ("IN.OT.MONTHLY_PERIOD_HOURS", "Overtime: monthly/period cap (hours)", "cap", "hours", "OSH Code 2020 - overtime limits"),
    ("IN.OT.CONSENT_REQUIRED", "Overtime: explicit employee consent required", "eligibility", "text", "Code on Wages 2019 / OSH Code 2020"),
    # ── Leave ────────────────────────────────────────────────────────────
    ("IN.LEAVE.CARRY_FORWARD_DAYS", "Leave: statutory carry-forward cap (days)", "cap", "days", "Code on Wages 2019; State Shops & Establishment Acts may differ"),
    ("IN.LEAVE.ENCRASHMENT_FREQUENCY", "Leave: encashment permitted", "eligibility", "text", "Code on Wages 2019 - annual encashment"),
    # ── F&F and exit ─────────────────────────────────────────────────────
    ("IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS", "F&F: wages payment deadline (working days from last working day, all exit types)", "deadline", "working_days", "Code on Wages 2019 - payment of wages within two working days"),
    ("IN.RESKILL.EMPLOYER_DEPOSIT_DAYS", "Worker re-skilling fund: employer deposit deadline (days after retrenchment)", "deadline", "days", "OSH Code 2020 - retrenchment contribution to worker re-skilling fund"),
    ("IN.RESKILL.DAYS_WAGES", "Worker re-skilling fund: days' last-drawn wages per retrenched worker", "formula", "days", "OSH Code 2020 - retrenchment contribution"),
    ("IN.RESKILL.DISBURSEMENT_DAYS", "Worker re-skilling fund: disbursement to worker (days)", "deadline", "days", "OSH Code 2020 - disbursement timeline"),
    ("IN.FNF.NOTICE_SHORTFILL_DAYS", "F&F: notice shortfall recovery basis (days)", "formula", "days", "Contractual; configure per company"),
    # ── Statutory response / claim clocks (drive helpdesk ticket deadlines) ──
    ("IN.GRIEVANCE.RESPONSE_DEADLINE_DAYS", "Grievance: days to acknowledge and respond", "deadline", "days", "Code on Industrial Relations 2020 - grievance redressal"),
    ("IN.POSH.INTERNAL_COMMITTEE_DEADLINE_DAYS", "POSH: days for the Internal Committee to complete its inquiry", "deadline", "days", "POSH Act 2013 read with the Code on Social Security 2020 - ICC timelines"),
    ("IN.PF.CLAIM.WINDOW_DAYS", "PF: days to lodge a claim with the establishment", "deadline", "days", "Code on Social Security 2020 - PF claim procedure"),
    ("IN.ESI.CLAIM.WINDOW_DAYS", "ESI: days to lodge a claim for benefit", "deadline", "days", "Code on Social Security 2020 - ESI claim procedure"),
    ("IN.LWF.CLAIM.WINDOW_DAYS", "LWF: days to claim a contribution refund or benefit", "deadline", "days", "State labour welfare fund acts"),
    ("IN.FNF.DISPUTE_RESPONSE_DEADLINE_DAYS", "F&F: days to respond to a settlement dispute", "deadline", "days", "Code on Wages 2019 - settlement dispute procedure"),
    ("IN.WAGES.DISPUTE_RESPONSE_DEADLINE_DAYS", "Wages: days to respond to a wages claim", "deadline", "days", "Code on Wages 2019 - wages claim / authority procedure"),
]


class StatutoryCatalog(models.AbstractModel):
    _name = "hrms.statutory.catalog"
    _description = "Statutory rule catalog seeder"

    @api.model
    def seed(self):
        """Create rule skeletons. Idempotent on scope_key.

        Deliberately creates no versions: no rate exists until a professional
        signs one off.
        """
        rule_model = self.env["hrms.statutory.rule"]
        created = 0
        for code, name, ctype, unit, hint in RULE_CATALOG:
            existing = rule_model.sudo().search([("code", "=", code)], limit=1)
            if existing:
                continue
            rule_model.sudo().create(
                {
                    "code": code,
                    "name": name,
                    "country_code": "IN",
                    "component_type": ctype,
                    "source_reference": (
                        "TO BE CONFIRMED BY A QUALIFIED PAYROLL/TAX PROFESSIONAL. "
                        f"Expected authority: {hint}"
                    ),
                    "notes": (
                        "Skeleton only. No value configured. A version row must be "
                        "created and signed off by a Statutory Validator before "
                        "any payroll can be processed. See "
                        "docs/compliance/statutory-config-register.md."
                    ),
                    "active": True,
                }
            )
            created += 1
        _logger.info(
            "hrms_statutory: catalog seeded. %d rules created, %d total. "
            "No values configured; sign-off required before go-live.",
            created,
            rule_model.sudo().search_count([]),
        )
        return created

    @api.model
    def catalog_codes(self):
        """Every code the catalog expects, so callers need not import this file."""
        return [code for code, *_ in RULE_CATALOG]

    @api.model
    def coverage_report(self):
        """Which codes have a signed-off, currently-effective version?"""
        ctx = self.env["hrms.statutory.context"]
        company = self.env.company
        report = {"total": len(RULE_CATALOG), "ready": [], "missing": [], "unvalidated": []}
        today = fields.Date.today()
        for code, name, *_ in RULE_CATALOG:
            try:
                version = ctx.resolve(code, company, on_date=today)
                report["ready"].append({"code": code, "version": version.version})
            except Exception:
                versions = self.env["hrms.statutory.rule.version"].search(
                    [("rule_id.code", "=", code)]
                )
                if versions:
                    report["unvalidated"].append({"code": code, "states": versions.mapped("state")})
                else:
                    report["missing"].append({"code": code, "name": name})
        report["go_live_ready"] = not report["missing"] and not report["unvalidated"]
        return report
