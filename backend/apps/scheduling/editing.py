"""Looking at a schedule version, editing it by hand, and publishing it.

- `load_version` reads a saved version for the engine (its own slots, people and pins) and validates it.
- `check_changes` / `apply_changes`: a manual change (who works which slot) is validated by the same validator as
  the generator's result; a change that would add a hard problem is refused with the validator's sentences.
  Only the newest version of a period can be edited, and only while it is a draft; days that have passed cannot.
- `add_seat` / `remove_seat`: one more or one fewer place on a shift of one day. The same number is saved as that
  date's staffing (`apps.staffing.day_staffing`), so arranging the schedule again keeps it.
- `start_draft`: editing a published schedule starts a new draft copy (publishing makes it the published one).
- `publish`: the draft becomes the published version, the previous one is kept as history, the history of
  assignments (`AssignmentEvent`) gets one row for every slot whose person changed, open offers of given-away
  shifts follow the slot (or end, when the giver lost it), and the employees of the location get an in-app notice.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from apps.notifications.models import Notification
from apps.scheduling.models import Assignment, AssignmentEvent, SchedulePeriod, ScheduleVersion, Shift
from apps.scheduling.problem_builder import BuiltProblem, build_problem_for_version, slot_key
from apps.staffing import day_staffing
from apps.staffing.models import EmployeeProfile, LocationClosure, Position, ShiftType
from engine.explain import new_soft_violations, without_pin
from engine.problem import Problem, shift_bounds
from engine.scoring import Scores, score
from engine.validator import Code, ValidationReport, Violation, validate

# Hard rules the manager may break by hand (docs/plan.md, section 24, point 7): the generator always keeps them,
# but a manual change, a removed place or publishing is not refused; the manager sees them as a warning.
MANAGER_MAY_BREAK = frozenset({Code.EXPERIENCE})


def blocking(violations) -> list[Violation]:
    """Hard problems that stop a manual change or publishing."""
    return [v for v in violations if v.code not in MANAGER_MAY_BREAK]


def accepted(violations) -> list[Violation]:
    """Hard problems the manager is allowed to keep (shown as a warning, never refused)."""
    return [v for v in violations if v.code in MANAGER_MAY_BREAK]


NOT_EDITABLE = "Ten grafik jest już opublikowany albo jest starszą wersją. Zacznij poprawki od najnowszej wersji."


@dataclass
class LoadedVersion:
    version: ScheduleVersion
    built: BuiltProblem
    schedule: dict[str, str | None]
    report: ValidationReport

    @property
    def problem(self) -> Problem:
        return self.built.problem

    @property
    def location_id(self) -> str:
        return str(self.version.period.location_id)

    @property
    def scores(self) -> Scores:
        return score(self.problem, self.report, location=self.location_id)


def load_version(version: ScheduleVersion) -> LoadedVersion:
    built, schedule = build_problem_for_version(version)
    return LoadedVersion(version, built, schedule, validate(built.problem, schedule))


def latest_version(period: SchedulePeriod) -> ScheduleVersion | None:
    return ScheduleVersion.objects.for_company(period.company_id).filter(period=period).order_by("-number").first()


def is_editable(version: ScheduleVersion) -> bool:
    if version.status != ScheduleVersion.Status.DRAFT:
        return False
    newest = latest_version(version.period)
    return newest is not None and newest.pk == version.pk


def save_scores(version: ScheduleVersion, scores: Scores) -> None:
    notes = (version.scores or {}).get("notes", [])
    version.scores = {**scores.as_dict(), "notes": notes}
    version.is_complete = scores.is_complete
    version.save(update_fields=["scores", "is_complete"])


# ----------------------------------------------------------------------------------------------- manual changes


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    problems: list[str]  # new hard problems (Polish sentences); empty when ok
    warnings: list[str]  # new broken soft rules, for information
    before: Scores
    after: Scores


def _resolve(loaded: LoadedVersion, changes: Mapping[str, str | None], today: date) -> dict[str, str | None]:
    """shift id -> employee id, translated to slot keys; refuses unknown shifts and days that have passed."""
    shifts = {
        str(pk): (key, day)
        for pk, key, day in Shift.objects.for_company(loaded.version.company_id)
        .filter(version=loaded.version, pk__in=list(changes))
        .values_list("pk", "slot_key", "date")
    }
    result = {}
    for shift_id, employee_id in changes.items():
        if shift_id not in shifts:
            raise HttpError(404, "Nie ma takiej zmiany w tym grafiku.")
        key, day = shifts[shift_id]
        if day < today:
            raise HttpError(409, "Ten dzień już minął, więc tej zmiany nie można poprawić.")
        result[key] = employee_id
    return result


def check_changes(
    loaded: LoadedVersion, changes: Mapping[str, str | None], today: date | None = None
) -> tuple[CheckResult, dict[str, str | None]]:
    """Validate the version with `changes` (shift id -> employee id or None) applied; nothing is saved."""
    today = today or timezone.localdate()
    by_key = _resolve(loaded, changes, today)
    problem = loaded.problem
    for key in by_key:  # a manual change moves the pin to the new person
        problem = without_pin(problem, key)
    before = validate(problem, loaded.schedule)
    after_schedule = {**loaded.schedule, **by_key}
    after = validate(problem, after_schedule)
    known = {v.message for v in before.hard}
    problems = [v.message for v in blocking(after.hard) if v.message not in known]
    warnings = [v.message for v in accepted(after.hard) if v.message not in known] + new_soft_violations(before, after)
    result = CheckResult(
        ok=not problems,
        problems=problems,
        warnings=warnings[:5],
        before=score(problem, before, location=loaded.location_id),
        after=score(problem, after, location=loaded.location_id),
    )
    return result, by_key


def apply_changes(version: ScheduleVersion, changes: Mapping[str, str | None], user) -> CheckResult:
    """Save a manual change of people. Refused (409) when it adds a hard problem or the version is not editable."""
    with transaction.atomic():
        version = ScheduleVersion.objects.select_for_update().get(pk=version.pk)
        if not is_editable(version):
            raise HttpError(409, NOT_EDITABLE)
        loaded = load_version(version)
        result, by_key = check_changes(loaded, changes)
        if not result.ok:
            raise HttpError(409, "Tej zmiany nie można zapisać: " + " ".join(result.problems))
        home = {e.id: e.home_location for e in loaded.problem.employees}
        rows = Assignment.objects.for_company(version.company_id).filter(
            shift__version=version, shift__slot_key__in=list(by_key)
        )
        for assignment in rows.select_related("shift"):
            employee_id = by_key[assignment.shift.slot_key]
            if str(assignment.employee_id or "") == str(employee_id or ""):
                continue
            assignment.employee_id = employee_id
            assignment.manual = True
            assignment.borrowed = employee_id is not None and home.get(employee_id) != str(assignment.shift.location_id)
            # A new person (or a hole) is not pinned until the manager pins it, as check_changes assumed.
            assignment.pinned = False
            assignment.save(update_fields=["employee", "manual", "borrowed", "pinned"])
        save_scores(version, result.after)
    return result


def set_pinned(version: ScheduleVersion, shift_id: str, pinned: bool) -> Assignment:
    """Pin a person to a slot, or keep an empty slot empty: arranging the schedule again keeps it as it is."""
    with transaction.atomic():
        version = ScheduleVersion.objects.select_for_update().get(pk=version.pk)
        if not is_editable(version):
            raise HttpError(409, NOT_EDITABLE)
        assignment = (
            Assignment.objects.for_company(version.company_id)
            .filter(shift__version=version, shift_id=shift_id)
            .select_related("shift")
            .first()
        )
        if assignment is None:
            raise HttpError(404, "Nie ma takiej zmiany w tym grafiku.")
        assignment.pinned = pinned
        assignment.save(update_fields=["pinned"])
    return assignment


# ----------------------------------------------------------------------------------------------- places on a shift

DAY_PASSED = "Ten dzień już minął, więc jego obsady nie można zmienić."


def _seats(version: ScheduleVersion, prefix: str) -> list[Shift]:
    """The places of one shift and position on one day, in the order of their place numbers."""
    rows = Shift.objects.for_company(version.company_id).filter(version=version, slot_key__startswith=prefix)
    return sorted(rows.select_related("assignment"), key=lambda s: int(s.slot_key.rsplit("/", 1)[1]))


def _mark_experienced(version, location, day, shift_type, position, seats: list[Shift]) -> None:
    """The first N places of the day need an experienced person, N = the date's staffing (as arranging numbers them)."""
    need = day_staffing.day_experienced(location, day, shift_type, position)
    for number, seat in enumerate(seats, start=1):
        wanted = number <= need
        if seat.needs_experienced != wanted:
            seat.needs_experienced = wanted
            seat.save(update_fields=["needs_experienced"])


