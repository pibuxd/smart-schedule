"""Looking at a schedule version, editing it by hand, and publishing it.

- `load_version` reads a saved version for the engine (its own slots, people and pins) and validates it.
- `check_changes` / `apply_changes`: a manual change (who works which slot) is validated by the same validator as
  the generator's result; a change that would add a hard problem is refused with the validator's sentences,
  unless the manager forces it (`force=True`): the manager has the last word, so the person is saved as
  `forced` and pinned, and the validator reports those problems as waived (they never block publishing).
  Only the newest version of a period can be edited, and only while it is a draft. Days that have passed can be
  corrected too (someone swapped outside the app), so hours are counted as they were worked; such a
  correction is pinned, because arranging again must not undo what really happened.
- `find_clashes`: other shifts of the person at the same time (here, or another location's draft or published
  schedule); with `remove_clashes` the manager's confirmed change takes the person off them first.
- `add_seat` / `remove_seat`: one more or one fewer place on a shift of one day. The same number is saved as that
  date's staffing (`apps.staffing.day_staffing`), so arranging the schedule again keeps it.
- `start_draft`: editing a published schedule starts a new draft copy (publishing makes it the published one).
- `delete_draft`: "Usuń szkic" removes only the newest draft; the version before it is current again.
- `publish`: the draft becomes the published version, the previous one is kept as history, the history of
  assignments (`AssignmentEvent`) gets one row for every slot whose person changed, open offers of given-away
  shifts follow the slot (or end, when the giver lost it), and the employees of the location get an in-app notice.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from apps.notifications.models import Notification
from apps.scheduling.models import Assignment, AssignmentEvent, GenerationRun, SchedulePeriod, ScheduleVersion, Shift
from apps.scheduling.problem_builder import BuiltProblem, build_problem_for_version, slot_key
from apps.staffing import day_staffing
from apps.staffing.models import EmployeeProfile, LocationClosure, Position, ShiftType, works_in_q
from engine.explain import new_soft_violations, new_waived_violations, returned_violations, without_pin
from engine.problem import Problem, shift_bounds
from engine.scoring import Scores, score
from engine.validator import Code, ValidationReport, Violation, validate

# Hard rules the manager may break by hand (docs/plan.md, section 26, point 7): the generator always keeps them,
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
    # Not ok, but the manager may save it anyway (`force`): every new problem is one the manager can overrule.
    can_force: bool = False
    # Slot keys that get the `forced` mark when the change is saved with `force`, and the scores then.
    forced: frozenset[str] = field(default_factory=frozenset)
    after_forced: Scores | None = None
    clashes: list = field(default_factory=list)  # Clash: other shifts of the person at the same time
    problems_if_removed: list[str] = field(default_factory=list)  # new hard problems left after taking them off
    # Those problems are all ones the manager may overrule: one confirmation sends `remove_clashes` and `force`.
    can_force_if_removed: bool = False

    @property
    def ok_if_removed(self) -> bool:
        """Fine once the person is taken off the clashing shifts (and the manager may change all of them)."""
        return all(c.can_remove for c in self.clashes) and not self.problems_if_removed


def _resolve(loaded: LoadedVersion, changes: Mapping[str, str | None]) -> dict[str, str | None]:
    """shift id -> employee id, translated to slot keys; refuses unknown shifts."""
    shifts = dict(
        (str(pk), key)
        for pk, key in Shift.objects.for_company(loaded.version.company_id)
        .filter(version=loaded.version, pk__in=list(changes))
        .values_list("pk", "slot_key")
    )
    result = {}
    for shift_id, employee_id in changes.items():
        if shift_id not in shifts:
            raise HttpError(404, "Nie ma takiej zmiany w tym grafiku.")
        result[shifts[shift_id]] = employee_id
    return result


WEEKDAYS = ("pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz.")


@dataclass(frozen=True)
class Clash:
    """Another shift the person put on a shift has at the same time: in this schedule, or in a draft or the published
    schedule of another location. The manager may take the person off it (docs/plan.md, section 27)."""

    employee: str
    shift_id: str
    version_id: str
    location_id: str
    location_name: str
    kind: str  # "here", "draft" or "published"
    start: datetime
    end: datetime
    text: str
    can_remove: bool
    reason: str = ""  # why the person cannot be taken off it
    slot_key: str = ""  # "here": the slot of this schedule


def _when(start: datetime, end: datetime, tz: str) -> str:
    begin, finish = start.astimezone(ZoneInfo(tz)), end.astimezone(ZoneInfo(tz))
    return f"{WEEKDAYS[begin.weekday()]} {begin:%d.%m}, {begin:%H:%M}–{finish:%H:%M}"


def _other_version_ids(version: ScheduleVersion) -> list:
    """Versions of other periods around this one that hold people's shifts: each published schedule, and its
    newest draft when that is newer."""
    other_versions: dict = {}
    for version_id, period_id, status in (
        ScheduleVersion.objects.for_company(version.company_id)
        .filter(status__in=[ScheduleVersion.Status.DRAFT, ScheduleVersion.Status.PUBLISHED])
        .exclude(period_id=version.period_id)
        .filter(
            period__start__lte=version.period.end + timedelta(days=1),
            period__end__gte=version.period.start - timedelta(days=1),
        )
        .order_by("number")
        .values_list("pk", "period_id", "status")
    ):
        kept = other_versions.setdefault(period_id, {})
        if status == ScheduleVersion.Status.PUBLISHED:
            kept.clear()  # an older draft is history once a newer version is published
        kept[status] = version_id
    return [v for kept in other_versions.values() for v in kept.values()]


def find_clashes(
    loaded: LoadedVersion, by_key: Mapping[str, str | None], manages: set[str] | None = None
) -> list[Clash]:
    """Shifts at the same time as the new assignments in `by_key` (slot key -> employee). `manages`: the ids of the
    locations the manager runs (None: all); only their schedules can be changed from here."""
    problem, version = loaded.problem, loaded.version
    slots = problem.slot_by_id
    wanted = {
        key: employee
        for key, employee in by_key.items()
        if employee and key in slots and loaded.schedule.get(key) != employee
    }
    if not wanted:
        return []
    names = {e.id: e.name for e in problem.employees}
    after = {**loaded.schedule, **by_key}
    result: list[Clash] = []
    # In this schedule: the person stays on another slot at the same time.
    here_keys = {
        other: key
        for key, employee in wanted.items()
        for other, someone in after.items()
        if other != key
        and other not in by_key  # asked for in the same change: stays a problem
        and someone == employee
        and other in slots
        and slots[other].start_utc < slots[key].end_utc
        and slots[key].start_utc < slots[other].end_utc
    }
    shift_ids = dict(
        Shift.objects.for_company(version.company_id)
        .filter(version=version, slot_key__in=list(here_keys))
        .values_list("slot_key", "pk")
    )
    location = version.period.location
    for other in here_keys:
        slot = slots[other]
        employee = after[other]
        result.append(
            Clash(
                employee=employee,
                shift_id=str(shift_ids[other]),
                version_id=str(version.pk),
                location_id=str(location.pk),
                location_name=location.name,
                kind="here",
                start=slot.start_utc,
                end=slot.end_utc,
                text=f"{names.get(employee, 'Ta osoba')} ma w tym czasie inną zmianę: "
                f"{_when(slot.start_utc, slot.end_utc, location.timezone)}.",
                can_remove=True,
                slot_key=other,
            )
        )
    rows = (
        Assignment.objects.for_company(version.company_id)
        .filter(employee__in=set(wanted.values()), shift__version__in=_other_version_ids(version))
        .select_related("shift__location", "shift__version")
    )
    now = timezone.now()
    elsewhere: dict[tuple, Clash] = {}  # (period, slot, person): the published shift wins over its draft copy
    for row in sorted(rows, key=lambda r: r.shift.version.status != ScheduleVersion.Status.PUBLISHED):
        shift = row.shift
        for key, employee in wanted.items():
            slot = slots[key]
            overlaps = shift.start_at < slot.end_utc and slot.start_utc < shift.end_at
            if str(row.employee_id) != employee or not overlaps:
                continue
            draft = shift.version.status == ScheduleVersion.Status.DRAFT
            where = f"w {'szkicu grafiku' if draft else 'grafiku'} lokalu {shift.location.name}"
            reason = ""
            if manages is not None and str(shift.location_id) not in manages:
                reason = f"Nie prowadzisz lokalu {shift.location.name}, więc poproś jego kierownika o zmianę."
            elif not draft and shift.start_at <= now:
                reason = "Ta zmiana już się zaczęła, więc nie można jej zmienić."
            elsewhere.setdefault(
                (shift.version.period_id, shift.slot_key, employee),
                Clash(
                    employee=employee,
                    shift_id=str(shift.pk),
                    version_id=str(shift.version_id),
                    location_id=str(shift.location_id),
                    location_name=shift.location.name,
                    kind="draft" if draft else "published",
                    start=shift.start_at,
                    end=shift.end_at,
                    text=f"{names.get(employee, 'Ta osoba')} ma w tym czasie zmianę {where}: "
                    f"{_when(shift.start_at, shift.end_at, shift.location.timezone)}.",
                    can_remove=not reason,
                    reason=reason,
                ),
            )
    return [*result, *elsewhere.values()]


def _without_clashes(problem: Problem, clashes: list[Clash]) -> Problem:
    """The problem as if the person were taken off the other locations' clashing shifts."""
    gone = {(c.employee, c.start, c.end) for c in clashes if c.kind == "published"}
    if not gone:
        return problem
    kept = tuple(e for e in problem.external_shifts if (e.employee, e.start_utc, e.end_utc) not in gone)
    return replace(problem, external_shifts=kept)


