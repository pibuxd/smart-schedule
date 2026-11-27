"""The schedule generator: an OR-Tools CP-SAT model of a `Problem`. Pure Python, no Django; runs only in the worker.

Two phases, as in docs/plan.md section 3:

1. minimise the number of unfilled slots (holes);
2. with that many holes at most, minimise the penalty: manager rules and employee requests weighed by the
   location's weight profile (80 : 20 by default), plus a cost for every changed published assignment.

With `diversity_from` ("Ułóż inaczej", docs/plan.md section 36) a phase runs between them: with no more holes, keep
as few of the earlier schedules' person-shifts beyond the allowed share as possible; the penalty phase then keeps
that difference.

Hard rules (always): one person or a hole per slot, the right position, home location only (borrowing is manual),
no "cannot" days, no overlapping shifts, pinned slots, frozen past days and "no exceptions" rules. There is no
contract type and no built-in labour law: the manager switches on rules from the catalog (docs/spec.md).

The penalty in phase 2 is a linear stand-in for `engine.scoring.penalty`. Most parts are exact (text
requests, hours, closings, days in a row); rules whose score is a share of a varying count (e.g. "rest
between shifts" = broken pairs / all pairs) divide by an estimate of that count instead. The manager always sees
the numbers from the independent validator, never the solver's own objective.

`solve` is meant to be called once per variant; `diversity_from` and `weights` also exist for the later
three-variant mode (70/30, 80/20, 90/10 with at least 15 % different assignments).
"""

from __future__ import annotations

import calendar
import math
import threading
import time as clock
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum

from ortools.sat.python import cp_model

from engine.problem import (
    BEGINNER,
    EXPERIENCED,
    AvailabilityState,
    Employee,
    ExternalShift,
    Problem,
    RequestType,
    RuleConfig,
    Schedule,
    Slot,
    WeightProfile,
    local_datetime,
)
from engine.rules_catalog import RULES_BY_CODE
from engine.validator import (
    PREFERRED_DAYS_SHARE,
    TARGET_HOURS_HARD_TOLERANCE,
    Code,
    RequestKind,
    experience_shifts,
    max_hours_tolerance,
    not_more_than_others_peers,
    validate,
)

# Objective coefficients are points of the 0–100 score times this factor, rounded to integers.
SCALE = 1_000_000
# Share of the time limit for phase 1 (holes); phase 2 gets the rest.
PHASE_1_SHARE = 0.4
# With `diversity_from`: at most this share of the time limit for the phase that makes the schedule different.
DIFFERENCE_SHARE = 0.2
# Time for each quick check that looks for the "no exceptions" rule that makes the problem impossible.
DIAGNOSIS_TIME_S = 2.0
DEFAULT_WORKERS = 8

# Hard violations of a partial schedule that adding more shifts can never repair. If the fixed part (pins and
# past days) already has one of these, there is no point in solving.
_MONOTONE_RULES = frozenset(
    {
        "min_rest_between_shifts",
        "max_consecutive_days",
        "preferred_shift_type_for_position",
        "same_shift_type_in_week",
        "max_shifts_per_week",
        "personal_max_hours",
        "max_hours_per_day",
        "min_weekly_rest",
    }
)
_MONOTONE_CODES = frozenset({Code.POSITION, Code.CANNOT, Code.OVERLAP, Code.EXPERIENCE, Code.ONE_SHIFT})


class SolveStatus(StrEnum):
    OPTIMAL = "optimal"  # both phases proved optimal
    FEASIBLE = "feasible"  # the best schedule found within the time limit
    TIMEOUT_NO_SOLUTION = "timeout_no_solution"
    INFEASIBLE = "infeasible"  # pins, past days or "no exceptions" rules cannot all be kept
    STOPPED = "stopped"  # the caller asked to stop (`should_stop`); no schedule is returned


@dataclass(frozen=True)
class SolveResult:
    status: SolveStatus
    schedule: Mapping[str, str | None] | None  # slot id -> employee id or None (hole); None without a solution
    holes: int | None = None
    objective: float | None = None  # the solver's own penalty estimate in points (not shown to the manager)
    time_ms: int = 0
    # Polish sentences for the manager when there is no schedule (why it is impossible / what to change).
    messages: tuple[str, ...] = ()

    @property
    def has_schedule(self) -> bool:
        return self.schedule is not None


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _seconds(slot: Slot) -> int:
    return round((slot.end_utc - slot.start_utc).total_seconds())


def _minutes(slot: Slot) -> int:
    """Hours rules count in minutes: exact for shift times on the minute, and coarse enough for the objective."""
    return round(_seconds(slot) / 60)


@dataclass(frozen=True)
class _Interval:
    """All candidate slots of one employee with the same start and end; at most one of them can be worked."""

    start: datetime  # UTC
    end: datetime  # UTC
    slots: tuple[Slot, ...]


