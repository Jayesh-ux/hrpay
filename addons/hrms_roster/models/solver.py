# -*- coding: utf-8 -*-
"""Roster solver: fill the demand curve, or explain why it cannot be filled.

This is deliberately *not* an optimiser. It is a constructive, auditable
allocator that works in the order an establishment manager would:

1. Mandatory cover first. Where demand exceeds the pool, the shortfall is the
   answer and is reported as such. Filling it by quietly double-booking an
   employee would produce a roster that looks complete and pays overtime nobody
   was there for.
2. Skills before availability.
3. Availability before preference.
4. Rest, weekly overtime caps and weekly day limits are hard constraints, checked
   before an assignment is proposed, because violating them is not a preference
   to be traded away - it is unlawful or unsafe.

The solver never writes assignments. It returns a proposal that a manager
reviews, confirms and publishes. An automatic roster that writes straight to the
record would make the published roster unreviewable, and the published roster is
the reference every attendance and overtime decision is judged against.

Known limitation: the weekly day limit and rest window are enforced greedily per
candidate, so the solver can decline an assignment that a different arrangement
would have allowed. It does not backtrack. For the establishments this was built
for, a documented shortfall a manager can act on is better than a schedule that
is optimal and cannot be explained.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, time, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SolverSettings(models.Model):
    """Solver limits, per establishment.

    Configurable rather than hardcoded because weekly day limits and overtime
    thresholds are enforced by the establishment's own contract, standing orders
    and policy, and those differ. Where a limit is governed by a statutory rule,
    the statutory code is recorded and resolved at solve time.
    """

    _name = "hrms.roster.solver.setting"
    _description = "Roster solver settings"
    _order = "establishment_id"

    name = fields.Char(compute="_compute_name", store=True)
    establishment_id = fields.Many2one(
        "hr.department", string="Establishment", required=True, ondelete="cascade"
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    active = fields.Boolean(default=True)

    max_days_per_week = fields.Integer(
        default=6,
        required=True,
        help="Maximum rostered days per employee per ISO week. Contractual or "
        "standing-order limit; set to 7 where none applies.",
    )
    min_rest_hours_between_shifts = fields.Float(
        default=8.0, digits=(8, 2), required=True,
        help="Minimum rest between the end of one shift and the start of the "
        "next. The shift template may demand more; this is the floor.",
    )
    max_consecutive_days = fields.Integer(
        default=6,
        help="Maximum consecutive rostered days without a day off. Limits "
        "fatigue, which no calculation will otherwise notice.",
    )
    honour_preferences = fields.Boolean(
        default=True,
        help="Prefer employees who asked for a shift. Soft: a preference is never "
        "satisfied at the cost of cover or a hard constraint.",
    )
    prefer_skill_match = fields.Boolean(
        default=True,
        help="Prefer the most specific skill match rather than the first "
        "available employee.",
    )
    max_weekly_hours = fields.Float(
        default=48.0, digits=(8, 2),
        help="Contractual weekly hour ceiling. Statutory overtime limits are "
        "separate and are not a substitute for this.",
    )
    night_shift_rotation = fields.Boolean(
        default=False,
        help="Rotate night shifts so the same employees do not always take them. "
        "Night work is an additional burden and an entitlement.",
    )
    unresolved_demand_strategy = fields.Selection(
        [
            ("report", "Report the shortfall"),
            ("raise_anomaly", "Report and raise an anomaly flag"),
        ],
        default="report",
        required=True,
    )

    @api.depends("establishment_id")
    def _compute_name(self):
        for rec in self:
            rec.name = f"Solver: {rec.establishment_id.name}"

    @api.constrains("max_days_per_week", "max_consecutive_days", "max_weekly_hours")
    def _check_limits(self):
        for rec in self:
            if not 1 <= rec.max_days_per_week <= 7:
                raise UserError("max_days_per_week must be between 1 and 7.")
            if not 1 <= rec.max_consecutive_days <= 7:
                raise UserError("max_consecutive_days must be between 1 and 7.")
            if rec.max_weekly_hours <= 0:
                raise UserError("max_weekly_hours must be positive.")


class EmployeeAvailability(models.Model):
    """Declared availability: the things that rule an employee out in advance.

    Kept separate from the roster itself so an unavailability is a fact about
    the period, not the absence of a shift. The solver treats missing availability
    as *unknown*, not as *available*, which is the safe direction: an employee the
    solver cannot see is left uncovered rather than rostered against their wishes.
    """

    _name = "hrms.roster.availability"
    _description = "Employee availability and preference"
    _order = "date_from"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="cascade", index=True
    )
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    kind = fields.Selection(
        [
            ("available", "Available and willing"),
            ("unavailable", "Unavailable"),
            ("preferred", "Specifically requesting this"),
            ("leave", "On approved leave"),
        ],
        required=True,
        default="unavailable",
        help="preferred = explicitly asking for this shift, which the solver "
        "honours last, after cover and hard constraints.",
    )
    note = fields.Char()
    source = fields.Selection(
        [
            ("employee", "Stated by the employee"),
            ("manager", "Stated by the manager"),
            ("leave", "Derived from approved leave"),
            ("contract", "Derived from the contract"),
        ],
        default="employee",
        required=True,
    )
    source_leave_id = fields.Many2one("hr.leave", ondelete="set null")
    shift_id = fields.Many2one(
        "hr.roster.shift",
        ondelete="set null",
        help="For a preference: the shift being asked for. Blank means any shift.",
    )

    @api.depends("employee_id", "date_from", "date_to", "kind")
    def _compute_name(self):
        for rec in self:
            rec.name = (
                f"{rec.employee_id.name} {rec.date_from} to {rec.date_to} "
                f"({rec.kind})"
            )

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for rec in self:
            if rec.date_to < rec.date_from:
                raise UserError(f"{rec.name}: end date precedes start date.")

    @api.model
    def sync_from_approved_leave(self, leave):
        """Mirror approved leave as unavailability.

        Called when leave is validated so the solver never proposes to roster
        somebody who is on approved leave. Done as a mirror rather than a live
        join so the roster shows what the solver knew, and when.
        """
        if leave.state != "validate":
            return self.browse()
        return self.create(
            [
                {
                    "company_id": leave.employee_id.company_id.id,
                    "employee_id": leave.employee_id.id,
                    "date_from": leave.date_from,
                    "date_to": leave.date_to,
                    "kind": "leave",
                    "source": "leave",
                    "source_leave_id": leave.id,
                    "note": f"Approved leave {leave.holiday_status_id.name or ''}".strip(),
                }
                for leave in leave
            ]
        )


class SolverResult(models.Model):
    """The solver's proposal, retained so it can be reviewed and compared."""

    _name = "hrms.roster.solver.result"
    _description = "Roster solver proposal"
    _order = "id desc"

    name = fields.Char(compute="_compute_name", store=True)
    roster_period_id = fields.Many2one(
        "hr.roster.period", required=True, ondelete="cascade", index=True
    )
    establishment_id = fields.Many2one("hr.department", required=True, index=True)
    setting_id = fields.Many2one("hrms.roster.solver.setting", ondelete="set null")
    created_by_id = fields.Many2one("res.users", ondelete="restrict", default=lambda self: self.env.user)
    created_at = fields.Datetime(default=fields.Datetime.now, readonly=True)

    proposal_json = fields.Text(required=True)
    unfilled_json = fields.Text(
        required=True,
        help="Demand the solver could not cover, with the reason for each: no "
        "available employee, a hard constraint, or a missing availability record. "
        "A solver result without this is not reviewable.",
    )
    stats_json = fields.Text()

    applied = fields.Boolean(readonly=True, copy=False)
    applied_at = fields.Datetime(readonly=True, copy=False)
    applied_by_id = fields.Many2one("res.users", readonly=True, copy=False, ondelete="restrict")
    assignment_count = fields.Integer(compute="_compute_assignment_count", store=True)

    @api.depends("roster_period_id", "establishment_id", "created_at")
    def _compute_name(self):
        for rec in self:
            rec.name = f"Solver {rec.created_at} - {rec.establishment_id.name}"

    @api.depends("roster_period_id", "applied")
    def _compute_assignment_count(self):
        periods = self.mapped("roster_period_id")
        counts = dict(
            self.env["hr.roster.assignment"]._read_group(
                [("roster_period_id", "in", periods.ids)],
                groupby=["roster_period_id"],
                aggregates=["__count"],
            )
        ) if periods else {}
        for rec in self:
            rec.assignment_count = counts.get(rec.roster_period_id.id, 0)

    def action_apply(self):
        """Write the proposal as draft assignments.

        Draft, never confirmed or published: the manager who runs the solver
        must still look at it. Auto-confirming would make the published roster
        something nobody read.
        """
        for rec in self:
            if rec.applied:
                raise UserError(f"{rec.name}: already applied.")
            period = rec.roster_period_id
            if period.state != "draft":
                raise UserError(
                    f"{rec.name}: roster period '{period.name}' is "
                    f"'{period.state}'. Only a draft period can be filled by the "
                    "solver."
                )
            unfilled = json.loads(rec.unfilled_json or "[]")
            if unfilled:
                raise UserError(
                    f"{rec.name}: this proposal leaves "
                    f"{sum(u['short_by'] for u in unfilled)} shift(s) uncovered. "
                    "A roster with a gap must be reviewed by a person, not "
                    "applied automatically. Review the unfilled list, adjust the "
                    "pool, then re-run or assign manually."
                )
            rec._action_apply_proposal()
        return True

    def _action_apply_proposal(self):
        self.ensure_one()
        Assignment = self.env["hr.roster.assignment"]
        period = self.roster_period_id
        for item in json.loads(self.proposal_json or "[]"):
            Assignment.create(
                {
                    "company_id": period.company_id.id,
                    "roster_period_id": period.id,
                    "employee_id": item["employee_id"],
                    "contract_id": item.get("contract_id") or False,
                    "shift_id": item["shift_id"],
                    "start_datetime": item["start_datetime"],
                    "end_datetime": item["end_datetime"],
                    "state": "draft",
                    "note": item.get("reason", "solver proposal"),
                }
            )
        self.write(
            {
                "applied": True,
                "applied_at": fields.Datetime.now(),
                "applied_by_id": self.env.user,
            }
        )
        self.env["hrms.audit.log"].log(
            self._name, self.id, "create",
            note=f"Solver proposal applied to {period.name} as draft assignments",
        )
        return True


