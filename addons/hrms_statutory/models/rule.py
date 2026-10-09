# -*- coding: utf-8 -*-
"""Effective-dated statutory configuration.

Every statutory rate, cap, slab, ceiling and deadline in this platform lives in
``hrms.statutory.rule`` as a versioned, source-referenced, sign-off-gated row.
No rate appears as a literal anywhere in code. See ADR-0003.

Lookup chain: country -> state -> establishment -> contract type -> effective date.
Applicable law resolves per establishment, never globally. See ADR-0005.
"""

import json
import logging
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StatutoryRule(models.Model):
    """One effective-dated statutory parameter.

    A rule row is *not* the live value. ``hrms.statutory.rule.version`` rows are.
    A new version supersedes the previous one from its ``effective_from`` onward;
    superseded versions stay queryable forever so that a payslip issued in 2026
    can still be reproduced in 2028 after a State notifies a new rule.
    """

    _name = "hrms.statutory.rule"
    _description = "Statutory rule (effective-dated, sign-off gated)"
    _order = "code, id"

    code = fields.Char(
        required=True,
        index=True,
        help="Stable dotted key, e.g. IN.PF.WAGE_CEILING. Assigned by us, "
        "documented in docs/compliance/statutory-config-register.md.",
    )
    name = fields.Char(required=True)
    country_code = fields.Char(required=True, default="IN", index=True)
    state_code = fields.Char(
        index=True,
        help="ISO 3166-2 subdivision. Empty means the value is national.",
    )
    component_type = fields.Selection(
        [
            ("threshold", "Threshold / wage ceiling"),
            ("rate", "Rate / percentage"),
            ("cap", "Cap / maximum"),
            ("deadline", "Statutory deadline"),
            ("exemption", "Exemption"),
            ("eligibility", "Eligibility condition"),
            ("formula", "Formula parameter"),
            ("classification", "Tax classification rule"),
            ("json_value", "JSON value (slabs, matrices, rule sets)"),
        ],
        required=True,
    )
    # Where this value applies. Blank fields widen the match.
    applies_to_establishment = fields.Boolean(
        default=False,
        help="Value is establishment-specific; requires state_code and a matching "
        "employee establishment.",
    )
    contract_type = fields.Selection(
        [
            ("permanent", "Permanent"),
            ("fixed_term", "Fixed-term"),
            ("contractor", "Contractor"),
            ("intern", "Intern"),
            ("trainee", "Trainee"),
            ("consultant", "Consultant"),
        ],
        help="Blank applies to every contract type.",
    )
    source_reference = fields.Text(
        required=True,
        help="Gazette notification, circular or statute section. Not optional.",
    )
    source_url = fields.Char()
    notes = fields.Text()
    active = fields.Boolean(default=True)
    versions = fields.One2many("hrms.statutory.rule.version", "rule_id")

    # PostgreSQL UNIQUE constraints cannot contain expressions, so the scope key
    # is materialised as a stored column instead of COALESCE(...) inline.
    scope_key = fields.Char(
        compute="_compute_scope_key",
        store=True,
        readonly=True,
        index=True,
        help="code|country|state|contract. Unique per scope: add a new version "
        "rather than editing an existing rule.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not (vals.get("source_reference") or "").strip():
                raise UserError(
                    "source_reference is required. A statutory rule must record "
                    "the Gazette notification, circular or statute section it "
                    "comes from; values are never baked into code."
                )
        return super().create(vals_list)

    @api.depends("code", "country_code", "state_code", "contract_type")
    def _compute_scope_key(self):
        for rec in self:
            rec.scope_key = "|".join(
                [
                    (rec.code or "").strip(),
                    (rec.country_code or "").strip(),
                    (rec.state_code or "").strip(),
                    (rec.contract_type or "").strip(),
                ]
            )

    _sql_constraints = [
        (
            "scope_key_unique",
            "UNIQUE(scope_key)",
            "One rule per scope; add a new version instead of editing.",
        )
    ]

    def action_open_versions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Versions",
            "res_model": "hrms.statutory.rule.version",
            "view_mode": "list,form",
            "domain": [("rule_id", "=", self.id)],
        }


