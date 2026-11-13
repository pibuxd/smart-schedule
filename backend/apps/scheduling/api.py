"""Schedule periods and generating a schedule (the solver runs in the worker; the frontend polls the run)."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.core.schemas import ErrorOut
from apps.scheduling.editing import manual_changes
from apps.scheduling.generation import ACTIVE, request_generation
from apps.scheduling.models import Assignment, GenerationRun, SchedulePeriod, ScheduleVersion, Shift
from apps.staffing.me import employee_context
from apps.staffing.models import EmployeeProfile
from apps.tenancy.context import context_for
from apps.tenancy.models import Location

router = Router(tags=["scheduling"])

# Longest period one generation covers (a month plus a few days of slack).
MAX_PERIOD_DAYS = 62

PeriodStatus = Literal["collecting", "draft", "published"]
RunStatus = Literal["queued", "running", "succeeded", "failed"]
SolverStatus = Literal["", "optimal", "feasible", "timeout_no_solution", "infeasible"]


class PeriodIn(Schema):
    start: date
    end: date
    # The day the manager will arrange the schedule = the last day to mark availability.
    # Left out: the location's default number of days before the start.
    availability_deadline: date | None = None


class PeriodUpdateIn(Schema):
    availability_deadline: date


class PeriodOut(Schema):
    id: UUID
    location_id: UUID
    start: date
    end: date
    status: PeriodStatus
    deadline: date
    # When the employees were last asked for their availability (None: not yet).
    availability_requested_at: datetime | None
    published_version_id: UUID | None
    latest_version_id: UUID | None
    latest_version_status: Literal["draft", "published", "superseded"] | None
    # A generation queued or running for this period (the screen keeps polling it after a reload).
    active_run_id: UUID | None
    # Manual changes in the newest version that arranging again would drop (they are not pinned).
    manual_changes: int
    # Active employees of the location who have not sent their availability ("Gotowe") for this period.
    missing_availability: int


class AskAvailabilityIn(Schema):
    # True: remind only those who have not finished marking yet.
    only_missing: bool = False


class AskAvailabilityOut(Schema):
    period: PeriodOut
    notified: int


class GenerateIn(Schema):
    # One period, or periods of several locations ("arrange all"): each location gets its own run.
    period_ids: list[UUID] = Field(min_length=1, max_length=50)


class ScoresOut(Schema):
    holes: int
    slots: int
    manager_rules: float
    employee_requests: float
    stability_changes: int
    hard_violations: int
    unmeasured_rules: int
    unscored_requests: int
    is_complete: bool
    is_valid: bool
    notes: list[str]


class GeneratedVersionOut(Schema):
    id: UUID
    period_id: UUID
    location_id: UUID
    number: int
    is_complete: bool
    scores: ScoresOut


class GenerationRunOut(Schema):
    id: UUID
    status: RunStatus
    solver_status: SolverStatus
    period_ids: list[UUID]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    time_ms: int | None
    # Polish text for the manager when the run failed (may have several lines).
    error: str
    versions: list[GeneratedVersionOut]


def _period_out(period: SchedulePeriod) -> PeriodOut:
    versions = list(period.versions.order_by("-number").values_list("id", "status"))
    published = next((pk for pk, status in versions if status == ScheduleVersion.Status.PUBLISHED), None)
    latest = period.versions.order_by("-number").first()
    active = period.generation_runs.filter(status__in=ACTIVE).order_by("-created_at").values_list("id", flat=True)
    return PeriodOut(
        id=period.id,
        location_id=period.location_id,
        start=period.start,
        end=period.end,
        status=period.status,
        deadline=period.deadline,
        availability_requested_at=period.availability_requested_at,
        published_version_id=published,
        latest_version_id=versions[0][0] if versions else None,
        latest_version_status=versions[0][1] if versions else None,
        active_run_id=active.first(),
        manual_changes=manual_changes(latest),
        missing_availability=_missing_availability(period),
    )


def _missing_availability(period: SchedulePeriod) -> int:
    from apps.availability.models import AvailabilitySubmission

    done = AvailabilitySubmission.objects.for_company(period.company_id).filter(period=period).values("employee")
    people = EmployeeProfile.objects.for_company(period.company_id).filter(
        home_location=period.location_id, is_active=True
    )
    return people.exclude(pk__in=done).count()


def _run_out(run: GenerationRun) -> GenerationRunOut:
    versions = [
        GeneratedVersionOut(
            id=v.id,
            period_id=v.period_id,
            location_id=v.period.location_id,
            number=v.number,
            is_complete=v.is_complete,
            scores=ScoresOut(**{"notes": [], **v.scores}),
        )
        for v in run.versions.select_related("period").order_by("period__location__name")
    ]
    return GenerationRunOut(
        id=run.id,
        status=run.status,
        solver_status=run.solver_status,
        period_ids=sorted(run.periods.values_list("id", flat=True), key=str),
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        time_ms=run.time_ms,
        error=run.error,
        versions=versions,
    )


@router.get("/locations/{location_id}/periods", response={200: list[PeriodOut], 403: ErrorOut, 404: ErrorOut})
def location_periods(request, location_id: UUID):
    ctx, location = context_for(request, Location, location_id)
    ctx.require_manager_of(location)
    return [_period_out(p) for p in ctx.qs(SchedulePeriod).filter(location=location).order_by("-start")]


@router.post(
    "/locations/{location_id}/periods",
    response={201: PeriodOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def create_period(request, location_id: UUID, payload: PeriodIn):
    ctx, location = context_for(request, Location, location_id)
    ctx.require_manager_of(location)
    ctx.require_writable()
    if payload.end < payload.start:
        raise HttpError(400, "Koniec okresu nie może być przed jego początkiem.")
    if payload.end - payload.start >= timedelta(days=MAX_PERIOD_DAYS):
        raise HttpError(400, f"Okres grafiku może mieć najwyżej {MAX_PERIOD_DAYS} dni.")
    if payload.availability_deadline is not None:
        _check_deadline(payload.availability_deadline, payload.start)
    with transaction.atomic():
        Location.objects.for_company(ctx.company).select_for_update().get(pk=location.pk)
        overlapping = ctx.qs(SchedulePeriod).filter(location=location, start__lte=payload.end, end__gte=payload.start)
        if overlapping.exists():
            raise HttpError(409, "Ten lokal ma już okres grafiku obejmujący część tych dni.")
        period = SchedulePeriod.objects.for_company(ctx.company).create(
            company=ctx.company,
            location=location,
            start=payload.start,
            end=payload.end,
            availability_deadline=payload.availability_deadline,
        )
    return Status(201, _period_out(period))


def _check_deadline(deadline: date, start: date) -> None:
    if deadline > start:
        raise HttpError(400, "Termin dyspozycji musi być najpóźniej w pierwszym dniu okresu.")


@router.patch(
    "/periods/{uuid:period_id}",
    response={200: PeriodOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def update_period(request, period_id: UUID, payload: PeriodUpdateIn):
    """Move the availability deadline (the day the manager will arrange the schedule)."""
    ctx, period = context_for(request, SchedulePeriod, period_id)
    ctx.require_manager_of(period.location)
    ctx.require_writable()
    _check_deadline(payload.availability_deadline, period.start)
    period.availability_deadline = payload.availability_deadline
    period.save(update_fields=["availability_deadline"])
    return _period_out(period)


@router.post(
    "/periods/{period_id}/ask-availability",
    response={200: AskAvailabilityOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def ask_for_availability(request, period_id: UUID, payload: AskAvailabilityIn):
    """ "Poproś o dyspozycje": an in-app notice with the period and the deadline for every active employee of the
    location (or only those who have not finished). Nothing is arranged automatically: the manager arranges the
    schedule when the deadline has passed or everyone has answered."""
    from apps.availability.models import AvailabilitySubmission
    from apps.notifications.models import Notification

    ctx, period = context_for(request, SchedulePeriod, period_id)
    ctx.require_manager_of(period.location)
    ctx.require_writable()
    if period.status != SchedulePeriod.Status.COLLECTING:
        raise HttpError(409, "Grafik na ten okres jest już ułożony, więc nie zbieramy dyspozycji.")
    people = ctx.qs(EmployeeProfile).filter(home_location=period.location, is_active=True)
    if payload.only_missing:
        done = ctx.qs(AvailabilitySubmission).filter(period=period).values_list("employee_id", flat=True)
        people = people.exclude(pk__in=list(done))
    user_ids = list(people.values_list("membership__user_id", flat=True))
    note = {
        "period_id": str(period.pk),
        "location_name": period.location.name,
        "start": period.start.isoformat(),
        "end": period.end.isoformat(),
        "deadline": period.deadline.isoformat(),
    }
    with transaction.atomic():
        Notification.objects.for_company(ctx.company).bulk_create(
            Notification(company=ctx.company, user_id=user_id, kind="availability_requested", payload=note)
            for user_id in user_ids
        )
        period.availability_requested_at = timezone.now()
        period.save(update_fields=["availability_requested_at"])
    return AskAvailabilityOut(period=_period_out(period), notified=len(user_ids))


@router.post(
    "/periods/generate",
    response={
        202: list[GenerationRunOut],
        402: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        409: ErrorOut,
        429: ErrorOut,
    },
)
def generate_schedule(request, payload: GenerateIn):
    """Start arranging schedules, one run per location. Answers at once; poll `GET /generation-runs/{id}`."""
    ids = list(dict.fromkeys(payload.period_ids))
    ctx, first = context_for(request, SchedulePeriod, ids[0])
    periods = [first] + [ctx.get(SchedulePeriod, pk=pk) for pk in ids[1:]]
    runs = request_generation(ctx, periods)
    return Status(202, [_run_out(run) for run in runs])


@router.get("/generation-runs/{run_id}", response={200: GenerationRunOut, 403: ErrorOut, 404: ErrorOut})
def generation_run(request, run_id: UUID):
    ctx, run = context_for(request, GenerationRun, run_id)
    for period in run.periods.select_related("location"):
        ctx.require_manager_of(period.location)
    return _run_out(run)


# --- The employee's "Mój grafik" -------------------------------------------------------------------------

# How far ahead "Mój grafik" lists shifts (about two monthly periods).
MY_SCHEDULE_DAYS = 62


class MyShiftOut(Schema):
    id: UUID  # the assignment
    date: date
    start_at: datetime
    end_at: datetime
    # Local wall-clock hours of the location, e.g. "06:00" and "14:00" (an overnight shift ends the next day).
    start_time: str
    end_time: str
    hours: float
    location_name: str
    position_name: str
    shift_type_name: str
    # True when the shift is in another location than my home one.
    away: bool
    coworkers: list[str]
    # "Oddaj zmianę": my active offer of this shift (open = nobody yet, claimed = waiting for the manager).
    offer_id: UUID | None = None
    offer_status: Literal["open", "claimed"] | None = None


class MonthHoursOut(Schema):
    month: str  # "2026-11"
    hours: float


class MyScheduleOut(Schema):
    home_location_name: str
    shifts: list[MyShiftOut]
    # Hours of published shifts in each month that the list touches (and the current month).
    months: list[MonthHoursOut]


def _hours(shift: Shift) -> float:
    return round((shift.end_at - shift.start_at).total_seconds() / 3600, 2)


@router.get("/me/schedule", response={200: MyScheduleOut, 404: ErrorOut})
def my_schedule(request, company_id: UUID):
    """My published shifts from today on, who works with me, and my hours per month. Works in read-only mode."""
    ctx, profile = employee_context(request, company_id)
    today = timezone.localdate()
    published = ctx.qs(Assignment).filter(employee=profile, shift__version__status=ScheduleVersion.Status.PUBLISHED)
    published = published.select_related("shift__location", "shift__position", "shift__shift_type")
    upcoming = list(
        published.filter(shift__date__gte=today, shift__date__lte=today + timedelta(days=MY_SCHEDULE_DAYS)).order_by(
            "shift__start_at"
        )
    )

    others: dict = defaultdict(list)
    if upcoming:
        same_days = (
            ctx.qs(Assignment)
            .filter(
                shift__version__status=ScheduleVersion.Status.PUBLISHED,
                shift__date__in={a.shift.date for a in upcoming},
                shift__location__in={a.shift.location_id for a in upcoming},
                employee__isnull=False,
            )
            .exclude(employee=profile)
            .select_related("shift", "employee__membership__user")
        )
        for other in same_days:
            others[(other.shift.location_id, other.shift.date)].append(other)

    from apps.marketplace.models import ShiftOffer
    from apps.marketplace.services import ACTIVE

    offers = {
        assignment_id: (pk, status)
        for pk, assignment_id, status in ctx.qs(ShiftOffer)
        .filter(assignment__in=[a.pk for a in upcoming], status__in=ACTIVE)
        .values_list("pk", "assignment_id", "status")
    }
    shifts = []
    for assignment in upcoming:
        shift = assignment.shift
        tz = ZoneInfo(shift.location.timezone)
        start, end = shift.start_at.astimezone(tz), shift.end_at.astimezone(tz)
        overlapping = [
            o
            for o in others[(shift.location_id, shift.date)]
            if o.shift.start_at < shift.end_at and o.shift.end_at > shift.start_at
        ]
        names = sorted({o.employee.membership.user.full_name for o in overlapping})
        shifts.append(
            MyShiftOut(
                id=assignment.id,
                date=shift.date,
                start_at=start,
                end_at=end,
                start_time=f"{start:%H:%M}",
                end_time=f"{end:%H:%M}",
                hours=_hours(shift),
                location_name=shift.location.name,
                position_name=shift.position.name,
                shift_type_name=shift.shift_type.name if shift.shift_type else "",
                away=shift.location_id != profile.home_location_id,
                coworkers=names,
                offer_id=offers.get(assignment.pk, (None, None))[0],
                offer_status=offers.get(assignment.pk, (None, None))[1],
            )
        )

    months = sorted({today.strftime("%Y-%m")} | {s.date.strftime("%Y-%m") for s in shifts})
    totals = dict.fromkeys(months, 0.0)
    first = date.fromisoformat(months[0] + "-01")
    for assignment in published.filter(shift__date__gte=first):
        key = assignment.shift.date.strftime("%Y-%m")
        if key in totals:
            totals[key] += _hours(assignment.shift)
    return MyScheduleOut(
        home_location_name=profile.home_location.name,
        shifts=shifts,
        months=[MonthHoursOut(month=m, hours=round(h, 2)) for m, h in totals.items()],
    )


# --- The manager's schedule: a version, explanations, manual changes, publishing ----------------------------

VersionStatus = Literal["draft", "published", "superseded"]
Wish = Literal["cannot", "neutral", "prefer"]


class VersionShiftOut(Schema):
    id: UUID  # the shift (slot)
    date: date
    start_time: str
    end_time: str
    hours: float
    shift_type_name: str
    position_id: UUID
    position_name: str
    employee_id: UUID | None
    employee_name: str
    pinned: bool
    manual: bool
    borrowed: bool
    # The person's calendar mark for this shift; None for a hole.
    wish: Wish | None
    # Hard problems on this shift (Polish sentences); a valid schedule has none.
    problems: list[str]
    past: bool


class VersionEmployeeOut(Schema):
    id: UUID
    name: str
    position_ids: list[UUID]
    hours: float
    shifts: int
    target_hours: float | None
    max_hours: float | None
    active: bool


class RuleResultOut(Schema):
    code: str
    label: str
    hard: bool
    # 0–100 how well it is kept; None: nothing to measure in this schedule.
    percent: float | None
    broken: int
    examples: list[str]


class UnmetRequestOut(Schema):
    employee_name: str
    text: str
    # "text" (written request), "prefer" ("chętnie" days), "unscored" (left to you),
    # "instruction" (the manager's own instruction about a person, scored with the manager's rules)
    kind: Literal["text", "prefer", "unscored", "instruction"]
    percent_kept: float | None


class VersionSummaryOut(Schema):
    id: UUID
    number: int
    status: VersionStatus
    created_at: datetime
    published_at: datetime | None
    generated: bool
    created_by_name: str


class PositionNameOut(Schema):
    id: UUID
    name: str


class VersionOut(Schema):
    id: UUID
    number: int
    status: VersionStatus
    created_at: datetime
    published_at: datetime | None
    editable: bool
    period: PeriodOut
    location_id: UUID
    location_name: str
    scores: ScoresOut
    shifts: list[VersionShiftOut]
    employees: list[VersionEmployeeOut]
    positions: list[PositionNameOut]
    hard_problems: list[str]
    rules: list[RuleResultOut]
    unmet_requests: list[UnmetRequestOut]
    notes: list[str]
    history: list[VersionSummaryOut]
    # A correction of a published schedule: people whose shifts would change on publishing.
    changed_people: list[str]


class CandidateOut(Schema):
    employee_id: UUID
    name: str
    current: bool
    possible: bool
    problems: list[str]
    notes: list[str]
    wish: Wish
    hours: float
    target_hours: float | None
    max_hours: float | None
    holes: int
    manager_rules: float
    employee_requests: float


class SlotEventOut(Schema):
    at: datetime
    reason: Literal["generated", "manual", "offer", "swap"]
    # Empty name: nobody (an unfilled shift).
    from_name: str
    to_name: str
    by_name: str


class ShiftExplanationOut(Schema):
    shift: VersionShiftOut
    summary: str
    candidates: list[CandidateOut]
    # Who held this shift before, newest first (published changes, given-away shifts).
    history: list[SlotEventOut]


def _slot_history(ctx, shift: Shift) -> list[SlotEventOut]:
    from apps.scheduling.models import AssignmentEvent

    def name(profile) -> str:
        return profile.membership.user.full_name if profile else ""

    rows = (
        ctx.qs(AssignmentEvent)
        .filter(period_id=shift.version.period_id, slot_key=shift.slot_key)
        .select_related("from_employee__membership__user", "to_employee__membership__user", "by")
        .order_by("-at")[:20]
    )
    return [
        SlotEventOut(
            at=e.at,
            reason=e.reason,
            from_name=name(e.from_employee),
            to_name=name(e.to_employee),
            by_name=e.by.full_name if e.by else "",
        )
        for e in rows
    ]


class ChangeIn(Schema):
    shift_id: UUID
    # None: leave the shift empty.
    employee_id: UUID | None = None


class ChangesIn(Schema):
    changes: list[ChangeIn] = Field(min_length=1, max_length=20)


class CheckOut(Schema):
    ok: bool
    problems: list[str]
    warnings: list[str]
    before: ScoresOut
    after: ScoresOut


class PinIn(Schema):
    pinned: bool


def _scores_out(scores) -> ScoresOut:
    return ScoresOut(**{**scores.as_dict(), "notes": []})


def _version_context(request, version_id: UUID):
    ctx, version = context_for(request, ScheduleVersion, version_id)
    ctx.require_manager_of(version.period.location)
    return ctx, version


def _local_times(shift_start: datetime, shift_end: datetime, tz: ZoneInfo) -> tuple[str, str]:
    return f"{shift_start.astimezone(tz):%H:%M}", f"{shift_end.astimezone(tz):%H:%M}"


def _shift_rows(loaded, today: date) -> dict[str, VersionShiftOut]:
    """slot key -> the shift as the grid shows it."""
    from engine.problem import AvailabilityState

    problem = loaded.problem
    tz = problem.tz
    names = {e.id: e.name for e in problem.employees}
    problems_by_slot: dict[str, list[str]] = defaultdict(list)
    for violation in loaded.report.hard:
        for slot_id in violation.slots:
            problems_by_slot[slot_id].append(violation.message)
    rows = {}
    shifts = (
        Shift.objects.for_company(loaded.version.company_id)
        .filter(version=loaded.version)
        .select_related("assignment", "position", "shift_type")
        .order_by("date", "start_at", "position__name", "slot_key")
    )
    for shift in shifts:
        assignment = shift.assignment
        employee_id = str(assignment.employee_id) if assignment.employee_id else None
        slot = problem.slot_by_id.get(shift.slot_key)
        wish = None
        if employee_id and slot is not None and employee_id in problem.employee_by_id:
            wish = AvailabilityState(problem.availability_for(employee_id, slot)).value
        start, end = _local_times(shift.start_at, shift.end_at, tz)
        rows[shift.slot_key] = VersionShiftOut(
            id=shift.id,
            date=shift.date,
            start_time=start,
            end_time=end,
            hours=_hours(shift),
            shift_type_name=shift.shift_type.name if shift.shift_type else "",
            position_id=shift.position_id,
            position_name=shift.position.name,
            employee_id=assignment.employee_id,
            employee_name=names.get(employee_id, "") if employee_id else "",
            pinned=assignment.pinned,
            manual=assignment.manual,
            borrowed=assignment.borrowed,
            wish=wish,
            problems=problems_by_slot.get(shift.slot_key, []),
            past=shift.date < today,
        )
    return rows


def _rule_results(loaded) -> list[RuleResultOut]:
    from engine.rules_catalog import RULES_BY_CODE

    results = []
    location = loaded.location_id
    for measure in sorted(loaded.report.rules, key=lambda m: m.rank):
        if measure.location != location:
            continue
        label = RULES_BY_CODE[measure.code].label
        if measure.code == "target_hours" and measure.hard:
            label += " (do 10 % odchylenia)"
        results.append(
            RuleResultOut(
                code=measure.code,
                label=label,
                hard=measure.hard,
                percent=round(100 * (1 - measure.degree), 1) if measure.instances else None,
                broken=len(measure.violations),
                examples=[v.message for v in measure.violations[:3]],
            )
        )
    return results


def _unmet_requests(loaded) -> list[UnmetRequestOut]:
    from engine.scoring import unmet_requests
    from engine.validator import RequestKind

    problem = loaded.problem
    names = {e.id: e.name for e in problem.employees}
    requests = {r.id: r for r in problem.requests}
    result = []
    for measure in unmet_requests(loaded.report, location=loaded.location_id)[:30]:
        kept = round(100 * (1 - measure.degree), 1)
        if measure.kind == RequestKind.TEXT:
            text = requests[measure.request_id].summary
        else:
            share = f"{kept:g}".replace(".", ",")
            text = f"Dni „chętnie”: dostał(a) zmiany w {share} % z nich (tyle, ile się dało)."
        kind = "instruction" if measure.by_manager else measure.kind.value
        result.append(UnmetRequestOut(employee_name=names[measure.employee], text=text, kind=kind, percent_kept=kept))
    for request_id in loaded.report.unscored_requests:
        request = requests[request_id]
        if problem.employee_by_id[request.employee].home_location != loaded.location_id:
            continue
        result.append(
            UnmetRequestOut(
                employee_name=names[request.employee], text=request.summary, kind="unscored", percent_kept=None
            )
        )
    return result


def _history(version: ScheduleVersion) -> list[VersionSummaryOut]:
    rows = (
        ScheduleVersion.objects.for_company(version.company_id)
        .filter(period=version.period_id)
        .select_related("created_by")
        .order_by("-number")
    )
    return [
        VersionSummaryOut(
            id=v.id,
            number=v.number,
            status=v.status,
            created_at=v.created_at,
            published_at=v.published_at,
            generated=v.from_run_id is not None,
            created_by_name=v.created_by.full_name if v.created_by else "",
        )
        for v in rows
    ]


def _version_out(ctx, loaded, today: date) -> VersionOut:
    from apps.billing.services import subscription_state
    from apps.scheduling.editing import changed_people, is_editable

    version, problem = loaded.version, loaded.problem
    period = version.period
    hours = loaded.report.hours
    shift_count: dict[str, int] = defaultdict(int)
    for employee_id in loaded.schedule.values():
        if employee_id:
            shift_count[employee_id] += 1
    location_id = loaded.location_id
    employees = [
        VersionEmployeeOut(
            id=e.id,
            name=e.name,
            position_ids=sorted(e.positions),
            hours=round(hours.get(e.id, 0.0), 2),
            shifts=shift_count[e.id],
            target_hours=e.target_hours_month,
            max_hours=e.max_hours_month,
            active=e.available,
        )
        for e in sorted(problem.employees, key=lambda e: e.name)
        if e.home_location == location_id or shift_count[e.id]
    ]
    notes = list((version.scores or {}).get("notes", []))
    position_ids = {str(s.position) for s in problem.slots}
    return VersionOut(
        id=version.id,
        number=version.number,
        status=version.status,
        created_at=version.created_at,
        published_at=version.published_at,
        editable=is_editable(version) and not subscription_state(ctx.company.pk).read_only,
        period=_period_out(period),
        location_id=period.location_id,
        location_name=period.location.name,
        scores=_scores_out(loaded.scores),
        shifts=list(_shift_rows(loaded, today).values()),
        employees=employees,
        positions=sorted(
            (PositionNameOut(id=pk, name=name) for pk, name in problem.position_names.items() if pk in position_ids),
            key=lambda p: p.name,
        ),
        hard_problems=[v.message for v in loaded.report.hard],
        rules=_rule_results(loaded),
        unmet_requests=_unmet_requests(loaded),
        notes=notes,
        history=_history(version),
        changed_people=changed_people(loaded),
    )


@router.get("/versions/{version_id}", response={200: VersionOut, 403: ErrorOut, 404: ErrorOut})
def schedule_version(request, version_id: UUID):
    """One version of a location's schedule: the grid, the three scores, rules, unmet requests and history."""
    from apps.scheduling.editing import load_version

    ctx, version = _version_context(request, version_id)
    return _version_out(ctx, load_version(version), timezone.localdate())


