# -*- coding: utf-8 -*-
"""Tests for final settlement.

The properties under test are mostly refusals. A settlement engine that quietly
produces a plausible number is more dangerous than one that stops, because the
number looks finished.

Run on the development machine:

    odoo -d test_hrms -i hrms_fnf --test-enable --stop-after-init
"""

from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


# JSON bodies for the fixture's ``json_value`` codes. The leave accrual and the
# encashment wage basis did not exist as codes until 2026-10-05; without them the
# F&F calculation refuses, which is correct behaviour but makes every other test
# in this file fail for the wrong reason.
_FIXTURE_JSON = {
    "IN.GRATUITY.ELIGIBILITY":
        '{"default": {"min_years": 5, "partial_year_month_threshold": 6}}',
    "IN.LEAVE.CARRY_FORWARD_DAYS": '{"default": 30}',
    "IN.LEAVE.ACCRUAL_DAYS_PER_YEAR": '{"default": {"annual_days": 18}}',
    "IN.FNF.ENCASHMENT_WAGE_BASIS": '{"basis": "wages", "average_months": 3}',
}


@tagged("post_install", "-at_install", "hrms_fnf")
class SettlementTestCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Reason = cls.env["hrms.fnf.reason"]
        cls.reason = cls.Reason.create(
            {
                "name": "Resignation (test)",
                "code": "resignation",
                "requires_notice": True,
                "gratuity_eligible": True,
                "permits_recovery": True,
                "payroll_deadline_rule": "IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS",
            }
        )
        cls.company = cls.env["res.company"].create({"name": "F&F Test Co"})
        cls.payroll = cls.env["res.users"].create(
            {
                "name": "Payroll Officer",
                "login": "fnf.payroll.test",
                "email": "fnf.payroll@example.invalid",
                "groups_id": [
                    (6, 0, [cls.env.ref("hrms_core_ext.group_hrms_payroll_admin").id])
                ],
            }
        )
        cls.finance = cls.env["res.users"].create(
            {
                "name": "Finance Approver",
                "login": "fnf.finance.test",
                "email": "fnf.finance@example.invalid",
                "groups_id": [
                    (
                        6,
                        0,
                        [cls.env.ref("hrms_core_ext.group_hrms_finance_approver").id],
                    )
                ],
            }
        )
        cls.employee = cls._make_employee()

    @classmethod
    def _make_employee(cls, **kw):
        dept = cls.env["hr.department"].create({"name": "Test Dept"})
        vals = {
            "name": "Settlement Employee",
            "company_id": cls.company.id,
            "department_id": dept.id,
            "join_date": date(2018, 1, 1),
            "hrms_service_start": date(2018, 1, 1),
            "contract_type": "permanent",
            "birthday": date(1990, 5, 15),
        }
        vals.update(kw)
        employee = cls.env["hr.employee"].create(vals)
        cls.env["hr.contract"].create(
            {
                "name": "Test contract",
                "employee_id": employee.id,
                "company_id": cls.company.id,
                "date_start": date(2018, 1, 1),
                "wage": 60000,
                "state": "open",
            }
        )
        return employee

    def _case(self, **kw):
        vals = {
            "employee_id": self.employee.id,
            "company_id": self.company.id,
            "reason_id": self.reason.id,
            "last_working_day": date(2026, 9, 30),
            "notice_period_days": 60,
            "notice_served_days": 60,
            "resignation_date": date(2026, 8, 1),
        }
        vals.update(kw)
        return self.env["hrms.fnf.case"].create(vals)

    @classmethod
    def _configure_statutory(cls):
        """Minimal sign-off so the deadline and gratuity can resolve."""
        Rule = cls.env["hrms.statutory.rule"]
        Version = cls.env["hrms.statutory.rule.version"]
        approver = cls.env["res.users"].create(
            {
                "name": "Statutory Signatory",
                "login": "fnf.signatory.test",
                "email": "fnf.signatory@example.invalid",
            }
        )
        specs = [
            ("IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS", "deadline", None, "2"),
            ("IN.GRATUITY.ELIGIBILITY", "json_value", None, None),
            ("IN.GRATUITY.DAYS_PER_YEAR", "formula", None, "15"),
            ("IN.GRATUITY.WAGES_DIVISOR", "formula", None, "26"),
            ("IN.GRATUITY.CEILING", "cap", 2000000, None),
            ("IN.GRATUITY.PAYMENT_DEADLINE_DAYS", "deadline", 30, None),
            ("IN.LEAVE.CARRY_FORWARD_DAYS", "json_value", None, None),
            ("IN.LEAVE.ACCRUAL_DAYS_PER_YEAR", "json_value", None, None),
            ("IN.FNF.ENCASHMENT_WAGE_BASIS", "json_value", None, None),
        ]
        for code, ctype, numeric, text in specs:
            rule = Rule.search(
                [("code", "=", code), ("country_code", "=", "IN")], limit=1
            )
            if not rule:
                rule = Rule.create(
                    {
                        "name": code,
                        "code": code,
                        "component_type": ctype,
                        "source_reference": "test fixture authority",
                    }
                )
            if rule.component_type != ctype:
                rule.write({"component_type": ctype})
            Version.create(
                {
                    "rule_id": rule.id,
                    "effective_from": date(2020, 1, 1),
                    "numeric_value": numeric if numeric is not None else 0,
                    "text_value": text,
                    "json_value": _FIXTURE_JSON.get(code),
                    "state": "validated",
                    "source_reference": "test fixture authority",
                    "validated_by": approver.id,
                }
            )
        return approver