class _Builder:
    def __init__(
        self,
        problem: Problem,
        *,
        relaxed_rules: frozenset[tuple[str, str]] = frozenset(),
        diversity_from: Sequence[Schedule] = (),
        min_difference: float = 0.15,
    ) -> None:
        self.p = problem
        self.m = cp_model.CpModel()
        # (location, rule code) of "no exceptions" rules treated as switched off (infeasibility diagnosis only).
        self.relaxed = relaxed_rules
        self.penalty: list[tuple[int, cp_model.LinearExprT]] = []
        self.x: dict[tuple[str, str], cp_model.IntVar] = {}
        self.x_of_slot: dict[str, list[tuple[str, cp_model.IntVar]]] = defaultdict(list)
        self.x_of_emp: dict[str, list[tuple[Slot, cp_model.IntVar]]] = defaultdict(list)
        self.u: dict[str, cp_model.IntVar] = {}
        # Person-shifts kept from each earlier schedule beyond the allowed share (`diversity_from`).
        self.shortfall: list[cp_model.IntVar] = []
        self._own_day: dict[tuple[str, date], cp_model.IntVar] = {}
        self._worked_any: dict[str, cp_model.IntVar] = {}

        self.fixed = self._fixed_assignments()
        self.externals = defaultdict(list)
        for ext in problem.external_shifts:
            self.externals[ext.employee].append(ext)
        self.baseline = validate(problem, {})  # schedule-independent request weights
        self.share = problem.weights.manager_share
        self.instruction_points = 0.0  # set by _rule_points: points per unit of a manager instruction's weight
        self.rule_points = self._rule_points()
        request_total = sum(r.weight for r in self.baseline.requests if not r.by_manager)
        self.request_points = (1 - self.share) * 100 / request_total if request_total else 0.0

        self._variables()
        self._intervals = {e.id: self._group_intervals(e.id) for e in problem.employees}
        self._no_overlap()
        self._one_shift()
        self._experienced()
        self._rules()
        self._requests()
        self._stability()
        for previous in diversity_from:
            self._diversity(previous, min_difference)

    # ----------------------------------------------------------------- setup

    def _fixed_assignments(self) -> dict[str, str | None]:
        """Slots whose person is decided before solving: frozen past days (published value) and pins."""
        return _fixed(self.p)

    def _eligible(self, employee: Employee, slot: Slot) -> bool:
        if not employee.available or not employee.works_in(slot.location) or slot.position not in employee.positions:
            return False
        if self.p.availability_for(employee.id, slot) == AvailabilityState.CANNOT:
            return False
        return not any(
            e.start_utc < slot.end_utc and slot.start_utc < e.end_utc for e in self.externals.get(employee.id, ())
        )

    def _variables(self) -> None:
        p, m = self.p, self.m
        for slot in p.slots:
            self.u[slot.id] = m.new_bool_var(f"hole[{slot.id}]")
            if slot.id in self.fixed:
                chosen = self.fixed[slot.id]
                if chosen is None:
                    m.add(self.u[slot.id] == 1)
                else:
                    self._add_x(chosen, slot, fixed=True)
                continue
            for employee in p.employees:
                if self._eligible(employee, slot):
                    self._add_x(employee.id, slot)
        for slot in p.slots:
            m.add(sum(v for _, v in self.x_of_slot[slot.id]) + self.u[slot.id] == 1)

    def _add_x(self, employee_id: str, slot: Slot, fixed: bool = False) -> None:
        var = self.m.new_bool_var(f"x[{employee_id},{slot.id}]")
        if fixed:
            self.m.add(var == 1)
        self.x[(employee_id, slot.id)] = var
        self.x_of_slot[slot.id].append((employee_id, var))
        self.x_of_emp[employee_id].append((slot, var))

    def _experienced(self) -> None:
        """Staffing "of these, N experienced": less experienced people get at most the remaining places
        (the validator's `check_experienced`). Never infeasible on its own: a place can stay unfilled."""
        for slots in self.p.experienced_groups:
            need = sum(1 for s in slots if s.needs_experienced)
            others = [
                var
                for slot in slots
                for employee_id, var in self.x_of_slot[slot.id]
                if self.p.employee_by_id[employee_id].level(slot.position) != EXPERIENCED
            ]
            if others:
                self.m.add(sum(others) <= len(slots) - need)

    def _group_intervals(self, employee_id: str) -> list[_Interval]:
        groups: dict[tuple[datetime, datetime], list[Slot]] = defaultdict(list)
        for slot, _ in self.x_of_emp.get(employee_id, ()):
            groups[(slot.start_utc, slot.end_utc)].append(slot)
        return [_Interval(s, e, tuple(slots)) for (s, e), slots in sorted(groups.items())]

    def work(self, employee_id: str, interval: _Interval) -> cp_model.LinearExprT:
        return sum(self.x[(employee_id, s.id)] for s in interval.slots)

    def own_day(self, employee_id: str, day: date) -> cp_model.IntVar | int:
        """1 when the employee works a slot of this problem starting that day."""
        key = (employee_id, day)
        if key not in self._own_day:
            vars_ = [v for s, v in self.x_of_emp.get(employee_id, ()) if s.date == day]
            self._own_day[key] = self._or(vars_, f"day[{employee_id},{day}]") if vars_ else 0
        return self._own_day[key]

    def worked_any(self, employee_id: str) -> cp_model.IntVar | int:
        if employee_id not in self._worked_any:
            vars_ = [v for _, v in self.x_of_emp.get(employee_id, ())]
            self._worked_any[employee_id] = self._or(vars_, f"active[{employee_id}]") if vars_ else 0
        return self._worked_any[employee_id]

    def _or(self, variables: Sequence[cp_model.IntVar], name: str) -> cp_model.IntVar:
        if len(variables) == 1:
            return variables[0]
        result = self.m.new_bool_var(name)
        self.m.add_max_equality(result, list(variables))
        return result

    def add_penalty(self, points: float, expr: cp_model.LinearExprT) -> None:
        """`points` (on the 0–100 scale) for every unit of `expr`; negative points reward it."""
        if points == 0:
            return
        coef = round(points * SCALE)
        if coef == 0:
            coef = 1 if points > 0 else -1
        self.penalty.append((coef, expr))

    # ----------------------------------------------------------------- always-hard rules

    def _no_overlap(self) -> None:
        for employee_id, intervals in self._intervals.items():
            self._cliques(employee_id, intervals, timedelta(0))

    def _one_shift(self) -> None:
        """Days marked "albo": at most one shift that day (shifts already outside this problem count too)."""
        for entry in self.p.one_shift_days():
            day = [var for slot, var in self.x_of_emp.get(entry.employee, ()) if slot.date == entry.date]
            if not day:
                continue
            outside = sum(1 for e in self.p.external_shifts if e.employee == entry.employee and e.date == entry.date)
            self.m.add(sum(day) <= max(0, 1 - outside))

    def _cliques(self, employee_id: str, intervals: list[_Interval], rest: timedelta) -> None:
        """At most one interval worked among those whose [start, end + rest) contain a common start point.
        Two intervals conflict exactly when they overlap or the gap between them is shorter than `rest`."""
        for point in intervals:
            members = [i for i in intervals if i.start <= point.start < i.end + rest]
            if sum(len(i.slots) for i in members) > 1:
                self.m.add(sum(self.work(employee_id, i) for i in members) <= 1)

    def _rest(self, employee_id: str, intervals: list[_Interval], need: timedelta, *, hard: bool) -> list:
        """Hard: forbid shifts closer than `need`. Soft: return (penalty unit) terms for each too-short gap."""
        terms: list[cp_model.LinearExprT] = []
        externals = self.externals.get(employee_id, ())
        for interval in intervals:
            for ext in externals:
                gap = max(interval.start - ext.end_utc, ext.start_utc - interval.end)
                if timedelta(0) <= gap < need:
                    if hard:
                        self.m.add(self.work(employee_id, interval) == 0)
                    else:
                        terms.append(self.work(employee_id, interval))
        if hard:
            self._cliques(employee_id, intervals, need)
            return terms
        for i, first in enumerate(intervals):
            for second in intervals[i + 1 :]:
                gap = second.start - first.end
                if second.start >= first.end + need:
                    break
                if gap < timedelta(0):
                    continue  # overlapping: never both worked
                pair = self.m.new_bool_var(f"rest[{employee_id}]")
                self.m.add(pair >= self.work(employee_id, first) + self.work(employee_id, second) - 1)
                terms.append(pair)
        return terms

    # ----------------------------------------------------------------- catalog rules

    def _rule_points(self) -> dict[tuple[str, str], float]:
        """Points of the 0–100 score per unit of degree for every soft rule (same weights as scoring)."""
        weights: dict[tuple[str, str], float] = {}
        for location in self.p.locations:
            soft = [r for r in self.p.rules_for(location) if not r.hard]
            for place, rule in enumerate(soft, start=1):
                weights[(location, rule.code)] = self.p.weights.rule_weight(place)
        total = sum(weights.values()) + sum(r.weight for r in self.baseline.requests if r.by_manager)
        if not total:
            return {}
        self.instruction_points = self.share * 100 / total
        return {key: self.share * 100 * w / total for key, w in weights.items()}

    def employees_of(self, location: str) -> list[Employee]:
        """Everyone who works in the location: as their main location or an extra one (as in the validator)."""
        return [e for e in self.p.employees if e.works_in(location)]

    def slots_of(self, location: str) -> list[Slot]:
        return [s for s in self.p.slots if s.location == location]

    def _per_person_estimate(self, location: str) -> float:
        """How many shifts one person of the location gets on average (to turn counts into shares)."""
        people = [e for e in self.employees_of(location) if self.x_of_emp.get(e.id)]
        return max(1.0, len(self.slots_of(location)) / max(1, len(people)))

    def _rules(self) -> None:
        for location in self.p.locations:
            for rule in self.p.rules_for(location):
                hard = rule.hard and (location, rule.code) not in self.relaxed
                if rule.hard and not hard:
                    continue  # relaxed for diagnosis: switched off
                points = 0.0 if hard else self.rule_points.get((location, rule.code), 0.0)
                getattr(self, f"_rule_{rule.code}")(rule, hard, points)

    def _rule_min_rest_between_shifts(self, rule: RuleConfig, hard: bool, points: float) -> None:
        need = timedelta(hours=float(rule.params["hours"]))
        estimate = max(1, len(self.slots_of(rule.location)))
        for employee in self.employees_of(rule.location):
            terms = self._rest(employee.id, self._intervals[employee.id], need, hard=hard)
            for term in terms:
                self.add_penalty(points / estimate, term)

    def _rule_max_consecutive_days(self, rule: RuleConfig, hard: bool, points: float) -> None:
        limit = int(rule.params["days"])
        estimate = max(1, len(self.slots_of(rule.location)))
        for employee in self.employees_of(rule.location):
            own_days = sorted({s.date for s, _ in self.x_of_emp.get(employee.id, ())})
            if not own_days:
                continue
            external_days = {e.date for e in self.externals.get(employee.id, ())}

            def worked(day: date, employee_id: str = employee.id, external: set = external_days):
                return 1 if day in external else self.own_day(employee_id, day)

            for day in own_days:
                window = sum(worked(day - timedelta(days=k)) for k in range(1, limit + 1))
                own = self.own_day(employee.id, day)
                if hard:
                    self.m.add(window + own <= limit)
                else:
                    broken = self.m.new_bool_var(f"run[{employee.id},{day}]")
                    self.m.add(broken >= window + own - limit)
                    self.add_penalty(points / estimate, broken)

    def _fairness(self, rule: RuleConfig, hard: bool, points: float, counted) -> None:
        by_position: dict[str, list[Slot]] = defaultdict(list)
        for slot in self.slots_of(rule.location):
            if counted(slot):
                by_position[slot.position].append(slot)
        total = sum(len(slots) for slots in by_position.values())
        for position, slots in sorted(by_position.items()):
            people = [
                e for e in self.employees_of(rule.location) if position in e.positions and self.x_of_emp.get(e.id)
            ]
            if len(people) < 2:
                continue
            ids = {s.id for s in slots}
            dates = sorted({s.date for s in slots})
            high = self.m.new_int_var(0, len(dates), f"high[{rule.code},{position}]")
            low = self.m.new_int_var(0, len(dates), f"low[{rule.code},{position}]")
            for employee in people:
                per_day: dict[date, list[cp_model.IntVar]] = defaultdict(list)
                for slot, var in self.x_of_emp[employee.id]:
                    if slot.id in ids:
                        per_day[slot.date].append(var)
                load = sum(self._or(v, f"load[{employee.id},{d}]") for d, v in per_day.items())
                self.m.add(high >= load)
                self.m.add(low <= load + len(dates) * (1 - self.worked_any(employee.id)))
            if hard:
                self.m.add(high - low <= 1)
            else:
                # The validator's degree is excess / highest load; kept exact (in thousandths) with a division.
                excess = self.m.new_int_var(0, len(dates), f"excess[{rule.code},{position}]")
                self.m.add(excess >= high - low - 1)
                divisor = self.m.new_int_var(1, max(1, len(dates)), f"divisor[{rule.code},{position}]")
                self.m.add_max_equality(divisor, [high, 1])
                degree = self.m.new_int_var(0, 1000, f"unfair[{rule.code},{position}]")
                self.m.add_division_equality(degree, excess * 1000, divisor)
                self.add_penalty(points * len(slots) / total / 1000, degree)

    def _rule_fair_weekends(self, rule: RuleConfig, hard: bool, points: float) -> None:
        self._fairness(rule, hard, points, lambda s: s.date.weekday() >= 5)

    def _rule_fair_closings(self, rule: RuleConfig, hard: bool, points: float) -> None:
        self._fairness(rule, hard, points, lambda s: s.is_closing)

    def _month_shares(self) -> dict[tuple[int, int], float]:
        covered: dict[tuple[int, int], int] = defaultdict(int)
        day = self.p.period_start
        while day <= self.p.period_end:
            covered[(day.year, day.month)] += 1
            day += timedelta(days=1)
        return {(y, m): n / calendar.monthrange(y, m)[1] for (y, m), n in covered.items()}

    def _monthly_hours(self, rule: RuleConfig, hard: bool, points: float, attr: str) -> None:
        shares = self._month_shares()
        people = [e for e in self.employees_of(rule.location) if getattr(e, attr) is not None]
        if attr == "target_hours_month":  # as in the validator: the target only in the main location
            people = [e for e in people if e.home_location == rule.location]
        for employee in people:
            monthly = float(getattr(employee, attr))
            elsewhere = self.p.minutes_elsewhere(employee.id, self.p.period_start, self.p.period_end)
            expected = sum(monthly * share * 60 for share in shares.values())
            per_month: dict[tuple[int, int], list] = defaultdict(list)
            for slot, var in self.x_of_emp.get(employee.id, ()):
                per_month[(slot.date.year, slot.date.month)].append(_minutes(slot) * var)
            top = sum(_minutes(s) for s, _ in self.x_of_emp.get(employee.id, ())) + 1
            measures = []
            for month, share in shares.items():
                hours = sum(per_month.get(month, []))
                bound = monthly * share * 60
                if attr == "max_hours_month":
                    bound *= 1 + max_hours_tolerance(rule)
                bound = max(0.0, bound - elsewhere.get(month, 0))  # minutes already worked in other locations
                if attr == "max_hours_month":
                    if hard:
                        if per_month.get(month):
                            self.m.add(hours <= math.floor(bound))
                        continue
                    over = self.m.new_int_var(0, top, f"over[{employee.id},{month}]")
                    self.m.add(over >= hours - round(bound))
                    measures.append(over)
                else:
                    dev = self.m.new_int_var(0, top + round(bound), f"dev[{employee.id},{month}]")
                    self.m.add(dev >= hours - round(bound))
                    self.m.add(dev >= round(bound) - hours)
                    measures.append(dev)
            if not measures:
                continue
            if hard:  # target hours "no exceptions": within 10 % (minus a minute per month for rounding)
                self.m.add(sum(measures) <= math.floor(TARGET_HOURS_HARD_TOLERANCE * expected) - len(measures))
                continue
            if expected <= 0:
                self.add_penalty(points / len(people), self.worked_any(employee.id))
                continue
            capped = self.m.new_int_var(0, math.ceil(expected), f"capped[{employee.id},{attr}]")
            self.m.add_min_equality(capped, [sum(measures), math.ceil(expected)])
            self.add_penalty(points / len(people) / expected, capped)

    def _rule_target_hours(self, rule: RuleConfig, hard: bool, points: float) -> None:
        self._monthly_hours(rule, hard, points, "target_hours_month")

    def _rule_personal_max_hours(self, rule: RuleConfig, hard: bool, points: float) -> None:
        self._monthly_hours(rule, hard, points, "max_hours_month")

    def _rule_preferred_shift_type_for_position(self, rule: RuleConfig, hard: bool, points: float) -> None:
        position, shift_type = rule.params.get("position"), rule.params.get("shift_type")
        if not position or not shift_type:
            return
        slots = [s for s in self.slots_of(rule.location) if s.position == position]
        for slot in slots:
            if slot.shift_type == shift_type:
                continue
            for _, var in self.x_of_slot[slot.id]:
                if hard:
                    self.m.add(var == 0)
                else:
                    self.add_penalty(points / len(slots), var)

    def _rule_min_position_on_closing(self, rule: RuleConfig, hard: bool, points: float) -> None:
        position = rule.params.get("position")
        if not position:
            return
        need = int(rule.params.get("count") or 1)
        closings: dict[tuple[date, str], list[Slot]] = defaultdict(list)
        for slot in self.slots_of(rule.location):
            if slot.is_closing:
                closings[(slot.date, slot.shift_type)].append(slot)
        for key, slots in closings.items():
            by_person: dict[str, list[cp_model.IntVar]] = defaultdict(list)
            for slot in slots:
                for employee_id, var in self.x_of_slot[slot.id]:
                    if position in self.p.employee_by_id[employee_id].positions:
                        by_person[employee_id].append(var)
            have = self.m.new_int_var(0, len(by_person), f"closers[{key[0]},{key[1]}]")
            self.m.add(have == sum(self._or(v, f"closer[{e},{key[0]}]") for e, v in by_person.items()))
            if hard:
                self.m.add(have >= need)
            else:
                missing = self.m.new_bool_var(f"no_closer[{key[0]},{key[1]}]")
                self.m.add(need * missing >= need - have)
                self.add_penalty(points / len(closings), missing)

    def _rule_experience_mix(self, rule: RuleConfig, hard: bool, points: float) -> None:
        shifts = experience_shifts(self.p, rule)
        for (day, shift_type), slots in shifts.items():
            # One person works at most one slot of a shift (no overlap), so summing the slot variables counts people.
            beginners, experienced = [], []
            for slot in slots:
                for employee_id, var in self.x_of_slot[slot.id]:
                    level = self.p.employee_by_id[employee_id].level(slot.position)
                    if level == BEGINNER:
                        beginners.append(var)
                    elif level == EXPERIENCED:
                        experienced.append(var)
            if not beginners:
                continue
            if hard:
                self.m.add(sum(beginners) <= sum(experienced))
            else:
                broken = self.m.new_bool_var(f"green[{day},{shift_type}]")
                self.m.add(sum(beginners) - sum(experienced) <= len(slots) * broken)
                self.add_penalty(points / len(shifts), broken)

    def _weeks_of(self, employee_id: str) -> dict[date, list[tuple[Slot, cp_model.IntVar]]]:
        weeks: dict[date, list[tuple[Slot, cp_model.IntVar]]] = defaultdict(list)
        for slot, var in self.x_of_emp.get(employee_id, ()):
            weeks[_week_start(slot.date)].append((slot, var))
        return weeks

    def _week_estimate(self, location: str) -> int:
        weeks = {_week_start(s.date) for s in self.slots_of(location)}
        people = [e for e in self.employees_of(location) if self.x_of_emp.get(e.id)]
        return max(1, len(weeks) * len(people))

    def _rule_same_shift_type_in_week(self, rule: RuleConfig, hard: bool, points: float) -> None:
        estimate = self._week_estimate(rule.location)
        for employee in self.employees_of(rule.location):
            for monday, items in self._weeks_of(employee.id).items():
                by_type: dict[str, list[cp_model.IntVar]] = defaultdict(list)
                for slot, var in items:
                    by_type[slot.shift_type].append(var)
                if len(by_type) < 2:
                    continue
                used = [self._or(v, f"type[{employee.id},{monday},{t}]") for t, v in by_type.items()]
                if hard:
                    self.m.add(sum(used) <= 1)
                else:
                    mixed = self.m.new_bool_var(f"mixed[{employee.id},{monday}]")
                    self.m.add((len(used) - 1) * mixed >= sum(used) - 1)
                    self.add_penalty(points / estimate, mixed)

    def _rule_max_shifts_per_week(self, rule: RuleConfig, hard: bool, points: float) -> None:
        limit = int(rule.params["shifts"])
        estimate = self._week_estimate(rule.location)
        for employee in self.employees_of(rule.location):
            for monday, items in self._weeks_of(employee.id).items():
                if len(items) <= limit:
                    continue
                count = sum(v for _, v in items)
                if hard:
                    self.m.add(count <= limit)
                else:
                    over = self.m.new_bool_var(f"many[{employee.id},{monday}]")
                    self.m.add((len(items) - limit) * over >= count - limit)
                    self.add_penalty(points / estimate, over)

    def _rule_max_hours_per_day(self, rule: RuleConfig, hard: bool, points: float) -> None:
        limit = round(float(rule.params["max_hours"]) * 60)
        estimate = max(1, len(self.slots_of(rule.location)))
        for employee in self.employees_of(rule.location):
            external: dict[date, int] = defaultdict(int)
            for ext in self.externals.get(employee.id, ()):
                external[ext.date] += round((ext.end_utc - ext.start_utc).total_seconds() / 60)
            by_day: dict[date, list[tuple[Slot, cp_model.IntVar]]] = defaultdict(list)
            for slot, var in self.x_of_emp.get(employee.id, ()):
                by_day[slot.date].append((slot, var))
            for day, items in sorted(by_day.items()):
                total = sum(_minutes(s) * v for s, v in items) + external[day]
                most = sum(_minutes(s) for s, _ in items) + external[day]
                if most <= limit:
                    continue
                if hard:
                    self.m.add(total <= limit)
                else:
                    over = self.m.new_bool_var(f"long_day[{employee.id},{day}]")
                    self.m.add((most - limit) * over >= total - limit)
                    self.add_penalty(points / estimate, over)

    def _rule_min_weekly_rest(self, rule: RuleConfig, hard: bool, points: float) -> None:
        """Every week with a shift needs a free window of `rest_hours` inside Monday 00:00 – Monday 00:00."""
        need = timedelta(hours=float(rule.params["rest_hours"]))
        tz = self.p.tz
        estimate = self._week_estimate(rule.location)
        for employee in self.employees_of(rule.location):
            intervals = self._intervals[employee.id]
            externals = self.externals.get(employee.id, ())
            for monday, items in sorted(self._weeks_of(employee.id).items()):
                week_start = local_datetime(monday, time(0), tz).astimezone(UTC)
                week_end = local_datetime(monday + timedelta(days=7), time(0), tz).astimezone(UTC)
                starts = {week_start}
                starts.update(i.end for i in intervals if week_start <= i.end < week_end)
                starts.update(e.end_utc for e in externals if week_start <= e.end_utc < week_end)
                windows = []
                for begin in sorted(starts):
                    finish = begin + need
                    if finish > week_end:
                        continue
                    if any(e.start_utc < finish and begin < e.end_utc for e in externals):
                        continue
                    free = self.m.new_bool_var(f"free[{employee.id},{begin:%Y%m%d%H%M}]")
                    for interval in intervals:
                        if interval.start < finish and begin < interval.end:
                            self.m.add(free + self.work(employee.id, interval) <= 1)
                    windows.append(free)
                if hard:
                    for _, var in items:
                        self.m.add(sum(windows) >= var)
                    continue
                broken = self.m.new_bool_var(f"no_rest[{employee.id},{monday}]")
                for _, var in items:
                    self.m.add(sum(windows) + broken >= var)
                self.add_penalty(points / estimate, broken)

    # ----------------------------------------------------------------- employee requests

    def _requests(self) -> None:
        p = self.p
        requests = {r.id: r for r in p.requests}
        for measure in self.baseline.requests:
            points = self.instruction_points if measure.by_manager else self.request_points
            if not points:
                continue
            employee_id = measure.employee
            mine = self.x_of_emp.get(employee_id, ())
            weight = measure.weight * points
            if measure.kind == RequestKind.PREFER:
                by_day: dict[date, list[cp_model.IntVar]] = defaultdict(list)
                for s, v in mine:
                    if p.availability_for(employee_id, s) == AvailabilityState.PREFER:
                        by_day[s.date].append(v)
                marked = sum(
                    1
                    for a in p.availability
                    if a.employee == employee_id
                    and a.state == AvailabilityState.PREFER
                    and p.period_start <= a.date <= p.period_end
                )
                possible = max(1.0, min(marked, self._per_person_estimate(p.main_location(employee_id))))
                for day, vars_ in by_day.items():
                    self.add_penalty(-weight / possible, self._or(vars_, f"prefer[{employee_id},{day}]"))
            elif measure.request_id is not None:
                self._text_request(requests[measure.request_id], weight)

    def _external_days(self, employee_id: str) -> set[date]:
        return {e.date for e in self.externals.get(employee_id, ())}

    def _busy(self, employee_id: str, day: date, external: set[date]) -> cp_model.LinearExprT:
        """1 when the person works that day (a shift outside the problem makes it a constant 1)."""
        return 1 if day in external else self.own_day(employee_id, day)

    def _text_request(self, request, weight: float) -> None:
        own = [(s, v) for s, v in self.x_of_emp.get(request.employee, ()) if request.covers(s.date)]
        if not own:
            return
        location = self.p.request_location(request)
        covered_days = len(request.dates) if request.dates else (self.p.period_end - self.p.period_start).days + 1
        period_days = (self.p.period_end - self.p.period_start).days + 1
        estimate = max(1.0, self._per_person_estimate(location) * min(1.0, covered_days / period_days))
        if request.type in (RequestType.AVOID_PERSON, RequestType.PREFER_PERSON) and request.same_day:
            self._same_day(request, own, weight / estimate)
            return
        if self._new_request(request, own, weight, estimate):
            return
        match request.type:
            case RequestType.AVOID_PERSON | RequestType.PREFER_PERSON:
                theirs = self.x_of_emp.get(request.subject_employee, ())
                for slot, var in own:
                    if not request.counts_slot(slot):
                        continue  # "nie razem na zamknięciu": only shifts of that type count
                    overlapping = [
                        v for o, v in theirs if slot.matches_pair(o, avoid=request.type == RequestType.AVOID_PERSON)
                    ]
                    if not overlapping:
                        continue
                    together = self.m.new_bool_var(f"together[{request.id},{slot.id}]")
                    if request.type == RequestType.AVOID_PERSON:
                        for other in overlapping:
                            self.m.add(together >= var + other - 1)
                        self.add_penalty(weight / estimate, together)
                    else:
                        self.m.add(together <= var)
                        self.m.add(together <= sum(overlapping))
                        self.add_penalty(-weight / estimate, together)
            case RequestType.SHIFT_TYPE:
                for slot, var in own:
                    if (slot.shift_type == request.shift_type) == request.avoid:
                        self.add_penalty(weight / estimate, var)
            case RequestType.POSITION:
                if not request.positions:
                    return
                for slot, var in own:
                    if (slot.position in request.positions) == request.avoid:
                        self.add_penalty(weight / estimate, var)
            case RequestType.HOURS_LIMIT:
                windows = request.hour_windows(self.p)
                limit = round(float(request.max_hours) * 60)
                for start, end, fixed in windows:
                    slots = [(s, v) for s, v in own if start <= s.date <= end]
                    if not slots or (limit == 0 and fixed > 0):
                        continue
                    cost = weight / len(windows)
                    if limit == 0:
                        self.add_penalty(cost, self._or([v for _, v in slots], f"any[{request.id},{start}]"))
                        continue
                    hours = fixed + sum(_minutes(s) * v for s, v in slots)
                    over = self.m.new_int_var(
                        0, fixed + sum(_minutes(s) for s, _ in slots), f"over[{request.id},{start}]"
                    )
                    self.m.add(over >= hours - limit)
                    capped = self.m.new_int_var(0, limit, f"capped[{request.id},{start}]")
                    self.m.add_min_equality(capped, [over, limit])
                    self.add_penalty(cost / limit, capped)
            case RequestType.SHIFTS_LIMIT:
                if request.max_shifts is None:
                    return
                windows = request.shift_windows(self.p)
                limit = request.max_shifts
                counted = [(s, v) for s, v in own if request.counts_slot(s)]
                for start, end, fixed in windows:
                    slots = [v for s, v in counted if start <= s.date <= end]
                    if not slots or (limit <= 0 and fixed > 0):
                        continue
                    cost = weight / len(windows)
                    if limit <= 0:
                        self.add_penalty(cost, self._or(slots, f"any_shift[{request.id},{start}]"))
                        continue
                    over = self.m.new_int_var(0, fixed + len(slots), f"shifts_over[{request.id},{start}]")
                    self.m.add(over >= fixed + sum(slots) - limit)
                    capped = self.m.new_int_var(0, limit, f"shifts_capped[{request.id},{start}]")
                    self.m.add_min_equality(capped, [over, limit])
                    self.add_penalty(cost / limit, capped)
            case RequestType.HOURS_TARGET:
                windows = request.target_windows(self.p)
                for start, end, target, fixed in windows:
                    slots = [(s, v) for s, v in own if start <= s.date <= end]
                    if not slots:
                        continue  # nothing here can move the hours: a constant for the solver
                    cost = weight / len(windows)
                    share = PREFERRED_DAYS_SHARE if request.preferred_dates else 0.0
                    # As the validator: |hours − target| / target (only the hours missing with `at_least`), capped
                    # at 1, for each window.
                    worked = fixed + sum(_minutes(s) * v for s, v in slots)
                    most = fixed + sum(_minutes(s) for s, _ in slots)
                    off = self.m.new_int_var(0, max(most, target), f"target_off[{request.id},{start}]")
                    if not request.at_least:
                        self.m.add(off >= worked - target)
                    self.m.add(off >= target - worked)
                    capped = self.m.new_int_var(0, target, f"target_capped[{request.id},{start}]")
                    self.m.add_min_equality(capped, [off, target])
                    self.add_penalty(cost * (1 - share) / target, capped)
                    elsewhere = [(s, v) for s, v in slots if s.date not in request.preferred_dates]
                    if share and elsewhere:
                        # "najlepiej pod koniec tygodnia": minutes on other days, capped at the target.
                        misplaced = self.m.new_int_var(
                            0, sum(_minutes(s) for s, _ in elsewhere), f"target_days[{request.id},{start}]"
                        )
                        self.m.add(misplaced == sum(_minutes(s) * v for s, v in elsewhere))
                        kept = self.m.new_int_var(0, target, f"target_days_capped[{request.id},{start}]")
                        self.m.add_min_equality(kept, [misplaced, target])
                        self.add_penalty(cost * share / target, kept)
            case RequestType.DAYS_OFF:
                if not request.dates:  # no dates: left to the manager, as in the validator
                    return
                if request.min_days is not None:
                    # "albo 24, albo 31 wolne": enough free days in each window (a shift elsewhere is no day off).
                    external = self._external_days(request.employee)
                    windows = request.count_windows(self.p)
                    for n, (days, need) in enumerate(windows):
                        free = [1 - self._busy(request.employee, d, external) for d in days]
                        short = self.m.new_int_var(0, need, f"days_off_short[{request.id},{n}]")
                        self.m.add(short >= need - sum(free))
                        self.add_penalty(weight / len(windows) / need, short)
                    return
                by_day: dict[date, list[cp_model.IntVar]] = defaultdict(list)
                for slot, var in own:
                    by_day[slot.date].append(var)
                for day, vars_ in by_day.items():
                    self.add_penalty(weight / len(request.dates), self._or(vars_, f"day_off[{request.id},{day}]"))
            case RequestType.WANT_WORK:
                if not request.dates:
                    return
                by_day = defaultdict(list)
                for slot, var in own:
                    if request.shift_type is None or slot.shift_type == request.shift_type:
                        by_day[slot.date].append(var)
                kept_on: dict[date, cp_model.IntVar] = {}
                for day, vars_ in by_day.items():
                    kept = self.m.new_bool_var(f"want_work[{request.id},{day}]")
                    self.m.add(request.shifts_per_day * kept <= sum(vars_))
                    kept_on[day] = kept
                windows = request.count_windows(self.p)
                for n, (days, need) in enumerate(windows):
                    short = self.m.new_int_var(0, need, f"want_work_short[{request.id},{n}]")
                    self.m.add(short >= need - sum(kept_on[d] for d in days if d in kept_on))
                    self.add_penalty(weight / len(windows) / need, short)
            case _:
                return

    def _same_day(self, request, own, unit: float) -> None:
        """avoid_person / prefer_person by whole days ("nie w te same dni co Marek", "te same dni wolne co Kasia")."""
        subject = request.subject_employee
        if subject is None:
            return
        me, mine_outside = request.employee, self._external_days(request.employee)
        theirs_outside = self._external_days(subject)
        if request.type == RequestType.AVOID_PERSON:
            for day in sorted({s.date for s, _ in own}):
                mine = self.own_day(me, day)
                theirs = self._busy(subject, day, theirs_outside)
                if isinstance(theirs, int):
                    if theirs:
                        self.add_penalty(unit, mine)
                    continue
                both = self.m.new_bool_var(f"same_day[{request.id},{day}]")
                self.m.add(both >= mine + theirs - 1)
                self.add_penalty(unit, both)
            return
        days = {s.date for s, _ in own} | {s.date for s, _ in self.x_of_emp.get(subject, ())}
        for day in sorted(d for d in days if request.covers(d)):
            mine, theirs = self._busy(me, day, mine_outside), self._busy(subject, day, theirs_outside)
            if isinstance(mine, int) and isinstance(theirs, int):
                continue
            apart = self.m.new_bool_var(f"apart[{request.id},{day}]")
            self.m.add(apart >= mine - theirs)
            self.m.add(apart >= theirs - mine)
            self.add_penalty(unit, apart)

    def _new_request(self, request, own, weight: float, estimate: float) -> bool:
        """The request types added on 27.11.2026 (docs/plan.md section 48); False for the others."""
        p, me = self.p, request.employee
        match request.type:
            case RequestType.TIME_OF_DAY:
                if request.from_time is None and request.to_time is None:
                    return True
                for slot, var in own:
                    if request.wrong_hours(p, slot):
                        self.add_penalty(weight / estimate, var)
            case RequestType.LOCATION:
                for slot, var in own:
                    if request.locations and (slot.location in request.locations) == request.avoid:
                        self.add_penalty(weight / estimate, var)
            case RequestType.SHIFT_LENGTH:
                for slot, var in own:
                    if request.min_shift_hours and slot.hours < request.min_shift_hours - 1e-9:
                        self.add_penalty(weight / estimate, var)
            case RequestType.DAYS_IN_ROW:
                self._days_in_row(request, weight / estimate)
            case RequestType.DAYS_OFF_IN_ROW:
                length = request.free_in_row
                windows = request.days_off_windows(p) if length else []
                external = self._external_days(me)
                for n, days in enumerate(windows):
                    blocks = []
                    for i in range(len(days) - length + 1):
                        run = days[i : i + length]
                        if run[-1] - run[0] != timedelta(days=length - 1) or any(d in external for d in run):
                            continue
                        block = self.m.new_bool_var(f"free_run[{request.id},{run[0]}]")
                        for d in run:
                            busy = self.own_day(me, d)
                            if not isinstance(busy, int):
                                self.m.add(block + busy <= 1)
                        blocks.append(block)
                    broken = self.m.new_bool_var(f"no_free_run[{request.id},{n}]")
                    self.m.add(sum(blocks) + broken >= 1)
                    self.add_penalty(weight / len(windows), broken)
            case RequestType.REST_AFTER:
                if request.any_shift:
                    return True
                mine = self.x_of_emp.get(me, ())
                outside = self._external_days(me) if request.next_shift_type is None else set()
                for slot, var in own:
                    if not request.counts_slot(slot):
                        continue
                    after = {slot.date + timedelta(days=k) for k in range(1, request.days_after + 1)}
                    if after & outside:
                        self.add_penalty(weight / estimate, var)
                        continue
                    later = [v for s, v in mine if s.date in after and request.unwelcome_after(s)]
                    if later:
                        bad = self.m.new_bool_var(f"rest_after[{request.id},{slot.id}]")
                        for v in later:
                            self.m.add(bad >= var + v - 1)
                        self.add_penalty(weight / estimate, bad)
            case RequestType.FREE_WEEKENDS:
                groups = request.weekend_groups(p)
                external = self._external_days(me)
                free_on: dict[date, cp_model.LinearExprT] = {}
                for saturdays, _ in groups:
                    for sat in saturdays:
                        if sat in free_on:
                            continue
                        days = (sat, sat + timedelta(days=1))
                        if any(d in external for d in days):
                            free_on[sat] = 0
                            continue
                        busy = [b for b in (self.own_day(me, d) for d in days) if not isinstance(b, int)]
                        if not busy:
                            free_on[sat] = 1
                            continue
                        free = self.m.new_bool_var(f"free_weekend[{request.id},{sat}]")
                        for b in busy:
                            self.m.add(free + b <= 1)
                        free_on[sat] = free
                for n, (saturdays, need) in enumerate(groups):
                    short = self.m.new_int_var(0, need, f"weekends_short[{request.id},{n}]")
                    self.m.add(short >= need - sum(free_on[sat] for sat in saturdays))
                    self.add_penalty(weight / len(groups) / need, short)
            case RequestType.SAME_SHIFT_TYPE:
                weeks: dict[date, dict[str, list[cp_model.IntVar]]] = defaultdict(lambda: defaultdict(list))
                for slot, var in own:
                    weeks[_week_start(slot.date)][slot.shift_type].append(var)
                for monday, by_type in sorted(weeks.items()):
                    if len(by_type) < 2:
                        continue
                    used = [self._or(v, f"pora[{request.id},{monday},{t}]") for t, v in by_type.items()]
                    mixed = self.m.new_bool_var(f"pora_mixed[{request.id},{monday}]")
                    self.m.add((len(used) - 1) * mixed >= sum(used) - 1)
                    self.add_penalty(weight / len(weeks), mixed)
            case RequestType.NOT_MORE_THAN_OTHERS:
                self._not_more_than_others(request, weight)
            case RequestType.NOT_ALONE:
                for slot, var in own:
                    if not request.counts_slot(slot):
                        continue
                    others = [
                        o for o in self.slots_of(slot.location) if o.id != slot.id and slot.matches_pair(o, avoid=True)
                    ]
                    filled = [(1 - self.u[o.id]) - self.x.get((me, o.id), 0) for o in others]
                    alone = self.m.new_bool_var(f"alone[{request.id},{slot.id}]")
                    self.m.add(alone >= var - sum(filled))
                    self.add_penalty(weight / estimate, alone)
            case _:
                return False
        return True

    def _days_in_row(self, request, unit: float) -> None:
        limit = request.max_in_row
        if not limit:
            return
        me = request.employee
        by_day: dict[date, list[cp_model.IntVar]] = defaultdict(list)
        for slot, var in self.x_of_emp.get(me, ()):
            if request.counts_slot(slot):
                by_day[slot.date].append(var)
        external = {d for d in self._external_days(me) if request.covers(d)} if request.any_shift else set()
        worked = {d: self._or(v, f"in_row[{request.id},{d}]") for d, v in by_day.items()}

        def on(day: date) -> cp_model.LinearExprT:
            return 1 if day in external else worked.get(day, 0)

        for day in sorted(worked):
            window = sum(on(day - timedelta(days=k)) for k in range(1, limit + 1))
            if isinstance(window, int) and window < limit:
                continue
            broken = self.m.new_bool_var(f"in_row_broken[{request.id},{day}]")
            self.m.add(broken >= window + worked[day] - limit)
            self.add_penalty(unit, broken)

    def _not_more_than_others(self, request, weight: float) -> None:
        """n · mine − Σ others above zero, in days with a counted shift (n = how many others)."""
        counted = [s for s in self.p.slots if request.counts_slot(s)]
        others = not_more_than_others_peers(self.p, request, counted)
        if not others:
            return
        ids = {s.id for s in counted}

        def load(employee_id: str) -> cp_model.LinearExprT:
            per_day: dict[date, list[cp_model.IntVar]] = defaultdict(list)
            for slot, var in self.x_of_emp.get(employee_id, ()):
                if slot.id in ids:
                    per_day[slot.date].append(var)
            return sum(self._or(v, f"others_load[{request.id},{employee_id},{d}]") for d, v in per_day.items())

        mine = load(request.employee)
        if isinstance(mine, int):
            return
        n = len(others)
        days = len({s.date for s in counted})
        excess = self.m.new_int_var(0, n * days, f"more_than_others[{request.id}]")
        self.m.add(excess >= n * mine - sum(load(e) for e in others))
        estimate = max(1.0, len(counted) / (n + 1))
        self.add_penalty(weight / estimate / n, excess)

    # ----------------------------------------------------------------- stability and variants

    def _stability(self) -> None:
        points = self.p.weights.stability_penalty
        for slot_id, before in self.p.published.items():
            if slot_id not in self.u or slot_id in self.fixed:
                continue
            if before is None:
                self.add_penalty(points, 1 - self.u[slot_id])
            elif (before, slot_id) in self.x:
                self.add_penalty(points, 1 - self.x[(before, slot_id)])

    def _diversity(self, previous: Schedule, min_difference: float) -> None:
        """Soft: every person-shift of `previous` kept beyond (1 - min_difference) of them is one unit of
        `shortfall`, which `solve` minimises after the holes and before the penalty. Never infeasible."""
        compared = _compared(self.p, previous, self.fixed)
        kept = [self.x[(e, s)] for e, seats in compared for s in seats if (e, s) in self.x and s not in self.fixed]
        allowed = math.floor((1 - min_difference) * len(compared))
        most = min(len(kept), len(compared)) - allowed
        if most <= 0:
            return
        short = self.m.new_int_var(0, most, f"same_as_before[{len(self.shortfall)}]")
        self.m.add(short >= sum(kept) - allowed)
        self.shortfall.append(short)

    # ----------------------------------------------------------------- solving

    def holes(self) -> cp_model.LinearExprT:
        return sum(self.u.values())

    def objective(self) -> cp_model.LinearExprT:
        return sum(coef * expr for coef, expr in self.penalty)

    def read(self, solver: cp_model.CpSolver) -> dict[str, str | None]:
        schedule: dict[str, str | None] = {}
        for slot in self.p.slots:
            schedule[slot.id] = next((e for e, v in self.x_of_slot[slot.id] if solver.boolean_value(v)), None)
        return schedule

    def hint(self, schedule: Mapping[str, str | None]) -> None:
        self.m.clear_hints()
        for (employee_id, slot_id), var in self.x.items():
            self.m.add_hint(var, schedule.get(slot_id) == employee_id)
        for slot_id, var in self.u.items():
            self.m.add_hint(var, schedule.get(slot_id) is None)