@router.get(
    "/versions/{version_id}/shifts/{shift_id}/explain",
    response={200: ShiftExplanationOut, 403: ErrorOut, 404: ErrorOut},
)
def explain_shift(request, version_id: UUID, shift_id: UUID):
    """Why this shift has its person (or nobody), and what each person with the position would change.
    Quick checks with the validator, no solver; the same list is the manual editor's choice of people."""
    from apps.scheduling.editing import load_version
    from engine.explain import explain_slot

    ctx, version = _version_context(request, version_id)
    shift = ctx.get(Shift, pk=shift_id, version=version)
    loaded = load_version(version)
    explanation = explain_slot(loaded.problem, loaded.schedule, shift.slot_key, base=loaded.report)
    row = _shift_rows(loaded, timezone.localdate())[shift.slot_key]
    return ShiftExplanationOut(
        shift=row,
        summary=explanation.summary,
        candidates=[
            CandidateOut(
                employee_id=c.employee,
                name=c.name,
                current=c.current,
                possible=c.possible,
                problems=list(c.blocked),
                notes=list(c.notes),
                wish=c.wish.value,
                hours=c.hours,
                target_hours=c.target_hours,
                max_hours=c.max_hours,
                holes=c.scores.holes,
                manager_rules=c.scores.manager_rules,
                employee_requests=c.scores.employee_requests,
            )
            for c in explanation.candidates
        ],
        history=_slot_history(ctx, shift),
    )


