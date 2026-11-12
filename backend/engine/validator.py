"""Independent schedule validator: hard rules, unfilled slots and how much each soft rule or request is broken.

Deliberately separate from the solver (stage 5): it shares only the `Problem` description, so a bug in the CP-SAT
model cannot hide itself. The solver's result is saved only if `validate(...).ok`; the same function answers the
"check my manual edit" endpoint (stage 8).

Every `Violation.message` is a Polish sentence for the manager.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from types import MappingProxyType

from engine.problem import (
    AvailabilityState,
    Contract,
    Employee,
    Problem,
    Request,
    RequestLevel,
    RequestType,
    RuleConfig,
    Schedule,
    Slot,
    local_datetime,
)

# Labour-law limits for an employment contract (Kodeks pracy art. 129, 132, 133), simplified: rest is measured
# between consecutive shifts and the working day is the calendar day a shift starts on (see docs/plan.md, stage 4).
LABOR_DAILY_REST = timedelta(hours=11)
LABOR_WEEKLY_REST = timedelta(hours=35)
LABOR_MAX_HOURS_PER_DAY = 8.0

# A "no exceptions" target_hours rule allows this relative deviation from the target.
TARGET_HOURS_HARD_TOLERANCE = 0.10

_EPS = 1e-9


class Code(StrEnum):
    UNKNOWN_SLOT = "unknown_slot"
    UNKNOWN_EMPLOYEE = "unknown_employee"
    POSITION = "position"
    CANNOT = "cannot"
    OVERLAP = "overlap"
    PINNED = "pinned"
    FROZEN = "frozen"
    LABOR_DAILY_REST = "labor_daily_rest"
    LABOR_DAILY_HOURS = "labor_daily_hours"
    LABOR_WEEKLY_REST = "labor_weekly_rest"
    RULE = "rule"  # a catalog rule; see Violation.rule_code


@dataclass(frozen=True)
class Violation:
    code: Code
    message: str
    employee: str | None = None
    slots: tuple[str, ...] = ()
    rule_code: str | None = None
    location: str | None = None


@dataclass(frozen=True)
class RuleMeasure:
    """How much one configured rule is broken: `degree` 0 (kept) … 1 (broken everywhere it could be)."""

    location: str
    code: str
    rank: int
    hard: bool
    instances: int  # how many places the rule could be broken in (0 = nothing to measure)
    degree: float
    violations: tuple[Violation, ...]


class RequestKind(StrEnum):
    TEXT = "text"  # a text request
    PREFER_NOT = "prefer_not"  # a "wolę nie" day in the calendar
    PREFER = "prefer"  # all "chętnie" days of one employee


@dataclass(frozen=True)
class RequestMeasure:
    location: str  # the employee's home location
    employee: str
    kind: RequestKind
    weight: float
    degree: float
    request_id: str | None = None
    date: date | None = None


@dataclass(frozen=True)
class ValidationReport:
    hard: tuple[Violation, ...]
    holes: tuple[str, ...]  # unfilled slot ids
    rules: tuple[RuleMeasure, ...]
    requests: tuple[RequestMeasure, ...]
    stability_changes: tuple[str, ...]  # slot ids whose person differs from the published schedule
    hours: Mapping[str, float] = field(default_factory=dict)  # employee id -> hours in this schedule

    @property
    def ok(self) -> bool:
        """No hard rule is broken (unfilled slots are allowed; they are reported in `holes`)."""
        return not self.hard


@dataclass(frozen=True)
class _Interval:
    start: datetime  # UTC
    end: datetime  # UTC
    date: date
    slot: Slot | None  # None for an external shift
    label: str


@dataclass(frozen=True)
class _Measured:
    instances: int
    degree: float
    violations: tuple[Violation, ...]


def _ratio(violated: int, instances: int) -> float:
    return violated / instances if instances else 0.0


def _hm(value: datetime, problem: Problem) -> str:
    return value.astimezone(problem.tz).strftime("%H:%M")


def _slot_text(slot: Slot, problem: Problem) -> str:
    name = f" {slot.shift_name}" if slot.shift_name else ""
    return f"{slot.date:%d.%m}{name} {_hm(slot.start, problem)}–{_hm(slot.end, problem)}"


def _hours_text(hours: float) -> str:
    """8 -> "8 h", 10.9833 -> "10 h 59 min" (rounded to the minute)."""
    minutes = round(hours * 60)
    whole, rest = divmod(minutes, 60)
    return f"{whole} h {rest} min" if rest else f"{whole} h"


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


class _Checker:
    def __init__(self, problem: Problem, schedule: Schedule) -> None:
        self.p = problem
        self.hard: list[Violation] = []
        self.assignment: dict[str, str | None] = {}
        for slot_id, employee_id in schedule.items():
            if slot_id not in problem.slot_by_id:
                message = "Grafik zawiera zmianę, której nie ma w tym okresie."
                self.hard.append(Violation(Code.UNKNOWN_SLOT, message, slots=(slot_id,)))
                continue
            if employee_id is not None and employee_id not in problem.employee_by_id:
                self.hard.append(
                    Violation(
                        Code.UNKNOWN_EMPLOYEE,
                        f"Na zmianie {_slot_text(problem.slot_by_id[slot_id], problem)} jest osoba spoza tego lokalu.",
                        slots=(slot_id,),
                    )
                )
                continue
            self.assignment[slot_id] = employee_id

        self.slots_of: dict[str, list[Slot]] = defaultdict(list)
        for slot in problem.slots:
            employee_id = self.assignment.get(slot.id)
            if employee_id is not None:
                self.slots_of[employee_id].append(slot)
        for slots in self.slots_of.values():
            slots.sort(key=lambda s: (s.start_utc, s.id))

        self.intervals_of: dict[str, list[_Interval]] = defaultdict(list)
        for employee_id, slots in self.slots_of.items():
            for slot in slots:
                self.intervals_of[employee_id].append(
                    _Interval(slot.start_utc, slot.end_utc, slot.date, slot, _slot_text(slot, problem))
                )
        for ext in problem.external_shifts:
            label = ext.label or f"{ext.date:%d.%m} {_hm(ext.start, problem)}–{_hm(ext.end, problem)}"
            self.intervals_of[ext.employee].append(_Interval(ext.start_utc, ext.end_utc, ext.date, None, label))
        for intervals in self.intervals_of.values():
            intervals.sort(key=lambda i: (i.start, i.end))

    # ----------------------------------------------------------------- helpers

    def name(self, employee_id: str) -> str:
        return self.p.employee_by_id[employee_id].name

    def employees_of(self, location: str) -> list[Employee]:
        return [e for e in self.p.employees if e.home_location == location]

    def hours_by_month(self, employee_id: str) -> dict[tuple[int, int], float]:
        result: dict[tuple[int, int], float] = defaultdict(float)
        for slot in self.slots_of.get(employee_id, ()):
            result[(slot.date.year, slot.date.month)] += slot.hours
        return result

    def month_shares(self) -> dict[tuple[int, int], float]:
        """Part of each calendar month the period covers (1.0 for a whole month)."""
        covered: dict[tuple[int, int], int] = defaultdict(int)
        day = self.p.period_start
        while day <= self.p.period_end:
            covered[(day.year, day.month)] += 1
            day += timedelta(days=1)
        return {(y, m): n / calendar.monthrange(y, m)[1] for (y, m), n in covered.items()}

    def gaps(self, employee_id: str) -> Iterable[tuple[_Interval, _Interval, timedelta]]:
        """Consecutive (earlier, later, rest between them) pairs with at least one shift from this schedule.
        Overlapping pairs are skipped here (they are an `overlap` violation)."""
        latest: _Interval | None = None
        for interval in self.intervals_of.get(employee_id, ()):
            if latest is not None:
                gap = interval.start - latest.end
                if gap >= timedelta(0) and (interval.slot is not None or latest.slot is not None):
                    yield latest, interval, gap
            if latest is None or interval.end > latest.end:
                latest = interval

    def is_frozen(self, slot: Slot) -> bool:
        before = self.p.frozen_before
        return before is not None and slot.date < before and slot.id in self.p.published

    # ----------------------------------------------------------------- basic hard rules

    def check_basic(self) -> None:
        p = self.p
        for slot in p.slots:
            employee_id = self.assignment.get(slot.id)
            pinned = p.pinned.get(slot.id)
            if pinned is not None and employee_id != pinned:
                self.hard.append(
                    Violation(
                        Code.PINNED,
                        f"Zmiana {_slot_text(slot, p)} jest przypięta do: {self.name(pinned)}.",
                        employee=pinned,
                        slots=(slot.id,),
                    )
                )
            if self.is_frozen(slot) and employee_id != p.published[slot.id]:
                self.hard.append(
                    Violation(
                        Code.FROZEN,
                        f"Zmiana {_slot_text(slot, p)} już minęła i nie można jej zmienić.",
                        slots=(slot.id,),
                    )
                )
            if employee_id is None:
                continue
            employee = p.employee_by_id[employee_id]
            if slot.position not in employee.positions:
                position = p.position_names.get(slot.position, "tym stanowisku")
                self.hard.append(
                    Violation(
                        Code.POSITION,
                        f"{employee.name} nie pracuje na stanowisku {position} ({_slot_text(slot, p)}).",
                        employee=employee_id,
                        slots=(slot.id,),
                    )
                )
            if p.availability_for(employee_id, slot) == AvailabilityState.CANNOT:
                self.hard.append(
                    Violation(
                        Code.CANNOT,
                        f"{employee.name} ma zaznaczone „nie mogę” ({_slot_text(slot, p)}).",
                        employee=employee_id,
                        slots=(slot.id,),
                    )
                )

    def check_overlaps(self) -> None:
        for employee_id, intervals in self.intervals_of.items():
            for i, first in enumerate(intervals):
                for second in intervals[i + 1 :]:
                    if second.start >= first.end:  # touching shifts (06–14, 14–22) do not overlap
                        break
                    if first.slot is None and second.slot is None:
                        continue
                    self.hard.append(
                        Violation(
                            Code.OVERLAP,
                            f"{self.name(employee_id)} ma dwie zmiany w tym samym czasie: "
                            f"{first.label} i {second.label}.",
                            employee=employee_id,
                            slots=tuple(i.slot.id for i in (first, second) if i.slot is not None),
                        )
                    )

    # ----------------------------------------------------------------- employment contract (always hard)

    def check_labor_law(self) -> None:
        p = self.p
        for employee in p.employees:
            if employee.contract != Contract.EMPLOYMENT or employee.id not in self.slots_of:
                continue
            for earlier, later, gap in self.gaps(employee.id):
                if gap < LABOR_DAILY_REST:
                    self.hard.append(
                        Violation(
                            Code.LABOR_DAILY_REST,
                            f"{employee.name} (umowa o pracę) ma tylko {_hours_text(gap.total_seconds() / 3600)} "
                            f"odpoczynku między {earlier.label} a {later.label}; potrzeba 11 h.",
                            employee=employee.id,
                            slots=tuple(i.slot.id for i in (earlier, later) if i.slot is not None),
                        )
                    )

            per_day: dict[date, list[_Interval]] = defaultdict(list)
            for interval in self.intervals_of[employee.id]:
                per_day[interval.date].append(interval)
            for day, intervals in sorted(per_day.items()):
                if all(i.slot is None for i in intervals):
                    continue
                hours = sum((i.end - i.start).total_seconds() for i in intervals) / 3600
                if hours > LABOR_MAX_HOURS_PER_DAY + _EPS:
                    self.hard.append(
                        Violation(
                            Code.LABOR_DAILY_HOURS,
                            f"{employee.name} (umowa o pracę) pracuje {day:%d.%m} {_hours_text(hours)}; "
                            "najwyżej 8 h na dobę.",
                            employee=employee.id,
                            slots=tuple(i.slot.id for i in intervals if i.slot is not None),
                        )
                    )

            weeks = sorted({_week_start(s.date) for s in self.slots_of[employee.id]})
            for monday in weeks:
                window_start = local_datetime(monday, time(0), p.tz).astimezone(UTC)
                window_end = local_datetime(monday + timedelta(days=7), time(0), p.tz).astimezone(UTC)
                longest = timedelta(0)
                free_from = window_start
                for interval in self.intervals_of[employee.id]:
                    if interval.end <= window_start or interval.start >= window_end:
                        continue
                    longest = max(longest, interval.start - free_from)
                    free_from = max(free_from, interval.end)
                longest = max(longest, window_end - free_from)
                if longest < LABOR_WEEKLY_REST:
                    sunday = monday + timedelta(days=6)
                    self.hard.append(
                        Violation(
                            Code.LABOR_WEEKLY_REST,
                            f"{employee.name} (umowa o pracę) nie ma 35 h wolnego w tygodniu "
                            f"{monday:%d.%m}–{sunday:%d.%m} (najdłużej {_hours_text(longest.total_seconds() / 3600)}).",
                            employee=employee.id,
                            slots=tuple(s.id for s in self.slots_of[employee.id] if _week_start(s.date) == monday),
                        )
                    )

    # ----------------------------------------------------------------- catalog rules

    def rule_min_rest_between_shifts(self, rule: RuleConfig) -> _Measured:
        need = timedelta(hours=float(rule.params["hours"]))
        instances, found = 0, []
        for employee in self.employees_of(rule.location):
            for earlier, later, gap in self.gaps(employee.id):
                instances += 1
                if gap < need:
                    found.append(
                        Violation(
                            Code.RULE,
                            f"{employee.name}: tylko {_hours_text(gap.total_seconds() / 3600)} przerwy między "
                            f"{earlier.label} a {later.label}.",
                            employee=employee.id,
                            slots=tuple(i.slot.id for i in (earlier, later) if i.slot is not None),
                        )
                    )
        return _Measured(instances, _ratio(len(found), instances), tuple(found))

    def rule_max_consecutive_days(self, rule: RuleConfig) -> _Measured:
        limit = int(rule.params["days"])
        instances = violated = 0
        found = []
        for employee in self.employees_of(rule.location):
            own_days = {s.date for s in self.slots_of.get(employee.id, ())}
            if not own_days:
                continue
            worked = own_days | {i.date for i in self.intervals_of[employee.id]}
            instances += len(own_days)
            run_start: date | None = None
            run = 0
            for day in sorted(worked):
                if run_start is not None and day == run_start + timedelta(days=run):
                    run += 1
                else:
                    run_start, run = day, 1
                if run > limit and day in own_days:
                    violated += 1
                    if run == limit + 1:
                        found.append(
                            Violation(
                                Code.RULE,
                                f"{employee.name} pracuje więcej niż {limit} dni z rzędu (od {run_start:%d.%m}).",
                                employee=employee.id,
                            )
                        )
        return _Measured(instances, _ratio(violated, instances), tuple(found))

    def _fairness(self, rule: RuleConfig, counted: Callable[[Slot], bool], what: str) -> _Measured:
        """Spread the counted slots evenly between people of each position; a difference of 1 is fine."""
        slots_by_position: dict[str, list[Slot]] = defaultdict(list)
        for slot in self.p.slots:
            if slot.location == rule.location and counted(slot):
                slots_by_position[slot.position].append(slot)
        weighted, total, found = 0.0, 0, []
        for position, slots in sorted(slots_by_position.items()):
            people = [
                e for e in self.employees_of(rule.location) if position in e.positions and self.slots_of.get(e.id)
            ]
            if len(people) < 2:
                continue
            loads = {e.id: len({s.date for s in slots if self.assignment.get(s.id) == e.id}) for e in people}
            high, low = max(loads.values()), min(loads.values())
            excess = max(0, high - low - 1)
            degree = excess / high if high else 0.0
            weighted += degree * len(slots)
            total += len(slots)
            if excess:
                name = self.p.position_names.get(position, "stanowisku")
                found.append(
                    Violation(Code.RULE, f"{what} na stanowisku {name} rozłożone nierówno: od {low} do {high}.")
                )
        return _Measured(total, weighted / total if total else 0.0, tuple(found))

    def rule_fair_weekends(self, rule: RuleConfig) -> _Measured:
        return self._fairness(rule, lambda s: s.date.weekday() >= 5, "Weekendy")

    def rule_fair_closings(self, rule: RuleConfig) -> _Measured:
        return self._fairness(rule, lambda s: s.is_closing, "Zamknięcia")

    def _monthly_hours(self, rule: RuleConfig, attr: str) -> _Measured:
        shares = self.month_shares()
        instances, degree_sum, found = 0, 0.0, []
        for employee in self.employees_of(rule.location):
            monthly = getattr(employee, attr)
            if monthly is None:
                continue
            instances += 1
            hours = self.hours_by_month(employee.id)
            expected = sum(monthly * share for share in shares.values())
            total = sum(hours.values())
            if attr == "max_hours_month":
                excess = sum(max(0.0, hours.get(m, 0.0) - monthly * share - _EPS) for m, share in shares.items())
                degree = min(1.0, excess / expected) if expected else (1.0 if excess > _EPS else 0.0)
                if excess > _EPS:
                    found.append(
                        Violation(
                            Code.RULE,
                            f"{employee.name} ma {_hours_text(total)}, więcej niż swoje maksimum "
                            f"({_hours_text(expected)} w tym okresie).",
                            employee=employee.id,
                        )
                    )
            else:
                deviation = sum(abs(hours.get(m, 0.0) - monthly * share) for m, share in shares.items())
                degree = min(1.0, deviation / expected) if expected else (1.0 if deviation > _EPS else 0.0)
                if degree > TARGET_HOURS_HARD_TOLERANCE + _EPS:
                    found.append(
                        Violation(
                            Code.RULE,
                            f"{employee.name} ma {_hours_text(total)}, a cel to {_hours_text(expected)} w tym okresie.",
                            employee=employee.id,
                        )
                    )
            degree_sum += degree
        return _Measured(instances, degree_sum / instances if instances else 0.0, tuple(found))

    def rule_target_hours(self, rule: RuleConfig) -> _Measured:
        return self._monthly_hours(rule, "target_hours_month")

    def rule_personal_max_hours(self, rule: RuleConfig) -> _Measured:
        return self._monthly_hours(rule, "max_hours_month")

    def rule_preferred_shift_type_for_position(self, rule: RuleConfig) -> _Measured:
        position, shift_type = rule.params.get("position"), rule.params.get("shift_type")
        if not position or not shift_type:
            return _Measured(0, 0.0, ())
        instances, found = 0, []
        for slot in self.p.slots:
            employee_id = self.assignment.get(slot.id)
            if slot.location != rule.location or slot.position != position or employee_id is None:
                continue
            instances += 1
            if slot.shift_type != shift_type:
                found.append(
                    Violation(
                        Code.RULE,
                        f"{self.name(employee_id)} ma inną porę niż ustalona dla stanowiska: "
                        f"{_slot_text(slot, self.p)}.",
                        employee=employee_id,
                        slots=(slot.id,),
                    )
                )
        return _Measured(instances, _ratio(len(found), instances), tuple(found))

    def rule_min_position_on_closing(self, rule: RuleConfig) -> _Measured:
        position = rule.params.get("position")
        if not position:
            return _Measured(0, 0.0, ())
        need = int(rule.params.get("count") or 1)
        closings: dict[tuple[date, str], list[Slot]] = defaultdict(list)
        for slot in self.p.slots:
            if slot.location == rule.location and slot.is_closing:
                closings[(slot.date, slot.shift_type)].append(slot)
        found = []
        for (_, _), slots in sorted(closings.items()):
            people = {self.assignment.get(s.id) for s in slots} - {None}
            have = sum(1 for e in people if position in self.p.employee_by_id[e].positions)
            if have < need:
                name = self.p.position_names.get(position, "wybranego stanowiska")
                found.append(
                    Violation(
                        Code.RULE,
                        f"Na zamknięciu {_slot_text(slots[0], self.p)} brakuje osoby ze stanowiska {name}.",
                        slots=tuple(s.id for s in slots),
                    )
                )
        return _Measured(len(closings), _ratio(len(found), len(closings)), tuple(found))

    def _per_week(self, rule: RuleConfig, broken: Callable[[list[Slot]], bool], message: str) -> _Measured:
        instances, found = 0, []
        for employee in self.employees_of(rule.location):
            weeks: dict[date, list[Slot]] = defaultdict(list)
            for slot in self.slots_of.get(employee.id, ()):
                weeks[_week_start(slot.date)].append(slot)
            for monday, slots in sorted(weeks.items()):
                instances += 1
                if broken(slots):
                    found.append(
                        Violation(
                            Code.RULE,
                            message.format(name=employee.name, week=f"{monday:%d.%m}"),
                            employee=employee.id,
                            slots=tuple(s.id for s in slots),
                        )
                    )
        return _Measured(instances, _ratio(len(found), instances), tuple(found))

    def rule_same_shift_type_in_week(self, rule: RuleConfig) -> _Measured:
        return self._per_week(
            rule,
            lambda slots: len({s.shift_type for s in slots}) > 1,
            "{name} ma w tygodniu od {week} różne pory zmian.",
        )

    def rule_max_shifts_per_week(self, rule: RuleConfig) -> _Measured:
        limit = int(rule.params["shifts"])
        return self._per_week(
            rule, lambda slots: len(slots) > limit, f"{{name}} ma w tygodniu od {{week}} więcej niż {limit} zmian."
        )

    def measure_rules(self) -> list[RuleMeasure]:
        measures = []
        for location in self.p.locations:
            for rule in self.p.rules_for(location):
                measured: _Measured = getattr(self, f"rule_{rule.code}")(rule)
                violations = tuple(
                    Violation(v.code, v.message, v.employee, v.slots, rule.code, rule.location)
                    for v in measured.violations
                )
                measures.append(
                    RuleMeasure(
                        location=rule.location,
                        code=rule.code,
                        rank=rule.rank,
                        hard=rule.hard,
                        instances=measured.instances,
                        degree=min(1.0, max(0.0, measured.degree)),
                        violations=violations,
                    )
                )
                if rule.hard:
                    self.hard.extend(violations)
        return measures

    # ----------------------------------------------------------------- employee requests

    def measure_requests(self) -> list[RequestMeasure]:
        p, weights = self.p, self.p.weights
        result: list[RequestMeasure] = []
        prefer_days: dict[str, int] = defaultdict(int)
        for entry in p.availability:
            if not p.period_start <= entry.date <= p.period_end:
                continue
            if entry.state == AvailabilityState.PREFER:
                prefer_days[entry.employee] += 1
            elif entry.state == AvailabilityState.PREFER_NOT:
                worked = any(
                    s.date == entry.date and p.availability_for(entry.employee, s) == AvailabilityState.PREFER_NOT
                    for s in self.slots_of.get(entry.employee, ())
                )
                result.append(
                    RequestMeasure(
                        location=p.employee_by_id[entry.employee].home_location,
                        employee=entry.employee,
                        kind=RequestKind.PREFER_NOT,
                        weight=weights.request_weight(RequestLevel.IMPORTANT),
                        degree=1.0 if worked else 0.0,
                        date=entry.date,
                    )
                )
        for employee_id, count in sorted(prefer_days.items()):
            slots = self.slots_of.get(employee_id, ())
            worked_days = {s.date for s in slots}
            hits = {s.date for s in slots if p.availability_for(employee_id, s) == AvailabilityState.PREFER}
            possible = min(count, len(worked_days))
            result.append(
                RequestMeasure(
                    location=p.employee_by_id[employee_id].home_location,
                    employee=employee_id,
                    kind=RequestKind.PREFER,
                    weight=weights.request_weight(RequestLevel.NICE_TO_HAVE),
                    degree=1 - len(hits) / possible if possible else 0.0,
                )
            )
        for request in p.requests:
            degree = self.request_degree(request)
            if degree is None:
                continue
            result.append(
                RequestMeasure(
                    location=p.employee_by_id[request.employee].home_location,
                    employee=request.employee,
                    kind=RequestKind.TEXT,
                    weight=weights.request_weight(request.level, request.manager_priority),
                    degree=min(1.0, max(0.0, degree)),
                    request_id=request.id,
                )
            )
        return result

    def request_degree(self, request: Request) -> float | None:
        """0 = kept … 1 = fully broken; None = not something the schedule can keep (scored by nobody)."""
        own = [s for s in self.slots_of.get(request.employee, ()) if request.covers(s.date)]
        match request.type:
            case RequestType.AVOID_PERSON | RequestType.PREFER_PERSON:
                if request.subject_employee is None:
                    return None
                if not own:
                    return 0.0
                theirs = self.slots_of.get(request.subject_employee, ())
                together = sum(
                    1
                    for s in own
                    if any(
                        o.location == s.location and o.start_utc < s.end_utc and s.start_utc < o.end_utc for o in theirs
                    )
                )
                if request.type == RequestType.AVOID_PERSON:
                    return together / len(own)
                return 1 - together / len(own)
            case RequestType.SHIFT_TYPE:
                if request.shift_type is None:
                    return None
                if not own:
                    return 0.0
                wrong = sum(1 for s in own if (s.shift_type == request.shift_type) == request.avoid)
                return wrong / len(own)
            case RequestType.HOURS_LIMIT:
                if request.max_hours is None:
                    return None
                hours = sum(s.hours for s in own)
                if request.max_hours <= 0:
                    return 1.0 if hours > _EPS else 0.0
                return max(0.0, hours - request.max_hours) / request.max_hours
            case _:
                return None

    # ----------------------------------------------------------------- everything

    def run(self) -> ValidationReport:
        self.check_basic()
        self.check_overlaps()
        self.check_labor_law()
        rules = self.measure_rules()
        requests = self.measure_requests()
        holes = tuple(s.id for s in self.p.slots if self.assignment.get(s.id) is None)
        published = self.p.published
        changes = tuple(
            s.id for s in self.p.slots if s.id in published and self.assignment.get(s.id) != published[s.id]
        )
        hours = {e.id: round(sum(s.hours for s in self.slots_of.get(e.id, ())), 4) for e in self.p.employees}
        return ValidationReport(
            hard=tuple(self.hard),
            holes=holes,
            rules=tuple(rules),
            requests=tuple(requests),
            stability_changes=changes,
            hours=MappingProxyType(hours),
        )


def validate(problem: Problem, schedule: Schedule) -> ValidationReport:
    """Check `schedule` against `problem`. Never raises for a bad schedule; every problem is in the report."""
    return _Checker(problem, schedule).run()


def is_valid(problem: Problem, schedule: Schedule) -> bool:
    return validate(problem, schedule).ok


__all__ = [
    "LABOR_DAILY_REST",
    "LABOR_MAX_HOURS_PER_DAY",
    "LABOR_WEEKLY_REST",
    "TARGET_HOURS_HARD_TOLERANCE",
    "Code",
    "RequestKind",
    "RequestMeasure",
    "RuleMeasure",
    "ValidationReport",
    "Violation",
    "is_valid",
    "validate",
]