def _solver(time_limit: float, workers: int, seed: int) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.05, time_limit)
    solver.parameters.num_workers = max(1, workers)
    solver.parameters.random_seed = seed
    return solver


# How often a running search asks the caller whether to stop.
STOP_POLL_S = 1.0


class _Search:
    """Runs CP-SAT searches that the caller can stop: `should_stop` is asked before each search and then,
    from a helper thread, every `STOP_POLL_S` while it runs; the search ends as soon as the answer is yes."""

    def __init__(self, should_stop: Callable[[], bool] | None) -> None:
        self.should_stop = should_stop
        self.stopped = False

    def run(self, solver: cp_model.CpSolver, model: cp_model.CpModel):
        if self.should_stop is None:
            return solver.solve(model)
        if self.should_stop():
            self.stopped = True
            return cp_model.UNKNOWN
        done = threading.Event()

        def watch() -> None:
            while not done.wait(STOP_POLL_S):
                if self.should_stop():
                    self.stopped = True
                    solver.stop_search()
                    return

        watcher = threading.Thread(target=watch, name="solver-stop-watch", daemon=True)
        watcher.start()
        try:
            return solver.solve(model)
        finally:
            done.set()
            watcher.join()


def _shift_of(slot: Slot) -> tuple:
    """The shift a slot is one seat of: two people swapped between seats of one shift is no difference."""
    return (slot.location, slot.date, slot.shift_type, slot.position, slot.start_utc, slot.end_utc)