def _changes(ctx, payload: ChangesIn) -> dict[str, str | None]:
    changes: dict[str, str | None] = {}
    for change in payload.changes:
        if change.employee_id is not None:
            ctx.get(EmployeeProfile, pk=change.employee_id)  # 404 for another company's person
        changes[str(change.shift_id)] = str(change.employee_id) if change.employee_id else None
    return changes


def _check_out(result) -> CheckOut:
    return CheckOut(
        ok=result.ok,
        problems=result.problems,
        warnings=result.warnings,
        before=_scores_out(result.before),
        after=_scores_out(result.after),
    )


@router.post(
    "/versions/{version_id}/check",
    response={200: CheckOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def check_schedule_changes(request, version_id: UUID, payload: ChangesIn):
    """Validate a manual change before saving it (e.g. while dragging): new problems and the new scores."""
    from apps.scheduling.editing import check_changes, load_version

    ctx, version = _version_context(request, version_id)
    result, _ = check_changes(load_version(version), _changes(ctx, payload))
    return _check_out(result)


@router.patch(
    "/versions/{version_id}/assignments",
    response={200: CheckOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def change_assignments(request, version_id: UUID, payload: ChangesIn):
    """Save a manual change (one shift, or two for a swap). Refused with the reasons when it breaks a hard rule."""
    from apps.scheduling.editing import apply_changes

    ctx, version = _version_context(request, version_id)
    ctx.require_writable()
    return _check_out(apply_changes(version, _changes(ctx, payload), ctx.user))


@router.post(
    "/versions/{version_id}/shifts/{shift_id}/pin",
    response={200: VersionShiftOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def pin_shift(request, version_id: UUID, shift_id: UUID, payload: PinIn):
    """Pin (or unpin) the person on a shift: arranging the schedule again keeps pinned people in place."""
    from apps.scheduling.editing import load_version, set_pinned

    ctx, version = _version_context(request, version_id)
    ctx.require_writable()
    shift = ctx.get(Shift, pk=shift_id, version=version)
    set_pinned(version, str(shift.pk), payload.pinned)
    return _shift_rows(load_version(version), timezone.localdate())[shift.slot_key]


@router.post(
    "/versions/{version_id}/draft",
    response={201: VersionSummaryOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut},
)
def start_correcting(request, version_id: UUID):
    """Correct a published schedule: a new draft copy (or the newest draft, if there already is one)."""
    from apps.scheduling.editing import start_draft

    ctx, version = _version_context(request, version_id)
    ctx.require_writable()
    draft = start_draft(version, ctx.user)
    return Status(201, next(v for v in _history(draft) if v.id == draft.id))


@router.post(
    "/versions/{version_id}/publish",
    response={200: VersionSummaryOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def publish_schedule(request, version_id: UUID):
    """Publish the newest draft: employees see it in "Mój grafik"; the previous version stays as history."""
    from apps.scheduling.editing import publish

    ctx, version = _version_context(request, version_id)
    ctx.require_writable()
    published = publish(version, ctx.user)
    return next(v for v in _history(published) if v.id == published.id)
