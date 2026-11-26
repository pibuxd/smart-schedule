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
from dataclasses import dataclass, field, replace
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone

from apps.assistant import readings
from apps.assistant.models import AssistantRuleSet, ManagerInstruction
from apps.availability.models import AvailabilityDay, TextRequest
from apps.rules.models import RuleSetting
from apps.rules.models import WeightProfile as WeightProfileModel
from apps.rules.services import merge, rule_configs
from apps.scheduling.models import Assignment, SchedulePeriod, ScheduleVersion, Shift
from apps.staffing.models import (
    EmployeeProfile,
    LocationClosure,
    Position,
    PositionExperience,
    ShiftType,
    StaffingException,
    StaffingRule,
    works_in_q,
)
from apps.tenancy.models import Location
from engine.problem import (
    EXPERIENCED,
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


def _min_days(data) -> int | None:
    value = data.get("min_days")
    return value if isinstance(value, int) and value >= 1 else None


def _shifts_per_day(data) -> int:
    value = data.get("shifts_per_day")
    return value if isinstance(value, int) and 1 <= value <= 3 else 1


def _max_shifts(data: dict) -> int | None:
    value = data.get("max_shifts")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _target_hours(data: dict) -> float | None:
    value = data.get("target_hours") if data.get("type") == "cel_godzin" else None
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) and value > 0 else None


def _preferred_dates(data: dict, start: date, end: date) -> frozenset[date]:
    """cel_godzin: the days of the period the hours should rather fall on ("najlepiej pod koniec tygodnia")."""
    week = data.get("prefer_weekdays") if data.get("type") == "cel_godzin" else None
    return frozenset(readings.dates_in({"weekdays": week}, start, end)) if isinstance(week, list) else frozenset()


def _positions(data: dict) -> frozenset[str]:
    """stanowisko: the position's ids (one per location of the person); other types have none."""
    values = data.get("positions") if data.get("type") == "stanowisko" else None
    return frozenset(str(v) for v in values) if isinstance(values, list) else frozenset()


REQUEST_TYPES = {
    "unikaj_osoby": RequestType.AVOID_PERSON,
    "preferuj_osobe": RequestType.PREFER_PERSON,
    "typ_zmiany": RequestType.SHIFT_TYPE,
    "stanowisko": RequestType.POSITION,
    "limit_godzin": RequestType.HOURS_LIMIT,
    "limit_zmian": RequestType.SHIFTS_LIMIT,
    "cel_godzin": RequestType.HOURS_TARGET,
    "wolne_dni": RequestType.DAYS_OFF,
    "chce_pracowac": RequestType.WANT_WORK,
    "inne": RequestType.OTHER,
}


def request_dates(data: dict, start: date, end: date) -> set[date]:
    dates = readings.dates_in(data, start, end)
    if dates and data.get("hours_period") == "week":
        # Include covered dates just outside the period for already published shifts in the same week.
        dates = readings.dates_in(
            data, start - timedelta(days=start.weekday()), end + timedelta(days=6 - end.weekday())
        )
    return dates


def instruction_request(data, employee_id, instruction_id, rank, start, end, names, shift_names) -> Request | None:
    kind = REQUEST_TYPES.get(str(data.get("type")))
    subject = str(data["subject_employee"]) if data.get("subject_employee") else None
    dates = request_dates(data, start, end)
    if (
        kind in (None, RequestType.OTHER)
        or employee_id not in names
        or (subject is not None and subject not in names)
        or (readings.has_days(data) and not dates)
    ):
        return None
    max_hours = data.get("max_hours")
    return Request(
        id=f"instruction:{instruction_id}",
        employee=employee_id,
        type=kind,
        dates=frozenset(dates),
        subject_employee=subject,
        shift_type=str(data["shift_type"]) if data.get("shift_type") else None,
        avoid=bool(data.get("avoid", False)),
        positions=_positions(data),
        max_hours=float(max_hours) if isinstance(max_hours, int | float) else None,
        max_shifts=_max_shifts(data),
        target_hours=_target_hours(data),
        at_least=_target_hours(data) is not None and data.get("at_least") is True,
        preferred_dates=_preferred_dates(data, start, end),
        weekly_hours=data.get("hours_period") == "week",
        daily_hours=data.get("hours_period") == "day",
        min_days=_min_days(data),
        shifts_per_day=_shifts_per_day(data),
        summary=readings.describe(data, names[employee_id], names, shift_names),
        by_manager=True,
        rank=rank,
    )


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