def add_seat(version: ScheduleVersion, day: date, shift_type: ShiftType, position: Position) -> Shift:
    """One more place (empty) on this shift and position that day, in the draft and in the date's staffing."""
    with transaction.atomic():
        version = ScheduleVersion.objects.select_for_update().select_related("period__location").get(pk=version.pk)
        if not is_editable(version):
            raise HttpError(409, NOT_EDITABLE)
        period, location = version.period, version.period.location
        if not period.start <= day <= period.end:
            raise HttpError(400, "Ten dzień jest poza okresem tego grafiku.")
        if day < timezone.localdate():
            raise HttpError(409, DAY_PASSED)
        if LocationClosure.objects.for_company(version.company_id).filter(location=location, date=day).exists():
            raise HttpError(409, "Lokal jest tego dnia zamknięty. Najpierw usuń ten dzień z dni zamknięcia.")
        seats = _seats(version, slot_key(day, str(shift_type.pk), str(position.pk), 0)[:-1])
        if seats:
            start_at, end_at = seats[0].start_at, seats[0].end_at
        else:
            start, end = day_staffing.day_hours(location, day, shift_type, position)
            if start is None or end is None:
                raise HttpError(
                    409,
                    f"Zmiana „{shift_type.name}” ma dowolne godziny. Ustaw je na ten dzień w ustawieniach lokalu, "
                    "w kalendarzu obsady.",
                )
            start_at, end_at = shift_bounds(day, start, end, ZoneInfo(location.timezone))
        place = int(seats[-1].slot_key.rsplit("/", 1)[1]) + 1 if seats else 1
        shift = Shift.objects.create(
            company_id=version.company_id,
            version=version,
            location=location,
            date=day,
            shift_type=shift_type,
            position=position,
            start_at=start_at,
            end_at=end_at,
            slot_key=slot_key(day, str(shift_type.pk), str(position.pk), place),
        )
        Assignment.objects.create(company_id=version.company_id, shift=shift)
        day_staffing.set_day_count(location, day, shift_type, position, len(seats) + 1)
        _mark_experienced(version, location, day, shift_type, position, [*seats, shift])
        save_scores(version, load_version(version).scores)
    return shift


