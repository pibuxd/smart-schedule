"""Reads one or more schedule periods from the database and describes them as an `engine.problem.Problem`.

Everything company-specific is resolved here, so the engine only sees plain data:

- slots from the weekly staffing table and the date exceptions; a flexible shift without hours stops the run
  (days that have passed keep the shifts of the published version, so a later change of settings does not
  rewrite history);
- active employees of the locations, plus anyone already in a pinned or past slot;
- rules of the location group with the location's own changes on top, in one list ordered by importance;
- text requests: interpreted ones as their type, unread or unclear ones as "other" (left to the manager);
- the published version (for stability and frozen days), pins from the newest version, and published shifts of
  the same people in other periods or locations (for rest and overlaps).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from apps.availability.models import AvailabilityDay, TextRequest
from apps.rules.models import RuleSetting
from apps.rules.models import WeightProfile as WeightProfileModel
from apps.rules.services import merge, rule_configs
from apps.scheduling.models import Assignment, SchedulePeriod, ScheduleVersion, Shift
from apps.staffing.models import EmployeeProfile, Position, ShiftType, StaffingException, StaffingRule
from apps.tenancy.models import Location
from engine.problem import (
    Availability,
    Employee,
    ExternalShift,
    Problem,
    Request,
    RequestLevel,
    RequestType,
    RuleConfig,
    Slot,
    WeightProfile,
    shift_bounds,
)

# How far around the period published shifts of the same people are read (rest, days in a row, weekly rest).
EXTERNAL_MARGIN = timedelta(days=7)

REQUEST_TYPES = {
    "unikaj_osoby": RequestType.AVOID_PERSON,
    "preferuj_osobe": RequestType.PREFER_PERSON,
    "typ_zmiany": RequestType.SHIFT_TYPE,
    "limit_godzin": RequestType.HOURS_LIMIT,
    "inne": RequestType.OTHER,
}


class BuildError(Exception):
    """The periods cannot be generated together; the message is a Polish sentence for the manager."""


@dataclass(frozen=True)
class SlotSource:
    """Where a slot of the problem comes from, to save it back as a `Shift`."""

    location_id: str
    shift_type_id: str | None
    position_id: str


@dataclass
class BuiltProblem:
    problem: Problem
    periods: list[SchedulePeriod]
    sources: dict[str, SlotSource]
    # Notes for the manager about settings that could not be used (e.g. a flexible shift without hours).
    notes: list[str] = field(default_factory=list)

    def period_of(self, location_id: str) -> SchedulePeriod:
        return next(p for p in self.periods if str(p.location_id) == location_id)


def slot_key(day: date, shift_type_id: str, position_id: str, place: int) -> str:
    """Stable between versions: the same date, shift, position and place number is the same slot."""
    return f"{day.isoformat()}/{shift_type_id}/{position_id}/{place}"


def _days(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def check_periods(periods: Sequence[SchedulePeriod]) -> None:
    """Periods generated together must be one company's, have the same dates and (if several) share a group."""
    if not periods:
        raise BuildError("Wybierz okres grafiku.")
    first = periods[0]
    if len({p.company_id for p in periods}) > 1:
        raise BuildError("Okresy należą do różnych firm.")
    if len({p.location_id for p in periods}) != len(periods):
        raise BuildError("Każdy lokal może mieć tylko jeden okres w jednym układaniu grafiku.")
    if any(p.start != first.start or p.end != first.end for p in periods):
        raise BuildError("Grafik dla kilku lokali naraz można ułożyć tylko dla okresów o tych samych datach.")
    if len(periods) > 1:
        groups = {p.location.group_id for p in periods}
        if len(groups) != 1 or None in groups:
            raise BuildError("Grafik dla kilku lokali naraz można ułożyć tylko w ramach jednej grupy lokali.")
    if len({p.location.timezone for p in periods}) > 1:
        raise BuildError("Lokale w różnych strefach czasowych trzeba układać osobno.")


def _employee_name(profile: EmployeeProfile) -> str:
    return profile.membership.user.full_name or "Pracownik bez imienia"