class RosterSolver(models.AbstractModel):
    _name = "hrms.roster.solver"
    _description = "Roster solver"

    # ─── Entry point ────────────────────────────────────────────────────
    @api.model
    def solve(self, roster_period, setting=None):
        """Return a persisted proposal. Never writes assignments."""
        if not roster_period._name == "hr.roster.period":
            raise UserError("solve() expects an hr.roster.period")
        if roster_period.state != "draft":
            raise UserError(
                f"'{roster_period.name}' is '{roster_period.state}'. Solve only "
                "against a draft period: a published roster is an obligation, not "
                "a proposal."
            )
        setting = setting or self.env["hrms.roster.solver.setting"].search(
            [("establishment_id", "=", roster_period.establishment_id.id),
             ("active", "=", True)],
            limit=1,
        )
        if not setting:
            raise UserError(
                f"No solver settings for establishment "
                f"'{roster_period.establishment_id.name}'. Weekly day limits, rest "
                "windows and hour ceilings come from the establishment's own "
                "contract and standing orders, so they must be configured rather "
                "than assumed."
            )

        plan = _RosterPlan(self, roster_period, setting)
        plan.load_pool()
        plan.load_availability()
        plan.solve_all_days()

        unfilled = plan.unfilled()
        proposal = plan.proposal()
        stats = plan.stats()
        result = self.env["hrms.roster.solver.result"].create(
            {
                "roster_period_id": roster_period.id,
                "establishment_id": roster_period.establishment_id.id,
                "setting_id": setting.id,
                "proposal_json": _json(proposal),
                "unfilled_json": _json(unfilled),
                "stats_json": _json(stats),
            }
        )
        _logger.info(
            "hrms_roster: solved %s: %d assignment(s) proposed, %d unfilled",
            roster_period.name, len(proposal), sum(u["short_by"] for u in unfilled),
        )
        return result