def _compared(
    problem: Problem, previous: Schedule, fixed: Mapping[str, str | None]
) -> list[tuple[str, tuple[str, ...]]]:
    """(employee, seats of that shift) for every person-shift of `previous` that arranging can change: its slot is
    still in the problem, is not fixed (pinned, a day that has passed) and no seat of that shift holds that person
    fixed."""
    seats: dict[tuple, list[str]] = defaultdict(list)
    for slot in problem.slots:
        seats[_shift_of(slot)].append(slot.id)
    compared = []
    for slot_id, employee_id in previous.items():
        slot = problem.slot_by_id.get(slot_id)
        if employee_id is None or slot is None or slot_id in fixed:
            continue
        group = tuple(seats[_shift_of(slot)])
        if any(fixed.get(s) == employee_id for s in group):
            continue
        compared.append((employee_id, group))
    return compared


def changed_shifts(problem: Problem, previous: Schedule, schedule: Schedule) -> tuple[int, int]:
    """How many person-shifts of `previous` that arranging could change have someone else in `schedule`, and out of
    how many (the measure `diversity_from` uses: who works which shift, day and position, whatever the seat)."""
    compared = _compared(problem, previous, _fixed(problem))
    changed = sum(1 for employee_id, seats in compared if all(schedule.get(s) != employee_id for s in seats))
    return changed, len(compared)


