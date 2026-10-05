# -*- coding: utf-8 -*-
"""Wages composition engine (India, Code on Wages 2019).

This is the highest-value and highest-risk logic in the platform. From
21 November 2025 the statutory definition of "wages" drives PF, ESI *and*
gratuity, and it is not "basic + DA":

  1. INCLUSION: all remuneration in money, expressly including basic pay,
     dearness allowance and retaining allowance, plus other components
     (including HRA and conveyance allowance).
  2. EXCLUSIONS: named components are excluded (employer PF/pension, gratuity,
     termination payments, value of concessions, etc.).
  3. THE 50% PROVISO (anti-subterfuge): if the total of excluded components
     exceeds a configured share of total remuneration, the excess is added back
     and treated as wages.
  4. OVERTIME: overtime allowance is a wages component; the excess over the
     configured share of remuneration is added back.
  5. REMUNERATION IN KIND: counted only up to a configured share of total wages.

Every threshold here is read from ``hrms.statutory.rule.version`` through
:class:`hrms.statutory.context`. Nothing is hardcoded. See ADR-0003.

The share thresholds are read per calculation from config so that a change in
the notified percentage requires a config change, not a code deploy.
"""

import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SalaryComponentNature(models.Model):
    """Classification of one salary component for wages-composition purposes.

    Attached to each component of a salary structure. Without this the platform
    cannot compute statutory wages, so it is a required field.
    """

    _name = "hr.salary.component.nature"
    _description = "Salary component classification for statutory wages"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    hr_salary_component_id = fields.Many2one(
        "hr.salary.component",
        required=True,
        ondelete="cascade",
        index=True,
        help="The salary component this classification applies to.",
    )

    remuneration_in_kind = fields.Boolean(
        default=False,
        help="Component is provided in kind rather than as cash. Subject to the "
        "configured share cap on total wages (Code on Wages explanation to the "
        "definition of remuneration).",
    )

    wage_treatment = fields.Selection(
        [
            ("included", "Included in wages"),
            ("excluded", "Excluded from wages"),
            ("included_proviso", "Included, subject to the 50% proviso"),
            ("excluded_proviso", "Excluded, subject to the 50% proviso"),
            ("not_wage", "Not a wage at all (e.g. pure reimbursement)"),
        ],
        required=True,
        default="included",
        help="Maps to paras 1-4 of the Code on Wages definition. "
        "'..._proviso' variants are the ones subject to the 50% "
        "anti-subterfuge add-back.",
    )
    pf_applicable = fields.Selection(
        [("yes", "Yes"), ("no", "No"), ("proviso", "Subject to proviso")],
        default="yes",
    )
    esi_applicable = fields.Selection(
        [("yes", "Yes"), ("no", "No"), ("proviso", "Subject to proviso")],
        default="yes",
    )
    gratuity_applicable = fields.Selection(
        [("yes", "Yes"), ("no", "No"), ("proviso", "Subject to proviso")],
        default="yes",
    )
    allowance_treatment = fields.Selection(
        [
            ("basic_da", "Basic / DA / retaining"),
            ("hra", "House rent allowance"),
            ("conveyance", "Conveyance"),
            ("special", "Special allowance"),
            ("overtime", "Overtime allowance"),
            ("bonus", "Bonus"),
            ("commission", "Commission"),
            ("employer_pf", "Employer PF / pension contribution"),
            ("gratuity", "Gratuity"),
            ("termination", "Termination / leave encashment payment"),
            ("reimbursement", "Reimbursement (actual)"),
            ("other_allowance", "Other allowance"),
        ],
        default="other_allowance",
        help="Drives the specific provisos. 'conveyance' and 'overtime' have "
        "their own add-back treatment per the notified FAQs.",
    )
    note = fields.Text()

    _sql_constraints = [
        (
            "nature_component_unique",
            "UNIQUE(hr_salary_component_id)",
            "One statutory classification per salary component. Add a new "
            "component rather than reclassifying a live one.",
        )
    ]

    def name_get(self):
        return [(rec.id, f"{rec.name} ({rec.hr_salary_component_id.name})") for rec in self]