def _keep_pinned_beginners(slots: list[Slot], pinned: dict, employees: dict) -> list[Slot]:
    """The manager may keep fewer experienced people than the staffing asks (a pinned manual change). Arranging
    again then asks for experience only on the places the pinned people leave, instead of failing."""
    groups: dict[tuple, list[Slot]] = defaultdict(list)
    for slot in slots:
        if slot.needs_experienced:
            groups[(slot.location, slot.date, slot.shift_type, slot.position)].append(slot)
    if not groups:
        return slots
    released: set[str] = set()
    for key, marked in groups.items():
        group = [s for s in slots if (s.location, s.date, s.shift_type, s.position) == key]
        beginners = sum(
            1
            for s in group
            if (e := pinned.get(s.id)) and e in employees and employees[e].level(s.position) != EXPERIENCED
        )
        excess = beginners - (len(group) - len(marked))
        released.update(s.id for s in marked[len(marked) - excess :] if excess > 0)
    return [replace(s, needs_experienced=False) if s.id in released else s for s in slots]


def _employee_name(profile: EmployeeProfile) -> str:
    return profile.membership.user.full_name or "Pracownik bez imienia"


class _Reader:
    # Shifts from the newest drafts of other locations count as taken (only when generating; editing and
    # publishing check the published schedules of other locations).
    include_drafts = True
    arranging = True  # building the problem for the generator (a saved version is read as it is)

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
            closed = set(
                self.qs(LocationClosure)
                .filter(location=period.location, date__range=(self.start, self.end))
                .values_list("date", flat=True)
            )
            slots += self._staffing_slots(period.location, frozen_days | closed)
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
                    needs_experienced=shift.needs_experienced,
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
        # (count, start, end, how many of them experienced)
        weekly: dict[int, dict[tuple, tuple[int, time | None, time | None, int]]] = defaultdict(dict)
        for rule in self.qs(StaffingRule).filter(location=location):
            weekly[rule.weekday][(rule.shift_type_id, rule.position_id)] = (
                rule.count,
                rule.start_time,
                rule.end_time,
                rule.experienced,
            )
        exceptions: dict[date, dict[tuple, tuple[int, time | None, time | None, int]]] = defaultdict(dict)
        for exc in self.qs(StaffingException).filter(location=location, date__range=(self.start, self.end)):
            exceptions[exc.date][(exc.shift_type_id, exc.position_id)] = (
                exc.count,
                exc.start_time,
                exc.end_time,
                exc.experienced,
            )

        slots, missing_hours = [], set()
        for day in _days(self.start, self.end):
            if day in skip_days:
                continue
            demand = dict(weekly.get(day.weekday(), {}))
            for key, (count, start, end, experienced) in exceptions.get(day, {}).items():
                base = demand.get(key)
                if start is None and base is not None:  # an exception without hours keeps the usual hours
                    start, end = base[1], base[2]
                demand[key] = (count, start, end, experienced)
            for (shift_type_id, position_id), (count, start, end, experienced) in sorted(demand.items(), key=str):
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
                            needs_experienced=place <= experienced,
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

    def assignments(
        self, version: ScheduleVersion | None, keys: set[str], pinned_only: bool = False, forced_only: bool = False
    ):
        if version is None:
            return {}
        rows = self.qs(Assignment).filter(shift__version=version, shift__slot_key__in=keys)
        if pinned_only:
            rows = rows.filter(pinned=True)  # a pinned hole stays empty
        if forced_only:
            rows = rows.filter(forced=True, employee__isnull=False)
        return {
            key: str(employee) if employee else None
            for key, employee in rows.values_list("shift__slot_key", "employee")
        }

    def employees(self, referenced: set[str]) -> list[Employee]:
        rows = list(
            self.qs(EmployeeProfile)
            .filter(Q(works_in_q(self.location_ids), is_active=True) | Q(pk__in=referenced))
            .select_related("membership__user")
            .order_by("pk")
        )
        ids = [p.pk for p in rows]
        extra: dict = defaultdict(set)
        for profile_id, location_id in EmployeeProfile.extra_locations.through.objects.filter(  # tenant-ok: profiles
            employeeprofile_id__in=ids
        ).values_list("employeeprofile_id", "location_id"):
            extra[profile_id].add(location_id)
        here_ids = set(self.location_ids)

        def works_here(p: EmployeeProfile) -> bool:
            return p.home_location_id in here_ids or bool(extra[p.pk] & here_ids)

        # A person from another location (borrowed, or taking a given-away shift) counts as having a position
        # here when one of their own positions has the same name (positions are per location).
        here = defaultdict(set)
        for pk, name in self.qs(Position).filter(location__in=self.location_ids).values_list("pk", "name"):
            here[name.casefold()].add(str(pk))
        away = {p.pk for p in rows if not works_here(p)}
        positions: dict = defaultdict(set)
        for profile_id, position_id, name in EmployeeProfile.positions.through.objects.filter(
            employeeprofile_id__in=ids
        ).values_list("employeeprofile_id", "position_id", "position__name"):
            positions[profile_id].add(str(position_id))
            if profile_id in away:
                positions[profile_id] |= here.get(name.casefold(), set())
        # Levels set for single positions; a person from another location carries the level to the positions
        # of the same name here, like the positions themselves.
        levels: dict = defaultdict(dict)
        for profile_id, position_id, name, level in (
            self.qs(PositionExperience)
            .filter(employee_id__in=ids)
            .values_list("employee_id", "position_id", "position__name", "level")
        ):
            if str(position_id) not in positions[profile_id]:
                continue  # a level left over for a position the person no longer has
            levels[profile_id][str(position_id)] = level
            if profile_id in away:
                for twin in here.get(name.casefold(), set()):
                    levels[profile_id][twin] = level
        return [
            Employee(
                id=str(p.pk),
                name=_employee_name(p),
                home_location=str(p.home_location_id),
                extra_locations=frozenset(str(loc) for loc in extra[p.pk]),
                positions=frozenset(positions[p.pk]),
                max_hours_month=p.max_hours_month,
                target_hours_month=p.target_hours_month,
                experience=p.experience,
                experience_by_position=levels[p.pk],
                available=p.is_active and works_here(p),
            )
            for p in rows
        ]

    def availability(self, employee_ids: list[str]) -> list[Availability]:
        rows = self.qs(AvailabilityDay).filter(
            employee__in=employee_ids, date__range=(self.start - EXTERNAL_MARGIN, self.end + EXTERNAL_MARGIN)
        )
        return [
            Availability(
                str(a.employee_id),
                a.date,
                a.state,
                a.from_time,
                a.to_time,
                from_time_2=a.from_time_2,
                to_time_2=a.to_time_2,
                one_shift=a.one_shift,
            )
            for a in rows
        ]

    def external_versions(self) -> list:
        """Versions of other periods whose shifts the same people already have: the published one of each period,
        and (when generating) its newest draft instead, if there is one newer, so that locations arranged one after
        another do not give a person the same hours twice (docs/plan.md, section 27)."""
        statuses = [ScheduleVersion.Status.PUBLISHED]
        if self.include_drafts:
            statuses.append(ScheduleVersion.Status.DRAFT)
        newest: dict = {}
        rows = (
            self.qs(ScheduleVersion)
            .filter(
                status__in=statuses,
                period__start__lte=self.end + EXTERNAL_MARGIN,
                period__end__gte=self.start - EXTERNAL_MARGIN,
            )
            .exclude(period__in=self.periods)
            .order_by("number")
            .values_list("pk", "period_id")
        )
        for version_id, period_id in rows:
            newest[period_id] = version_id
        return list(newest.values())

    def external_shifts(self, employee_ids: list[str]) -> list[ExternalShift]:
        rows = (
            self.qs(Assignment)
            .filter(
                employee__in=employee_ids,
                shift__version__in=self.external_versions(),
                shift__date__range=(self.start - EXTERNAL_MARGIN, self.end + EXTERNAL_MARGIN),
            )
            .select_related("shift", "shift__location", "shift__version")
        )
        return [
            ExternalShift(
                employee=str(a.employee_id),
                date=a.shift.date,
                start=a.shift.start_at.astimezone(self.tz),
                end=a.shift.end_at.astimezone(self.tz),
                label=f"{a.shift.date:%d.%m} {a.shift.location.name}"
                + (" (szkic)" if a.shift.version.status == ScheduleVersion.Status.DRAFT else ""),
            )
            for a in rows
        ]

    # ----------------------------------------------------------------- rules, requests, weights

    def rules(self) -> list[RuleConfig]:
        result = []
        for location in self.locations:
            group_rows = self.qs(RuleSetting).filter(group_id=location.group_id) if location.group_id else []
            rows = merge(group_rows, self.qs(RuleSetting).filter(location=location))
            from apps.assistant.agreements import rule_rows

            agreement = self.qs(AssistantRuleSet).filter(location=location, period__in=self.periods).first()
            snapshot = rule_rows(agreement)
            if snapshot is not None:
                rows = snapshot
            result += rule_configs(str(location.id), rows)
        return result

    def requests(self, employee_ids: set[str]) -> list[Request]:
        result = []
        rows = (
            self.qs(TextRequest)
            .filter(TextRequest.for_periods(self.periods), manager_rejected=False)
            .select_related("period")
        )
        for row in rows.exclude(
            status__in=[TextRequest.Status.REJECTED, TextRequest.Status.ANSWERED, TextRequest.Status.SUPERSEDED]
        ).order_by("created_at"):
            employee_id = str(row.employee_id)
            if employee_id not in employee_ids:
                continue
            data = readings.saved_reading(row.interpretation, row.text)
            interpreted = row.status == TextRequest.Status.INTERPRETED
            # A lasting request carried over from an earlier month keeps only its lasting wishes here.
            carried = not row.is_own(self.periods)
            # One message may hold several wishes: the first at the top, the others in `more` (ids "<pk>:2", …).
            parts = [data, *(data.get("more") or [])] if interpreted else [data]
            for number, part in enumerate(parts, start=1):
                if carried and part.get("lasting") is False:
                    continue
                request = self._text_request(row, part, interpreted, employee_ids)
                if request is not None:
                    if number > 1:
                        request = replace(request, id=f"{row.pk}:{number}")
                    result.append(request)
        return result + self.instructions(employee_ids)

    def _text_request(self, row: TextRequest, data: dict, interpreted: bool, employee_ids: set[str]) -> Request | None:
        if interpreted and readings.calendar_only(data):
            return None  # "nie mogę od 9 do 11": only marked in the calendar ("mogę" outside those hours)
        employee_id = str(row.employee_id)
        kind = REQUEST_TYPES.get(str(data.get("type")), RequestType.OTHER) if interpreted else RequestType.OTHER
        subject = data.get("subject_employee")
        subject = str(subject) if subject and str(subject) in employee_ids else None
        if kind in (RequestType.AVOID_PERSON, RequestType.PREFER_PERSON) and subject is None:
            kind = RequestType.OTHER
        level = data.get("level")
        dates = request_dates(data, self.start, self.end)
        if readings.has_days(data) and not dates:
            return None  # about days outside this period: nothing to keep here
        max_hours = data.get("max_hours")
        return Request(
            id=str(row.pk),
            employee=employee_id,
            type=kind,
            level=level if level in RequestLevel._value2member_map_ else RequestLevel.IMPORTANT,
            manager_priority=row.manager_priority,
            dates=frozenset(dates),
            subject_employee=subject,
            shift_type=str(data["shift_type"]) if data.get("shift_type") else None,
            avoid=bool(data.get("avoid", False)),
            positions=_positions(data),
            max_hours=float(max_hours) if isinstance(max_hours, int | float) else None,
            max_shifts=_max_shifts(data),
            target_hours=_target_hours(data),
            at_least=_target_hours(data) is not None and data.get("at_least") is True,
            preferred_dates=_preferred_dates(data, self.start, self.end),
            weekly_hours=data.get("hours_period") == "week",
            daily_hours=data.get("hours_period") == "day",
            min_days=_min_days(data),
            shifts_per_day=_shifts_per_day(data),
            summary=str(data.get("part_summary") or data.get("summary") or row.text[:200]),
            # A request for a month (no period) or a lasting one is about the person: it counts where they work.
            location=str(row.period.location_id) if row.period_id and not row.lasting else None,
        )

    def instructions(self, employee_ids: set[str]) -> list[Request]:
        """The manager's instructions about people: scored with the manager's rules, ranked by their place."""
        rows = (
            self.qs(ManagerInstruction)
            .filter(location__in=self.locations)
            .filter(Q(rule_set__period__in=self.periods) | Q(rule_set__isnull=True))
            .select_related("employee__membership__user")
            .order_by("location_id", "position", "created_at")
        )
        people = self.qs(EmployeeProfile).filter(pk__in=employee_ids).select_related("membership__user")
        names = {str(e.pk): _employee_name(e) for e in people}
        shift_names = {str(s.pk): s.name for s in self.qs(ShiftType).filter(location__in=self.locations)}
        result, places = [], {}
        for row in rows:
            data = readings.saved_reading(row.data, row.source_text)
            employee_id = str(row.employee_id)
            rank = places.get(row.location_id, 0) + 1
            request = instruction_request(
                data, employee_id, str(row.pk), rank, self.start, self.end, names, shift_names
            )
            if request is not None:
                places[row.location_id] = rank
                result.append(replace(request, location=str(row.location_id)))
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

    def forced(self, slots: Sequence[Slot], published: dict, pinned: dict) -> dict[str, str]:
        """The manager's overrides that still stand when arranging again: on a pinned slot (newest version) or
        on a day that has passed (published version), as long as that person keeps the slot."""
        keys = {s.id for s in slots}
        fixed = {s.id: published[s.id] for s in slots if s.date < self.today and s.id in published}
        fixed.update(pinned)
        marked: dict[str, str] = {}
        for period in self.periods:
            marked.update(self.assignments(self.published.get(period.id), keys, forced_only=True))
            marked.update(self.assignments(self.latest.get(period.id), keys, pinned_only=True, forced_only=True))
        return {key: employee for key, employee in marked.items() if fixed.get(key) == employee}

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
        pinned: dict[str, str | None] = {}
        for period in self.periods:
            published.update(self.assignments(self.published.get(period.id), keys))
            pinned.update(self.assignments(self.latest.get(period.id), keys, pinned_only=True))
        referenced = {e for e in (*published.values(), *pinned.values()) if e}
        employees = self.employees(referenced)
        if self.arranging:
            slots = _keep_pinned_beginners(slots, pinned, {e.id: e for e in employees})
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
            forced=self.forced(slots, published, pinned),
            external_shifts=tuple(self.external_shifts(employee_ids)),
            position_names=self.position_names(),
        )
        return BuiltProblem(problem=problem, periods=self.periods, sources=self.sources, notes=self.notes)