class _RosterPlan:
    """The working state of one solve. Plain object, no ORM state."""

    def __init__(self, solver, period, setting):
        self.solver = solver
        self.env = solver.env
        self.period = period
        self.setting = setting
        self.pool = []                 # dicts of candidate employees
        self.unavailable = defaultdict(list)   # employee_id -> [(from, to, kind)]
        self.preference = defaultdict(list)    # employee_id -> [(from, to, shift_id)]
        # existing state
        self.assigned = defaultdict(list)      # employee_id -> [item]
        self.week_days = defaultdict(set)      # (employee_id, iso_year, iso_week) -> set(weekday)
        self.week_hours = defaultdict(float)
        self.day_count = defaultdict(int)      # employee_id -> unbroken run of rostered days
        self.last_end = {}                     # employee_id -> datetime the last shift ended
        self.last_day = {}                     # employee_id -> date of the last rostered day
        self.existing_count = 0
        self.proposed = []
        self.gaps = []

    # ─── Load ───────────────────────────────────────────────────────────
    def load_pool(self):
        Employee = self.env["hr.employee"].sudo()
        domain = [
            ("company_id", "=", self.period.company_id.id),
            ("hrms_separation_state", "in", ("none", "resignation_pending")),
            "|",
            ("join_date", "<=", self.period.date_to),
            ("join_date", "=", False),
        ]
        if self.period.establishment_id:
            domain += [
                "|",
                ("hrms_establishment_id", "=", self.period.establishment_id.id),
                ("department_id", "=", self.period.establishment_id.id),
            ]
        for employee in Employee.search(domain):
            contract = employee.contract_id
            if not contract or not contract.wage:
                _logger.info(
                    "hrms_roster: excluding %s from the solver pool: no contract wage",
                    employee.name,
                )
                continue
            if employee.hrms_last_working_day and employee.hrms_last_working_day <= self.period.date_to:
                _logger.info(
                    "hrms_roster: excluding %s: last working day %s is inside the period",
                    employee.name, employee.hrms_last_working_day,
                )
                continue
            self.pool.append(
                {
                    "employee_id": employee.id,
                    "name": employee.name,
                    "contract_id": contract.id,
                    "hourly_rate": float(contract.wage) / 208.0,
                    "skills": set(employee.skill_ids.ids),
                    "shift_credits": defaultdict(int),
                }
            )
        if not self.pool:
            raise UserError(
                f"'{self.period.name}': no rosterable employees. Every employee in "
                "the establishment is either outside its dates, already separated, "
                "or has no contract wage."
            )

    def load_availability(self):
        avail = self.env["hrms.roster.availability"].sudo().search(
            [
                ("company_id", "=", self.period.company_id.id),
                ("employee_id", "in", [p["employee_id"] for p in self.pool]),
                ("date_from", "<=", self.period.date_to),
                ("date_to", ">=", self.period.date_from),
            ]
        )
        for rec in avail:
            window = (rec.date_from, rec.date_to)
            if rec.kind in ("unavailable", "leave"):
                self.unavailable[rec.employee_id.id].append((window, rec.kind))
            elif rec.kind == "preferred":
                self.preference[rec.employee_id.id].append((window, rec.shift_id.id))

        existing = self.env["hr.roster.assignment"].sudo().search(
            [
                ("roster_period_id", "=", self.period.id),
                ("state", "in", ("confirmed", "published", "relieved")),
            ]
        )
        for a in existing:
            item = {
                "assignment_id": a.id,
                "employee_id": a.employee_id.id,
                "shift_id": a.shift_id.id,
                "start": a.start_datetime,
                "end": a.end_datetime,
                "hours": a.paid_hours,
                "existing": True,
            }
            self.assigned[a.employee_id.id].append(item)
            self._account(item)
            self.existing_count += 1

    # ─── Constraints ────────────────────────────────────────────────────
    def _account(self, item):
        """Fold one assignment into the rolling constraint counters."""
        emp = item["employee_id"]
        start = item["start"]
        iso = start.isocalendar()
        self.week_days[(emp, iso[0], iso[1])].add(start.weekday())
        self.week_hours[(emp, iso[0], iso[1])] += item["hours"]
        self.last_end[emp] = item["end"]
        day = start.date()
        # A day off breaks the run. Counting consecutive *assigned* days rather
        # than consecutive calendar days is what makes max_consecutive_days a
        # fatigue limit rather than a rest-day scheduler.
        if self.last_day.get(emp) == day - timedelta(days=1):
            self.day_count[emp] += 1
        else:
            self.day_count[emp] = 1
        self.last_day[emp] = day

    def _hard_block(self, candidate, shift, day):
        """Return a reason string if this assignment must not be made, else None."""
        emp = candidate["employee_id"]
        setting = self.setting

        # Unavailability, including mirrored leave.
        for (start, end), kind in self.unavailable.get(emp, []):
            if start <= day <= end:
                if kind == "leave":
                    return f"on approved leave ({start} to {end})"
                return f"declared unavailable ({start} to {end})"

        # Overlap with an existing or already-proposed assignment.
        for item in self.assigned.get(emp, []):
            if item["start"].date() == day or (
                shift.overnight and (item["start"].date() == day - timedelta(days=1))
            ):
                return f"already assigned {item['start']:%d %b %H:%M}-{item['end']:%H:%M}"

        # Rest window.
        floor = setting.min_rest_hours_between_shifts
        last = self.last_end.get(emp)
        if last:
            gap = (day_start(shift, day) - last).total_seconds() / 3600.0
            if gap < max(floor, shift.rest_after_hours or 0):
                return f"only {gap:.1f}h rest since the previous shift ends {last:%d %b %H:%M}"

        iso = day.isocalendar()
        key = (emp, iso[0], iso[1])
        if day.weekday() not in self.week_days[key] and \
                len(self.week_days[key]) >= setting.max_days_per_week:
            return f"already rostered {len(self.week_days[key])} day(s) this ISO week (max {setting.max_days_per_week})"

        projected = self.week_hours[key] + (shift.duration_hours or 0)
        if projected > setting.max_weekly_hours:
            return f"would reach {projected:.1f}h this ISO week (contractual max {setting.max_weekly_hours:.1f}h)"

        if self.day_count[emp] + 1 > setting.max_consecutive_days:
            return f"would be {self.day_count[emp] + 1} consecutive days (max {setting.max_consecutive_days})"
        return None

    def _rank(self, candidate, shift, demand, day):
        """Ordering key. Lower sorts first. Hard constraints are already applied."""
        emp = candidate["employee_id"]
        iso_key = None
        skill_rank = 0
        if self.setting.prefer_skill_match and demand.required_skill_ids:
            overlap = candidate["skills"] & set(demand.required_skill_ids.ids)
            # Most specific match: an exact single-skill match beats a broad one.
            skill_rank = -len(overlap) if overlap else 10_000
        preference_rank = 10_000
        if self.setting.honour_preferences:
            for (start, end), shift_id in self.preference.get(emp, []):
                if start <= day <= end and (
                    not shift_id or shift_id == shift.id
                ):
                    preference_rank = 0
                    break
        night_rank = 0
        if self.setting.night_shift_rotation and shift.is_night_shift:
            night_rank = candidate["shift_credits"][shift.id]
        load_rank = len(self.assigned.get(emp, []))
        return (night_rank, skill_rank, preference_rank, load_rank, emp)

    # ─── Solve ──────────────────────────────────────────────────────────
    def solve_all_days(self):
        Demand = self.env["hr.roster.demand"].sudo()
        Shift = self.env["hr.roster.shift"].sudo()
        demands = Demand.search(
            [
                ("establishment_id", "=", self.period.establishment_id.id),
                ("active", "=", True),
            ]
        )
        if not demands:
            raise UserError(
                f"'{self.period.name}': no staffing demand is configured for "
                f"'{self.period.establishment_id.name}'. The solver fills a "
                "demand curve; with no curve it has nothing to do."
            )
        shifts = {s.id: s for s in Shift.search([("company_id", "=", self.period.company_id.id)])}

        day = self.period.date_from
        while day <= self.period.date_to:
            for demand in demands:
                if int(demand.weekday) != day.weekday():
                    continue
                if demand.shift_id.id not in shifts:
                    continue
                for slot in range(demand.required_headcount):
                    self._fill_one_slot(day, demand, shifts[demand.shift_id.id])
            day += timedelta(days=1)

    def _fill_one_slot(self, day, demand, shift):
        ranked = []
        blockers = defaultdict(int)
        for candidate in self.pool:
            reason = self._hard_block(candidate, shift, day)
            if reason:
                blockers[reason.split("(")[0].strip()] += 1
                continue
            ranked.append((self._rank(candidate, shift, demand, day), candidate))
        if not ranked:
            self.gaps.append(
                {
                    "date": str(day),
                    "shift_id": shift.id,
                    "shift": shift.name,
                    "required": 1,
                    "rostered": 0,
                    "short_by": 1,
                    "reason": "no rosterable employee passed the hard constraints",
                    "blockers": dict(sorted(blockers.items(), key=lambda kv: -kv[1])),
                }
            )
            return
        ranked.sort(key=lambda pair: pair[0])
        _, chosen = ranked[0]
        start = day_start(shift, day)
        end = start + timedelta(hours=span_hours(shift))
        item = {
            "employee_id": chosen["employee_id"],
            "employee": chosen["name"],
            "contract_id": chosen["contract_id"],
            "shift_id": shift.id,
            "shift": shift.name,
            "start_datetime": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_datetime": end.strftime("%Y-%m-%d %H:%M:%S"),
            "paid_hours": shift.duration_hours,
            "reason": _reason_text(ranked[0][0], shift),
        }
        self.proposed.append(item)
        self.assigned[chosen["employee_id"]].append(
            {
                "employee_id": chosen["employee_id"],
                "shift_id": shift.id,
                "start": start,
                "end": end,
                "hours": shift.duration_hours,
            }
        )
        self._account(
            {
                "employee_id": chosen["employee_id"],
                "start": start,
                "end": end,
                "hours": shift.duration_hours,
            }
        )
        chosen["shift_credits"][shift.id] += 1

    # ─── Output ─────────────────────────────────────────────────────────
    def proposal(self):
        return self.proposed

    def unfilled(self):
        """Aggregate per date and shift, with the blockers that caused them."""
        grouped = defaultdict(lambda: {"short_by": 0, "blockers": defaultdict(int)})
        for gap in self.gaps:
            key = (gap["date"], gap["shift_id"])
            grouped[key]["short_by"] += gap["short_by"]
            grouped[key]["short"] = gap["shift"]
            for reason, count in gap.get("blockers", {}).items():
                grouped[key]["blockers"][reason] = max(
                    grouped[key]["blockers"][reason], count
                )
        out = []
        for (day, shift_id), agg in sorted(grouped.items()):
            out.append(
                {
                    "date": day,
                    "shift_id": shift_id,
                    "shift": agg.get("shift", ""),
                    "short_by": agg["short_by"],
                    "reason": "no employee satisfied the hard constraints",
                    "blockers": dict(agg["blockers"]),
                }
            )
        return out

    def stats(self):
        by_employee = defaultdict(lambda: {"days": 0, "hours": 0.0, "nights": 0})
        for item in self.proposed:
            entry = by_employee[item["employee_id"]]
            entry["days"] += 1
            entry["hours"] += item["paid_hours"]
            if item["shift_id"] and "Night" in (item["shift"] or ""):
                entry["nights"] += 1
        return {
            "employees_in_pool": len(self.pool),
            "assignments_proposed": len(self.proposed),
            "existing_assignments": self.existing_count,
            "unfilled_shifts": sum(u["short_by"] for u in self.unfilled()),
            "per_employee": {
                self.pool_name(eid): v for eid, v in sorted(by_employee.items())
            },
        }

    def pool_name(self, employee_id):
        for candidate in self.pool:
            if candidate["employee_id"] == employee_id:
                return candidate["name"]
        return str(employee_id)