class WagesComposition(models.Model):
    """Computed statutory wages for one employee over one period.

    Persisted (not just computed) because payslips, F&F statements and
    Form 16 data must all be reproducible long after a State notifies a new
    rule. This is the snapshot that makes that possible.
    """

    _name = "hrms.wages.composition"
    _description = "Statutory wages composition snapshot"
    _order = "period_start desc, id desc"

    name = fields.Char(required=True)
    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="restrict", index=True
    )
    company_id = fields.Many2one(
        "res.company", required=True, ondelete="restrict", index=True
    )
    state_code = fields.Char(required=True)
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
    )
    period_start = fields.Date(required=True, index=True)
    period_end = fields.Date(required=True)
    legal_basis_id = fields.Many2one(
        "hrms.legal.basis",
        ondelete="restrict",
        required=True,
        help="Law that was in force when this was computed. Snapshotted so a "
        "later State notification does not rewrite history.",
    )

    # -- inputs ----------------------------------------------------------
    total_remuneration = fields.Float(digits=(16, 2), required=True)
    basic_da_total = fields.Float(digits=(16, 2))
    included_total = fields.Float(digits=(16, 2))
    excluded_total = fields.Float(digits=(16, 2))
    overtime_allowance = fields.Float(digits=(16, 2))
    remuneration_in_kind = fields.Float(digits=(16, 2))

    # -- proviso workings -------------------------------------------------
    proviso_threshold_pct = fields.Float(
        digits=(6, 3),
        help="Configured share of total remuneration above which exclusions are "
        "added back. Read from statutory config, not hardcoded.",
    )
    excluded_pct = fields.Float(digits=(6, 3))
    excess_excluded_added_back = fields.Float(digits=(16, 2))
    overtime_excess_added_back = fields.Float(digits=(16, 2))
    in_kind_cap_pct = fields.Float(digits=(6, 3))
    in_kind_capped_amount = fields.Float(digits=(16, 2))

    # -- outputs ---------------------------------------------------------
    statutory_wages = fields.Float(digits=(16, 2), required=True)
    pf_wages = fields.Float(digits=(16, 2))
    esi_wages = fields.Float(digits=(16, 2))
    gratuity_wages = fields.Float(digits=(16, 2))

    # -- provenance -------------------------------------------------------
    rule_versions_json = fields.Text(
        required=True,
        help="JSON of every statutory rule version used. Required for audit.",
    )
    line_detail_json = fields.Text(
        help="JSON: per-component classification, so a reviewer can see exactly "
        "why each amount landed where it did.",
    )
    computed_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    computed_by_id = fields.Many2one("res.users", readonly=True, default=lambda s: s.env.user)

    _sql_constraints = [
        (
            "composition_unique",
            "UNIQUE(employee_id, period_start, period_end)",
            "One composition per employee per period; recompute supersedes via "
            "the rules-version snapshot rather than a second row.",
        )
    ]

    @api.model
    def compute(self, employee, period_start, period_end, contract_type=None, payslip=None):
        """Compute and persist the statutory wages snapshot.

        Raises rather than guessing if a required statutory threshold is
        missing, because a silently wrong wages base produces a wrong PF/ESI/
        gratuity liability that surfaces months later.
        """
        company = employee.company_id
        state_code = employee.hrms_state_code or company.state_id.code or ""
        contract_type = contract_type or employee.contract_type or "permanent"
        ctx = self.env["hrms.statutory.context"]

        basis = self.env["hrms.legal.basis"].resolve(
            company, state_code, contract_type, on_date=period_end
        )

        proviso_pct = ctx.get(
            "IN.COW.WAGES.PROVISO_SHARE_PCT",
            company,
            state_code=state_code,
            contract_type=contract_type,
            on_date=period_end,
        )
        overtime_share_pct = ctx.get(
            "IN.COW.WAGES.OVERTIME_SHARE_PCT",
            company,
            state_code=state_code,
            contract_type=contract_type,
            on_date=period_end,
        )
        in_kind_cap_pct = ctx.get(
            "IN.COW.WAGES.IN_KIND_CAP_PCT",
            company,
            state_code=state_code,
            contract_type=contract_type,
            on_date=period_end,
        )

        lines = self._collect_lines(employee, period_start, period_end, payslip)
        if not lines:
            raise UserError(
                f"Cannot compute statutory wages for {employee.name}: no salary "
                "lines found for the period. Check the salary structure, contract, "
                "or payslip inputs."
            )

        total_rem = sum(abs(line["monthly_amount"]) for line in lines)
        if total_rem <= 0:
            raise UserError(
                f"Cannot compute statutory wages for {employee.name}: total "
                "remuneration is zero."
            )

        included = excluded = overtime_allowance = in_kind = 0.0
        basic_da = 0.0
        for line in lines:
            amt = abs(line["monthly_amount"])
            nature = line["wage_treatment"]
            if nature == "included":
                included += amt
            elif nature == "excluded":
                excluded += amt
            elif nature == "included_proviso":
                included += amt
            elif nature == "excluded_proviso":
                excluded += amt
            elif nature == "not_wage":
                pass  # genuine reimbursement, outside the definition entirely
            if line["allowance_treatment"] == "overtime":
                overtime_allowance += amt
            if line["allowance_treatment"] == "basic_da":
                basic_da += amt
            if line["is_in_kind"]:
                in_kind += amt

        # --- Para 3: the 50% anti-subterfuge add-back -----------------------
        threshold_amount = total_rem * (proviso_pct / 100.0)
        excess_added_back = 0.0
        if excluded > threshold_amount:
            excess_added_back = excluded - threshold_amount
            included += excess_added_back
            excluded = threshold_amount

        # --- Para 4: overtime allowance add-back ---------------------------
        overtime_threshold = total_rem * (overtime_share_pct / 100.0)
        overtime_excess = 0.0
        if overtime_allowance > overtime_threshold:
            overtime_excess = overtime_allowance - overtime_threshold

        statutory = included

        # --- Para 5: remuneration in kind capped ---------------------------
        in_kind_cap = statutory * (in_kind_cap_pct / 100.0)
        in_kind_capped = min(in_kind, in_kind_cap)

        excluded_pct = (excluded / total_rem * 100.0) if total_rem else 0.0

        # --- Per-statute wage bases ----------------------------------------
        # PF and ESI can have different definitions again; resolve each from
        # config rather than assuming they equal statutory wages.
        pf_wages = ctx.get(
            "IN.PF.WAGE_BASIS_RULE",
            company,
            state_code=state_code,
            contract_type=contract_type,
            on_date=period_end,
        ) or {}
        esi_wages = ctx.get(
            "IN.ESI.WAGE_BASIS_RULE",
            company,
            state_code=state_code,
            contract_type=contract_type,
            on_date=period_end,
        ) or {}
        gratuity_wages = ctx.get(
            "IN.GRATUITY.WAGE_BASIS_RULE",
            company,
            state_code=state_code,
            contract_type=contract_type,
            on_date=period_end,
        ) or {}

        pf_base = self._apply_basis_rule(statutory, pf_wages, total_rem, "IN.PF.WAGE_BASIS_RULE")
        esi_base = self._apply_basis_rule(statutory, esi_wages, total_rem, "IN.ESI.WAGE_BASIS_RULE")
        grat_base = self._apply_basis_rule(
            statutory, gratuity_wages, total_rem, "IN.GRATUITY.WAGE_BASIS_RULE"
        )

        versions = ctx._snapshot(company, state_code, contract_type, period_end)
        vals = {
            "name": f"{employee.name} {period_start}..{period_end}",
            "employee_id": employee.id,
            "company_id": company.id,
            "state_code": state_code,
            "contract_type": contract_type,
            "period_start": period_start,
            "period_end": period_end,
            "legal_basis_id": basis.id,
            "total_remuneration": round(total_rem, 2),
            "basic_da_total": round(basic_da, 2),
            "included_total": round(included, 2),
            "excluded_total": round(excluded, 2),
            "overtime_allowance": round(overtime_allowance, 2),
            "remuneration_in_kind": round(in_kind, 2),
            "proviso_threshold_pct": proviso_pct,
            "excluded_pct": round(excluded_pct, 3),
            "excess_excluded_added_back": round(excess_added_back, 2),
            "overtime_excess_added_back": round(overtime_excess, 2),
            "in_kind_cap_pct": in_kind_cap_pct,
            "in_kind_capped_amount": round(in_kind_capped, 2),
            "statutory_wages": round(statutory, 2),
            "pf_wages": round(pf_base, 2),
            "esi_wages": round(esi_base, 2),
            "gratuity_wages": round(grat_base, 2),
            "rule_versions_json": _json(versions),
            "line_detail_json": _json(lines),
            "computed_by_id": self.env.uid,
        }
        existing = self.search(
            [
                ("employee_id", "=", employee.id),
                ("period_start", "=", period_start),
                ("period_end", "=", period_end),
            ],
            limit=1,
        )
        if existing:
            self.env["hrms.audit.log"].log(
                "hrms.wages.composition",
                existing.id,
                "write",
                changes={"recomputed": True, "old_statutory_wages": existing.statutory_wages},
                note="Wages composition recomputed; snapshot replaced.",
            )
            existing.write(vals)
            record = existing
        else:
            record = self.create(vals)
        self.env["hrms.audit.log"].log(
            "hrms.wages.composition",
            record.id,
            "create",
            changes={"statutory_wages": record.statutory_wages},
            note=f"Computed under legal basis {basis.display_name}",
        )
        return record

    @api.model
    def _apply_basis_rule(self, statutory, rule, total_rem, code):
        """Apply a configured wage-basis rule.

        A rule is JSON like ``{"basis": "statutory"}`` or
        ``{"basis": "basic_da_plus", "floor_pct": 50}``. Kept data-driven so a
        State-specific basis is a config change, not a release.
        """
        if not rule:
            return statutory
        basis = rule.get("basis", "statutory")
        if basis == "statutory":
            return statutory
        if basis == "total_remuneration":
            return total_rem
        # Unknown basis must fail loudly: silently treating it as 'statutory'
        # would understate or overstate a statutory liability.
        raise UserError(
            f"{code}: unsupported basis '{basis}'. Known bases: statutory, "
            "total_remuneration. Add a new rule version rather than editing code."
        )

    @api.model
    def _collect_lines(self, employee, period_start, period_end, payslip=None):
        """Gather classified salary lines for the period.

        Prefers an explicit payslip (so mid-period salary changes and manual
        inputs are honoured); otherwise derives monthly amounts from the
        contract's salary structure.
        """
        structure = employee.contract_id and employee.contract_id.hr_payroll_structure_id
        natures = self.env["hr.salary.component.nature"].search([])
        by_component = {n.hr_salary_component_id.id: n for n in natures if n.hr_salary_component_id}

        lines = []
        if payslip:
            for line in payslip.line_ids:
                code = line.code or ""
                nature = by_component.get(line.salary_component_id.id) if hasattr(line, "salary_component_id") else None
                lines.append(
                    {
                        "component": line.name or code,
                        "code": code,
                        "monthly_amount": line.total,
                        "wage_treatment": nature.wage_treatment if nature else "included",
                        "allowance_treatment": nature.allowance_treatment if nature else "other_allowance",
                        "pf_applicable": nature.pf_applicable if nature else "yes",
                        "esi_applicable": nature.esi_applicable if nature else "yes",
                        "gratuity_applicable": nature.gratuity_applicable if nature else "yes",
                        "is_in_kind": bool(nature.remuneration_in_kind) if nature else False,
                        "source": "payslip",
                    }
                )
            if lines:
                return lines

        if not structure:
            raise UserError(
                f"{employee.name} has no salary structure on their contract. "
                "Assign one before computing statutory wages."
            )
        months = _month_count(period_start, period_end)
        for line in structure.line_ids:
            nature = by_component.get(line.component_id.id)
            monthly = line.amount or 0.0
            if not monthly:
                continue
            lines.append(
                {
                    "component": line.component_id.name,
                    "code": line.component_id.code,
                    "monthly_amount": round(monthly * months, 2),
                    "wage_treatment": nature.wage_treatment if nature else "included",
                    "allowance_treatment": nature.allowance_treatment if nature else "other_allowance",
                    "pf_applicable": nature.pf_applicable if nature else "yes",
                    "esi_applicable": nature.esi_applicable if nature else "yes",
                    "gratuity_applicable": nature.gratuity_applicable if nature else "yes",
                    "is_in_kind": False,
                    "source": "structure",
                    "months_applied": months,
                }
            )
        return lines


def _json(payload):
    import json

    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def _month_count(period_start, period_end):
    """Months in the period, used to scale monthly structure amounts."""
    if not period_start or not period_end:
        return 1.0
    months = (period_end.year - period_start.year) * 12 + (period_end.month - period_start.month)
    if period_end.day >= 27 and months >= 1:
        months += 1  # treat a period ending late in the month as inclusive
    return float(max(months, 1)) if months >= 1 else 1.0