class _VersionReader(_Reader):
    """The slots and people of one saved version, as they were (not as the settings say today)."""

    include_drafts = False
    arranging = False

    def __init__(self, version: ScheduleVersion, extra_employees: Sequence[str] = ()) -> None:
        # No frozen days: the version is read as a whole.
        super().__init__([version.period], today=version.period.start)
        self.version = version
        self.extra_employees = {str(e) for e in extra_employees}
        self.latest = {version.period_id: version}  # pins of this version, not of a newer one

    def slots(self) -> list[Slot]:
        by_day = self._published_slots(self.version)
        return [slot for day in sorted(by_day) for slot in by_day[day]]

    def forced(self, slots: Sequence[Slot], published: dict, pinned: dict) -> dict[str, str]:
        return self.assignments(self.version, {s.id for s in slots}, forced_only=True)

    def employees(self, referenced: set[str]) -> list[Employee]:
        in_version = self.qs(Assignment).filter(shift__version=self.version, employee__isnull=False)
        in_version = {str(e) for e in in_version.values_list("employee", flat=True)}
        return super().employees(referenced | in_version | self.extra_employees)


def build_problem_for_version(
    version: ScheduleVersion, extra_employees: Sequence[str] = ()
) -> tuple[BuiltProblem, dict[str, str | None]]:
    """A saved version described for the engine, with its schedule (slot id -> employee id or None).
    `extra_employees`: people from anywhere in the company to check as candidates (e.g. for a given-away shift),
    with their calendar and their published shifts elsewhere."""
    version = ScheduleVersion.objects.select_related("period__location").get(pk=version.pk)
    reader = _VersionReader(version, extra_employees)
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