def _forcing(problem: Problem, standing, by_key, schedule, known: set[str], new, location: str):
    """Slot keys whose `forced` mark overrules every problem in `new` (empty when that is not enough), and the scores
    then. First only the changed slots the problems are about; if that is not enough, every changed slot."""
    if not new:
        return frozenset(), None
    filled = {k for k, e in by_key.items() if e is not None}
    touched = {k for k in filled if any(k in v.slots or (not v.slots and v.employee == by_key[k]) for v in new)}
    for keys in (touched, filled):
        if not keys:
            continue
        trial = replace(problem, forced={**standing, **{k: by_key[k] for k in keys}})
        report = validate(trial, schedule)
        if all(v.message in known for v in blocking(report.hard)):
            return frozenset(keys), score(trial, report, location=location)
    return frozenset(), None


def _check(
    loaded: LoadedVersion,
    by_key: Mapping[str, str | None],
    before: ValidationReport | None = None,
    *,
    manages: set[str] | None = None,
    clashes: bool = False,
) -> CheckResult:
    """The result of putting `by_key` (slot key -> employee id or None) into the schedule of `loaded`. With
    `clashes`, also the person's other shifts at the same time and what is left once they are taken off them."""
    problem = loaded.problem
    for key in by_key:  # a manual change moves the pin to the new person
        problem = without_pin(problem, key)
    before = before or validate(problem, loaded.schedule)
    after_schedule = {**loaded.schedule, **by_key}
    # An earlier override was about the person who held the slot; the new one needs the manager's word again.
    standing = {k: v for k, v in problem.forced.items() if by_key.get(k, v) == v}
    problem = replace(problem, forced=standing)
    after = validate(problem, after_schedule)
    known = {v.message for v in before.hard}
    receivers = {e for k, e in by_key.items() if e is not None and loaded.schedule.get(k) != e}
    known |= returned_violations(before, after, receivers)
    new = [v for v in blocking(after.hard) if v.message not in known]
    # An earlier override does not cover this change: what it would newly waive needs the manager's word too.
    new += blocking(new_waived_violations(before, after, receivers))
    warnings = [v.message for v in accepted(after.hard) if v.message not in known] + new_soft_violations(before, after)
    forced, after_forced = _forcing(problem, standing, by_key, after_schedule, known, new, loaded.location_id)

    found = find_clashes(loaded, by_key, manages) if clashes else []
    problems_if_removed = [v.message for v in new]
    can_force_if_removed = bool(forced)
    if found:
        freed = _without_clashes(problem, found)
        moved = {**after_schedule, **{c.slot_key: None for c in found if c.kind == "here"}}
        removed = validate(freed, moved)
        left = [v for v in blocking(removed.hard) if v.message not in known]
        left += blocking(new_waived_violations(before, removed, receivers))
        problems_if_removed = [v.message for v in left]
        can_force_if_removed = bool(_forcing(freed, standing, by_key, moved, known, left, loaded.location_id)[0])
    return CheckResult(
        ok=not new,
        problems=[v.message for v in new],
        warnings=warnings[:5],
        before=score(problem, before, location=loaded.location_id),
        after=score(problem, after, location=loaded.location_id),
        can_force=bool(forced),
        forced=forced,
        after_forced=after_forced,
        clashes=found,
        problems_if_removed=problems_if_removed,
        can_force_if_removed=can_force_if_removed,
    )


