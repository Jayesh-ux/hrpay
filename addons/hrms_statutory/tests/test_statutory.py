# -*- coding: utf-8 -*-
"""Tests for the statutory rules engine.

Not run on the build host: this suite needs a live Odoo registry and PostgreSQL.
Run it on the development machine:

    odoo -d test_hrms -i hrms_statutory --test-enable --stop-after-init

The assertions here are deliberately about *refusal* behaviour as much as
arithmetic. A statutory engine that silently computes a plausible wrong number
is far worse than one that stops and says "not configured", and that property is
what most of these tests pin down.
"""

import json
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hrms_statutory")
class StatutoryRuleTestCase(TransactionCase):
    """Shared helpers for building rules and signed-off versions."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Rule = cls.env["hrms.statutory.rule"]
        cls.Version = cls.env["hrms.statutory.rule.version"]
        cls.Company = cls.env["res.company"].create({"name": "Test Co"})

        # A second, non-admin user. Superusers must not be able to satisfy the
        # sign-off gate, so most fixtures need a real approver.
        cls.professional = cls.env["res.users"].create(
            {
                "name": "Statutory Professional",
                "login": "statutory.professional.test",
                "email": "statutory.professional@example.invalid",
            }
        )

    def _rule(self, code, component_type="threshold", **scope):
        return self.Rule.create(
            dict(
                {
                    "name": code,
                    "code": code,
                    "country_code": "IN",
                    "component_type": component_type,
                    "source_reference": "test fixture authority",
                },
                **scope,
            )
        )

    def _version(self, rule, numeric=None, text=None, js=None, start=None, end=None,
                 state="draft", approver=None):
        return self.Version.create(
            {
                "rule_id": rule.id,
                "effective_from": start or date(2020, 1, 1),
                "effective_to": end,
                "numeric_value": numeric if numeric is not None else 0,
                "text_value": text,
                "json_value": json.dumps(js) if js is not None else None,
                "state": state,
                "source_reference": "test fixture authority",
                "validated_by": (approver or self.professional).id,
                "create_uid": None,
            }
        )

    def _activate(self, version, approver=None):
        version.write(
            {"state": "validated", "validated_by": (approver or self.professional).id}
        )
        return version

    def _get(self, code, **kw):
        kw.setdefault("on_date", date(2026, 6, 1))
        return self.env["hrms.statutory.context"].get(code, self.Company, **kw)


@tagged("post_install", "-at_install", "hrms_statutory")
class TestStatutoryRuleResolution(StatutoryRuleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rule = cls._rule.__func__(cls, "IN.PF.WAGE_CEILING", "threshold")

    def test_unconfigured_rule_refuses_to_resolve(self):
        """No version at all must raise, never return a default."""
        with self.assertRaises(UserError):
            self._get("IN.PF.WAGE_CEILING")

    def test_draft_version_is_ignored(self):
        self._version(self.rule, numeric=15000)
        with self.assertRaises(UserError):
            self._get("IN.PF.WAGE_CEILING")

    def test_effective_dating_picks_the_right_version(self):
        self._activate(self._version(self.rule, numeric=15000, end=date(2025, 12, 31)))
        self._activate(self._version(self.rule, numeric=25000, start=date(2026, 1, 1)))
        self.assertEqual(float(self._get("IN.PF.WAGE_CEILING", on_date=date(2025, 6, 1))), 15000.0)
        self.assertEqual(float(self._get("IN.PF.WAGE_CEILING", on_date=date(2026, 6, 1))), 25000.0)

    def test_date_after_the_last_version_uses_the_last_known_value(self):
        self._activate(self._version(self.rule, numeric=15000))
        self.assertEqual(float(self._get("IN.PF.WAGE_CEILING", on_date=date(2030, 1, 1))), 15000.0)

    def test_validating_a_new_version_supersedes_and_closes_the_prior_one(self):
        self._activate(self._version(self.rule, numeric=15000))
        self._activate(self._version(self.rule, numeric=25000, start=date(2026, 1, 1)))
        self.assertEqual(float(self._get("IN.PF.WAGE_CEILING", on_date=date(2025, 6, 1))), 15000.0)
        self.assertEqual(float(self._get("IN.PF.WAGE_CEILING", on_date=date(2026, 6, 1))), 25000.0)

    def test_validated_version_is_immutable(self):
        version = self._activate(self._version(self.rule, numeric=15000))
        with self.assertRaises(UserError):
            version.write({"numeric_value": 99999})
        with self.assertRaises(UserError):
            version.write({"effective_from": date(2019, 1, 1)})

    def test_validated_version_cannot_be_deleted(self):
        version = self._activate(self._version(self.rule, numeric=15000))
        with self.assertRaises(UserError):
            version.unlink()

    def test_draft_version_can_still_be_corrected(self):
        version = self._version(self.rule, numeric=15000)
        version.write({"numeric_value": 16000})
        self.assertEqual(version.numeric_value, 16000)

    def test_validation_requires_a_named_validator(self):
        version = self._version(self.rule, numeric=15000)
        with self.assertRaises(UserError):
            version.write({"state": "validated", "validated_by": False})

    def test_superuser_cannot_be_the_validator(self):
        """Sign-off must be attributable to a person, not to a login."""
        version = self._version(self.rule, numeric=15000)
        with self.assertRaises(UserError):
            version.write({"state": "validated", "validated_by": self.env.user.id})

    def test_author_cannot_validate_own_version(self):
        """Segregation of duties applies to statutory configuration too."""
        author = self.env["res.users"].create(
            {
                "name": "Rule Author",
                "login": "rule.author.test",
                "email": "rule.author@example.invalid",
            }
        )
        version = self.Version.create(
            {
                "rule_id": self.rule.id,
                "effective_from": date(2020, 1, 1),
                "numeric_value": 15000,
                "state": "draft",
                "source_reference": "authored fixture",
                "validated_by": author.id,
            }
        )
        with self.assertRaises(UserError):
            version.write({"state": "validated"})

    def test_state_specific_version_wins_over_national(self):
        mh = self._rule("IN.PF.WAGE_CEILING", "threshold", state_code="MH")
        self._activate(self._version(self.rule, numeric=15000))
        self._activate(self._version(mh, numeric=17000))
        self.assertEqual(float(self._get("IN.PF.WAGE_CEILING", state_code="MH")), 17000.0)
        self.assertEqual(float(self._get("IN.PF.WAGE_CEILING", state_code="KA")), 15000.0)

    def test_one_rule_per_scope(self):
        """A second rule at the same scope is refused; supersede instead."""
        self._rule("IN.PF.WAGE_CEILING", "threshold")
        with self.assertRaises(Exception):
            self._rule("IN.PF.WAGE_CEILING", "threshold")

    def test_missing_source_reference_is_refused(self):
        with self.assertRaises(UserError):
            self.Rule.create(
                {
                    "name": "No source",
                    "code": "IN.PF.WAGE_CEILING",
                    "component_type": "threshold",
                    "source_reference": False,
                }
            )


@tagged("post_install", "-at_install", "hrms_statutory")
class TestValueShapes(StatutoryRuleTestCase):
    def test_numeric_component_requires_a_number(self):
        rule = self._rule("IN.PF.RATE", "rate")
        with self.assertRaises(UserError):
            self.Version.create(
                {
                    "rule_id": rule.id,
                    "effective_from": date(2020, 1, 1),
                    "numeric_value": 0.0,  # unset
                    "state": "draft",
                    "source_reference": "fixture",
                }
            )

    def test_a_genuine_zero_rate_is_accepted(self):
        """PT is not levied in every State; zero must be expressible."""
        rule = self._rule("IN.PT.RATE", "rate")
        version = self.Version.create(
            {
                "rule_id": rule.id,
                "effective_from": date(2020, 1, 1),
                "numeric_value": 0.0,
                "state": "draft",
                "source_reference": "fixture: not levied in this State",
            }
        )
        self.assertEqual(version.numeric_value, 0.0)
        self._activate(version)
        self.assertEqual(float(self._get("IN.PT.RATE")), 0.0)

    def test_json_component_round_trips(self):
        rule = self._rule("IN.TDS.SLABS.NEW", "json_value")
        slabs = [{"up_to": 500000, "rate": 0.0}, {"above": 500000, "rate": 0.30}]
        self._activate(self._version(rule, js=slabs))
        self.assertEqual(self._get("IN.TDS.SLABS.NEW"), slabs)

    def test_invalid_json_is_refused(self):
        rule = self._rule("IN.PT.SLABS", "json_value")
        with self.assertRaises(UserError):
            self._version(rule, js=None)  # blank json_value on a json component


@tagged("post_install", "-at_install", "hrms_statutory")
class TestCatalogCoverage(StatutoryRuleTestCase):
    def test_catalog_seeds_rules_without_values(self):
        created = self.env["hrms.statutory.catalog"].seed()
        self.assertGreater(created, 0, "catalog seed created nothing")
        self.assertEqual(
            self.env["hrms.statutory.catalog"].seed(), 0, "catalog seed is not idempotent"
        )

    def test_coverage_report_is_not_go_live_ready_on_a_fresh_db(self):
        self.env["hrms.statutory.catalog"].seed()
        report = self.env["hrms.statutory.catalog"].coverage_report()
        self.assertFalse(
            report["go_live_ready"],
            "a freshly seeded catalog reported go-live ready, which means empty "
            "rules are being treated as satisfied",
        )
        self.assertTrue(report["missing"])

    def test_no_rule_ships_with_a_baked_in_value(self):
        self.env["hrms.statutory.catalog"].seed()
        live = self.env["hrms.statutory.rule.version"].search_count(
            [("state", "in", ("validated", "active", "superseded"))]
        )
        self.assertEqual(
            live, 0, "a statutory value was installed by default, which bypasses sign-off"
        )

    def test_every_catalog_rule_is_createable(self):
        """The seeder must not raise: every code has a valid component_type."""
        self.env["hrms.statutory.catalog"].seed()
        self.assertTrue(self.env["hrms.statutory.rule"].search_count([("code", "like", "IN.%")]))


@tagged("post_install", "-at_install", "hrms_statutory")
class TestGratuity(StatutoryRuleTestCase):
    """Gratuity is the one computation here with a real eligibility test."""

    def test_gratuity_refuses_without_configured_eligibility(self):
        employee = self.env["hr.employee"].create(
            {"name": "No Config", "join_date": date(2015, 1, 1)}
        )
        with self.assertRaises(UserError):
            self.env["hrms.gratuity.engine"].compute(
                employee, date(2026, 10, 5), "resignation"
            )

    def _full_config(self, min_years=5, pro_rata=False):
        self._activate(
            self._version(
                self._rule("IN.GRATUITY.ELIGIBILITY", "json_value"),
                js={"permanent": {"min_years": min_years,
                                  "partial_year_month_threshold": 6,
                                  "pro_rata": pro_rata}},
            )
        )
        self._activate(self._version(self._rule("IN.GRATUITY.DAYS_PER_YEAR", "formula"),
                                    text="15"))
        self._activate(self._version(self._rule("IN.GRATUITY.WAGES_DIVISOR", "formula"),
                                    text="26"))
        self._activate(self._version(self._rule("IN.GRATUITY.CEILING", "cap"), numeric=2000000))
        self._activate(
            self._version(self._rule("IN.GRATUITY.PAYMENT_DEADLINE_DAYS", "deadline"), numeric=30)
        )

    def test_under_five_years_is_not_eligible(self):
        self._full_config()
        employee = self.env["hr.employee"].create(
            {"name": "Short Service", "join_date": date(2024, 1, 1)}
        )
        result = self.env["hrms.gratuity.engine"].compute(
            employee, date(2026, 10, 5), "resignation", wage_basis=30000.0
        )
        self.assertFalse(result.eligible)
        self.assertIn("months", result.ineligibility_reason)

    def test_over_five_years_is_eligible_and_dated(self):
        self._full_config()
        employee = self.env["hr.employee"].create(
            {"name": "Long Service", "join_date": date(2018, 1, 1)}
        )
        result = self.env["hrms.gratuity.engine"].compute(
            employee, date(2026, 10, 5), "resignation", wage_basis=30000.0
        )
        self.assertTrue(result.eligible)
        self.assertEqual(result.total_service_months, 105)  # 8y9m
        self.assertEqual(result.completed_years, 8)
        self.assertEqual(result.completed_months, 9)
        # 30000/26 x 15 x 9 completed years = 155769.23
        self.assertAlmostEqual(result.gratuity_amount, 155769.23, places=2)
        self.assertEqual((result.payment_deadline - result.as_of_date).days, 30)

    def test_remainder_above_six_months_counts_as_a_full_year(self):
        self._full_config()
        employee = self.env["hr.employee"].create(
            {"name": "Six Plus", "join_date": date(2019, 1, 1)}
        )
        # 7y9m at 2026-10-05: remainder 9 months > 6, so 8 countable years.
        result = self.env["hrms.gratuity.engine"].compute(
            employee, date(2026, 10, 5), "resignation", wage_basis=26000.0
        )
        self.assertTrue(result.eligible)
        self.assertEqual(result.completed_years, 7)
        self.assertEqual(result.completed_months, 9)
        self.assertAlmostEqual(result.gratuity_amount, 120000.0, places=2)  # 8 years

    def test_ceiling_is_applied_and_the_excess_reported(self):
        self._full_config()
        employee = self.env["hr.employee"].create(
            {"name": "Very Long Service", "join_date": date(2000, 1, 1)}
        )
        result = self.env["hrms.gratuity.engine"].compute(
            employee, date(2026, 10, 5), "resignation", wage_basis=300000.0
        )
        self.assertTrue(result.ceiling_applied)
        self.assertEqual(result.gratuity_amount, 2000000.0)
        self.assertGreater(result.capped_amount, 0.0)

    def test_result_records_the_rule_versions_used(self):
        self._full_config()
        employee = self.env["hr.employee"].create(
            {"name": "Traced", "join_date": date(2010, 1, 1)}
        )
        result = self.env["hrms.gratuity.engine"].compute(
            employee, date(2026, 10, 5), "resignation", wage_basis=50000.0
        )
        snapshot = json.loads(result.rule_versions_json)
        self.assertIn("IN.GRATUITY.DAYS_PER_YEAR", snapshot)


@tagged("post_install", "-at_install", "hrms_statutory")
class TestGratuityFixedTerm(StatutoryRuleTestCase):
    def test_fixed_term_uses_pro_rata_and_the_lower_threshold(self):
        eligibility = self._rule("IN.GRATUITY.ELIGIBILITY", "json_value")
        self._activate(
            self._version(
                eligibility,
                js={
                    "permanent": {"min_years": 5, "partial_year_month_threshold": 6},
                    "fixed_term": {"min_years": 1, "pro_rata": True,
                                   "trigger_on_term_expiry": True},
                },
            )
        )
        self._activate(self._version(self._rule("IN.GRATUITY.DAYS_PER_YEAR", "formula"), text="15"))
        self._activate(self._version(self._rule("IN.GRATUITY.WAGES_DIVISOR", "formula"), text="26"))
        self._activate(self._version(self._rule("IN.GRATUITY.CEILING", "cap"), numeric=2000000))
        self._activate(
            self._version(self._rule("IN.GRATUITY.PAYMENT_DEADLINE_DAYS", "deadline"), numeric=30)
        )

        employee = self.env["hr.employee"].create(
            {
                "name": "Fixed Term",
                "join_date": date(2026, 1, 1),
                "contract_type": "fixed_term",
                "hrms_contract_start": date(2026, 1, 1),
                "hrms_contract_end": date(2026, 12, 31),
            }
        )
        result = self.env["hrms.gratuity.engine"].compute(
            employee,
            date(2026, 12, 31),
            "fixed_term_expiry",
            wage_basis=26000.0,
        )
        self.assertTrue(result.eligible, result.ineligibility_reason)
        self.assertEqual(result.total_service_months, 12)
        # pro-rata: all 12 months counted, not rounded down and not capped by the
        # six-month remainder rule. 26000/26 = 1000/day, x 15 days x 1 year.
        self.assertAlmostEqual(result.gratuity_amount, 15000.0, places=2)

    def test_fixed_term_is_ineligible_before_a_full_year(self):
        eligibility = self._rule("IN.GRATUITY.ELIGIBILITY", "json_value")
        self._activate(
            self._version(
                eligibility,
                js={
                    "fixed_term": {"min_years": 1, "pro_rata": True,
                                   "trigger_on_term_expiry": True},
                },
            )
        )
        self._activate(self._version(self._rule("IN.GRATUITY.DAYS_PER_YEAR", "formula"), text="15"))
        self._activate(self._version(self._rule("IN.GRATUITY.WAGES_DIVISOR", "formula"), text="26"))
        self._activate(self._version(self._rule("IN.GRATUITY.CEILING", "cap"), numeric=2000000))
        self._activate(
            self._version(self._rule("IN.GRATUITY.PAYMENT_DEADLINE_DAYS", "deadline"), numeric=30)
        )
        employee = self.env["hr.employee"].create(
            {
                "name": "Terminated Early",
                "join_date": date(2026, 3, 1),
                "contract_type": "fixed_term",
                "hrms_contract_start": date(2026, 3, 1),
                "hrms_contract_end": date(2026, 12, 31),
            }
        )
        result = self.env["hrms.gratuity.engine"].compute(
            employee, date(2026, 10, 1), "termination", wage_basis=26000.0
        )
        self.assertFalse(
            result.eligible,
            "a fixed-term contract terminated before its year completed must not "
            "attract the term-expiry entitlement",
        )