def _fixed(problem: Problem) -> dict[str, str | None]:
    """Slots whose person is decided before solving: frozen past days (published value) and pins."""
    fixed: dict[str, str | None] = {}
    if problem.frozen_before is not None:
        for slot in problem.slots:
            if slot.date < problem.frozen_before and slot.id in problem.published:
                fixed[slot.id] = problem.published[slot.id]
    fixed.update(problem.pinned)
    return fixed


def _kept_forced(problem: Problem) -> dict[str, str]:
    """Forced assignments that stay: the slot is pinned to that person, or the day has passed."""
    if not problem.forced:
        return {}
    fixed = _fixed(problem)
    return {s: e for s, e in problem.forced.items() if fixed.get(s) == e}


def _without_slots(problem: Problem, kept: Mapping[str, str]) -> Problem:
    """`problem` without the `kept` slots; their people have them as shifts outside the problem."""
    outside = tuple(
        ExternalShift(employee, slot.date, slot.start, slot.end)
        for slot_id, employee in kept.items()
        for slot in (problem.slot_by_id[slot_id],)
    )
    return replace(
        problem,
        slots=tuple(s for s in problem.slots if s.id not in kept),
        pinned={k: v for k, v in problem.pinned.items() if k not in kept},
        published={k: v for k, v in problem.published.items() if k not in kept},
        forced={},
        external_shifts=(*problem.external_shifts, *outside),
    )