class _Reader:
    def __init__(self, periods: Sequence[SchedulePeriod], today: date | None) -> None:
        check_periods(periods)
        self.periods = list(periods)
        self.company_id = periods[0].company_id
        self.start, self.end = periods[0].start, periods[0].end
        self.locations = [p.location for p in periods]
        self.location_ids = [loc.id for loc in self.locations]
        self.tz = ZoneInfo(self.locations[0].timezone)
        self.today = today or timezone.localdate(timezone=self.tz)
        self.notes: list[str] = []
        self.sources: dict[str, SlotSource] = {}

        versions = ScheduleVersion.objects.for_company(self.company_id).filter(period__in=self.periods)
        self.published = {v.period_id: v for v in versions.filter(status=ScheduleVersion.Status.PUBLISHED)}
        self.latest: dict = {}
        for version in versions.order_by("number"):
            self.latest[version.period_id] = version

    def qs(self, model):
        return model.objects.for_company(self.company_id)

    # ----------------------------------------------------------------- slots

    def slots(self) -> list[Slot]:
        slots: list[Slot] = []
        for period in self.periods:
            published = self.published.get(period.id)
            frozen_days: set[date] = set()
            if published is not None:
                # Days that have passed keep the published shifts (also days where nobody was needed).
                frozen_days = {day for day in _days(self.start, self.end) if day < self.today}
                by_day = self._published_slots(published)
                slots += [slot for day in sorted(frozen_days) for slot in by_day.get(day, [])]
            slots += self._staffing_slots(period.location, frozen_days)
        return slots

    def _published_slots(self, version: ScheduleVersion) -> dict[date, list[Slot]]:
        result: dict[date, list[Slot]] = defaultdict(list)
        for shift in self.qs(Shift).filter(version=version).select_related("shift_type"):
            key = shift.slot_key
            shift_type = shift.shift_type
            result[shift.date].append(
                Slot(
                    id=key,
                    location=str(shift.location_id),
                    date=shift.date,
                    shift_type=str(shift.shift_type_id or ""),
                    position=str(shift.position_id),
                    start=shift.start_at.astimezone(self.tz),
                    end=shift.end_at.astimezone(self.tz),
                    shift_name=shift_type.name if shift_type else "",
                    is_closing=bool(shift_type and shift_type.is_closing),
                )
            )
            self.sources[key] = SlotSource(
                str(shift.location_id),
                str(shift.shift_type_id) if shift.shift_type_id else None,
                str(shift.position_id),
            )
        return result

    def _staffing_slots(self, location: Location, skip_days: set[date]) -> list[Slot]:
        shift_types = {st.id: st for st in self.qs(ShiftType).filter(location=location)}
        weekly: dict[int, dict[tuple, tuple[int, time | None, time | None]]] = defaultdict(dict)
        for rule in self.qs(StaffingRule).filter(location=location):
            weekly[rule.weekday][(rule.shift_type_id, rule.position_id)] = (rule.count, rule.start_time, rule.end_time)
        exceptions: dict[date, dict[tuple, tuple[int, time | None, time | None]]] = defaultdict(dict)
        for exc in self.qs(StaffingException).filter(location=location, date__range=(self.start, self.end)):
            exceptions[exc.date][(exc.shift_type_id, exc.position_id)] = (exc.count, exc.start_time, exc.end_time)

        slots, missing_hours = [], set()
        for day in _days(self.start, self.end):
            if day in skip_days:
                continue
            demand = dict(weekly.get(day.weekday(), {}))
            for key, (count, start, end) in exceptions.get(day, {}).items():
                base = demand.get(key)
                if start is None and base is not None:  # an exception without hours keeps the usual hours
                    start, end = base[1], base[2]
                demand[key] = (count, start, end)
            for (shift_type_id, position_id), (count, start, end) in sorted(demand.items(), key=str):
                if not count:
                    continue
                shift_type = shift_types[shift_type_id]
                start, end = start or shift_type.start_time, end or shift_type.end_time
                if start is None or end is None or start == end:
                    missing_hours.add(shift_type.name)
                    continue
                begin, finish = shift_bounds(day, start, end, self.tz)
                for place in range(1, count + 1):
                    key = slot_key(day, str(shift_type_id), str(position_id), place)
                    slots.append(
                        Slot(
                            id=key,
                            location=str(location.id),
                            date=day,
                            shift_type=str(shift_type_id),
                            position=str(position_id),
                            start=begin,
                            end=finish,
                            shift_name=shift_type.name,
                            is_closing=shift_type.is_closing,
                        )
                    )
                    self.sources[key] = SlotSource(str(location.id), str(shift_type_id), str(position_id))
        if missing_hours:
            # Skipping these would hide a whole unstaffed shift (no slot, so no hole): stop and say what to fix.
            names = ", ".join(f"„{name}”" for name in sorted(missing_hours))
            raise BuildError(
                f"W lokalu {location.name} zmiana {names} ma dowolne godziny, ale w obsadzie nie ustawiono, "
                "od której do której. Uzupełnij godziny w ustawieniach lokalu i ułóż grafik ponownie."
            )
        return slots

    # ----------------------------------------------------------------- people

    def assignments(self, version: ScheduleVersion | None, keys: set[str], pinned_only: bool = False):
        if version is None:
            return {}
        rows = self.qs(Assignment).filter(shift__version=version, shift__slot_key__in=keys)
        if pinned_only:
            rows = rows.filter(pinned=True, employee__isnull=False)
        return {
            key: str(employee) if employee else None
            for key, employee in rows.values_list("shift__slot_key", "employee")
        }

    def employees(self, referenced: set[str]) -> list[Employee]:
        rows = list(
            self.qs(EmployeeProfile)
            .filter(Q(home_location__in=self.location_ids, is_active=True) | Q(pk__in=referenced))
            .select_related("membership__user")
            .order_by("pk")
        )
        ids = [p.pk for p in rows]
        positions: dict = defaultdict(set)
        for profile_id, position_id in EmployeeProfile.positions.through.objects.filter(
            employeeprofile_id__in=ids
        ).values_list("employeeprofile_id", "position_id"):
            positions[profile_id].add(str(position_id))
        return [
            Employee(
                id=str(p.pk),
                name=_employee_name(p),
                home_location=str(p.home_location_id),
                positions=frozenset(positions[p.pk]),
                contract=p.contract,
                max_hours_month=p.max_hours_month,
                target_hours_month=p.target_hours_month,
                available=p.is_active and p.home_location_id in self.location_ids,
            )
            for p in rows
        ]

    def availability(self, employee_ids: list[str]) -> list[Availability]:
        rows = self.qs(AvailabilityDay).filter(
            employee__in=employee_ids, date__range=(self.start - EXTERNAL_MARGIN, self.end + EXTERNAL_MARGIN)
        )
        return [Availability(str(a.employee_id), a.date, a.state, a.from_time, a.to_time) for a in rows]

    def external_shifts(self, employee_ids: list[str]) -> list[ExternalShift]:
        rows = (
            self.qs(Assignment)
            .filter(
                employee__in=employee_ids,
                shift__version__status=ScheduleVersion.Status.PUBLISHED,
                shift__date__range=(self.start - EXTERNAL_MARGIN, self.end + EXTERNAL_MARGIN),
            )
            .exclude(shift__version__period__in=self.periods)
            .select_related("shift", "shift__location")
        )
        return [
            ExternalShift(
                employee=str(a.employee_id),
                date=a.shift.date,
                start=a.shift.start_at.astimezone(self.tz),
                end=a.shift.end_at.astimezone(self.tz),
                label=f"{a.shift.date:%d.%m} {a.shift.location.name}",
            )
            for a in rows
        ]

    # ----------------------------------------------------------------- rules, requests, weights

    def rules(self) -> list[RuleConfig]:
        result = []
        for location in self.locations:
            group_rows = self.qs(RuleSetting).filter(group_id=location.group_id) if location.group_id else []
            rows = merge(group_rows, self.qs(RuleSetting).filter(location=location))
            result += rule_configs(str(location.id), rows)
        return result

    def requests(self, employee_ids: set[str]) -> list[Request]:
        result = []
        rows = self.qs(TextRequest).filter(period__in=self.periods, manager_rejected=False)
        for row in rows.exclude(status=TextRequest.Status.REJECTED).order_by("created_at"):
            employee_id = str(row.employee_id)
            if employee_id not in employee_ids:
                continue
            data = row.interpretation or {}
            kind = RequestType.OTHER
            if row.status == TextRequest.Status.INTERPRETED:
                kind = REQUEST_TYPES.get(str(data.get("type")), RequestType.OTHER)
            subject = data.get("subject_employee")
            subject = str(subject) if subject and str(subject) in employee_ids else None
            if kind in (RequestType.AVOID_PERSON, RequestType.PREFER_PERSON) and subject is None:
                kind = RequestType.OTHER
            level = data.get("level")
            dates = set()
            for value in data.get("dates") or []:
                try:
                    dates.add(date.fromisoformat(str(value)))
                except ValueError:
                    continue
            max_hours = data.get("max_hours")
            result.append(
                Request(
                    id=str(row.pk),
                    employee=employee_id,
                    type=kind,
                    level=level if level in RequestLevel._value2member_map_ else RequestLevel.IMPORTANT,
                    manager_priority=row.manager_priority,
                    dates=frozenset(dates),
                    subject_employee=subject,
                    shift_type=str(data["shift_type"]) if data.get("shift_type") else None,
                    avoid=bool(data.get("avoid", False)),
                    max_hours=float(max_hours) if isinstance(max_hours, int | float) else None,
                    summary=str(data.get("summary") or row.text[:200]),
                )
            )
        return result

    def weights(self) -> WeightProfile:
        """The location's profile for a single location, else the group's; defaults when neither exists."""
        profiles = self.qs(WeightProfileModel)
        profile = None
        if len(self.locations) == 1:
            profile = profiles.filter(location=self.locations[0]).first()
        group_id = self.locations[0].group_id
        if profile is None and group_id:
            profile = profiles.filter(group_id=group_id).first()
        if profile is None:
            return WeightProfile()
        return WeightProfile(
            manager_share=float(profile.manager_share),
            level_weights=profile.level_weights or {},
            rank_decay=float(profile.rank_decay),
            stability_penalty=float(profile.stability_penalty),
        )

    def position_names(self) -> dict[str, str]:
        return {
            str(pk): name
            for pk, name in self.qs(Position).filter(location__in=self.location_ids).values_list("pk", "name")
        }

    # ----------------------------------------------------------------- everything

    def build(self) -> BuiltProblem:
        slots = self.slots()
        keys = {s.id for s in slots}
        published: dict[str, str | None] = {}
        pinned: dict[str, str] = {}
        for period in self.periods:
            published.update(self.assignments(self.published.get(period.id), keys))
            pinned.update(self.assignments(self.latest.get(period.id), keys, pinned_only=True))
        referenced = {e for e in published.values() if e} | set(pinned.values())
        employees = self.employees(referenced)
        employee_ids = [e.id for e in employees]
        problem = Problem(
            period_start=self.start,
            period_end=self.end,
            employees=tuple(employees),
            slots=tuple(slots),
            availability=tuple(self.availability(employee_ids)),
            rules=tuple(self.rules()),
            requests=tuple(self.requests(set(employee_ids))),
            weights=self.weights(),
            timezone=str(self.tz),
            pinned=pinned,
            published=published,
            frozen_before=self.today,
            external_shifts=tuple(self.external_shifts(employee_ids)),
            position_names=self.position_names(),
        )
        return BuiltProblem(problem=problem, periods=self.periods, sources=self.sources, notes=self.notes)


