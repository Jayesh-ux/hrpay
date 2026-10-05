# -*- coding: utf-8 -*-
"""Roster solver tests.

These are authored, not executed: this host has no Odoo, PostgreSQL or Docker,
and the user's instruction is that runtime testing happens on their laptop at
Gate 1A. They are written to be run there without modification.

The emphasis is on the solver refusing to produce an unlawful roster rather than
on it producing a complete one. A solver that quietly double-books an employee
to close a gap is worse than one that reports the gap, so the refusal paths are
the ones worth testing.
"""

import json
from datetime import date, datetime

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hrms_roster")
class TestRosterSolver(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")
        cls.establishment = cls.env["hr.department"].create(
            {"name": "Plant 1", "hrms_is_establishment": True}
        )
        cls.day_shift = cls.env["hr.roster.shift"].create(
            {
                "name": "Day 09-18",
                "company_id": cls.company.id,
                "start_time": 9.0,
                "end_time": 18.0,
                "break_minutes": 30,
                "rest_after_hours": 12.0,
            }
        )
        cls.night_shift = cls.env["hr.roster.shift"].create(
            {
                "name": "Night 22-06",
                "company_id": cls.company.id,
                "start_time": 22.0,
                "end_time": 6.0,
                "overnight": True,
                "break_minutes": 30,
                "rest_after_hours": 12.0,
                "is_night_shift": True,
            }
        )
        cls.setting = cls.env["hrms.roster.solver.setting"].create(
            {
                "establishment_id": cls.establishment.id,
                "company_id": cls.company.id,
                "max_days_per_week": 6,
                "max_weekly_hours": 48.0,
                "min_rest_hours_between_shifts": 8.0,
                "max_consecutive_days": 6,
            }
        )
        cls.period = cls.env["hr.roster.period"].create(
            {
                "name": "Test week",
                "company_id": cls.company.id,
                "establishment_id": cls.establishment.id,
                "date_from": "2026-08-03",
                "date_to": "2026-08-09",
            }
        )

    def _employee(self, name, wage=1000.0, skills=None):
        user = self.env["res.users"].create(
            {
                "name": name,
                "login": name.lower().replace(" ", ".") + "@test.local",
                "company_id": self.company.id,
                "groups_id": [(6, 0, [self.env.ref("hr.group_hr_user").id])],
            }
        )
        employee = self.env["hr.employee"].create(
            {
                "name": name,
                "user_id": user.id,
                "company_id": self.company.id,
                "department_id": self.establishment.id,
                "join_date": "2020-01-01",
                "hrms_establishment_id": self.establishment.id,
                "skill_ids": [(6, 0, skills or [])],
            }
        )
        self.env["hr.contract"].create(
            {
                "name": f"{name} contract",
                "employee_id": employee.id,
                "company_id": self.company.id,
                "wage": wage,
                "date_start": "2020-01-01",
            }
        )
        return employee

    def _demand_all_days(self, shift=None, headcount=1):
        """A full week of demand, so weekly ceilings are actually exercised."""
        for weekday in "0123456":
            self._demand(shift=shift, headcount=headcount, weekday=weekday)

    def _demand(self, shift=None, headcount=1, weekday=None, skills=None):
        return self.env["hr.roster.demand"].create(
            {
                "establishment_id": self.establishment.id,
                "company_id": self.company.id,
                "weekday": weekday or "0",
                "shift_id": (shift or self.day_shift).id,
                "required_headcount": headcount,
                "required_skill_ids": [(6, 0, skills or [])],
            }
        )

    def _solve(self):
        return self.env["hrms.roster.solver"].solve(self.period, self.setting)

    # ─── Refusals ───────────────────────────────────────────────────────
    def test_solver_refuses_non_draft_period(self):
        self.period.action_publish()
        with self.assertRaises(UserError):
            self._solve()

    def test_solver_refuses_without_settings(self):
        self.setting.active = False
        with self.assertRaises(UserError):
            self._solve()

    def test_solver_refuses_without_demand(self):
        with self.assertRaises(UserError):
            self._solve()

    def test_solver_refuses_when_pool_is_empty(self):
        self._demand()
        self.period.date_from = "2030-01-07"
        self.period.date_to = "2030-01-07"
        with self.assertRaises(UserError):
            self._solve()

    def test_excluded_employee_cannot_be_rostered(self):
        """A departed employee must never appear in a proposal."""
        self._demand(headcount=2)
        active = self._employee("Active One")
        departed = self._employee("Departed")
        departed.write({"hrms_separation_state": "terminated"})
        result = self._solve()
        proposed = {p["employee_id"] for p in _loads(result.proposal_json)}
        self.assertIn(active.id, proposed)
        self.assertNotIn(departed.id, proposed)

    def test_last_working_day_inside_period_excludes_employee(self):
        self._demand(headcount=2)
        leaving = self._employee("Leaving Midweek")
        leaving.hrms_last_working_day = "2026-08-05"
        self._employee("Staying")
        result = self._solve()
        proposed = {p["employee_id"] for p in _loads(result.proposal_json)}
        self.assertNotIn(leaving.id, proposed)

    def test_employee_on_approved_leave_is_not_rostered(self):
        self._demand(headcount=2)
        away = self._employee("On Leave")
        self._employee("Available")
        self.env["hrms.roster.availability"].create(
            {
                "employee_id": away.id,
                "company_id": self.company.id,
                "date_from": "2026-08-03",
                "date_to": "2026-08-09",
                "kind": "leave",
            }
        )
        result = self._solve()
        proposed = {p["employee_id"] for p in _loads(result.proposal_json)}
        self.assertNotIn(away.id, proposed)

    def test_declared_unavailable_is_not_rostered(self):
        self._demand(headcount=2)
        busy = self._employee("Busy That Day")
        self._employee("Free That Day")
        self.env["hrms.roster.availability"].create(
            {
                "employee_id": busy.id,
                "company_id": self.company.id,
                "date_from": "2026-08-03",
                "date_to": "2026-08-03",
                "kind": "unavailable",
            }
        )
        result = self._solve()
        proposed = {p["employee_id"] for p in _loads(result.proposal_json)}
        self.assertNotIn(busy.id, proposed)

    # ─── The gaps are the point ─────────────────────────────────────────
    def test_shortfall_is_reported_not_double_booked(self):
        """Demand above the pool yields a gap, never a double-booking."""
        self._demand(headcount=3)
        one = self._employee("Only One")
        self._employee("Only Two")
        result = self._solve()
        unfilled = _loads(result.unfilled_json)
        self.assertEqual(sum(u["short_by"] for u in unfilled), 1)
        # The critical assertion: nobody appears twice on the same date.
        seen = [(p["employee_id"], p["start_datetime"][:10]) for p in _loads(result.proposal_json)]
        self.assertEqual(len(seen), len(set(seen)))

    def test_proposal_never_exceeds_weekly_hour_ceiling(self):
        self._demand_all_days(headcount=1)
        self._employee("Sole Worker")
        result = self._solve()
        hours = sum(p["paid_hours"] for p in _loads(result.proposal_json))
        self.assertLessEqual(hours, 48.0)

    def test_proposal_never_exceeds_weekly_day_cap(self):
        self._demand_all_days(headcount=1)
        self._employee("Sole Worker Two")
        result = self._solve()
        for item in _loads(result.proposal_json):
            iso = _iso(item["start_datetime"])
            days = {
                p["start_datetime"][:10]
                for p in _loads(result.proposal_json)
                if _iso(p["start_datetime"]) == iso
            }
            self.assertLessEqual(len(days), self.setting.max_days_per_week)

    def test_proposal_never_breaches_consecutive_day_cap(self):
        self._demand_all_days(headcount=1)
        self._employee("Sole Worker Three")
        result = self._solve()
        longest, run = 1, 1
        dates = sorted({p["start_datetime"][:10] for p in _loads(result.proposal_json)})
        for previous, current in zip(dates, dates[1:]):
            gap = (
                self.env["hr.roster.solver"].env.cr  # placeholder to keep lint quiet
            ) and 0
            if _days_between(previous, current) == 1:
                run += 1
                longest = max(longest, run)
            else:
                run = 1
        self.assertLessEqual(longest, self.setting.max_consecutive_days)

    def test_rest_window_is_enforced(self):
        self._demand_all_days(headcount=1)
        self._employee("Sole Worker Four")
        result = self._solve()
        by_employee = {}
        for item in _loads(result.proposal_json):
            by_employee.setdefault(item["employee_id"], []).append(item)
        for items in by_employee.values():
            items.sort(key=lambda i: i["start_datetime"])
            for previous, current in zip(items, items[1:]):
                if _days_between(previous["start_datetime"][:10], current["start_datetime"][:10]) != 1:
                    continue
                gap_hours = _hours_between(previous["end_datetime"], current["start_datetime"])
                self.assertGreaterEqual(
                    gap_hours,
                    max(self.setting.min_rest_hours_between_shifts, 0.0),
                    "rostered a turn-around with insufficient rest",
                )

    def test_overnight_shift_ends_next_day(self):
        self._demand(shift=self.night_shift, headcount=1)
        self._employee("Night Worker")
        result = self._solve()
        for item in _loads(result.proposal_json):
            self.assertGreater(item["end_datetime"], item["start_datetime"])
        # 22:00 to 06:00 spans midnight, so the end date must be the following day.
        for item in _loads(result.proposal_json):
            self.assertNotEqual(item["start_datetime"][:10], item["end_datetime"][:10])

    def test_nobody_is_rostered_twice_on_the_same_date(self):
        self._demand_all_days(headcount=1)
        for i in range(4):
            self._employee(f"Worker {i}")
        result = self._solve()
        seen = [(p["employee_id"], p["start_datetime"][:10]) for p in _loads(result.proposal_json)]
        self.assertEqual(len(seen), len(set(seen)))

    # ─── Preference is a soft constraint ─────────────────────────────────
    def test_skill_match_outranks_stated_preference(self):
        skill = self.env["hr.skill"].create({"name": "Forklift"})
        self._demand(headcount=1, skills=[skill.id])
        skilled = self._employee("Skilled", skills=[skill.id])
        eager = self._employee("Eager")
        self.env["hrms.roster.availability"].create(
            {
                "employee_id": eager.id,
                "company_id": self.company.id,
                "date_from": "2026-08-03",
                "date_to": "2026-08-03",
                "kind": "preferred",
                "source": "employee",
            }
        )
        result = self._solve()
        proposed = _loads(result.proposal_json)
        self.assertTrue(proposed)
        self.assertEqual(proposed[0]["employee_id"], skilled.id)

    def test_preference_honoured_when_nothing_else_differs(self):
        self._demand(headcount=1)
        choosy = self._employee("Choosy")
        self._employee("Unbothered")
        self.env["hrms.roster.availability"].create(
            {
                "employee_id": choosy.id,
                "company_id": self.company.id,
                "date_from": "2026-08-03",
                "date_to": "2026-08-03",
                "kind": "preferred",
                "source": "employee",
            }
        )
        result = self._solve()
        monday = [p for p in _loads(result.proposal_json) if p["start_datetime"][:10] == "2026-08-03"]
        self.assertTrue(monday)
        self.assertEqual(monday[0]["employee_id"], choosy.id)

    # ─── Applying a proposal ─────────────────────────────────────────────
    def test_apply_creates_draft_assignments_only(self):
        self._demand(headcount=1)
        self._employee("Applied Worker")
        self._employee("Applied Worker Two")
        result = self._solve()
        result.action_apply()
        created = self.env["hr.roster.assignment"].search(
            [("roster_period_id", "=", self.period.id)]
        )
        self.assertTrue(created)
        self.assertEqual(set(created.mapped("state")), {"draft"})

    def test_apply_refuses_a_proposal_with_unfilled_demand(self):
        """A gap must be resolved by a person, not applied automatically."""
        self._demand(headcount=3)
        self._employee("Lonely One")
        self._employee("Lonely Two")
        result = self._solve()
        self.assertTrue(_loads(result.unfilled_json))
        with self.assertRaises(UserError):
            result.action_apply()
        self.assertFalse(
            self.env["hr.roster.assignment"].search([("roster_period_id", "=", self.period.id)])
        )

    def test_apply_is_refused_twice(self):
        self._demand(headcount=1)
        self._employee("Once Only")
        self._employee("Once Only Two")
        result = self._solve()
        result.action_apply()
        with self.assertRaises(UserError):
            result.action_apply()

    def test_solver_result_grants_no_write_permission(self):
        """A proposal is evidence; rewriting it would void the unfilled list.

        Asserted through the ACL because that is what actually holds: Odoo does
        not refuse ORM writes to readonly fields, so marking the fields readonly
        would protect nothing on its own.
        """
        acl = self.env.ref("hrms_roster.access_roster_solver_result_read")
        self.assertFalse(acl.perm_write)
        self.assertFalse(acl.perm_unlink)
        self.assertTrue(acl.perm_read)

    def test_availability_dates_must_be_ordered(self):
        employee = self._employee("Bad Dates")
        with self.assertRaises(UserError):
            self.env["hrms.roster.availability"].create(
                {
                    "employee_id": employee.id,
                    "company_id": self.company.id,
                    "date_from": "2026-08-09",
                    "date_to": "2026-08-03",
                    "kind": "unavailable",
                }
            )

@tagged("post_install", "-at_install", "hrms_roster")
class TestRosterSolverSettings(TransactionCase):
    def test_settings_reject_out_of_range_limits(self):
        department = self.env["hr.department"].create(
            {"name": "Plant 2", "hrms_is_establishment": True}
        )
        for field, value in (
            ("max_days_per_week", 0),
            ("max_days_per_week", 8),
            ("max_consecutive_days", 0),
            ("max_consecutive_days", 9),
            ("max_weekly_hours", 0.0),
        ):
            with self.assertRaises(UserError):
                self.env["hrms.roster.solver.setting"].create(
                    {
                        "establishment_id": department.id,
                        "company_id": self.env.company.id,
                        field: value,
                    }
                )

    def test_default_settings_cover_a_full_week_and_a_full_day(self):
        """Defaults must not silently forbid ordinary rostering.

        An earlier default of 16 hours rest on a 09:00-18:00 shift made
        consecutive day shifts impossible, because the next start would have had
        to be 10:00 or later. That failed silently: the roster simply came out
        short. The defaults are now ordinary, and the hour ceiling is what
        limits sustained daily working.
        """
        setting = self.env["hrms.roster.solver.setting"].create(
            {
                "establishment_id": self.env["hr.department"]
                .create({"name": "Plant 3", "hrms_is_establishment": True})
                .id,
                "company_id": self.env.company.id,
            }
        )
        self.assertEqual(setting.max_days_per_week, 6)
        self.assertEqual(setting.max_consecutive_days, 6)
        self.assertEqual(setting.max_weekly_hours, 48.0)
        self.assertLessEqual(setting.min_rest_hours_between_shifts, 12.0)


_FMT = "%Y-%m-%d %H:%M:%S"
_DAY_FMT = "%Y-%m-%d"


def _loads(text):
    return json.loads(text or "[]")


def _iso(datetime_text):
    return datetime.strptime(datetime_text, _FMT).isocalendar()[:2]


def _days_between(earlier, later):
    return (date.strptime(later, _DAY_FMT) - date.strptime(earlier, _DAY_FMT)).days


def _hours_between(earlier, later):
    return (datetime.strptime(later, _FMT) - datetime.strptime(earlier, _FMT)).total_seconds() / 3600.0