def check_changes(
    loaded: LoadedVersion, changes: Mapping[str, str | None], manages: set[str] | None = None
) -> tuple[CheckResult, dict[str, str | None]]:
    """Validate the version with `changes` (shift id -> employee id or None) applied; nothing is saved.
    Also lists the clashing shifts and whether the change would be fine once the person is taken off them."""
    by_key = _resolve(loaded, changes)
    return _check(loaded, by_key, manages=manages, clashes=True), by_key


def check_drops(loaded: LoadedVersion, shift_id: str, manages: set[str] | None = None) -> dict[str, CheckResult]:
    """What dropping the person of `shift_id` on every other shift would do (a swap, or a move onto an empty
    shift), by the id of the shift dropped on. One answer for the whole drag, so the screen has the result of
    each drop before the manager gets there. Shifts of the same person are left out; days that have passed are
    in, because a draft can correct them. One validator run per shift (about 5 ms each on a month of one
    location). Other shifts at the same time (`clashes`) are looked up only for drops that put someone on two
    shifts at once, here or in another location's draft or published schedule (read once). Nothing is saved."""
    shifts = {
        str(pk): (key, day)
        for pk, key, day in Shift.objects.for_company(loaded.version.company_id)
        .filter(version=loaded.version)
        .values_list("pk", "slot_key", "date")
    }
    if shift_id not in shifts:
        raise HttpError(404, "Nie ma takiej zmiany w tym grafiku.")
    source, _ = shifts[shift_id]
    person = loaded.schedule.get(source)
    if person is None:
        return {}
    # Before the drop only pins differ between targets, and a pin never breaks the schedule it was read from,
    # so one "before" serves every target that is not pinned itself.
    pinned = loaded.problem.pinned
    before = validate(without_pin(loaded.problem, source), loaded.schedule)
    slots = loaded.problem.slot_by_id
    busy: dict[str, list] = defaultdict(list)  # person -> (start, end, slot key here or None) of their shifts
    for key, employee in loaded.schedule.items():
        if employee and key in slots:
            busy[employee].append((slots[key].start_utc, slots[key].end_utc, key))
    elsewhere = (
        Assignment.objects.for_company(loaded.version.company_id)
        .filter(shift__version__in=_other_version_ids(loaded.version), employee__isnull=False)
        .values_list("employee_id", "shift__start_at", "shift__end_at")
    )
    for employee, start, end in elsewhere:
        busy[str(employee)].append((start, end, None))

    def clashing(by_key) -> bool:
        return any(
            k not in by_key and start < slots[key].end_utc and slots[key].start_utc < end
            for key, employee in by_key.items()
            if employee
            for start, end, k in busy.get(employee, ())
        )

    results = {}
    for target_id, (target, _) in shifts.items():
        other = loaded.schedule.get(target)
        if other == person:
            continue
        by_key = {target: person, source: other}
        before_drop = None if target in pinned else before
        results[target_id] = _check(loaded, by_key, before_drop, manages=manages, clashes=clashing(by_key))
    return results