def remove_seat(version: ScheduleVersion, shift_id: str) -> None:
    """One place fewer on this shift that day; whoever had this place loses it. The other places keep their people
    and their numbers stay 1…n, as arranging the schedule again would number them. Refused (409) when the
    schedule would break a hard rule it kept before (e.g. a beginner left without an experienced person)."""
    with transaction.atomic():
        version = ScheduleVersion.objects.select_for_update().select_related("period__location").get(pk=version.pk)
        if not is_editable(version):
            raise HttpError(409, NOT_EDITABLE)
        shift = Shift.objects.for_company(version.company_id).filter(version=version, pk=shift_id).first()
        if shift is None:
            raise HttpError(404, "Nie ma takiej zmiany w tym grafiku.")
        if shift.date < timezone.localdate():
            raise HttpError(409, DAY_PASSED)
        known = {v.message for v in load_version(version).report.hard}
        seats = _seats(version, shift.slot_key.rsplit("/", 1)[0] + "/")
        last = seats[-1]
        if last.pk != shift.pk:
            kept, removed = last.assignment, next(s for s in seats if s.pk == shift.pk).assignment
            for name in ("employee_id", "pinned", "manual", "borrowed"):
                setattr(removed, name, getattr(kept, name))
            removed.save(update_fields=["employee", "pinned", "manual", "borrowed"])
        last.delete()
        if shift.shift_type is not None:  # a deleted shift type has no staffing to change
            day_staffing.set_day_count(
                version.period.location, shift.date, shift.shift_type, shift.position, len(seats) - 1
            )
            _mark_experienced(
                version, version.period.location, shift.date, shift.shift_type, shift.position, seats[:-1]
            )
        loaded = load_version(version)
        problems = [v.message for v in blocking(loaded.report.hard) if v.message not in known]
        if problems:  # like any manual change; raising here undoes the removal
            raise HttpError(409, "Tego miejsca nie można usunąć: " + " ".join(problems))
        save_scores(version, loaded.scores)


