"""Reporting, deciding and counting other hours of a published shift (overtime or leaving early).

- `report`: an employee reports the hours they really work on one of their published shifts (at most
  `PAST_DAYS` back). It waits for the manager; a newer report of the same shift replaces the waiting one.
- `decide`: the manager approves or rejects a waiting report. Approved hours replace earlier approved ones.
- `set_hours`: the manager sets the hours alone, at once (over a waiting report too). The schedule's own hours
  bring the plan back.
- `worked_hours`: the hours that count for a list of published assignments (approved change, else the plan).
- `refresh_after_publish` / `person_left_shift`: a person who loses a published shift (a corrected schedule, or a
  change in place) loses its waiting report, and is told when approved hours of it stop counting.

The published shift keeps its planned hours: the generator, the validator and the scores read the plan. Only the
counting of hours (reports, "Mój grafik", the assistant) reads `worked_hours`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from apps.notifications.services import location_manager_ids, notify
from apps.scheduling.models import Assignment, ScheduleVersion, Shift
from apps.staffing.models import EmployeeProfile
from apps.worktime.models import HoursChange

# How far back an employee may report other hours (the manager may correct any published shift).
PAST_DAYS = 14
MAX_LENGTH = timedelta(hours=24)
REASON_MAX = 300
TIME_PATTERN = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

NOT_PUBLISHED = "Inne godziny zapisuje się tylko przy zmianie z opublikowanego grafiku."
TOO_OLD = f"Inne godziny zgłosisz najwyżej {PAST_DAYS} dni wstecz. Starszą zmianę popraw razem z kierownikiem."
SAME_HOURS = "To są te same godziny, które liczą się teraz. Nic się nie zmieniło."
TOO_LONG = "Zmiana może trwać najwyżej 24 godziny. Sprawdź godziny początku i końca."
DECIDED = "To zgłoszenie jest już rozstrzygnięte albo wycofane. Odśwież ekran."
GONE = "Ta osoba nie ma już tej zmiany w opublikowanym grafiku, więc zgłoszenie wygasło."
NOBODY = "Na tej zmianie nikogo nie ma, więc nie ma czyich godzin zmienić."


def parse_time(value: str) -> time:
    """ "6:00" or "06:00" -> time(6, 0); a Polish 400 for anything else."""
    match = TIME_PATTERN.match((value or "").strip())
    if match is None:
        raise HttpError(400, "Podaj godzinę w postaci GG:MM, np. 14:30.")
    return time(int(match.group(1)), int(match.group(2)))


def local_time(moment: datetime, tz: ZoneInfo) -> str:
    return f"{moment.astimezone(tz):%H:%M}"


def hours_between(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds() / 3600, 2)


def resolve(shift: Shift, start: time, end: time) -> tuple[datetime, datetime]:
    """Wall-clock hours of the location -> moments. The start is the day with that hour nearest to the planned
    start (a night shift may start before midnight or after it); the end is the first such hour after the start,
    so an end before the start is the next day, as in the location's shift settings."""
    tz = ZoneInfo(shift.location.timezone)
    planned = shift.start_at.astimezone(tz)
    candidates = [datetime.combine(planned.date() + timedelta(days=d), start, tzinfo=tz) for d in (-1, 0, 1)]
    start_at = min(candidates, key=lambda c: abs(c - planned))
    end_at = datetime.combine(start_at.date(), end, tzinfo=tz)
    if end_at <= start_at:
        end_at = datetime.combine(start_at.date() + timedelta(days=1), end, tzinfo=tz)
    return start_at, end_at


# ----------------------------------------------------------------------------------------------- counting


@dataclass(frozen=True)
class Worked:
    """The hours that count for one published assignment: an approved change, or the plan."""

    start_at: datetime
    end_at: datetime
    change: HoursChange | None

    @property
    def hours(self) -> float:
        return hours_between(self.start_at, self.end_at)

    @property
    def changed(self) -> bool:
        return self.change is not None

    def difference_minutes(self, shift: Shift) -> int:
        planned = (shift.end_at - shift.start_at).total_seconds()
        return round(((self.end_at - self.start_at).total_seconds() - planned) / 60)


def _key(assignment: Assignment) -> tuple[str, str, str]:
    return (str(assignment.shift.version.period_id), assignment.shift.slot_key, str(assignment.employee_id))