def _fixed_conflicts(problem: Problem, fixed: Mapping[str, str | None]) -> list[str]:
    """Hard violations that pins and past days already have on their own (no other shift can fix them)."""
    report = validate(problem, fixed)
    messages = []
    for violation in report.hard:
        if violation.code in _MONOTONE_CODES or (
            violation.code == Code.RULE and violation.rule_code in _MONOTONE_RULES
        ):
            messages.append(violation.message)
    return list(dict.fromkeys(messages))


def _diagnose(problem: Problem, workers: int, seed: int, budget_s: float) -> list[str]:
    """Name the "no exceptions" rules that make the schedule impossible (each one tried switched off).

    Takes at most about `budget_s` in total, so a location with many such rules does not wait much longer."""
    deadline = clock.monotonic() + budget_s
    hard = [(loc, r.code) for loc in problem.locations for r in problem.rules_for(loc) if r.hard]
    culprits = []
    for key in hard:
        left = deadline - clock.monotonic()
        if left <= 0:
            break
        builder = _Builder(problem, relaxed_rules=frozenset({key}))
        status = _solver(min(DIAGNOSIS_TIME_S, left), workers, seed).solve(builder.m)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            culprits.append(key)
    if not culprits and hard and clock.monotonic() < deadline:
        builder = _Builder(problem, relaxed_rules=frozenset(hard))
        status = _solver(DIAGNOSIS_TIME_S, workers, seed).solve(builder.m)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            culprits = hard
    if not culprits:
        return [
            "Nie da się ułożyć grafiku przy obecnych ustawieniach. Sprawdź przypięte zmiany i zasady „bez wyjątków”."
        ]
    labels = ", ".join(f"„{RULES_BY_CODE[code].label}”" for _, code in dict.fromkeys(culprits))
    return [
        f"Nie da się ułożyć grafiku, w którym wszyscy trzymają się zasad „bez wyjątków”: {labels}. "
        "Zmień te zasady na zwykłe albo popraw obsadę, dyspozycje lub cele godzin."
    ]