# ----------------------------------------------------------------------------------------------- drafts, publishing


def lock_period(version: ScheduleVersion) -> None:
    """Lock the company row, then the period. Generation also locks the company first, so publishing while a
    schedule is being queued waits instead of deadlocking (same lock order everywhere)."""
    from apps.tenancy.models import Company

    Company.objects.select_for_update().filter(pk=version.company_id).first()
    SchedulePeriod.objects.select_for_update().filter(pk=version.period_id).first()


def start_draft(version: ScheduleVersion, user) -> ScheduleVersion:
    """A new draft copy of `version` to correct (the newest draft itself when there already is one)."""
    with transaction.atomic():
        lock_period(version)
        newest = latest_version(version.period)
        if newest is not None and newest.status == ScheduleVersion.Status.DRAFT:
            return newest
        number = (newest.number if newest else 0) + 1
        copy = ScheduleVersion.objects.create(
            company_id=version.company_id,
            period=version.period,
            number=number,
            created_by=user,
            scores=version.scores,
            is_complete=version.is_complete,
        )
        shifts = Shift.objects.for_company(version.company_id).filter(version=version).select_related("assignment")
        shifts = list(shifts)
        new_shifts = Shift.objects.bulk_create(
            Shift(
                company_id=s.company_id,
                version=copy,
                location_id=s.location_id,
                date=s.date,
                shift_type_id=s.shift_type_id,
                position_id=s.position_id,
                start_at=s.start_at,
                end_at=s.end_at,
                slot_key=s.slot_key,
                needs_experienced=s.needs_experienced,
            )
            for s in shifts
        )
        old = {s.slot_key: s.assignment for s in shifts}
        Assignment.objects.bulk_create(
            Assignment(
                company_id=s.company_id,
                shift=s,
                employee_id=old[s.slot_key].employee_id,
                pinned=old[s.slot_key].pinned,
                borrowed=old[s.slot_key].borrowed,
                manual=old[s.slot_key].manual,
            )
            for s in new_shifts
        )
    return copy


def supersede_older_drafts(period: SchedulePeriod, newer_than: ScheduleVersion) -> None:
    ScheduleVersion.objects.for_company(period.company_id).filter(
        period=period, status=ScheduleVersion.Status.DRAFT, number__lt=newer_than.number
    ).update(status=ScheduleVersion.Status.SUPERSEDED)


def publish(version: ScheduleVersion, user, *, notify: bool = True) -> ScheduleVersion:
    """Make the draft the published schedule of its period. Holes are allowed (the screen warns); hard problems
    are not. The previous published version and older drafts become history."""
    with transaction.atomic():
        lock_period(version)
        version = ScheduleVersion.objects.select_related("period__location").get(pk=version.pk)
        if not is_editable(version):
            raise HttpError(409, "Opublikować można tylko najnowszy szkic grafiku.")
        loaded = load_version(version)
        if blocking(loaded.report.hard):
            reasons = " ".join(v.message for v in blocking(loaded.report.hard)[:5])
            raise HttpError(409, "Grafiku nie można opublikować, bo łamie reguły: " + reasons)
        period = version.period
        previous = (
            ScheduleVersion.objects.for_company(version.company_id)
            .filter(period=period, status=ScheduleVersion.Status.PUBLISHED)
            .first()
        )
        _record_history(version, previous, user)
        ScheduleVersion.objects.for_company(version.company_id).filter(
            period=period, status=ScheduleVersion.Status.PUBLISHED
        ).update(status=ScheduleVersion.Status.SUPERSEDED)
        supersede_older_drafts(period, version)
        version.status = ScheduleVersion.Status.PUBLISHED
        version.published_at = timezone.now()
        save_scores(version, loaded.scores)
        version.save(update_fields=["status", "published_at"])
        period.status = SchedulePeriod.Status.PUBLISHED
        period.save(update_fields=["status"])
        from apps.marketplace.services import refresh_after_publish

        refresh_after_publish(version, previous)
        if notify:
            _notify_published(version, first=previous is None)
    return version


