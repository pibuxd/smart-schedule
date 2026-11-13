"""The scheduling task as plain data: what the solver, validator and scoring all work on. No Django.

The Django layer (`apps.scheduling`, stage 5) reads the database and builds one `Problem`. Everything in here is
immutable and identified by string ids (the database UUIDs as text), so the engine can be tested without a database.

Times: every slot carries timezone-aware start and end. Durations and gaps are always computed in UTC, so a shift
over a daylight-saving change has its real length (22:00–06:00 is 9 h on the last Sunday of October in Warsaw).
Dates (`Slot.date`, availability, weeks, months) are local calendar dates of the location; a shift belongs to the
date it starts on, also when it ends after midnight.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from functools import cached_property
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

from engine.rules_catalog import RULES_BY_CODE, validate_params

DEFAULT_TIMEZONE = "Europe/Warsaw"


class ProblemError(ValueError):
    """The problem description is inconsistent (a bug in the code that built it, not a user mistake)."""


class AvailabilityState(StrEnum):
    CANNOT = "cannot"
    PREFER_NOT = "prefer_not"
    NEUTRAL = "neutral"
    PREFER = "prefer"


class RequestType(StrEnum):
    """Text requests after interpretation (stage 10). Polish names in the spec: unikaj_osoby, preferuj_osobe, …"""

    AVOID_PERSON = "avoid_person"
    PREFER_PERSON = "prefer_person"
    SHIFT_TYPE = "shift_type"
    HOURS_LIMIT = "hours_limit"
    OTHER = "other"  # read by the manager, not scored


class RequestLevel(StrEnum):
    VERY_IMPORTANT = "bardzo_wazne"
    IMPORTANT = "wazne"
    NICE_TO_HAVE = "mile_widziane"


class ManagerPriority(StrEnum):
    LOWER = "lower"
    NORMAL = "normal"
    HIGHER = "higher"


def _freeze(mapping: Mapping[Any, Any] | None) -> Mapping[Any, Any]:
    return MappingProxyType(dict(mapping or {}))


def local_datetime(day: date, at: time, tz: ZoneInfo) -> datetime:
    """`day` + `at` on the location's wall clock. A time skipped by DST (02:30 in spring) maps to the instant
    an hour later (03:30); a repeated time (02:30 in autumn) is its first occurrence."""
    naive = datetime.combine(day, at)
    aware = naive.replace(tzinfo=tz)
    # Round-trip through UTC to normalise a non-existent wall time to a real instant.
    return aware.astimezone(UTC).astimezone(tz)


def shift_bounds(day: date, start: time, end: time, tz: ZoneInfo | str = DEFAULT_TIMEZONE) -> tuple[datetime, datetime]:
    """Start and end of a shift that begins on `day`. End at or before start means the shift ends the next day."""
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    end_day = day + timedelta(days=1) if end <= start else day
    return local_datetime(day, start, zone), local_datetime(end_day, end, zone)


def _require_aware(value: datetime, what: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProblemError(f"{what} must be timezone-aware")


@dataclass(frozen=True)
class Employee:
    id: str
    name: str
    home_location: str
    positions: frozenset[str]
    max_hours_month: float | None = None  # personal maximum (soft rule personal_max_hours)
    target_hours_month: float | None = None  # soft rule target_hours
    # False for someone switched off (or borrowed from another location) who only keeps the shifts they already
    # have in this problem (pins, past days): the generator gives them nothing new. The validator ignores it.
    available: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", frozenset(self.positions))


@dataclass(frozen=True)
class Slot:
    """One person needed on one shift: date × shift type × position × place number (`id` is the stable slot key)."""

    id: str
    location: str
    date: date
    shift_type: str
    position: str
    start: datetime
    end: datetime
    shift_name: str = ""
    is_closing: bool = False

    def __post_init__(self) -> None:
        _require_aware(self.start, f"Slot {self.id} start")
        _require_aware(self.end, f"Slot {self.id} end")
        if self.end_utc <= self.start_utc:
            raise ProblemError(f"Slot {self.id} ends before it starts")

    @property
    def start_utc(self) -> datetime:
        return self.start.astimezone(UTC)

    @property
    def end_utc(self) -> datetime:
        return self.end.astimezone(UTC)

    @property
    def hours(self) -> float:
        return (self.end_utc - self.start_utc).total_seconds() / 3600


@dataclass(frozen=True)
class ExternalShift:
    """A shift the employee already has outside this problem (previous period, another location's published
    schedule). It is fixed: it only counts for overlaps, rest and hours in a day."""

    employee: str
    date: date
    start: datetime
    end: datetime
    label: str = ""

    def __post_init__(self) -> None:
        _require_aware(self.start, "External shift start")
        _require_aware(self.end, "External shift end")
        if self.end_utc <= self.start_utc:
            raise ProblemError("External shift ends before it starts")

    @property
    def start_utc(self) -> datetime:
        return self.start.astimezone(UTC)

    @property
    def end_utc(self) -> datetime:
        return self.end.astimezone(UTC)


@dataclass(frozen=True)
class Availability:
    """An employee's mark for one day. Without hours it covers every shift that starts that day.

    With hours (`from_time`/`to_time`, either may be open) it covers a window on that day's wall clock; an end
    at or before the start means the next morning (e.g. 22:00-06:00 for a night shift):
    - "cannot" and "prefer not" apply to shifts that overlap the window ("nie mogę od 8 do 12");
    - "prefer" and "neutral" mean "I can only in these hours": a shift that fits inside the window gets that
      state, any other shift of that day counts as "cannot" (people mark the hours they can
      work).
    No entry for a day means "neutral" (nothing submitted).
    """

    employee: str
    date: date
    state: AvailabilityState
    from_time: time | None = None
    to_time: time | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", AvailabilityState(self.state))
        if self.from_time is not None and self.from_time == self.to_time:
            raise ProblemError("Availability hours must not start and end at the same time")


@dataclass(frozen=True)
class Request:
    """A text request after interpretation. Requests rejected by the manager are not passed in at all."""

    id: str
    employee: str
    type: RequestType
    level: RequestLevel = RequestLevel.IMPORTANT
    manager_priority: ManagerPriority = ManagerPriority.NORMAL
    dates: frozenset[date] = frozenset()  # empty = the whole period
    subject_employee: str | None = None  # avoid_person / prefer_person
    shift_type: str | None = None  # shift_type
    avoid: bool = False  # shift_type: True = "not this shift type", False = "only this shift type"
    max_hours: float | None = None  # hours_limit, over the dates of the request (or the whole period)
    summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", RequestType(self.type))
        object.__setattr__(self, "level", RequestLevel(self.level))
        object.__setattr__(self, "manager_priority", ManagerPriority(self.manager_priority))
        object.__setattr__(self, "dates", frozenset(self.dates))

    def covers(self, day: date) -> bool:
        return not self.dates or day in self.dates


@dataclass(frozen=True)
class RuleConfig:
    """A catalog rule switched on for one location (group settings already resolved by the Django layer).

    `rank` is the place on the location's list (1 = most important); only the order matters.
    """

    code: str
    location: str
    rank: int
    hard: bool = False
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.code not in RULES_BY_CODE:
            raise ProblemError(f"Unknown rule code: {self.code}")
        problems = validate_params(self.code, dict(self.params))
        if problems:
            raise ProblemError(f"Rule {self.code}: {', '.join(problems)}")
        merged = {**RULES_BY_CODE[self.code].params, **dict(self.params)}
        object.__setattr__(self, "params", _freeze(merged))


def default_level_weights() -> dict[str, float]:
    """Same defaults as `apps.rules.models.default_level_weights` (kept in sync by a test)."""
    return {"bardzo_wazne": 9.0, "wazne": 3.0, "mile_widziane": 1.0, "manager_higher": 2.0, "manager_lower": 0.5}


@dataclass(frozen=True)
class WeightProfile:
    manager_share: float = 0.8
    level_weights: Mapping[str, float] = field(default_factory=default_level_weights)
    rank_decay: float = 0.75
    # Cost of changing one published assignment, in points of the 0–100 combined score.
    stability_penalty: float = 5.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "level_weights", _freeze({**default_level_weights(), **dict(self.level_weights)}))
        if not 0 <= self.manager_share <= 1:
            raise ProblemError("manager_share must be between 0 and 1")
        if not 0 < self.rank_decay <= 1:
            raise ProblemError("rank_decay must be in (0, 1]")

    def rule_weight(self, place: int) -> float:
        """Weight of the soft rule at `place` (1-based) among a location's soft rules."""
        return self.rank_decay ** (place - 1)

    def request_weight(self, level: RequestLevel, priority: ManagerPriority = ManagerPriority.NORMAL) -> float:
        weight = self.level_weights[str(level)]
        if priority == ManagerPriority.HIGHER:
            weight *= self.level_weights["manager_higher"]
        elif priority == ManagerPriority.LOWER:
            weight *= self.level_weights["manager_lower"]
        return weight