def _reason_text(rank, shift):
    night_rank, skill_rank, preference_rank, load_rank, emp = rank
    parts = []
    if night_rank:
        parts.append("rotating night shifts")
    if skill_rank == 0:
        parts.append("exact skill match")
    elif skill_rank < 0:
        parts.append(f"{abs(skill_rank)} skill(s) matched")
    if preference_rank == 0:
        parts.append("employee requested this shift")
    if load_rank:
        parts.append(f"lightest current load ({load_rank} shift(s))")
    return "; ".join(parts) or "only eligible employee"


def span_hours(shift):
    """Span of duty including the paid break, derived from the shift times."""
    span = shift.end_time - shift.start_time
    if shift.overnight:
        span += 24.0
    return max(span, 0.0)


def day_start(shift, day):
    hour = int(shift.start_time)
    minute = int(round((shift.start_time - hour) * 60))
    return datetime.combine(day, time(hour, minute))


def _json(payload):
    return json.dumps(payload, indent=2, sort_keys=True, default=str)

class HrLeaveRosterSync(models.Model):
    """Keep the solver's view of leave current.

    Lives here rather than in hrms_core_ext because hrms_core_ext cannot depend
    on hrms_roster; the dependency runs the other way. Mirroring leave means the
    solver never proposes a shift for somebody who is on approved leave.
    """

    _inherit = "hr.leave"

    def action_validate(self):
        result = super().action_validate()
        self.env["hrms.roster.availability"].sync_from_approved_leave(self)
        return result