def _changes_for(assignments: list[Assignment], status: str) -> dict[tuple[str, str, str], HoursChange]:
    rows = [a for a in assignments if a.employee_id]
    if not rows:
        return {}
    company_id = rows[0].company_id
    changes = HoursChange.objects.for_company(company_id).filter(
        status=status,
        employee_id__in={a.employee_id for a in rows},
        period_id__in={a.shift.version.period_id for a in rows},
        slot_key__in={a.shift.slot_key for a in rows},
    )
    return {change.key: change for change in changes}


def worked_hours(assignments: Iterable[Assignment]) -> dict:
    """assignment id -> `Worked` for published assignments with a person (shift and version loaded)."""
    rows = [a for a in assignments if a.employee_id]
    approved = _changes_for(rows, HoursChange.Status.APPROVED)
    result = {}
    for assignment in rows:
        change = approved.get(_key(assignment))
        shift = assignment.shift
        if change is None:
            result[assignment.pk] = Worked(shift.start_at, shift.end_at, None)
        else:
            result[assignment.pk] = Worked(change.start_at, change.end_at, change)
    return result


def pending_reports(assignments: Iterable[Assignment]) -> dict:
    """assignment id -> the waiting report of the person on it."""
    rows = [a for a in assignments if a.employee_id]
    pending = _changes_for(rows, HoursChange.Status.PENDING)
    return {a.pk: pending[_key(a)] for a in rows if _key(a) in pending}


def current_assignments(changes: list[HoursChange]) -> dict:
    """change id -> the published assignment it is about, while the same person still has the shift (one query)."""
    if not changes:
        return {}
    published = (
        Assignment.objects.for_company(changes[0].company_id)
        .filter(
            shift__version__status=ScheduleVersion.Status.PUBLISHED,
            shift__version__period_id__in={c.period_id for c in changes},
            shift__slot_key__in={c.slot_key for c in changes},
            employee_id__in={c.employee_id for c in changes},
        )
        .select_related("shift__version", "shift__location", "shift__position")
    )
    by_key = {_key(a): a for a in published}
    return {c.pk: by_key[c.key] for c in changes if c.key in by_key}


def published_assignment(change: HoursChange) -> Assignment | None:
    """The published assignment this change is about, while the same person still has the shift."""
    return (
        Assignment.objects.for_company(change.company_id)
        .filter(
            employee_id=change.employee_id,
            shift__slot_key=change.slot_key,
            shift__version__period_id=change.period_id,
            shift__version__status=ScheduleVersion.Status.PUBLISHED,
        )
        .select_related("shift__version", "shift__location", "shift__position", "shift__shift_type")
        .first()
    )


# ----------------------------------------------------------------------------------------------- checks


def _lock_person(profile_id) -> None:
    """Changes of one person's hours wait for each other (overlap checks see each other's result)."""
    EmployeeProfile.objects.select_for_update().filter(pk=profile_id).first()


def _load(assignment_id, company_id) -> Assignment:
    assignment = (
        Assignment.objects.for_company(company_id)
        .filter(pk=assignment_id)
        .select_related(
            "shift__version", "shift__location", "shift__position", "shift__shift_type", "employee__membership__user"
        )
        .first()
    )
    if assignment is None:
        raise HttpError(404, "Nie znaleziono tej zmiany.")
    if assignment.shift.version.status != ScheduleVersion.Status.PUBLISHED:
        raise HttpError(409, NOT_PUBLISHED)
    return assignment


def _check_overlap(assignment: Assignment, start_at: datetime, end_at: datetime) -> None:
    """The new hours must not run into another published shift of the same person (any location), with the
    hours that count for that shift."""
    others = list(
        Assignment.objects.for_company(assignment.company_id)
        .filter(
            employee_id=assignment.employee_id,
            shift__version__status=ScheduleVersion.Status.PUBLISHED,
            shift__start_at__lt=end_at + MAX_LENGTH,
            shift__end_at__gt=start_at - MAX_LENGTH,
        )
        .exclude(pk=assignment.pk)
        .select_related("shift__version", "shift__location")
    )
    for other, worked in worked_hours(others).items():
        if worked.start_at < end_at and worked.end_at > start_at:
            row = next(o for o in others if o.pk == other)
            tz = ZoneInfo(row.shift.location.timezone)
            raise HttpError(
                409,
                f"Te godziny nachodzą na inną zmianę tej osoby: {_day(row.shift.date)}, "
                f"{local_time(worked.start_at, tz)}–{local_time(worked.end_at, tz)}, {row.shift.location.name}.",
            )