def _record_history(version: ScheduleVersion, previous: ScheduleVersion | None, user) -> None:
    before: dict[str, str | None] = {}
    if previous is not None:
        before = {
            key: str(employee) if employee else None
            for key, employee in Assignment.objects.for_company(version.company_id)
            .filter(shift__version=previous)
            .values_list("shift__slot_key", "employee")
        }
    events = []
    rows = list(
        Assignment.objects.for_company(version.company_id).filter(shift__version=version).select_related("shift")
    )
    for assignment in rows:
        key = assignment.shift.slot_key
        now = str(assignment.employee_id) if assignment.employee_id else None
        was = before.get(key)
        if now == was or (now is None and key not in before):
            continue
        events.append(
            AssignmentEvent(
                company_id=version.company_id,
                location_id=assignment.shift.location_id,
                period_id=version.period_id,
                slot_key=key,
                from_employee_id=was,
                to_employee_id=now,
                reason=AssignmentEvent.Reason.MANUAL if assignment.manual else AssignmentEvent.Reason.GENERATED,
                by=user,
            )
        )
    kept = {assignment.shift.slot_key for assignment in rows}
    for key, was in before.items():  # a place that is gone (removed by hand, or the staffing got smaller)
        if was is not None and key not in kept:
            events.append(
                AssignmentEvent(
                    company_id=version.company_id,
                    location_id=version.period.location_id,
                    period_id=version.period_id,
                    slot_key=key,
                    from_employee_id=was,
                    to_employee_id=None,
                    reason=AssignmentEvent.Reason.MANUAL,
                    by=user,
                )
            )
    AssignmentEvent.objects.bulk_create(events)


def changed_people(loaded: LoadedVersion) -> list[str]:
    """Names of the people whose shifts in this draft differ from the published schedule of the same period, so
    the manager knows whom to tell before publishing a correction. Empty when nothing is published yet."""
    version = loaded.version
    if version.status != ScheduleVersion.Status.DRAFT:
        return []
    published = (
        ScheduleVersion.objects.for_company(version.company_id)
        .filter(period_id=version.period_id, status=ScheduleVersion.Status.PUBLISHED)
        .values_list("pk", flat=True)
        .first()
    )
    if published is None:
        return []
    before = {
        key: str(employee) if employee else None
        for key, employee in Assignment.objects.for_company(version.company_id)
        .filter(shift__version_id=published)
        .values_list("shift__slot_key", "employee")
    }
    affected: set[str] = set()
    for key in before.keys() | loaded.schedule.keys():  # also places that are gone from the draft
        now, was = loaded.schedule.get(key), before.get(key)
        if now != was:
            affected.update(e for e in (now, was) if e)
    names = {e.id: e.name for e in loaded.problem.employees}
    return sorted(names.get(e, "") for e in affected if names.get(e))


def _notify_published(version: ScheduleVersion, *, first: bool) -> None:
    period = version.period
    in_schedule = Assignment.objects.for_company(version.company_id).filter(
        shift__version=version, employee__isnull=False
    )
    profiles = EmployeeProfile.objects.for_company(version.company_id).filter(
        pk__in=in_schedule.values("employee")
    ) | EmployeeProfile.objects.for_company(version.company_id).filter(home_location=period.location, is_active=True)
    user_ids = set(profiles.values_list("membership__user_id", flat=True))
    payload = {
        "period_id": str(period.pk),
        "location_name": period.location.name,
        "start": period.start.isoformat(),
        "end": period.end.isoformat(),
        "changed": not first,
    }
    Notification.objects.for_company(version.company_id).bulk_create(
        Notification(company_id=version.company_id, user_id=user_id, kind="schedule_published", payload=payload)
        for user_id in sorted(user_ids, key=str)
    )


def manual_changes(version: ScheduleVersion | None) -> int:
    """Manual changes that arranging the schedule again would drop (not pinned)."""
    if version is None:
        return 0
    return (
        Assignment.objects.for_company(version.company_id)
        .filter(shift__version=version, manual=True, pinned=False)
        .count()
    )


__all__ = [
    "CheckResult",
    "LoadedVersion",
    "accepted",
    "add_seat",
    "apply_changes",
    "blocking",
    "check_changes",
    "is_editable",
    "latest_version",
    "load_version",
    "manual_changes",
    "publish",
    "remove_seat",
    "set_pinned",
    "start_draft",
]
