# -*- coding: utf-8 -*-
"""Seeding tests.

The seeder is the most dangerous piece of code in this addon, because a
seeder that creates a usable value makes an unconfigured database look like a
working one. These tests are written to fail loudly if that ever happens.

Authored, not executed: no Odoo or PostgreSQL on the development host. Run them
with ``make test-odoo`` on the laptop.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models.catalog import RULE_CATALOG


@tagged("post_install", "-at_install", "hrms_statutory")
class TestCatalogSeed(TransactionCase):
    def setUp(self):
        super().setUp()
        self.catalog = self.env["hrms.statutory.catalog"]
        self.rule_model = self.env["hrms.statutory.rule"]
        self.version_model = self.env["hrms.statutory.rule.version"]

    # ─── What the seeder must never do ──────────────────────────────────
    def test_seed_creates_no_versions_at_all(self):
        self.catalog.seed()
        self.assertEqual(
            self.version_model.search_count([]),
            0,
            "the seeder must not create a single rule version: a version is a "
            "value, and a value without sign-off is exactly what must not exist",
        )

    def test_seeded_rule_cannot_be_used_for_a_calculation(self):
        """A skeleton with no version must refuse to resolve."""
        self.catalog.seed()
        ctx = self.env["hrms.statutory.context"]
        with self.assertRaises(UserError):
            ctx.get("IN.PF.EMPLOYEE_RATE", self.env.company)

    def test_no_seeded_code_resolves(self):
        """Every catalog code must stay unresolved after seeding."""
        self.catalog.seed()
        ctx = self.env["hrms.statutory.context"]
        resolved = []
        for code in self.catalog.catalog_codes():
            try:
                ctx.resolve(code, self.env.company)
            except UserError:
                continue
            resolved.append(code)
        self.assertEqual(
            resolved,
            [],
            f"these codes resolved to a usable value after seeding: {resolved}",
        )

    def test_seeded_rules_are_active_so_they_are_visible(self):
        """A skeleton nobody can find is a skeleton nobody fills in."""
        self.catalog.seed()
        codes = set(self.rule_model.search([("active", "=", True)]).mapped("code"))
        for code, *_ in RULE_CATALOG:
            self.assertIn(code, codes)

    def test_every_seeded_rule_has_a_source_reference(self):
        """source_reference is required, and 'TODO' would defeat the purpose."""
        self.catalog.seed()
        for rule in self.rule_model.search([]):
            self.assertTrue(rule.source_reference, f"{rule.code} has no source")
            self.assertIn(
                "TO BE CONFIRMED",
                rule.source_reference,
                f"{rule.code} must state that the source is unconfirmed",
            )

    def test_seeding_is_idempotent(self):
        first = self.catalog.seed()
        second = self.catalog.seed()
        self.assertEqual(second, 0, "re-seeding created duplicate rules")
        self.assertEqual(
            self.rule_model.search_count([("code", "in", self.catalog.catalog_codes())]),
            len(RULE_CATALOG),
        )
        self.assertTrue(first >= 0)

    def test_catalog_has_no_duplicate_codes(self):
        codes = [code for code, *_ in RULE_CATALOG]
        self.assertEqual(
            len(codes), len(set(codes)), "duplicate code in RULE_CATALOG would "
            "silently collapse into one rule"
        )

    def test_catalog_codes_matches_the_table(self):
        self.assertEqual(len(self.catalog.catalog_codes()), len(RULE_CATALOG))

    # ─── The sign-off gate still holds after seeding ────────────────────
    def test_cannot_validate_a_version_without_a_validator(self):
        self.catalog.seed()
        rule = self.rule_model.search([("code", "=", "IN.PF.EMPLOYEE_RATE")])
        version = self.version_model.create(
            {
                "rule_id": rule.id,
                "effective_from": "2026-04-01",
                "numeric_value": 12.0,
            }
        )
        with self.assertRaises(UserError):
            version.write({"state": "validated"})

    def test_author_cannot_validate_their_own_version(self):
        self.catalog.seed()
        rule = self.rule_model.search([("code", "=", "IN.PF.EMPLOYEE_RATE")])
        version = self.version_model.create(
            {
                "rule_id": rule.id,
                "effective_from": "2026-04-01",
                "numeric_value": 12.0,
            }
        )
        with self.assertRaises(UserError):
            version.write({"state": "validated", "validated_by": version.create_uid})

    def test_draft_version_still_refuses_to_serve_a_value(self):
        self.catalog.seed()
        rule = self.rule_model.search([("code", "=", "IN.PF.EMPLOYEE_RATE")])
        version = self.version_model.create(
            {
                "rule_id": rule.id,
                "effective_from": "2026-04-01",
                "numeric_value": 12.0,
            }
        )
        with self.assertRaises(UserError):
            version.value()

    def test_coverage_report_refuses_to_declare_go_live_readiness(self):
        self.catalog.seed()
        report = self.catalog.coverage_report()
        self.assertFalse(report["go_live_ready"])
        self.assertEqual(len(report["missing"]), len(RULE_CATALOG))
        self.assertEqual(report["ready"], [])


@tagged("post_install", "-at_install", "hrms_statutory")
class TestPostInitHook(TransactionCase):
    def test_hook_leaves_everything_unresolved(self):
        """The hook's own post-condition: nothing is live."""
        from .. import post_init_hook

        post_init_hook(self.env)
        ctx = self.env["hrms.statutory.context"]
        with self.assertRaises(UserError):
            ctx.get("IN.PF.WAGE_CEILING", self.env.company)