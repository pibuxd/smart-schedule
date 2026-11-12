"""The schedule generator: an OR-Tools CP-SAT model of a `Problem`. Pure Python, no Django; runs only in the worker.

Two phases, as in docs/plan.md section 3:

1. minimise the number of unfilled slots (holes);
2. with that many holes at most, minimise the penalty: manager rules and employee requests weighed by the
   location's weight profile (80 : 20 by default), plus a cost for every changed published assignment.

Hard rules (always): one person or a hole per slot, the right position, home location only (borrowing is manual),
no "cannot" days, no overlapping shifts, pinned slots, frozen past days, "no exceptions" rules and, for employment
contracts, 11 h daily rest, 35 h weekly rest and at most 8 h a day.

The penalty in phase 2 is a linear stand-in for `engine.scoring.penalty`. Most parts are exact (requests,
"wolę nie" days, hours, closings, days in a row); rules whose score is a share of a varying count (e.g. "rest
between shifts" = broken pairs / all pairs) divide by an estimate of that count instead. The manager always sees
the numbers from the independent validator, never the solver's own objective.

`solve` is meant to be called once per variant; `diversity_from` and `weights` exist for the later three-variant
mode (70/30, 80/20, 90/10 with at least 15 % different assignments).
"""

from __future__ import annotations

import calendar
import math
import time as clock
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum

from ortools.sat.python import cp_model

from engine.problem import (
    AvailabilityState,
    Contract,
    Employee,
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
    LABOR_DAILY_REST,
    LABOR_MAX_HOURS_PER_DAY,
    LABOR_WEEKLY_REST,
    TARGET_HOURS_HARD_TOLERANCE,
    Code,
    RequestKind,
    validate,
)

# Objective coefficients are points of the 0–100 score times this factor, rounded to integers.
SCALE = 1_000_000
# Share of the time limit for phase 1 (holes); phase 2 gets the rest.
PHASE_1_SHARE = 0.4
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
    }
)
_MONOTONE_CODES = frozenset(
    {Code.POSITION, Code.CANNOT, Code.OVERLAP, Code.LABOR_DAILY_REST, Code.LABOR_DAILY_HOURS, Code.LABOR_WEEKLY_REST}
)