def _check_times(assignment: Assignment, start_at: datetime, end_at: datetime) -> None:
    if end_at - start_at > MAX_LENGTH:
        raise HttpError(400, TOO_LONG)
    _check_overlap(assignment, start_at, end_at)


WEEKDAYS = ("pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz.")


def _day(day) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day:%d.%m}"


# ----------------------------------------------------------------------------------------------- notifications


def payload(change: HoursChange, shift: Shift | None = None) -> dict:
    """What a notification about a change says (the text is built on read)."""
    tz = ZoneInfo(change.location.timezone)
    planned_start = shift.start_at if shift else change.planned_start_at
    planned_end = shift.end_at if shift else change.planned_end_at
    planned_minutes = (planned_end - planned_start).total_seconds() / 60
    return {
        "change_id": str(change.pk),
        "date": change.date.isoformat(),
        "start_time": local_time(change.start_at, tz),
        "end_time": local_time(change.end_at, tz),
        "planned_start_time": local_time(planned_start, tz),
        "planned_end_time": local_time(planned_end, tz),
        "difference": round((change.end_at - change.start_at).total_seconds() / 60 - planned_minutes),
        "location_name": change.location.name,
        "position_name": shift.position.name if shift else "",
        "employee_name": change.employee.membership.user.full_name or "Pracownik bez imienia",
        "reason": change.reason,
    }


def _user_of(profile: EmployeeProfile):
    return profile.membership.user_id


# ----------------------------------------------------------------------------------------------- the employee


def check_report(assignment: Assignment, start: time, end: time, *, today=None) -> tuple[datetime, datetime]:
    """The moments of an employee's report of other hours on their published shift, or a Polish HttpError.
    Saves nothing (the assistant checks its proposals with it too)."""
    today = today or timezone.localdate()
    shift = assignment.shift
    if shift.version.status != ScheduleVersion.Status.PUBLISHED:
        raise HttpError(409, NOT_PUBLISHED)
    if shift.date < today - timedelta(days=PAST_DAYS):
        raise HttpError(409, TOO_OLD)
    start_at, end_at = resolve(shift, start, end)
    current = worked_hours([assignment])[assignment.pk]
    if (start_at, end_at) == (current.start_at, current.end_at):
        raise HttpError(400, SAME_HOURS)
    waiting = pending_reports([assignment]).get(assignment.pk)
    if waiting is not None and (waiting.start_at, waiting.end_at) == (start_at, end_at):
        raise HttpError(409, "Takie zgłoszenie już czeka na kierownika.")
    _check_times(assignment, start_at, end_at)
    return start_at, end_at


def report(
    profile: EmployeeProfile,
    assignment_id,
    start: time,
    end: time,
    reason: str,
    user,
    *,
    source_request=None,
    today=None,
) -> HoursChange:
    """The employee's report of other hours on one of their published shifts. It waits for the manager."""
    with transaction.atomic():
        _lock_person(profile.pk)
        assignment = _load(assignment_id, profile.company_id)
        if assignment.employee_id != profile.pk:
            raise HttpError(404, "Nie znaleziono tej zmiany.")
        shift = assignment.shift
        start_at, end_at = check_report(assignment, start, end, today=today)
        now = timezone.now()
        HoursChange.objects.for_company(profile.company_id).filter(
            period_id=shift.version.period_id,
            slot_key=shift.slot_key,
            employee=profile,
            status=HoursChange.Status.PENDING,
        ).update(status=HoursChange.Status.CANCELLED, decided_at=now)
        change = HoursChange.objects.create(
            company_id=profile.company_id,
            location=shift.location,
            period_id=shift.version.period_id,
            slot_key=shift.slot_key,
            employee=profile,
            date=shift.date,
            planned_start_at=shift.start_at,
            planned_end_at=shift.end_at,
            start_at=start_at,
            end_at=end_at,
            reason=reason.strip()[:REASON_MAX],
            requested_by=user,
            source_request=source_request,
        )
        notify(profile.company_id, location_manager_ids(shift.location), "hours_reported", payload(change, shift))
    return change