@tagged("post_install", "-at_install", "hrms_fnf")
class TestSettlementGates(SettlementTestCase):
    def test_calculate_produces_an_itemised_statement(self):
        self._configure_statutory()
        case = self._case()
        case.action_calculate()
        self.assertEqual(case.separation_state, "calculated")
        self.assertTrue(case.statement_json)
        self.assertTrue(case.statement_checksum)
        self.assertGreater(case.gross_payable, 0.0)

    def test_unconfigured_statutory_deadline_leaves_payable_by_empty(self):
        """No configured deadline must be visibly absent, not silently wrong."""
        case = self._case()
        self.assertFalse(
            case.payable_by,
            "payable_by was computed without a signed-off deadline rule",
        )

    def test_configured_deadline_is_anchored_to_the_last_working_day(self):
        self._configure_statutory()
        case = self._case()
        self.assertTrue(case.payable_by)
        self.assertGreater(case.payable_by, case.last_working_day)

    def test_recalculation_is_refused_after_acknowledgement(self):
        self._configure_statutory()
        case = self._case()
        case.action_calculate()
        case.action_acknowledge()
        with self.assertRaises(UserError):
            case.action_calculate()

    def test_statement_inputs_lock_after_acknowledgement(self):
        self._configure_statutory()
        case = self._case()
        case.action_calculate()
        case.action_acknowledge()
        with self.assertRaises(UserError):
            case.write({"last_working_day": date(2026, 9, 15)})

    def test_calculated_case_cannot_be_deleted(self):
        self._configure_statutory()
        case = self._case()
        case.action_calculate()
        with self.assertRaises(UserError):
            case.unlink()

    def test_draft_case_can_be_deleted(self):
        case = self._case()
        self.assertTrue(case.unlink())

    def test_notice_data_is_required_when_the_reason_carries_notice(self):
        case = self._case(notice_period_days=0)
        with self.assertRaises(UserError):
            case.action_calculate()

    def test_only_one_case_per_employee(self):
        self._case()
        with self.assertRaises(Exception):
            self._case()

    def test_acknowledgement_requires_a_calculated_statement(self):
        case = self._case()
        with self.assertRaises(UserError):
            case.action_acknowledge()


@tagged("post_install", "-at_install", "hrms_fnf")
class TestSettlementApproval(SettlementTestCase):
    def test_superuser_cannot_approve(self):
        self._configure_statutory()
        case = self._case()
        case.action_calculate()
        with self.assertRaises(UserError):
            case.action_approve()

    def test_only_the_calculated_states_can_be_approved(self):
        self._configure_statutory()
        case = self._case()
        case.action_calculate()
        case.with_user(self.finance).action_approve()
        with self.assertRaises(UserError):
            case.with_user(self.finance).action_approve()

    def test_negative_settlement_without_recovery_permission_is_refused(self):
        self._configure_statutory()
        no_recovery = self.Reason.create(
            {
                "name": "Death (test)",
                "code": "death",
                "gratuity_eligible": False,
                "permits_recovery": False,
                "payroll_deadline_rule": "IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS",
            }
        )
        case = self._case(reason_id=no_recovery.id, notice_period_days=0, resignation_date=False)
        case.action_calculate()
        # Force a negative position by recording a deduction that exceeds pay.
        case.statement_json = (
            '{"payable_lines": [], "deduction_lines": [{"line_type": "asset_recovery",'
            ' "amount": 5000.0, "is_deduction": true, "is_negative": true,'
            ' "rule_code": null, "label": "Asset recovery", "computation": {}}],'
            ' "details": {}}'
        )
        self.assertTrue(case.is_negative_settlement)
        with self.assertRaises(UserError):
            case.action_approve()

    def test_dispute_requires_a_reason(self):
        self._configure_statutory()
        case = self._case()
        case.action_calculate()
        with self.assertRaises(UserError):
            case.action_raise_dispute("  ")
        case.action_raise_dispute("Notice period not correctly applied")
        self.assertEqual(case.separation_state, "disputed")

    def test_paid_case_cannot_be_paid_again(self):
        self._configure_statutory()
        case = self._case()
        case.action_calculate()
        case.with_user(self.finance).action_approve()
        case.with_user(self.finance).action_mark_paid(reference="NEFT/001")
        self.assertEqual(case.payment_reference, "NEFT/001")
        with self.assertRaises(UserError):
            case.with_user(self.finance).action_mark_paid()


@tagged("post_install", "-at_install", "hrms_fnf")
class TestNoticeShortfall(SettlementTestCase):
    def test_shortfall_is_computed_from_period_minus_served(self):
        case = self._case(notice_period_days=60, notice_served_days=30)
        self.assertEqual(case.notice_shortfall_days, 30)

    def test_working_past_notice_yields_no_shortfall(self):
        case = self._case(notice_period_days=60, notice_served_days=90)
        self.assertEqual(case.notice_shortfall_days, 0)

    def test_shortfall_is_not_recovered_when_the_reason_forbids_it(self):
        """Recovering without authority is itself unlawful."""
        self._configure_statutory()
        no_recovery = self.Reason.create(
            {
                "name": "Retirement (no recovery, test)",
                "code": "retirement",
                "requires_notice": True,
                "gratuity_eligible": False,
                "permits_recovery": False,
                "payroll_deadline_rule": "IN.FNF.WAGE_PAYMENT_DEADLINE_WORKING_DAYS",
            }
        )
        case = self._case(
            reason_id=no_recovery.id,
            notice_period_days=60,
            notice_served_days=20,
        )
        case.action_calculate()
        import json

        details = json.loads(case.statement_json)["details"]["notice"]
        self.assertEqual(details["shortfall_days"], 40)
        self.assertFalse(details["recovery_permitted"])
        self.assertIn("note", details)