class StatutoryRuleVersion(models.Model):
    """An immutable, signed-off value for a rule over a date range.

    Immutable by policy: ``write`` on the value columns raises. Superseding is
    done by creating a new version with a later ``effective_from``.
    """

    _name = "hrms.statutory.rule.version"
    _description = "Statutory rule version (immutable, sign-off gated)"
    _order = "effective_from desc, id desc"

    rule_id = fields.Many2one(
        "hrms.statutory.rule", required=True, ondelete="restrict", index=True
    )
    version = fields.Integer(required=True, default=1)
    effective_from = fields.Date(required=True, index=True)
    effective_to = fields.Date(
        help="Blank = open-ended. Set when superseded, never on the active row.",
    )

    # The value is deliberately heterogeneous: numbers, strings and JSON are all
    # legitimate statutory content (slabs are lists, eligibility is prose, rates
    # are decimals).
    numeric_value = fields.Float(
        digits=(16, 4),
        help="Numeric value for threshold/rate/cap. Leave empty for others.",
    )
    text_value = fields.Char(help="Text value for formula/eligibility.")
    json_value = fields.Text(help="JSON value for slabs, matrices, rule sets.")

    unit = fields.Selection(
        [
            ("currency", "Currency amount"),
            ("percent", "Percent"),
            ("days", "Days"),
            ("hours", "Hours"),
            ("count", "Count"),
            ("months", "Months"),
            ("working_days", "Working days"),
            ("text", "Text"),
            ("json", "JSON"),
        ],
        default="currency",
    )

    # Sign-off gate. Enforced by _check_signoff before any write.
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("validated", "Validated"),
            ("active", "Active"),
            ("superseded", "Superseded"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    validated_by = fields.Many2one(
        "res.users",
        string="Validated by",
        ondelete="restrict",
        help="Must be a named professional user, never the developer who "
        "authored the row. See ADR-0003 sign-off protocol.",
    )
    validated_at = fields.Datetime(readonly=True)
    validation_note = fields.Text(
        help="Why this value is correct, and against which authority.",
    )
    source_reference = fields.Text(
        help="Snapshot of the rule's source at validation time. Copied from the "
        "rule so the version stays self-contained.",
    )

    @api.constrains("numeric_value", "text_value", "json_value", "rule_id")
    def _check_value_shape(self):
        for rec in self:
            ct = rec.rule_id.component_type
            if ct in ("threshold", "rate", "cap") and rec.numeric_value is False:
                # A zero rate is legitimate (e.g. PT not levied in some states),
                # so test for "unset" rather than falsiness.
                raise UserError(
                    f"Statutory rule {rec.rule_id.code} has component_type "
                    f"'{ct}' but no numeric_value. If the intended value is "
                    f"genuinely zero, set it explicitly rather than leaving it blank."
                )
            if ct == "formula" and not (rec.text_value or "").strip():
                raise UserError(f"Statutory rule {rec.rule_id.code} is a formula but text_value is empty.")
            if ct == "json_value" and not (rec.json_value or "").strip():
                raise UserError(f"Statutory rule {rec.rule_id.code} requires json_value.")
            if rec.json_value:
                try:
                    json.loads(rec.json_value)
                except ValueError as exc:
                    raise UserError(f"json_value is not valid JSON: {exc}")

    @api.constrains("effective_from", "effective_to")
    def _check_dates(self):
        for rec in self:
            if rec.effective_to and rec.effective_to < rec.effective_from:
                raise UserError(
                    f"effective_to ({rec.effective_to}) precedes effective_from "
                    f"({rec.effective_from})."
                )

    def _check_signoff(self, vals):
        """Raise unless the move satisfies the sign-off gate.

        Called from ``write`` and ``create``. This is the enforcement point for
        "no statutory value goes live without a qualified professional's
        sign-off" — the working rules make that non-negotiable.
        """
        if not vals:
            return
        target = vals.get("state")
        if target not in ("validated", "active", "superseded"):
            return
        for rec in self:
            new_state = target if rec in self else vals.get("state")
            if new_state not in ("validated", "active", "superseded"):
                continue
            if new_state == "superseded":
                # Superseding is the automatic close-out that write() applies to
                # the prior version once a new one is validated. It carries the
                # validator from the version's own sign-off; it is not itself a
                # fresh sign-off.
                continue
            validator = vals.get("validated_by")
            if not validator:
                raise UserError(
                    f"Cannot set state '{new_state}' on {rec.rule_id.code}: "
                    "validated_by is required. A statutory value must be signed "
                    "off by a named payroll/tax professional."
                )
            validator_id = (
                validator.id if hasattr(validator, "id") else validator
            )
            if rec.id and validator_id and validator_id == rec.create_uid.id:
                raise UserError(
                    f"Cannot sign off {rec.rule_id.code}: the author of the row "
                    "cannot also be the validator. Segregation of duties applies "
                    "to statutory configuration too."
                )

    def _check_value_shape_at_create(self, vals):
        """Reject an unset numeric component at create time.

        ``fields.Float`` coerces a missing value to 0.0 on the record, so the
        record-level ``_check_value_shape`` can no longer tell "unset" from a
        genuine zero. The raw inboxed values still can.
        """
        rule = self.env["hrms.statutory.rule"].browse(vals.get("rule_id"))
        if not rule:
            return
        if (
            rule.component_type in ("threshold", "rate", "cap")
            and "numeric_value" not in vals
        ):
            raise UserError(
                f"Statutory rule {rule.code} has component_type "
                f"'{rule.component_type}' but no numeric_value. If the intended "
                f"value is genuinely zero, set it explicitly rather than leaving "
                f"it blank."
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_signoff(vals)
            self._check_value_shape_at_create(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._check_signoff(vals)
        immutable = {"numeric_value", "text_value", "json_value", "effective_from"}
        locked = immutable & set(vals)
        if locked:
            for rec in self:
                if rec.state in ("validated", "active", "superseded"):
                    raise UserError(
                        f"{rec.rule_id.code}: {', '.join(sorted(locked))} is immutable "
                        f"once the version is '{rec.state}'. Create a new version "
                        f"with a later effective_from instead. History must remain "
                        f"reproducible."
                    )
        if vals.get("state") == "validated":
            vals.setdefault("validated_at", fields.Datetime.now())
        result = super().write(vals)
        if "state" in vals:
            # Mark the prior version superseded, closing its date range.
            for rec in self.filtered(lambda r: r.state == "validated"):
                prior = self.search(
                    [
                        ("rule_id", "=", rec.rule_id.id),
                        ("id", "!=", rec.id),
                        ("state", "in", ("active", "validated")),
                        ("effective_to", "=", False),
                    ],
                    order="effective_from desc",
                    limit=1,
                )
                if prior:
                    prior.write({"state": "superseded", "effective_to": rec.effective_from - relativedelta(days=1)})
        return result

    def unlink(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(
                    f"Cannot delete statutory version for {rec.rule_id.code}: it is "
                    f"'{rec.state}'. Statutory history is permanent. Supersede it."
                )
        return super().unlink()

    # -- value access ----------------------------------------------------
    def value(self):
        self.ensure_one()
        if self.state not in ("validated", "active", "superseded"):
            raise UserError(
                f"Statutory rule {self.rule_id.code} is '{self.state}', not "
                "validated. It cannot be used for a calculation. Sign it off, or "
                "choose a different scope."
            )
        ct = self.rule_id.component_type
        if ct in ("threshold", "rate", "cap"):
            return self.numeric_value
        if ct == "formula":
            return self.text_value
        if ct in ("json_value", "classification", "eligibility"):
            if not self.json_value:
                return self.text_value
            return json.loads(self.json_value)
        if ct == "deadline":
            # A deadline can be configured as a day count (numeric) or as an
            # expression (text); prefer the numeric form when one is set.
            return self.numeric_value if self.numeric_value else self.text_value
        return self.text_value


class LegalBasis(models.Model):
    """Which law governs which establishment, from when.

    Required because only ~10 of 36 Indian States/UTs had notified their own
    Labour Code rules as of 2026-10-05; where a State has not notified,
    pre-Codes rules continue insofar as they are not inconsistent with the
    Codes. That decision must be recorded, not defaulted in code. See ADR-0005.
    """

    _name = "hrms.legal.basis"
    _description = "Applicable legal basis for an establishment"
    _order = "effective_from desc"

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        "res.company", required=True, ondelete="restrict", index=True
    )
    state_code = fields.Char(
        required=True,
        help="ISO 3166-2 subdivision code, e.g. MH, KA, TN, DL.",
    )
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
    )
    regime = fields.Selection(
        [
            ("codes", "Labour Codes (notified State rules)"),
            ("transitional", "Transitional: pre-Codes rules continue where not inconsistent"),
            ("legacy", "Pre-Codes rules"),
        ],
        required=True,
        default="transitional",
        help="As at 2026-10-05 most States are transitional: the Codes are in "
        "force nationally but State rules are not yet notified.",
    )
    effective_from = fields.Date(required=True, default=fields.Date.today)
    effective_to = fields.Date()
    authority = fields.Char(
        help="Notifying authority, e.g. 'Government of Maharashtra'."
    )
    notification_ref = fields.Char(
        help="Gazette reference for the notification, or 'not yet notified'."
    )
    source_reference = fields.Text(required=True)
    reviewed_by = fields.Many2one("res.users", ondelete="restrict")
    reviewed_at = fields.Datetime()
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed")],
        default="draft",
        required=True,
    )
    notes = fields.Text()

    scope_key = fields.Char(
        compute="_compute_scope_key",
        store=True,
        readonly=True,
        index=True,
        help="company|state|contract|from. Unique per scope.",
    )

    @api.depends("company_id", "state_code", "contract_type", "effective_from")
    def _compute_scope_key(self):
        for rec in self:
            rec.scope_key = "|".join(
                [
                    str(rec.company_id.id or 0),
                    (rec.state_code or "").strip(),
                    (rec.contract_type or "").strip(),
                    str(rec.effective_from or ""),
                ]
            )

    _sql_constraints = [
        (
            "legal_basis_scope_unique",
            "UNIQUE(scope_key)",
            "One legal basis per scope and start date.",
        )
    ]

    def action_confirm(self):
        for rec in self:
            if not rec.reviewed_by:
                raise UserError(
                    f"{rec.name}: reviewed_by is required. Applicable law must be "
                    "reviewed by a named professional, not defaulted."
                )
            if not rec.notification_ref:
                raise UserError(
                    f"{rec.name}: notification_ref is required. Record the gazette "
                    "reference, or 'not yet notified' for a transitional basis."
                )
        self.write({"state": "confirmed"})
        return True

    @api.model
    def resolve(self, company, state_code, contract_type="permanent", on_date=None):
        """Return the legal basis in force. Raises if there is none.

        Deliberately raises rather than guessing. A wrong legal basis silently
        produces a wrong payslip; a loud failure produces a fixable task.
        """
        on_date = on_date or fields.Date.today()
        domain = [
            ("company_id", "=", company.id),
            ("state_code", "=", state_code),
            ("contract_type", "=", contract_type),
            ("effective_from", "<=", on_date),
            ("state", "=", "confirmed"),
        ]
        candidates = self.search(domain)
        candidates = candidates.filtered(
            lambda b: not b.effective_to or b.effective_to >= on_date
        )
        # An establishment may match several rows if scopes overlap; take the most
        # specific/latest and warn loudly, because overlap usually means a data
        # entry error.
        if not candidates:
            raise UserError(
                f"No confirmed legal basis for state {state_code}, contract type "
                f"{contract_type}, effective {on_date} at company "
                f"{company.display_name}. Record one in HR > Statutory > Legal "
                f"Basis before processing payroll. Applicable law resolves per "
                f"establishment; it is never inferred."
            )
        if len(candidates) > 1:
            _logger.warning(
                "hrms: %d overlapping legal bases for state=%s type=%s at %s; "
                "using the latest effective_from",
                len(candidates),
                state_code,
                contract_type,
                company.display_name,
            )
        return max(candidates, key=lambda b: b.effective_from)


class StatutoryContext(models.AbstractModel):
    """Read-only accessor for statutory values, resolved through the full chain.

    Every rules module goes through here. The returned snapshot is attached to
    immutable calculation records so a historical result stays reproducible.
    """

    _name = "hrms.statutory.context"
    _description = "Statutory context resolver"

    @api.model
    def _snapshot(self, company, state_code, contract_type, on_date):
        """All versions that a calculation used, for audit reproducibility."""
        versions = self.env["hrms.statutory.rule.version"].search(
            [
                ("effective_from", "<=", on_date),
                "|",
                ("effective_to", "=", False),
                ("effective_to", ">=", on_date),
                ("rule_id.country_code", "=", company.country_id.code or "IN"),
            ]
        )
        rows = []
        for ver in versions:
            rule = ver.rule_id
            if rule.state_code and rule.state_code != state_code:
                continue
            if rule.contract_type and rule.contract_type != contract_type:
                continue
            try:
                val = ver.value()
            except UserError:
                continue
            rows.append(
                {
                    "code": rule.code,
                    "version": ver.version,
                    "rule_id": rule.id,
                    "version_id": ver.id,
                    "effective_from": str(ver.effective_from),
                    "value": val,
                    "unit": ver.unit,
                    "source_reference": ver.source_reference,
                }
            )
        return rows

    @api.model
    def resolve(self, code, company, state_code=None, contract_type="permanent", on_date=None):
        """Resolve one statutory value, honouring scope specificity.

        Order of preference: exact state + contract type -> state -> contract type
        -> national. Raises if nothing matches.
        """
        on_date = on_date or fields.Date.today()
        rules = self.env["hrms.statutory.rule"].search(
            [("code", "=", code), ("country_code", "=", (company.country_id.code or "IN"))]
        )
        if not rules:
            raise UserError(
                f"No statutory rule configured for '{code}'. Add it in "
                f"HR > Statutory > Rules with a source reference before use. "
                f"Statutory values are never hardcoded."
            )
        applicable = rules.filtered(
            lambda r: r.active
            and (not r.contract_type or r.contract_type == contract_type)
            and (not r.state_code or r.state_code == state_code)
        )
        if not applicable:
            raise UserError(
                f"Statutory rule '{code}' has no version in scope for state="
                f"{state_code}, contract_type={contract_type}."
            )
        # Most specific wins: state-specific beats national.
        specific = applicable.filtered(lambda r: r.state_code and r.state_code == state_code)
        chosen = specific[:1] if specific else applicable[:1]
        rule = chosen[0]

        versions = self.env["hrms.statutory.rule.version"].search(
            [
                ("rule_id", "=", rule.id),
                ("effective_from", "<=", on_date),
                "|",
                ("effective_to", "=", False),
                ("effective_to", ">=", on_date),
            ],
            order="effective_from desc",
            limit=1,
        )
        if not versions:
            raise UserError(
                f"Statutory rule '{code}' ({rule.display_name}) has no version "
                f"effective on {on_date}. Either no version has been created, or "
                f"the previous one expired without a successor."
            )
        return versions[0]

    @api.model
    def get(self, code, company, state_code=None, contract_type="permanent", on_date=None):
        """Convenience: resolve and return just the value."""
        return self.resolve(
            code, company, state_code=state_code, contract_type=contract_type, on_date=on_date
        ).value()

    @api.model
    def get_json(self, code, company, state_code=None, contract_type="permanent", on_date=None):
        return self.resolve(
            code, company, state_code=state_code, contract_type=contract_type, on_date=on_date
        ).value() or {}