class SolveStatus(StrEnum):
    OPTIMAL = "optimal"  # both phases proved optimal
    FEASIBLE = "feasible"  # the best schedule found within the time limit
    TIMEOUT_NO_SOLUTION = "timeout_no_solution"
    INFEASIBLE = "infeasible"  # pins, past days or "no exceptions" rules cannot all be kept


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
        self._own_day: dict[tuple[str, date], cp_model.IntVar] = {}
        self._worked_any: dict[str, cp_model.IntVar] = {}

        self.fixed = self._fixed_assignments()
        self.externals = defaultdict(list)
        for ext in problem.external_shifts:
            self.externals[ext.employee].append(ext)
        self.baseline = validate(problem, {})  # schedule-independent request weights
        self.share = problem.weights.manager_share
        self.rule_points = self._rule_points()
        request_total = sum(r.weight for r in self.baseline.requests)
        self.request_points = (1 - self.share) * 100 / request_total if request_total else 0.0

        self._variables()
        self._intervals = {e.id: self._group_intervals(e.id) for e in problem.employees}
        self._no_overlap()
        self._labor_law()
        self._rules()
        self._requests()
        self._stability()
        for previous in diversity_from:
            self._diversity(previous, min_difference)

    # ----------------------------------------------------------------- setup

    def _fixed_assignments(self) -> dict[str, str | None]:
        """Slots whose person is decided before solving: frozen past days (published value) and pins."""
        p, fixed = self.p, {}
        if p.frozen_before is not None:
            for slot in p.slots:
                if slot.date < p.frozen_before and slot.id in p.published:
                    fixed[slot.id] = p.published[slot.id]
        fixed.update(p.pinned)
        return fixed

    def _eligible(self, employee: Employee, slot: Slot) -> bool:
        if not employee.available or employee.home_location != slot.location or slot.position not in employee.positions:
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

    def _cliques(self, employee_id: str, intervals: list[_Interval], rest: timedelta) -> None:
        """At most one interval worked among those whose [start, end + rest) contain a common start point.
        Two intervals conflict exactly when they overlap or the gap between them is shorter than `rest`."""
        for point in intervals:
            members = [i for i in intervals if i.start <= point.start < i.end + rest]
            if sum(len(i.slots) for i in members) > 1:
                self.m.add(sum(self.work(employee_id, i) for i in members) <= 1)

    def _labor_law(self) -> None:
        for employee in self.p.employees:
            if employee.contract != Contract.EMPLOYMENT:
                continue
            intervals = self._intervals[employee.id]
            if not intervals:
                continue
            self._rest(employee.id, intervals, LABOR_DAILY_REST, hard=True)
            self._daily_hours(employee.id)
            self._weekly_rest(employee.id, intervals)

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

    def _daily_hours(self, employee_id: str) -> None:
        limit = round(LABOR_MAX_HOURS_PER_DAY * 3600)
        external: dict[date, int] = defaultdict(int)
        for ext in self.externals.get(employee_id, ()):
            external[ext.date] += round((ext.end_utc - ext.start_utc).total_seconds())
        by_day: dict[date, list[tuple[Slot, cp_model.IntVar]]] = defaultdict(list)
        for slot, var in self.x_of_emp[employee_id]:
            by_day[slot.date].append((slot, var))
        for day, items in by_day.items():
            self.m.add(sum(_seconds(s) * v for s, v in items) + external[day] <= limit)

    def _weekly_rest(self, employee_id: str, intervals: list[_Interval]) -> None:
        """Every week with a shift needs a free window of 35 h inside Monday 00:00 – Monday 00:00."""
        tz = self.p.tz
        externals = self.externals.get(employee_id, ())
        by_week: dict[date, list[tuple[Slot, cp_model.IntVar]]] = defaultdict(list)
        for slot, var in self.x_of_emp[employee_id]:
            by_week[_week_start(slot.date)].append((slot, var))
        for monday, items in by_week.items():
            week_start = local_datetime(monday, time(0), tz).astimezone(UTC)
            week_end = local_datetime(monday + timedelta(days=7), time(0), tz).astimezone(UTC)
            starts = {week_start}
            starts.update(i.end for i in intervals if week_start <= i.end < week_end)
            starts.update(e.end_utc for e in externals if week_start <= e.end_utc < week_end)
            windows = []
            for begin in sorted(starts):
                finish = begin + LABOR_WEEKLY_REST
                if finish > week_end:
                    continue
                if any(e.start_utc < finish and begin < e.end_utc for e in externals):
                    continue
                free = self.m.new_bool_var(f"free[{employee_id},{begin:%Y%m%d%H%M}]")
                for interval in intervals:
                    if interval.start < finish and begin < interval.end:
                        self.m.add(free + self.work(employee_id, interval) <= 1)
                windows.append(free)
            for _, var in items:
                self.m.add(sum(windows) >= var)

    # ----------------------------------------------------------------- catalog rules

    def _rule_points(self) -> dict[tuple[str, str], float]:
        """Points of the 0–100 score per unit of degree for every soft rule (same weights as scoring)."""
        weights: dict[tuple[str, str], float] = {}
        for location in self.p.locations:
            soft = [r for r in self.p.rules_for(location) if not r.hard]
            for place, rule in enumerate(soft, start=1):
                weights[(location, rule.code)] = self.p.weights.rule_weight(place)
        total = sum(weights.values())
        return {key: self.share * 100 * w / total for key, w in weights.items()} if total else {}

    def employees_of(self, location: str) -> list[Employee]:
        return [e for e in self.p.employees if e.home_location == location]

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
        for employee in people:
            monthly = float(getattr(employee, attr))
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

    # ----------------------------------------------------------------- employee requests

    def _requests(self) -> None:
        p, points = self.p, self.request_points
        if not points:
            return
        requests = {r.id: r for r in p.requests}
        for measure in self.baseline.requests:
            employee_id = measure.employee
            mine = self.x_of_emp.get(employee_id, ())
            weight = measure.weight * points
            if measure.kind == RequestKind.PREFER_NOT:
                hits = [
                    v
                    for s, v in mine
                    if s.date == measure.date and p.availability_for(employee_id, s) == AvailabilityState.PREFER_NOT
                ]
                if hits:
                    self.add_penalty(weight, self._or(hits, f"prefer_not[{employee_id},{measure.date}]"))
            elif measure.kind == RequestKind.PREFER:
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
                possible = max(1.0, min(marked, self._per_person_estimate(p.employee_by_id[employee_id].home_location)))
                for day, vars_ in by_day.items():
                    self.add_penalty(-weight / possible, self._or(vars_, f"prefer[{employee_id},{day}]"))
            elif measure.request_id is not None:
                self._text_request(requests[measure.request_id], weight)

    def _text_request(self, request, weight: float) -> None:
        own = [(s, v) for s, v in self.x_of_emp.get(request.employee, ()) if request.covers(s.date)]
        if not own:
            return
        location = self.p.employee_by_id[request.employee].home_location
        covered_days = len(request.dates) if request.dates else (self.p.period_end - self.p.period_start).days + 1
        period_days = (self.p.period_end - self.p.period_start).days + 1
        estimate = max(1.0, self._per_person_estimate(location) * min(1.0, covered_days / period_days))
        match request.type:
            case RequestType.AVOID_PERSON | RequestType.PREFER_PERSON:
                theirs = self.x_of_emp.get(request.subject_employee, ())
                for slot, var in own:
                    overlapping = [
                        v
                        for o, v in theirs
                        if o.location == slot.location and o.start_utc < slot.end_utc and slot.start_utc < o.end_utc
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
            case RequestType.HOURS_LIMIT:
                hours = sum(_minutes(s) * v for s, v in own)
                limit = round(float(request.max_hours) * 60)
                if limit <= 0:
                    self.add_penalty(weight, self._or([v for _, v in own], f"any[{request.id}]"))
                    return
                over = self.m.new_int_var(0, sum(_minutes(s) for s, _ in own), f"over[{request.id}]")
                self.m.add(over >= hours - limit)
                capped = self.m.new_int_var(0, limit, f"over_capped[{request.id}]")
                self.m.add_min_equality(capped, [over, limit])
                self.add_penalty(weight / limit, capped)
            case _:
                return

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
        kept = [
            self.x[(e, s)] for s, e in previous.items() if e is not None and (e, s) in self.x and s not in self.fixed
        ]
        if kept:
            self.m.add(sum(kept) <= math.floor((1 - min_difference) * len(kept)))

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


def _diagnose(problem: Problem, workers: int, seed: int) -> list[str]:
    """Name the "no exceptions" rules that make the schedule impossible (each one tried switched off)."""
    hard = [(loc, r.code) for loc in problem.locations for r in problem.rules_for(loc) if r.hard]
    culprits = []
    for key in hard:
        builder = _Builder(problem, relaxed_rules=frozenset({key}))
        status = _solver(DIAGNOSIS_TIME_S, workers, seed).solve(builder.m)
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            culprits.append(key)
    if not culprits and hard:
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
) -> SolveResult:
    """Build the best schedule found within `time_limit_s` (fewest holes first, then the lowest penalty).

    `weights` replaces the problem's weight profile (variants with another manager share); every schedule in
    `diversity_from` must differ from the new one in at least `min_difference` of its assignments.
    """
    started = clock.monotonic()
    if weights is not None:
        problem = replace(problem, weights=weights)

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
    status = first.solve(builder.m)
    if status == cp_model.INFEASIBLE:
        return SolveResult(
            SolveStatus.INFEASIBLE, None, time_ms=elapsed_ms(), messages=tuple(_diagnose(problem, workers, seed))
        )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return SolveResult(
            SolveStatus.TIMEOUT_NO_SOLUTION,
            None,
            time_ms=elapsed_ms(),
            messages=("Nie udało się ułożyć grafiku w wyznaczonym czasie. Spróbuj ponownie.",),
        )
    phase_1_optimal = status == cp_model.OPTIMAL
    best_holes = round(first.objective_value)
    schedule = builder.read(first)

    # Phase 2: the lowest penalty with no more holes.
    builder.m.add(builder.holes() <= best_holes)
    builder.m.minimize(builder.objective())
    builder.hint(schedule)
    second = _solver(time_limit_s - (clock.monotonic() - started), workers, seed)
    status = second.solve(builder.m)
    objective = None
    optimal = False
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        schedule = builder.read(second)
        objective = second.objective_value / SCALE
        optimal = phase_1_optimal and status == cp_model.OPTIMAL
    holes = sum(1 for v in schedule.values() if v is None)
    return SolveResult(
        SolveStatus.OPTIMAL if optimal else SolveStatus.FEASIBLE,
        schedule,
        holes=holes,
        objective=objective,
        time_ms=elapsed_ms(),
    )


__all__ = ["SolveResult", "SolveStatus", "solve"]