def cancel(change: HoursChange, profile: EmployeeProfile) -> HoursChange:
    """The employee takes back a report that still waits for the manager."""
    with transaction.atomic():
        locked = HoursChange.objects.for_company(change.company_id).select_for_update().get(pk=change.pk)
        if locked.employee_id != profile.pk or locked.by_manager:
            raise HttpError(404, "Nie znaleziono tego zgłoszenia.")
        if locked.status != HoursChange.Status.PENDING:
            raise HttpError(409, DECIDED)
        locked.status = HoursChange.Status.CANCELLED
        locked.decided_at = timezone.now()
        locked.save(update_fields=["status", "decided_at"])
    return locked


# ----------------------------------------------------------------------------------------------- the manager


def _replace_approved(change: HoursChange, user, now) -> None:
    HoursChange.objects.for_company(change.company_id).filter(
        period_id=change.period_id,
        slot_key=change.slot_key,
        employee_id=change.employee_id,
        status=HoursChange.Status.APPROVED,
    ).exclude(pk=change.pk).update(status=HoursChange.Status.REPLACED, decided_at=now, decided_by=user)


def check_approve(change: HoursChange, assignment: Assignment) -> None:
    """Approved hours must not run into another shift of the person (a Polish HttpError). Saves nothing."""
    _check_times(assignment, change.start_at, change.end_at)


def decide(change: HoursChange, user, *, approve: bool) -> HoursChange:
    """Approve or reject a waiting report. A report whose person lost the shift ends as cancelled (409)."""
    gone = False
    with transaction.atomic():
        _lock_person(change.employee_id)
        locked = (
            HoursChange.objects.for_company(change.company_id)
            .select_for_update()
            .select_related("location", "employee__membership__user")
            .get(pk=change.pk)
        )
        if locked.status != HoursChange.Status.PENDING:
            raise HttpError(409, DECIDED)
        assignment = published_assignment(locked)
        now = timezone.now()
        if assignment is None:
            locked.status, locked.decided_at = HoursChange.Status.CANCELLED, now
            locked.save(update_fields=["status", "decided_at"])
            gone = True
        else:
            if approve:
                check_approve(locked, assignment)
                _replace_approved(locked, user, now)
            locked.status = HoursChange.Status.APPROVED if approve else HoursChange.Status.REJECTED
            locked.decided_by, locked.decided_at = user, now
            locked.save(update_fields=["status", "decided_by", "decided_at"])
            kind = "hours_approved" if approve else "hours_rejected"
            notify(locked.company_id, [_user_of(locked.employee)], kind, payload(locked, assignment.shift))
    if gone:  # after the block, so the cancelled report stays saved
        raise HttpError(409, GONE)
    return locked


def check_set(assignment: Assignment, start: time, end: time) -> tuple[datetime, datetime]:
    """The moments of the manager's own change of a person's hours on a published shift, or a Polish HttpError.
    Saves nothing (the assistant's plan is checked with it before the manager accepts it)."""
    if assignment.employee_id is None:
        raise HttpError(409, NOBODY)
    shift = assignment.shift
    if shift.version.status != ScheduleVersion.Status.PUBLISHED:
        raise HttpError(409, NOT_PUBLISHED)
    start_at, end_at = resolve(shift, start, end)
    current = worked_hours([assignment])[assignment.pk]
    waiting = pending_reports([assignment]).get(assignment.pk)
    if (start_at, end_at) == (current.start_at, current.end_at) and waiting is None:
        raise HttpError(400, SAME_HOURS)
    if (start_at, end_at) != (shift.start_at, shift.end_at):
        _check_times(assignment, start_at, end_at)
    return start_at, end_at


