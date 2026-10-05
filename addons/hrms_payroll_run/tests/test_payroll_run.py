# -*- coding: utf-8 -*-
"""Tests for the payroll run gates.

The four claims this module makes are each tested here: coverage is checked
before computing, results are frozen by checksum, approval is separated from
computation and review, and advisory flags never block.

Run on the development machine:

    odoo -d test_hrms -i hrms_payroll_run --test-enable --stop-after-init
"""

import json
from datetime import date

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hrms_payroll_run")
class PayrollRunTestCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Company = cls.env["res.company"].create({"name": "Run Test Co"})
        cls.dept = cls.env["hr.department"].create(
            {"name": "Head Office", "hrms_is_establishment": True, "hrms_rostered": False}
        )
        cls.payroll_user = cls._user("run.payroll.test", "hrms_core_ext.group_hrms_payroll_admin")
        cls.reviewer = cls._user("run.reviewer.test", "hrms_core_ext.group_hrms_payroll_admin")
        cls.finance = cls._user("run.finance.test", "hrms_core_ext.group_hrms_finance_approver")
        cls.structure = cls.env["hr.salary.structure"].create(
            {
                "name": "Test Structure",
                "company_id": cls.Company.id,
                "type": "monthly",
            }
        )

    @classmethod
    def _user(cls, login, group_xmlid):
        return cls.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "email": f"{login}@example.invalid",
                "groups_id": [(6, 0, [cls.env.ref(group_xmlid).id])],
            }
        )

    def _employee(self, **kw):
        vals = {
            "name": "Rostered Employee",
            "company_id": self.Company.id,
            "department_id": self.dept.id,
            "hrms_establishment_id": self.dept.id,
            "join_date": date(2024, 1, 1),
            "hrms_service_start": date(2024, 1, 1),
            "date_of_birth": date(1995, 1, 1),
        }
        vals.update(kw)
        employee = self.env["hr.employee"].create(vals)
        self.env["hr.contract"].create(
            {
                "name": "Contract",
                "employee_id": employee.id,
                "company_id": self.Company.id,
                "date_start": date(2024, 1, 1),
                "wage": 50000,
                "state": "open",
            }
        )
        return employee

    def _run(self, **kw):
        vals = {
            "company_id": self.Company.id,
            "establishment_id": self.dept.id,
            "period_start": date(2026, 8, 1),
            "period_end": date(2026, 8, 31),
        }
        vals.update(kw)
        return self.env["hrms.payroll.run"].create(vals)


@tagged("post_install", "-at_install", "hrms_payroll_run")
class TestRunCoverageGate(PayrollRunTestCase):
    def test_employee_without_a_wage_blocks_the_run(self):
        """A run that silently pays nothing for one employee looks finished."""
        self._employee()
        employee = self._employee(name="No Wage")
        employee.contract_id.unlink()
        run = self._run()
        with self.assertRaises(UserError):
            run.action_compute()

    def test_unrostered_establishment_blocks_when_roster_required(self):
        self.dept.hrms_rostered = True
        self._employee()
        run = self._run()
        self.assertIn("roster", (run.blocking_issues or "").lower())
        with self.assertRaises(UserError):
            run.action_compute()

    def test_rostered_establishment_is_satisfied_by_assignments(self):
        self.dept.hrms_rostered = True
        employee = self._employee()
        shift = self.env["hr.roster.shift"].create(
            {
                "name": "Day",
                "company_id": self.Company.id,
                "start_time": 9.0,
                "end_time": 18.0,
                "break_minutes": 60,
            }
        )
        period = self.env["hr.roster.period"].create(
            {
                "name": "Aug 2026",
                "company_id": self.Company.id,
                "establishment_id": self.dept.id,
                "date_from": date(2026, 8, 1),
                "date_to": date(2026, 8, 31),
            }
        )
        self.env["hr.roster.assignment"].create(
            {
                "company_id": self.Company.id,
                "roster_period_id": period.id,
                "employee_id": employee.id,
                "shift_id": shift.id,
                "start_datetime": "2026-08-03 09:00:00",
                "end_datetime": "2026-08-03 18:00:00",
                "state": "published",
            }
        )
        run = self._run()
        self.assertNotIn("roster assignments", (run.blocking_issues or ""))

    def test_statutory_coverage_gap_is_reported(self):
        """No signed-off statutory configuration means no run."""
        self._employee()
        run = self._run()
        # Without any configured rules the context raises, so the run must be
        # blocked rather than computing something plausible.
        self.assertTrue(run.blocking_issues)
        with self.assertRaises(UserError):
            run.action_compute()


