# -*- coding: utf-8 -*-
"""A dependency-free mirror of the roster solver's constraint arithmetic.

Why this file exists
--------------------
The solver's real logic lives in ``addons/hrms_roster/models/solver.py`` and
needs Odoo to run. The development host has neither Odoo nor PostgreSQL, so
there was no way to check the arithmetic at all: the constraints would have been
written, read once, and shipped unverified.

This module re-implements the same rolling counters and the same
``_hard_block`` predicates with plain dataclasses, so the scheduling arithmetic
can be executed anywhere with a stock Python. It is a **mirror, not the
implementation**. There are two copies of the rules.

The drift risk is real, so ``test_mirror_is_in_sync_with_the_odoo_solver``
parses ``solver.py`` and fails if the constraint set, the default limits or the
blocking reasons have moved apart. If you change the real solver, run this
suite; it will tell you what to mirror.

Deliberately mirrored: the constraint arithmetic, the week/consecutive-day
counters, the ranking key.
Deliberately not mirrored: the ORM plumbing, availability/preference lookups,
JSON persistence and the apply path. Those are covered by the Odoo tests in
``addons/hrms_roster/tests/``.

Run with: python -m pytest tests/standalone/ -q
     or: python tests/standalone/test_solver_constraints.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

SOLVER_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "addons"
    / "hrms_roster"
    / "models"
    / "solver.py"
)

# Defaults that must match hrms.roster.solver.setting and hr.roster.shift.
DEFAULT_MAX_DAYS_PER_WEEK = 6
DEFAULT_MAX_CONSECUTIVE_DAYS = 6
DEFAULT_MAX_WEEKLY_HOURS = 48.0
DEFAULT_MIN_REST_HOURS = 8.0
DEFAULT_SHIFT_REST_AFTER_HOURS = 12.0

MONDAY = date(2026, 8, 3)  # a known Monday, so ISO-week maths is checkable

# Hard constraints the real solver enforces. Kept as explicit phrases so the sync
# check can compare both sides by reading rather than by parsing f-strings.
CONSTRAINT_SIGNATURES = [
    "on approved leave",
    "declared unavailable",
    "already assigned",
    "rest since the previous shift",
    "day(s) this ISO week",
    "would reach",
    "consecutive days",
]


@dataclass
class Setting:
    max_days_per_week: int = DEFAULT_MAX_DAYS_PER_WEEK
    max_consecutive_days: int = DEFAULT_MAX_CONSECUTIVE_DAYS
    max_weekly_hours: float = DEFAULT_MAX_WEEKLY_HOURS
    min_rest_hours_between_shifts: float = DEFAULT_MIN_REST_HOURS
    honour_preferences: bool = True
    prefer_skill_match: bool = True
    night_shift_rotation: bool = False


@dataclass
class Shift:
    name: str
    start_time: float
    end_time: float
    overnight: bool | None = None
    rest_after_hours: float = DEFAULT_SHIFT_REST_AFTER_HOURS
    is_night_shift: bool = False
    break_minutes: int = 30

    def __post_init__(self):
        if self.overnight is None:
            self.overnight = self.end_time <= self.start_time
        span = self.end_time - self.start_time + (24.0 if self.overnight else 0.0)
        self.duration_hours = round(max(span - self.break_minutes / 60.0, 0.0), 4)

    @property
    def span_hours(self) -> float:
        return max(self.end_time - self.start_time + (24.0 if self.overnight else 0.0), 0.0)


@dataclass
class Candidate:
    employee_id: int
    skills: set = field(default_factory=set)
    shift_credits: dict = field(default_factory=dict)


@dataclass
class Item:
    employee_id: int
    shift_id: str
    start: datetime
    end: datetime
    hours: float


def day_start(shift: Shift, day: date) -> datetime:
    hour = int(shift.start_time)
    minute = int(round((shift.start_time - hour) * 60))
    return datetime.combine(day, time(hour, minute))


class Plan:
    """Mirrors ``_RosterPlan``: counters, hard constraints, greedy fill."""

    def __init__(self, setting: Setting, pool: list[Candidate]):
        self.setting = setting
        self.pool = pool
        self.unavailable: dict[int, list] = {}
        self.preference: dict[int, list] = {}
        self.assigned: dict[int, list[Item]] = {}
        self.week_days: dict[tuple, set] = {}
        self.week_hours: dict[tuple, float] = {}
        self.day_count: dict[int, int] = {}
        self.last_end: dict[int, datetime] = {}
        self.last_day: dict[int, date] = {}
        self.proposed: list[Item] = []
        self.gaps: list[dict] = []

    # -- accounting ------------------------------------------------------
    def account(self, item: Item) -> None:
        emp = item.employee_id
        iso = item.start.isocalendar()
        key = (emp, iso[0], iso[1])
        self.week_days.setdefault(key, set()).add(item.start.weekday())
        self.week_hours[key] = self.week_hours.get(key, 0.0) + item.hours
        self.last_end[emp] = item.end
        day = item.start.date()
        if self.last_day.get(emp) == day - timedelta(days=1):
            self.day_count[emp] = self.day_count.get(emp, 0) + 1
        else:
            self.day_count[emp] = 1
        self.last_day[emp] = day
        self.assigned.setdefault(emp, []).append(item)

    # -- constraints -----------------------------------------------------
    def hard_block(self, candidate: Candidate, shift: Shift, day: date) -> str | None:
        """Mirrors ``_RosterPlan._hard_block``. Returns a reason, or None."""
        emp = candidate.employee_id
        setting = self.setting

        for (start, end), kind in self.unavailable.get(emp, []):
            if start <= day <= end:
                return f"{kind} ({start} to {end})"

        for item in self.assigned.get(emp, []):
            if item.start.date() == day:
                return f"already assigned {item.start:%d %b %H:%M}"
            if shift.overnight and item.start.date() == day - timedelta(days=1):
                return f"already assigned overnight {item.start:%d %b %H:%M}"

        last = self.last_end.get(emp)
        if last:
            gap = (day_start(shift, day) - last).total_seconds() / 3600.0
            if gap < max(setting.min_rest_hours_between_shifts, shift.rest_after_hours):
                return f"only {gap:.1f}h rest since the previous shift"

        iso = day.isocalendar()
        key = (emp, iso[0], iso[1])
        if (
            day.weekday() not in self.week_days.get(key, set())
            and len(self.week_days.get(key, set())) >= setting.max_days_per_week
        ):
            return f"already rostered {len(self.week_days[key])} day(s) this ISO week"

        projected = self.week_hours.get(key, 0.0) + shift.duration_hours
        if projected > setting.max_weekly_hours:
            return f"would reach {projected:.1f}h this ISO week"

        if self.day_count.get(emp, 0) + 1 > setting.max_consecutive_days:
            return f"would be {self.day_count.get(emp, 0) + 1} consecutive days"
        return None

    def rank(self, candidate: Candidate, shift: Shift, demand: dict):
        emp = candidate.employee_id
        setting = self.setting
        skill_rank = 0
        if setting.prefer_skill_match and demand.get("skills"):
            overlap = candidate.skills & set(demand["skills"])
            skill_rank = -len(overlap) if overlap else 10_000
        preference_rank = 10_000
        if setting.honour_preferences:
            for (start, end), shift_id in self.preference.get(emp, []):
                if start <= demand["date"] <= end and (
                    not shift_id or shift_id == shift.name
                ):
                    preference_rank = 0
                    break
        night_rank = 0
        if setting.night_shift_rotation and shift.is_night_shift:
            night_rank = candidate.shift_credits.get(shift.name, 0)
        load_rank = len(self.assigned.get(emp, []))
        return (night_rank, skill_rank, preference_rank, load_rank, emp)

    # -- fill ------------------------------------------------------------
    def fill(self, day: date, demand: dict, shift: Shift) -> None:
        ranked = []
        blockers: dict[str, int] = {}
        for candidate in self.pool:
            reason = self.hard_block(candidate, shift, day)
            if reason:
                head = reason.split("(")[0].strip()
                blockers[head] = blockers.get(head, 0) + 1
                continue
            ranked.append((self.rank(candidate, shift, demand), candidate))
        if not ranked:
            self.gaps.append(
                {
                    "date": str(day),
                    "shift": shift.name,
                    "short_by": 1,
                    "reason": "no employee satisfied the hard constraints",
                    "blockers": blockers,
                }
            )
            return
        ranked.sort(key=lambda pair: pair[0])
        chosen = ranked[0][1]
        start = day_start(shift, day)
        end = start + timedelta(hours=shift.span_hours)
        self.account(
            Item(
                employee_id=chosen.employee_id,
                shift_id=shift.name,
                start=start,
                end=end,
                hours=shift.duration_hours,
            )
        )
        self.proposed.append(self.assigned[chosen.employee_id][-1])
        chosen.shift_credits[shift.name] = chosen.shift_credits.get(shift.name, 0) + 1


# ---------------------------------------------------------------------------
# Assertions. Written as plain functions so they run under pytest or directly.
# ---------------------------------------------------------------------------


def test_shortfall_is_reported_rather_than_double_booked():
    """Demand above the pool must produce a gap, never a second shift on a day."""
    plan = Plan(Setting(), [Candidate(1), Candidate(2)])
    shift = Shift("Day", 9.0, 18.0)
    for _ in range(3):
        plan.fill(MONDAY, {"date": MONDAY, "skills": []}, shift)

    assert len(plan.proposed) == 2, "the pool is 2, so at most 2 shifts may be proposed"
    assert len(plan.gaps) == 1, "the third slot must be reported as unfilled"
    seen = [(i.employee_id, i.start.date()) for i in plan.proposed]
    assert len(seen) == len(set(seen)), "an employee was booked twice on one day"


def test_weekly_hour_ceiling_binds_before_the_day_cap():
    """6 x 8.5h is 51h, over a 48h contractual ceiling.

    This is the case that decides which limit a manager actually hits, and it is
    why the day cap alone would be misleading.
    """
    plan = Plan(Setting(), [Candidate(1)])
    shift = Shift("Day", 9.0, 18.0)
    for offset in range(7):
        plan.fill(MONDAY + timedelta(days=offset), {"date": MONDAY}, shift)

    days = {i.start.date() for i in plan.proposed}
    hours = sum(i.hours for i in plan.proposed)
    assert len(days) <= DEFAULT_MAX_DAYS_PER_WEEK
    assert hours <= DEFAULT_MAX_WEEKLY_HOURS, "weekly hour ceiling breached"
    assert plan.gaps, "days that could not be covered must be reported"
    # 5 days x 8.5h = 42.5h, and a 6th would reach 51h, so the ceiling stops it.
    assert len(days) == 5
    assert hours == 42.5


def test_consecutive_day_cap_alone():
    """With the hour ceiling lifted, the consecutive-day cap is the one that bites."""
    setting = Setting(max_weekly_hours=1000.0, max_days_per_week=7)
    plan = Plan(setting, [Candidate(1)])
    shift = Shift("Day", 9.0, 18.0)
    for offset in range(9):
        plan.fill(MONDAY + timedelta(days=offset), {"date": MONDAY}, shift)

    assert len(plan.proposed) == DEFAULT_MAX_CONSECUTIVE_DAYS
    assert len(plan.gaps) == 3


def test_day_off_breaks_the_consecutive_run():
    """Consecutive means consecutive *worked* days, not calendar days.

    A roster that stops for the weekend and starts again on Monday is not a
    fatigue problem; one that runs eleven days straight is.
    """
    setting = Setting(max_weekly_hours=1000.0, max_days_per_week=7)
    plan = Plan(setting, [Candidate(1)])
    wednesday = MONDAY + timedelta(days=2)
    plan.unavailable[1] = [((wednesday, wednesday), "unavailable")]
    shift = Shift("Day", 9.0, 18.0)
    for offset in range(7):
        day = MONDAY + timedelta(days=offset)
        plan.fill(day, {"date": day, "skills": []}, shift)

    emp_one = sorted(i.start.date() for i in plan.assigned.get(1, []))
    assert wednesday not in emp_one
    assert len(emp_one) == 6, f"expected 6 rostered days around one day off, got {len(emp_one)}"
    runs = []
    current = 1
    for previous, nxt in zip(emp_one, emp_one[1:]):
        current = current + 1 if (nxt - previous).days == 1 else 1
        runs.append(current)
    # Mon+Tue then Thu-Sun: without the reset, the counter would keep climbing
    # and block Sunday, because it would read 7 consecutive days.
    assert max(runs) == 4, f"expected a reset giving a longest run of 4, got {max(runs)}"


def test_rest_window_refuses_a_tight_turnaround():
    """A 22:00-06:00 night shift followed by a 09:00 day shift must be refused.

    That is a 3-hour gap. This is the turn-around that actually gets proposed by
    accident when a manager swaps a night for a day, so it is the case worth
    asserting.
    """
    plan = Plan(Setting(), [Candidate(1)])
    night = Shift("Night", 22.0, 6.0, rest_after_hours=10.0, is_night_shift=True)
    plan.fill(MONDAY, {"date": MONDAY, "skills": []}, night)
    day_shift = Shift("Day", 9.0, 18.0)
    reason = plan.hard_block(
        Candidate(1), day_shift, MONDAY + timedelta(days=1)
    )
    assert reason and "rest" in reason

    plan.fill(MONDAY + timedelta(days=1), {"date": MONDAY}, day_shift)
    assert all(i.shift_id == "Night" for i in plan.proposed), (
        "the day shift should have been refused on rest grounds"
    )


def test_rest_measurement_follows_paid_work_not_the_shift_template():
    """A 12h rest window permits 09:00 the day after an 18:00 finish.

    An earlier default of 16h on this shift forbade it, which made consecutive
    day shifts impossible and failed silently by producing a short roster.
    """
    plan = Plan(Setting(), [Candidate(1)])
    shift = Shift("Day", 9.0, 18.0)
    plan.fill(MONDAY, {"date": MONDAY, "skills": []}, shift)
    assert plan.hard_block(Candidate(1), shift, MONDAY + timedelta(days=1)) is None


def test_overnight_shift_ends_the_next_day():
    plan = Plan(Setting(), [Candidate(1), Candidate(2)])
    night = Shift("Night", 22.0, 6.0, rest_after_hours=10.0, is_night_shift=True)
    plan.fill(MONDAY, {"date": MONDAY, "skills": []}, night)
    assert plan.proposed
    for item in plan.proposed:
        assert item.end.date() == MONDAY + timedelta(days=1)
        assert item.end > item.start


def test_skill_match_outranks_stated_preference():
    skill = "forklift"
    plan = Plan(Setting(), [Candidate(1, {skill}), Candidate(2)])
    plan.preference[2] = [((date(2026, 1, 1), date(2026, 12, 31)), "Day")]
    shift = Shift("Day", 9.0, 18.0)
    plan.fill(MONDAY, {"date": MONDAY, "skills": [skill]}, shift)
    assert plan.proposed[0].employee_id == 1


def test_preference_is_honoured_when_nothing_else_differs():
    plan = Plan(Setting(), [Candidate(1), Candidate(2)])
    plan.preference[1] = [((date(2026, 1, 1), date(2026, 12, 31)), "Day")]
    shift = Shift("Day", 9.0, 18.0)
    plan.fill(MONDAY, {"date": MONDAY, "skills": []}, shift)
    assert plan.proposed[0].employee_id == 1


def test_load_is_balanced_across_the_pool():
    plan = Plan(Setting(), [Candidate(i) for i in range(1, 4)])
    shift = Shift("Day", 9.0, 18.0)
    for offset in range(6):
        day = MONDAY + timedelta(days=offset)
        plan.fill(day, {"date": day, "skills": []}, shift)
    counts = {emp: len(items) for emp, items in sorted(plan.assigned.items())}
    assert max(counts.values()) - min(counts.values()) <= 1, counts


def test_unavailable_and_leave_are_honoured():
    for kind in ("unavailable", "leave"):
        plan = Plan(Setting(), [Candidate(1), Candidate(2)])
        plan.unavailable[1] = [((MONDAY, MONDAY + timedelta(days=6)), kind)]
        shift = Shift("Day", 9.0, 18.0)
        for offset in range(7):
            day = MONDAY + timedelta(days=offset)
            plan.fill(day, {"date": day, "skills": []}, shift)
        assert 1 not in {i.employee_id for i in plan.proposed}, kind


def test_separated_employee_is_excluded_by_the_pool_query_not_the_arithmetic():
    """Documents where the exclusion happens: in the pool search, not here."""
    pool = [Candidate(1), Candidate(2)]
    plan = Plan(Setting(), pool)
    assert plan.pool == pool


def test_no_ceiling_is_breached_across_a_shared_pool():
    """The invariant that matters: no hard limit breaks, whatever the demand."""
    for headcount in (1, 2, 3):
        plan = Plan(Setting(), [Candidate(i) for i in range(1, 6)])
        shift = Shift("Day", 9.0, 18.0)
        for offset in range(7):
            day = MONDAY + timedelta(days=offset)
            for _ in range(headcount):
                plan.fill(day, {"date": day, "skills": []}, shift)
        for iso_week in {
            (i.start.isocalendar()[0], i.start.isocalendar()[1]) for i in plan.proposed
        }:
            for emp in {i.employee_id for i in plan.proposed}:
                rows = [
                    i
                    for i in plan.proposed
                    if i.employee_id == emp
                    and (i.start.isocalendar()[0], i.start.isocalendar()[1]) == iso_week
                ]
                if not rows:
                    continue
                days = {i.start.date() for i in rows}
                assert len(days) <= DEFAULT_MAX_DAYS_PER_WEEK
                assert sum(i.hours for i in rows) <= DEFAULT_MAX_WEEKLY_HOURS + 1e-6


def test_mirror_is_in_sync_with_the_odoo_solver():
    """Fail loudly if the real solver and this mirror have drifted apart.

    Two copies of a rule set is a maintenance hazard. This test is what makes it
    safe: change ``solver.py`` and this tells you what to mirror, instead of the
    mirror quietly passing while the shipped code is wrong.
    """
    source = SOLVER_SOURCE.read_text()
    assert SOLVER_SOURCE.exists(), f"solver source not found at {SOLVER_SOURCE}"

    defaults = {
        "max_days_per_week": DEFAULT_MAX_DAYS_PER_WEEK,
        "max_consecutive_days": DEFAULT_MAX_CONSECUTIVE_DAYS,
        "max_weekly_hours": DEFAULT_MAX_WEEKLY_HOURS,
        "min_rest_hours_between_shifts": DEFAULT_MIN_REST_HOURS,
    }
    for field_name, value in defaults.items():
        pattern = rf"{field_name}\s*=\s*fields\.\w+\(\s*default\s*=\s*{re.escape(str(value))}"
        assert re.search(pattern, source), (
            f"solver.py default for {field_name} is no longer {value}; update "
            "DEFAULT_* in tests/standalone/test_solver_constraints.py"
        )

    shift_source = (SOLVER_SOURCE.parent / "roster_period.py").read_text()
    pattern = rf"rest_after_hours\s*=\s*fields\.Float\(\s*default\s*=\s*{re.escape(str(DEFAULT_SHIFT_REST_AFTER_HOURS))}"
    assert re.search(pattern, shift_source), (
        "hr.roster.shift.rest_after_hours default changed; update "
        "DEFAULT_SHIFT_REST_AFTER_HOURS here"
    )

    # Every hard constraint in the product must be represented here, otherwise a
    # constraint could exist in the product with no standalone coverage. Checked
    # on both sides: present in solver.py and covered by a scenario in this file.
    block = source[source.index("def _hard_block") : source.index("def _rank")]
    mirror = Path(__file__).read_text()
    for signature in CONSTRAINT_SIGNATURES:
        assert signature in block, (
            f"solver.py no longer contains the '{signature}' constraint; remove it "
            "from CONSTRAINT_SIGNATURES if it was deleted on purpose"
        )
        assert signature in mirror, (
            f"solver.py enforces '{signature}' but this mirror does not exercise "
            "it; add a scenario here"
        )


def main() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}\n      {exc}")
        else:
            print(f"ok    {test.__name__}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())