def apply_changes(
    version: ScheduleVersion,
    changes: Mapping[str, str | None],
    user,
    force: bool = False,
    today: date | None = None,
    *,
    remove_clashes: bool = False,
    manages: set[str] | None = None,
) -> CheckResult:
    """Save a manual change of people. Refused (409) when the version is not editable, or when it adds a hard
    problem and the manager did not `force` it. `remove_clashes`: first take the person off their other shifts at
    the same time (the manager confirmed it), here and in other locations the manager runs."""
    today = today or timezone.localdate()
    with transaction.atomic():
        version = ScheduleVersion.objects.select_for_update().get(pk=version.pk)
        if not is_editable(version):
            raise HttpError(409, NOT_EDITABLE)
        loaded = load_version(version)
        result, by_key = check_changes(loaded, changes, manages=manages)
        clashes = result.clashes if remove_clashes else []
        if clashes:
            blocked = next((c for c in clashes if not c.can_remove), None)
            if blocked is not None:
                raise HttpError(409, f"{blocked.text} {blocked.reason}")
            if result.problems_if_removed and not (force and result.can_force_if_removed):
                raise HttpError(409, "Tej zmiany nie można zapisać: " + " ".join(result.problems_if_removed))
            for clash in clashes:  # other locations first, so this schedule is checked against what is left
                if clash.kind == "draft":
                    other = ScheduleVersion.objects.for_company(version.company_id).get(pk=clash.version_id)
                    try:
                        apply_changes(other, {clash.shift_id: None}, user)
                    except HttpError as error:
                        raise HttpError(
                            409, f"W szkicu grafiku lokalu {clash.location_name}: {error.message}"
                        ) from error
                elif clash.kind == "published":
                    take_off_published(clash, user, moved_to=version.period.location)
            # Read again (other locations changed); the change now also empties the clashing slots here.
            by_key = {**by_key, **{c.slot_key: None for c in clashes if c.kind == "here"}}
            loaded = load_version(version)
            result = _check(loaded, by_key)
        forced = result.forced if force else frozenset()
        if not result.ok and not forced:
            raise HttpError(409, "Tej zmiany nie można zapisać: " + " ".join(result.problems))
        people = loaded.problem.employee_by_id
        rows = Assignment.objects.for_company(version.company_id).filter(
            shift__version=version, shift__slot_key__in=list(by_key)
        )
        for assignment in rows.select_related("shift"):
            employee_id = by_key[assignment.shift.slot_key]
            if str(assignment.employee_id or "") == str(employee_id or ""):
                continue
            assignment.employee_id = employee_id
            assignment.manual = True
            assignment.borrowed = employee_id is not None and not (
                employee_id in people and people[employee_id].works_in(str(assignment.shift.location_id))
            )
            assignment.forced = assignment.shift.slot_key in forced
            # A new person (or a hole) is not pinned until the manager pins it, as check_changes assumed. Two
            # kinds stay through arranging again by themselves: an override (the generator would never repeat
            # it) and a correction of a day that has passed (it records what really happened).
            assignment.pinned = assignment.forced or assignment.shift.date < today
            assignment.save(update_fields=["employee", "manual", "borrowed", "pinned", "forced"])
        save_scores(version, result.after_forced if forced and result.after_forced else result.after)
    return result