@dataclass(frozen=True)
class Problem:
    """Everything needed to build or check the schedule of one period (one location or a whole group)."""

    period_start: date
    period_end: date  # inclusive
    employees: tuple[Employee, ...]
    slots: tuple[Slot, ...]
    availability: tuple[Availability, ...] = ()
    rules: tuple[RuleConfig, ...] = ()
    requests: tuple[Request, ...] = ()
    weights: WeightProfile = field(default_factory=WeightProfile)
    timezone: str = DEFAULT_TIMEZONE
    # slot id -> employee id that the manager pinned there.
    pinned: Mapping[str, str] = field(default_factory=dict)
    # The published schedule being replaced (slot id -> employee id or None for a hole), for stability and freezing.
    published: Mapping[str, str | None] = field(default_factory=dict)
    # Slots dated before this day keep their published assignment (days that have passed).
    frozen_before: date | None = None
    external_shifts: tuple[ExternalShift, ...] = ()
    # Display names for messages (position id -> name); ids are used where a name is missing.
    position_names: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("employees", "slots", "availability", "rules", "requests", "external_shifts"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "pinned", _freeze(self.pinned))
        object.__setattr__(self, "published", _freeze(self.published))
        object.__setattr__(self, "position_names", _freeze(self.position_names))
        self._check()

    def _check(self) -> None:
        if self.period_end < self.period_start:
            raise ProblemError("Period ends before it starts")
        ZoneInfo(self.timezone)
        if len(self.employee_by_id) != len(self.employees):
            raise ProblemError("Duplicate employee id")
        if len(self.slot_by_id) != len(self.slots):
            raise ProblemError("Duplicate slot id")
        for slot in self.slots:
            if not self.period_start <= slot.date <= self.period_end:
                raise ProblemError(f"Slot {slot.id} is outside the period")
        known = self.employee_by_id
        for item in (*self.availability, *self.external_shifts):
            if item.employee not in known:
                raise ProblemError(f"Unknown employee {item.employee}")
        if len({(a.employee, a.date) for a in self.availability}) != len(self.availability):
            raise ProblemError("More than one availability entry for an employee and day")
        for request in self.requests:
            if request.employee not in known:
                raise ProblemError(f"Request {request.id}: unknown employee")
            if request.subject_employee is not None and request.subject_employee not in known:
                raise ProblemError(f"Request {request.id}: unknown subject employee")
        if len({(r.location, r.code) for r in self.rules}) != len(self.rules):
            raise ProblemError("A rule is configured twice for one location")
        for slot_id, employee_id in self.pinned.items():
            if slot_id not in self.slot_by_id or employee_id not in known:
                raise ProblemError(f"Pin on {slot_id} refers to an unknown slot or employee")

    @cached_property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @cached_property
    def employee_by_id(self) -> Mapping[str, Employee]:
        return _freeze({e.id: e for e in self.employees})

    @cached_property
    def slot_by_id(self) -> Mapping[str, Slot]:
        return _freeze({s.id: s for s in self.slots})

    @cached_property
    def availability_by_key(self) -> Mapping[tuple[str, date], Availability]:
        return _freeze({(a.employee, a.date): a for a in self.availability})

    @cached_property
    def locations(self) -> tuple[str, ...]:
        return tuple(sorted({s.location for s in self.slots} | {e.home_location for e in self.employees}))

    def rules_for(self, location: str) -> tuple[RuleConfig, ...]:
        return tuple(sorted((r for r in self.rules if r.location == location), key=lambda r: r.rank))

    def availability_window(self, entry: Availability) -> tuple[datetime, datetime]:
        """The covered window of an availability entry as real instants (UTC)."""
        start = local_datetime(entry.date, entry.from_time or time(0), self.tz)
        if entry.to_time is None:
            end = local_datetime(entry.date + timedelta(days=1), time(0), self.tz)
        elif entry.to_time <= (entry.from_time or time(0)):  # ends the next morning
            end = local_datetime(entry.date + timedelta(days=1), entry.to_time, self.tz)
        else:
            end = local_datetime(entry.date, entry.to_time, self.tz)
        return start.astimezone(UTC), end.astimezone(UTC)

    def availability_for(self, employee_id: str, slot: Slot) -> AvailabilityState:
        """The availability state that applies to `employee_id` working `slot` (NEUTRAL when none applies)."""
        entry = self.availability_by_key.get((employee_id, slot.date))
        if entry is None:
            return AvailabilityState.NEUTRAL
        if entry.from_time is None and entry.to_time is None:
            return entry.state
        window_start, window_end = self.availability_window(entry)
        if entry.state in (AvailabilityState.PREFER, AvailabilityState.NEUTRAL):
            fits = window_start <= slot.start_utc and slot.end_utc <= window_end
            return entry.state if fits else AvailabilityState.CANNOT
        overlaps = slot.start_utc < window_end and window_start < slot.end_utc
        return entry.state if overlaps else AvailabilityState.NEUTRAL


Schedule = Mapping[str, str | None]
"""A schedule: slot id -> employee id, or None (or a missing key) for an unfilled slot."""