def set_hours(assignment: Assignment, start: time, end: time, reason: str, user) -> Worked:
    """The manager's own change of one person's hours on a published shift, at once. Hours equal to the plan bring
    the plan back. A waiting report of the shift is approved when the hours are the same, otherwise replaced."""
    with transaction.atomic():
        if assignment.employee_id is None:
            raise HttpError(409, NOBODY)
        _lock_person(assignment.employee_id)
        assignment = _load(assignment.pk, assignment.company_id)
        shift = assignment.shift
        start_at, end_at = check_set(assignment, start, end)
        waiting = pending_reports([assignment]).get(assignment.pk)
        to_plan = (start_at, end_at) == (shift.start_at, shift.end_at)
        now = timezone.now()
        employee_user = [_user_of(assignment.employee)]
        if waiting is not None and (waiting.start_at, waiting.end_at) == (start_at, end_at):
            _replace_approved(waiting, user, now)
            waiting.status, waiting.decided_by, waiting.decided_at = HoursChange.Status.APPROVED, user, now
            waiting.save(update_fields=["status", "decided_by", "decided_at"])
            notify(assignment.company_id, employee_user, "hours_approved", payload(waiting, shift))
            return Worked(start_at, end_at, waiting)
        if waiting is not None:
            waiting.status, waiting.decided_by, waiting.decided_at = HoursChange.Status.REPLACED, user, now
            waiting.save(update_fields=["status", "decided_by", "decided_at"])
        change = HoursChange(
            company_id=assignment.company_id,
            location=shift.location,
            period_id=shift.version.period_id,
            slot_key=shift.slot_key,
            employee=assignment.employee,
            date=shift.date,
            planned_start_at=shift.start_at,
            planned_end_at=shift.end_at,
            start_at=start_at,
            end_at=end_at,
            reason=reason.strip()[:REASON_MAX],
            status=HoursChange.Status.APPROVED,
            by_manager=True,
            requested_by=user,
            decided_by=user,
            decided_at=now,
        )
        # Earlier approved hours give way; hours equal to the plan need no row of their own (the plan counts).
        _replace_approved(change, user, now)
        if not to_plan:
            change.save()
        notify(assignment.company_id, employee_user, "hours_set", payload(change, shift))
    return Worked(start_at, end_at, None if to_plan else change)


def _holders(version: ScheduleVersion | None) -> set[tuple[str, str]]:
    """(slot_key, employee id) of every filled shift of a version."""
    if version is None:
        return set()
    return {
        (key, str(employee))
        for key, employee in Assignment.objects.for_company(version.company_id)
        .filter(shift__version=version, employee__isnull=False)
        .values_list("shift__slot_key", "employee_id")
    }


def _end_for_lost_shift(changes: list[HoursChange]) -> None:
    """The people of `changes` no longer have those published shifts: a waiting report ends (cancelled) and approved
    hours stop counting (they stay approved and count again if the shift comes back). Each person is told."""
    if not changes:
        return
    now = timezone.now()
    waiting = [change.pk for change in changes if change.status == HoursChange.Status.PENDING]
    if waiting:
        HoursChange.objects.for_company(changes[0].company_id).filter(pk__in=waiting).update(
            status=HoursChange.Status.CANCELLED, decided_at=now
        )
    for change in changes:
        notify(
            change.company_id,
            [_user_of(change.employee)],
            "hours_lost",
            {**payload(change), "approved": change.status == HoursChange.Status.APPROVED},
        )


def _open_changes(company_id, period_id, **filters) -> list[HoursChange]:
    return list(
        HoursChange.objects.for_company(company_id)
        .filter(period_id=period_id, status__in=[HoursChange.Status.PENDING, HoursChange.Status.APPROVED], **filters)
        .select_related("location", "employee__membership__user")
    )


def person_left_shift(assignment: Assignment, employee_id) -> None:
    """A published shift went from `employee_id` to someone else (or nobody) in place: a handover, the manager's
    change or swap, a clash taken off. Their waiting report of it ends and they hear what happened to the hours."""
    if employee_id is None:
        return
    shift = assignment.shift
    _end_for_lost_shift(
        _open_changes(assignment.company_id, shift.version.period_id, slot_key=shift.slot_key, employee_id=employee_id)
    )


def refresh_after_publish(version: ScheduleVersion, previous: ScheduleVersion | None = None) -> int:
    """A newly published version: waiting reports of people who no longer have that shift end (cancelled). People
    who lose a shift in this correction hear about it, also when their approved hours stop counting (told once:
    only for shifts they had in the version it replaces). Returns how many reports ended."""
    holders = _holders(version)
    before = _holders(previous)
    lost = []
    for change in _open_changes(version.company_id, version.period_id):
        key = (change.slot_key, str(change.employee_id))
        if key in holders:
            continue
        if change.status == HoursChange.Status.PENDING or key in before:
            lost.append(change)
    _end_for_lost_shift(lost)
    return sum(1 for change in lost if change.status == HoursChange.Status.PENDING)