def take_off_published(clash: Clash, user, *, moved_to) -> None:
    """Take a person off a published shift of another location in place (the manager confirmed a clash): the slot
    becomes a hole there and in that period's newest draft, with a history row; the person and the other managers
    are told. Open offers of that shift end."""
    from apps.marketplace.services import ACTIVE, expire_offer, offer_query
    from apps.notifications.services import location_manager_ids, notify

    row = (
        Assignment.objects.select_for_update(of=("self",))
        .select_related("shift__location", "shift__position", "shift__version", "employee__membership__user")
        .get(shift_id=clash.shift_id)
    )
    shift = row.shift
    company_id = shift.company_id
    employee = row.employee
    if employee is None or str(employee.pk) != clash.employee:
        return  # someone changed it meanwhile; nothing to take off
    for offer in offer_query(company_id).filter(assignment=row, status__in=ACTIVE):
        expire_offer(offer)
    for assignment in [row, *_newest_draft_rows(shift, employee)]:
        assignment.employee = None
        assignment.manual = True
        assignment.borrowed = False
        assignment.pinned = False
        assignment.forced = False
        assignment.save(update_fields=["employee", "manual", "borrowed", "pinned", "forced"])
    AssignmentEvent.objects.create(
        company_id=company_id,
        location_id=shift.location_id,
        period_id=shift.version.period_id,
        slot_key=shift.slot_key,
        from_employee=employee,
        to_employee=None,
        reason=AssignmentEvent.Reason.MANUAL,
        by=user,
    )
    save_scores(shift.version, load_version(shift.version).scores)
    from apps.worktime.services import person_left_shift

    person_left_shift(row, employee.pk)
    tz = ZoneInfo(shift.location.timezone)
    begin, finish = shift.start_at.astimezone(tz), shift.end_at.astimezone(tz)
    payload = {
        "date": shift.date.isoformat(),
        "start_time": f"{begin:%H:%M}",
        "end_time": f"{finish:%H:%M}",
        "position_name": shift.position.name,
        "location_name": shift.location.name,
        "moved_to": moved_to.name,
        "employee_name": employee.membership.user.full_name or "Pracownik bez imienia",
    }
    notify(company_id, [employee.membership.user_id], "shift_removed", payload)
    others = set(location_manager_ids(shift.location)) - {getattr(user, "pk", None)}
    notify(company_id, others, "shift_emptied", payload)