class _VersionReader(_Reader):
    """The slots and people of one saved version, as they were (not as the settings say today)."""

    def __init__(self, version: ScheduleVersion) -> None:
        # No frozen days: the version is read as a whole.
        super().__init__([version.period], today=version.period.start)
        self.version = version

    def slots(self) -> list[Slot]:
        by_day = self._published_slots(self.version)
        return [slot for day in sorted(by_day) for slot in by_day[day]]

    def employees(self, referenced: set[str]) -> list[Employee]:
        in_version = self.qs(Assignment).filter(shift__version=self.version, employee__isnull=False)
        return super().employees(referenced | {str(e) for e in in_version.values_list("employee", flat=True)})


def build_problem_for_version(version: ScheduleVersion) -> tuple[BuiltProblem, dict[str, str | None]]:
    """A saved version described for the engine, with its schedule (slot id -> employee id or None)."""
    version = ScheduleVersion.objects.select_related("period__location").get(pk=version.pk)
    reader = _VersionReader(version)
    built = reader.build()
    schedule = reader.assignments(version, {s.id for s in built.problem.slots})
    return built, schedule


def build_problem(periods: Sequence[SchedulePeriod], today: date | None = None) -> BuiltProblem:
    """Describe `periods` (one location, or the same dates in every location of a group) for the engine."""
    periods = list(SchedulePeriod.objects.filter(pk__in=[p.pk for p in periods]).select_related("location"))
    return _Reader(sorted(periods, key=lambda p: p.location.name), today).build()


__all__ = [
    "BuildError",
    "BuiltProblem",
    "SlotSource",
    "build_problem",
    "build_problem_for_version",
    "check_periods",
    "slot_key",
]