def solve(
    problem: Problem,
    *,
    time_limit_s: float = 30.0,
    workers: int = DEFAULT_WORKERS,
    seed: int = 0,
    weights: WeightProfile | None = None,
    diversity_from: Iterable[Schedule] = (),
    min_difference: float = 0.15,
    should_stop: Callable[[], bool] | None = None,
) -> SolveResult:
    """Build the best schedule found within `time_limit_s` (fewest holes first, then the lowest penalty).

    `weights` replaces the problem's weight profile (variants with another manager share). Every schedule in
    `diversity_from` should differ from the new one in at least `min_difference` of its person-shifts that are not
    fixed (`changed_shifts`): as close to that as possible without more holes, before the penalty counts.
    `should_stop` is asked about once a second while searching; when it says yes the search ends at once and
    the result is `STOPPED` without a schedule (the manager cancelled the generation).
    """
    started = clock.monotonic()
    if weights is not None:
        problem = replace(problem, weights=weights)
    kept = _kept_forced(problem)
    if kept:
        # The manager's forced assignments break hard rules on purpose, so they cannot be part of the model.
        # They leave it as shifts the person already has (no overlap, rest counted) and return in the result.
        result = solve(
            _without_slots(problem, kept),
            time_limit_s=time_limit_s,
            workers=workers,
            seed=seed,
            diversity_from=[{k: v for k, v in s.items() if k not in kept} for s in diversity_from],
            min_difference=min_difference,
            should_stop=should_stop,
        )
        if result.schedule is None:
            return result
        return replace(result, schedule={**result.schedule, **kept})

    def elapsed_ms() -> int:
        return round((clock.monotonic() - started) * 1000)

    builder = _Builder(problem, diversity_from=tuple(diversity_from), min_difference=min_difference)
    conflicts = _fixed_conflicts(problem, builder.fixed)
    if conflicts:
        intro = "Przypięte zmiany albo dni, które już minęły, łamią reguły, więc grafiku nie da się ułożyć:"
        return SolveResult(SolveStatus.INFEASIBLE, None, time_ms=elapsed_ms(), messages=(intro, *conflicts))

    # Phase 1: as few holes as possible.
    builder.m.minimize(builder.holes())
    first = _solver(time_limit_s * PHASE_1_SHARE - (clock.monotonic() - started), workers, seed)
    search = _Search(should_stop)
    status = search.run(first, builder.m)
    if search.stopped:
        return SolveResult(SolveStatus.STOPPED, None, time_ms=elapsed_ms())
    if status == cp_model.INFEASIBLE:
        return SolveResult(
            SolveStatus.INFEASIBLE,
            None,
            time_ms=elapsed_ms(),
            messages=tuple(_diagnose(problem, workers, seed, budget_s=time_limit_s)),
        )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return SolveResult(
            SolveStatus.TIMEOUT_NO_SOLUTION,
            None,
            time_ms=elapsed_ms(),
            messages=("Nie udało się ułożyć grafiku w wyznaczonym czasie. Spróbuj ponownie.",),
        )
    optimal = status == cp_model.OPTIMAL
    best_holes = round(first.objective_value)
    schedule = builder.read(first)
    builder.m.add(builder.holes() <= best_holes)

    if builder.shortfall:
        # Between the phases: as different from the earlier schedules as asked, with no more holes.
        builder.m.minimize(sum(builder.shortfall))
        builder.hint(schedule)
        budget = min(time_limit_s * DIFFERENCE_SHARE, time_limit_s - (clock.monotonic() - started))
        middle = _solver(budget, workers, seed)
        status = search.run(middle, builder.m)
        if search.stopped:
            return SolveResult(SolveStatus.STOPPED, None, time_ms=elapsed_ms())
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            schedule = builder.read(middle)
            builder.m.add(sum(builder.shortfall) <= round(middle.objective_value))
        optimal = optimal and status == cp_model.OPTIMAL

    # Phase 2: the lowest penalty with no more holes.
    builder.m.minimize(builder.objective())
    builder.hint(schedule)
    second = _solver(time_limit_s - (clock.monotonic() - started), workers, seed)
    status = search.run(second, builder.m)
    if search.stopped:
        return SolveResult(SolveStatus.STOPPED, None, time_ms=elapsed_ms())
    objective = None
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        schedule = builder.read(second)
        objective = second.objective_value / SCALE
    optimal = optimal and status == cp_model.OPTIMAL
    holes = sum(1 for v in schedule.values() if v is None)
    return SolveResult(
        SolveStatus.OPTIMAL if optimal else SolveStatus.FEASIBLE,
        schedule,
        holes=holes,
        objective=objective,
        time_ms=elapsed_ms(),
    )


__all__ = ["SolveResult", "SolveStatus", "changed_shifts", "solve"]