def _newest_draft_rows(shift: Shift, employee) -> list[Assignment]:
    newest = latest_version(shift.version.period)
    if newest is None or newest.status != ScheduleVersion.Status.DRAFT or newest.pk == shift.version_id:
        return []
    return list(
        Assignment.objects.for_company(shift.company_id).filter(
            shift__version=newest, shift__slot_key=shift.slot_key, employee=employee
        )
    )


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
                forced=old[s.slot_key].forced,
            )
            for s in new_shifts
        )
    return copy


def supersede_older_drafts(period: SchedulePeriod, newer_than: ScheduleVersion) -> None:
    ScheduleVersion.objects.for_company(period.company_id).filter(
        period=period, status=ScheduleVersion.Status.DRAFT, number__lt=newer_than.number
    ).update(status=ScheduleVersion.Status.SUPERSEDED)


def delete_draft(version: ScheduleVersion) -> SchedulePeriod:
    """ "Usuń szkic": only the newest draft goes for good. The version before it is current again: an earlier
    unpublished attempt becomes the editable draft, a published schedule stays as it is. With no version left,
    the period goes back to collecting availability, as before the first arranging."""
    with transaction.atomic():
        lock_period(version)
        version = ScheduleVersion.objects.select_related("period").get(pk=version.pk)
        if not is_editable(version):
            raise HttpError(409, "Usunąć można tylko najnowszy szkic grafiku. Opublikowany grafik zostaje.")
        period = version.period
        arranging = (GenerationRun.Status.QUEUED, GenerationRun.Status.RUNNING)
        if period.generation_runs.filter(status__in=arranging).exists():
            raise HttpError(409, "Grafik na ten okres właśnie się układa. Poczekaj albo przerwij układanie.")
        version.delete()
        previous = latest_version(period)
        if previous is None:
            period.status = SchedulePeriod.Status.COLLECTING
            period.save(update_fields=["status"])
        elif previous.published_at is None and previous.status == ScheduleVersion.Status.SUPERSEDED:
            previous.status = ScheduleVersion.Status.DRAFT
            previous.save(update_fields=["status"])
    return period


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
        from apps.assistant.agreements import consume

        consume(version.period, version.published_at)
        period.status = SchedulePeriod.Status.PUBLISHED
        period.save(update_fields=["status"])
        from apps.marketplace.services import refresh_after_publish

        refresh_after_publish(version, previous)
        from apps.worktime.services import refresh_after_publish as refresh_hours

        refresh_hours(version)
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
    ) | EmployeeProfile.objects.for_company(version.company_id).filter(works_in_q(period.location), is_active=True)
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
    "check_drops",
    "is_editable",
    "latest_version",
    "load_version",
    "manual_changes",
    "publish",
    "remove_seat",
    "set_pinned",
    "start_draft",
]