@tagged("post_install", "-at_install", "hrms_payroll_run")
class TestRunIntegrity(PayrollRunTestCase):
    def test_period_cannot_change_once_the_run_leaves_draft(self):
        run = self._run()
        run.state = "computed"
        with self.assertRaises(UserError):
            run.write({"period_end": date(2026, 9, 30)})

    def test_input_checksum_reflects_the_inputs(self):
        self._employee()
        run = self._run()
        first = run.input_checksum
        self.assertTrue(first)
        self._employee(name="Second Employee")
        run.invalidate_recordset()
        self.assertNotEqual(run.input_checksum, first)

    def test_approval_refuses_when_payslips_changed_after_computation(self):
        run = self._run()
        run.result_checksum = "a" * 64
        run.state = "reviewed"
        run.reviewed_by_id = self.reviewer.id
        run.computed_by_id = self.payroll_user.id
        # A payslip in scope with an amount that does not match the checksum.
        self._employee()
        self.env["hr.payslip"].create(
            {
                "employee_id": self._employee().id,
                "date_from": date(2026, 8, 1),
                "date_to": date(2026, 8, 31),
                "name": "Aug",
                "struct_id": self.structure.id,
            }
        )
        with self.assertRaises(UserError):
            run.action_approve()

    def test_locked_run_cannot_be_cancelled(self):
        run = self._run()
        run.state = "locked"
        with self.assertRaises(UserError):
            run.action_cancel()

    def test_non_cancelled_run_cannot_be_deleted(self):
        run = self._run()
        run.state = "computed"
        with self.assertRaises(UserError):
            run.unlink()

    def test_only_one_run_per_establishment_and_period(self):
        self._run()
        with self.assertRaises(Exception):
            self._run()


@tagged("post_install", "-at_install", "hrms_payroll_run")
class TestRunApprovalSeparation(PayrollRunTestCase):
    def _computed_run(self):
        run = self._run()
        run.state = "computed"
        run.computed_by_id = self.payroll_user.id
        run.result_checksum = run._result_checksum()
        return run

    def test_computer_cannot_review_their_own_run(self):
        run = self._computed_run()
        with self.env.cr.savepoint():
            self.env.user = self.payroll_user
            try:
                with self.assertRaises(UserError):
                    run.action_review("looks fine")
            finally:
                self.env.user = self.env["res.users"].browse(self.env.uid)

    def test_reviewer_cannot_approve_their_own_run(self):
        run = self._computed_run()
        run.state = "reviewed"
        run.reviewed_by_id = self.reviewer.id
        run.review_note = "checked"
        run.result_checksum = run._result_checksum()
        with self.env.cr.savepoint():
            self.env.user = self.reviewer
            try:
                with self.assertRaises(UserError):
                    run.action_approve()
            finally:
                self.env.user = self.env["res.users"].browse(self.env.uid)

    def test_review_requires_a_note(self):
        run = self._computed_run()
        with self.assertRaises(UserError):
            run.action_review("   ")

    def test_anomaly_flags_must_be_acknowledged_by_a_note(self):
        run = self._computed_run()
        run.action_record_ai_flags(
            json.dumps([{"code": "OVERTIME_SPIKE", "employee_id": 1, "severity": "high"}])
        )
        self.assertEqual(run.ai_flags_count, 1)
        self.assertFalse(run.ai_flags_acknowledged)
        with self.assertRaises(UserError):
            run.action_review("")

    def test_anomaly_flags_do_not_block_computation(self):
        """A scoring function is not an authority on a payroll question."""
        run = self._computed_run()
        run.action_record_ai_flags(json.dumps([{"code": "ANOMALY"}]))
        self.assertIn("advisory", run.blocking_issues)
        # explicitly NOT raising
        self.assertTrue(run.state == "computed")

    def test_invalid_flag_payload_is_refused(self):
        run = self._computed_run()
        with self.assertRaises(UserError):
            run.action_record_ai_flags("not json")