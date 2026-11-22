"""Schedule periods and generating a schedule (the solver runs in the worker; the frontend polls the run)."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.core.schemas import ErrorOut
from apps.scheduling.editing import manual_changes
from apps.scheduling.generation import ACTIVE, cancel_generation, request_generation
from apps.scheduling.models import Assignment, GenerationRun, SchedulePeriod, ScheduleVersion, Shift
from apps.staffing.me import employee_context
from apps.staffing.models import EmployeeProfile, Position, ShiftType, works_in_q
from apps.staffing.shortage import ExperiencedShortOut, experienced_shortage
from apps.tenancy.context import context_for
from apps.tenancy.models import Location
from apps.worktime.schemas import WaitingHoursOut, WorkedOut, report_out, worked_out

router = Router(tags=["scheduling"])

# Longest period one generation covers (a month plus a few days of slack).
MAX_PERIOD_DAYS = 62

PeriodStatus = Literal["collecting", "draft", "published"]
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
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
    # Positions where one shift needs more experienced people than the location has (a warning before arranging).
    experienced_short: list[ExperiencedShortOut]


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
        experienced_short=experienced_shortage(period.company_id, period.location_id, period.start, period.end),
    )


def _missing_availability(period: SchedulePeriod) -> int:
    from apps.availability.models import AvailabilitySubmission

    done = AvailabilitySubmission.objects.for_company(period.company_id).filter(period=period).values("employee")
    people = EmployeeProfile.objects.for_company(period.company_id).filter(
        works_in_q(period.location_id), is_active=True
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
    _check_period_dates(payload.start, payload.end)
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
            deadline_set_at=timezone.now(),
        )
    return Status(201, _period_out(period))


# Periods are planned around today: a typo like year 0001 or 9999 would break date arithmetic everywhere.
PERIOD_PAST_DAYS = 366
PERIOD_FUTURE_DAYS = 2 * 366
DEADLINE_BEFORE_START_DAYS = 120


def _check_period_dates(start: date, end: date) -> None:
    today = timezone.localdate()
    if start < today - timedelta(days=PERIOD_PAST_DAYS):
        raise HttpError(400, "Okres grafiku może zaczynać się najwcześniej rok temu. Sprawdź rok.")
    if end > today + timedelta(days=PERIOD_FUTURE_DAYS):
        raise HttpError(400, "Okres grafiku może kończyć się najpóźniej za dwa lata. Sprawdź rok.")


def _check_deadline(deadline: date, start: date) -> None:
    if deadline > start:
        raise HttpError(400, "Termin dyspozycji musi być najpóźniej w pierwszym dniu okresu.")
    if deadline < start - timedelta(days=DEADLINE_BEFORE_START_DAYS):
        raise HttpError(400, "Termin dyspozycji może być najwcześniej 120 dni przed początkiem okresu. Sprawdź rok.")


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
    if period.availability_deadline != payload.availability_deadline:
        period.availability_deadline = payload.availability_deadline
        period.deadline_set_at = timezone.now()
        period.save(update_fields=["availability_deadline", "deadline_set_at"])
    return _period_out(period)


@router.delete(
    "/periods/{uuid:period_id}", response={204: None, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut}
)
def delete_period(request, period_id: UUID):
    """Delete a period added by mistake (e.g. wrong dates), with its drafts. A period whose schedule was ever
    published stays: employees saw it and hours are counted from it."""
    ctx, period = context_for(request, SchedulePeriod, period_id)
    ctx.require_manager_of(period.location)
    ctx.require_writable()
    with transaction.atomic():
        period = ctx.qs(SchedulePeriod).select_for_update().get(pk=period.pk)
        versions = ctx.qs(ScheduleVersion).filter(period=period)
        if versions.filter(published_at__isnull=False).exists():
            raise HttpError(409, "Ten grafik był już opublikowany, więc okresu nie można usunąć.")
        if period.generation_runs.filter(status__in=ACTIVE).exists():
            raise HttpError(409, "Grafik na ten okres właśnie się układa. Poczekaj albo przerwij układanie.")
        versions.delete()
        period.delete()
    return Status(204, None)


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
    people = ctx.qs(EmployeeProfile).filter(works_in_q(period.location), is_active=True)
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
        from apps.assistant import agreements

        agreements.lock_location(period.location)
        period = ctx.qs(SchedulePeriod).select_for_update().get(pk=period.pk)
        if period.status != SchedulePeriod.Status.COLLECTING:
            raise HttpError(409, "Grafik na ten okres jest już ułożony.")
        agreements.bind_pending(period)
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


@router.post(
    "/generation-runs/{run_id}/cancel",
    response={200: GenerationRunOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def cancel_generation_run(request, run_id: UUID):
    """Stop arranging: nothing is saved, the earlier draft stays, and the generation is not counted."""
    ctx, run = context_for(request, GenerationRun, run_id)
    return _run_out(cancel_generation(ctx, run))


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
    # The location hands given-away shifts over without the manager ("Weź zmianę" moves it at once).
    handover_at_once: bool = False
    # Hours that count instead of the schedule's (approved overtime or a shorter shift); None: as planned.
    worked: WorkedOut | None = None
    # My report of other hours, waiting for the manager.
    report: WaitingHoursOut | None = None
    # I may report other hours of this shift ("Zgłoś inne godziny"): published, at most 14 days back.
    can_report: bool = False


class MonthHoursOut(Schema):
    month: str  # "2026-11"
    hours: float
    # Pay for the month's published shifts in złoty before tax (hours that count × the shift's rate on its day,
    # plus supplements; docs/plan.md section 35); None when none of them has a rate, so the screen shows no pay.
    pay: float | None = None
    # Of `pay`: the supplements (e.g. for nights).
    supplements_pay: float | None = None
    # Hours of the month on shifts without a rate (not in `pay`).
    unpriced_hours: float = 0


class MyScheduleOut(Schema):
    home_location_name: str
    # From now on: shifts that have not ended (with the hours that count).
    shifts: list[MyShiftOut]
    # My shifts that ended in the last 14 days, newest first (to report overtime after the fact).
    recent: list[MyShiftOut] = Field(default_factory=list)
    # Last day covered by a published schedule of my location (days off up to it are shown too); None = none.
    published_until: date | None = None
    # Hours of published shifts in each month that the list touches (and the current month).
    months: list[MonthHoursOut]


def _hours(shift: Shift) -> float:
    return round((shift.end_at - shift.start_at).total_seconds() / 3600, 2)


@router.get("/me/schedule", response={200: MyScheduleOut, 404: ErrorOut})
def my_schedule(request, company_id: UUID):
    """My published shifts from today on, who works with me, my shifts of the last two weeks, and my hours per month
    (approved other hours count instead of the schedule's) with the pay. Works in read-only mode."""
    from apps.pay.services import Pay, PayRules
    from apps.worktime.services import PAST_DAYS, pending_reports, worked_hours

    ctx, profile = employee_context(request, company_id)
    today = timezone.localdate()
    now = timezone.now()
    published = ctx.qs(Assignment).filter(employee=profile, shift__version__status=ScheduleVersion.Status.PUBLISHED)
    published = published.select_related("shift__location", "shift__position", "shift__shift_type", "shift__version")
    near = list(
        published.filter(
            shift__date__gte=today - timedelta(days=PAST_DAYS + 1),
            shift__date__lte=today + timedelta(days=MY_SCHEDULE_DAYS),
        ).order_by("shift__start_at")
    )
    worked = worked_hours(near)
    upcoming = [a for a in near if worked[a.pk].end_at > now]
    recent = [
        a for a in reversed(near) if worked[a.pk].end_at <= now and a.shift.date >= today - timedelta(days=PAST_DAYS)
    ]
    waiting = pending_reports(near)

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

    def shift_out(assignment: Assignment) -> MyShiftOut:
        shift = assignment.shift
        tz = ZoneInfo(shift.location.timezone)
        start, end = shift.start_at.astimezone(tz), shift.end_at.astimezone(tz)
        overlapping = [
            o
            for o in others[(shift.location_id, shift.date)]
            if o.shift.start_at < shift.end_at and o.shift.end_at > shift.start_at
        ]
        names = sorted({o.employee.membership.user.full_name for o in overlapping})
        return MyShiftOut(
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
            handover_at_once=shift.location.handover_without_approval,
            worked=worked_out(worked[assignment.pk], shift),
            report=report_out(waiting.get(assignment.pk), shift),
            can_report=shift.date >= today - timedelta(days=PAST_DAYS),
        )

    shifts = [shift_out(a) for a in upcoming]
    past = [shift_out(a) for a in recent]
    # The months of "Minione zmiany" too: on the 1st, yesterday's corrected shift belongs to the previous month.
    months = sorted({today.strftime("%Y-%m")} | {s.date.strftime("%Y-%m") for s in [*shifts, *past]})
    totals = dict.fromkeys(months, 0.0)  # seconds, rounded once
    pay = {month: Pay() for month in months}
    first = date.fromisoformat(months[0] + "-01")
    in_months = list(published.filter(shift__date__gte=first))
    counted, rules = worked_hours(in_months), PayRules(in_months)
    for assignment in in_months:
        key = assignment.shift.date.strftime("%Y-%m")
        if key in totals:
            totals[key] += counted[assignment.pk].seconds
            rules.add(pay[key], assignment, counted[assignment.pk])
    published_until = (
        ctx.qs(SchedulePeriod)
        .filter(
            location_id__in=profile.location_ids(),
            versions__status=ScheduleVersion.Status.PUBLISHED,
            end__gte=today,
            start__lte=today + timedelta(days=MY_SCHEDULE_DAYS),
        )
        .aggregate(until=Max("end"))["until"]
    )
    if published_until:
        published_until = min(published_until, today + timedelta(days=MY_SCHEDULE_DAYS))
    return MyScheduleOut(
        home_location_name=profile.home_location.name,
        shifts=shifts,
        recent=past,
        published_until=published_until,
        months=[
            MonthHoursOut(
                month=m,
                hours=round(h / 3600, 2),
                pay=pay[m].amount,
                supplements_pay=pay[m].supplements,
                unpriced_hours=pay[m].unpriced_hours,
            )
            for m, h in totals.items()
        ],
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
    shift_type_id: UUID | None  # empty when the shift type was deleted later
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
    # The manager put this person here against a hard rule; `overridden` are the problems they accepted.
    forced: bool
    overridden: list[str]
    # The person's assignment on this shift (for "Zmień godziny" in a published schedule).
    assignment_id: UUID | None = None
    # Hours that count for the person instead of the schedule's; None: as planned.
    worked: WorkedOut | None = None
    # The person reported other hours that wait for the manager ("Godziny").
    hours_report: WaitingHoursOut | None = None


class VersionEmployeeOut(Schema):
    id: UUID
    name: str
    position_ids: list[UUID]
    hours: float
    shifts: int
    target_hours: float | None
    max_hours: float | None
    active: bool
    # Hours in published schedules of the person's other locations on the days of this period.
    hours_elsewhere: float = 0
    # The person's main location is another one (they work here as an extra location).
    home_location_name: str | None = None


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
    hard_problems: list[str]  # stop publishing
    # Hard rules the manager broke by hand and may keep (e.g. fewer experienced people than the staffing asks).
    accepted_problems: list[str]
    rules: list[RuleResultOut]
    # The manager's unmet instructions in full, then at most UNMET_LISTED employee requests, then the unscored ones.
    unmet_requests: list[UnmetRequestOut]
    # Employee requests checked and found not (fully) kept, counted before the list above is cut.
    unmet_request_count: int
    notes: list[str]
    history: list[VersionSummaryOut]
    today: date  # days before it have passed: their shifts and places cannot be changed
    # A correction of a published schedule: people whose shifts would change on publishing.
    changed_people: list[str]


class CandidateOut(Schema):
    employee_id: UUID
    name: str
    current: bool
    possible: bool
    # Not possible, but the manager may put the person in anyway ("Wpisz mimo to").
    can_force: bool
    problems: list[str]
    # Blocked (also) because they have another shift at the same time: the manager may move them here.
    clash: bool
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
    reasons: list[str]
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
    # Save even when the change breaks a hard rule ("nie mogę", a "no exceptions" rule).
    force: bool = False
    # The manager confirmed: take the person off their other shifts at the same time (they become holes).
    remove_clashes: bool = False


class ClashOut(Schema):
    shift_id: UUID
    employee_id: UUID
    kind: str  # "here" (this schedule), "draft" or "published" (another location's schedule)
    location_name: str
    text: str
    can_remove: bool
    reason: str


class CheckOut(Schema):
    ok: bool
    # Not ok, but the manager can save it anyway with `force`.
    can_force: bool
    problems: list[str]
    warnings: list[str]
    before: ScoresOut
    after: ScoresOut
    # Other shifts of the person at the same time. `problems_if_removed`: what would still be broken once the person
    # is taken off them; `ok_if_removed`: the manager may take them off and the change is then fine.
    clashes: list[ClashOut]
    problems_if_removed: list[str]
    ok_if_removed: bool
    # Not fine once the person is taken off, but only because of problems the manager may overrule: one
    # confirmation saves it with `remove_clashes` and `force`.
    can_force_if_removed: bool


class ShiftFitOut(Schema):
    shift_id: UUID
    # prefer: marked "chętnie"; can: marked "mogę"; cannot: "nie mogę" (the manager may overrule it) or another
    # shift at that time (never possible).
    fit: Literal["prefer", "can", "cannot"]
    reason: str


class DropCheckOut(CheckOut):
    shift_id: str  # the shift the person would be dropped on


class PinIn(Schema):
    pinned: bool


class SeatIn(Schema):
    date: date
    shift_type_id: UUID
    position_id: UUID


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
    overridden_by_slot: dict[str, list[str]] = defaultdict(list)
    for violation in loaded.report.waived:
        about = violation.slots or [s for s, e in problem.forced.items() if e == violation.employee]
        for slot_id in about:
            if slot_id in problem.forced:
                overridden_by_slot[slot_id].append(violation.message)
    rows = {}
    shifts = list(
        Shift.objects.for_company(loaded.version.company_id)
        .filter(version=loaded.version)
        .select_related("assignment", "position", "shift_type", "version", "location")
        .order_by("date", "start_at", "position__name", "slot_key")
    )
    from apps.worktime.services import pending_reports, worked_hours

    assignments = [shift.assignment for shift in shifts]
    worked, waiting = worked_hours(assignments), pending_reports(assignments)
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
            shift_type_id=shift.shift_type_id,
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
            forced=assignment.forced and employee_id is not None,
            overridden=overridden_by_slot.get(shift.slot_key, []),
            assignment_id=assignment.pk,
            worked=worked_out(worked.get(assignment.pk), shift),
            hours_report=report_out(waiting.get(assignment.pk), shift),
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


UNMET_LISTED = 30  # employee requests listed on the schedule card; the count covers all of them


def _unmet_requests(loaded) -> tuple[list[UnmetRequestOut], int]:
    """Unmet requests to list, and how many employee requests are unmet in total.
    The manager's own instructions are never cut: there are few and they matter most."""
    from engine.scoring import unmet_requests
    from engine.validator import RequestKind

    problem = loaded.problem
    names = {e.id: e.name for e in problem.employees}
    requests = {r.id: r for r in problem.requests}
    measures = unmet_requests(loaded.report, location=loaded.location_id)
    orders = [m for m in measures if m.by_manager]
    asked = [m for m in measures if not m.by_manager]
    result = []
    for measure in orders + asked[:UNMET_LISTED]:
        kept = round(100 * (1 - measure.degree), 1)
        if measure.kind == RequestKind.TEXT:
            text = requests[measure.request_id].summary
        else:
            share = f"{kept:g}".replace(".", ",")
            text = f"Dni „chętnie”: zmiany są w {share} % z nich (tyle, ile się dało)."
        kind = "instruction" if measure.by_manager else measure.kind.value
        result.append(UnmetRequestOut(employee_name=names[measure.employee], text=text, kind=kind, percent_kept=kept))
    for request_id in loaded.report.unscored_requests:
        request = requests[request_id]
        if problem.request_location(request) != loaded.location_id:
            continue
        result.append(
            UnmetRequestOut(
                employee_name=names[request.employee], text=request.summary, kind="unscored", percent_kept=None
            )
        )
    return result, len(asked)


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
    from apps.scheduling.editing import accepted, blocking, changed_people, is_editable

    version, problem = loaded.version, loaded.problem
    period = version.period
    hours = loaded.report.hours
    shift_count: dict[str, int] = defaultdict(int)
    for employee_id in loaded.schedule.values():
        if employee_id:
            shift_count[employee_id] += 1
    location_id = loaded.location_id
    homes = {e.home_location for e in problem.employees}
    location_names = {str(pk): name for pk, name in ctx.qs(Location).filter(pk__in=homes).values_list("pk", "name")}
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
            hours_elsewhere=round(
                sum(problem.minutes_elsewhere(e.id, problem.period_start, problem.period_end).values()) / 60, 2
            ),
            home_location_name=None if e.home_location == location_id else location_names.get(e.home_location),
        )
        for e in sorted(problem.employees, key=lambda e: e.name)
        if e.works_in(location_id) or shift_count[e.id]
    ]
    notes = list((version.scores or {}).get("notes", []))
    position_ids = {str(s.position) for s in problem.slots}
    unmet, unmet_count = _unmet_requests(loaded)
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
        hard_problems=[v.message for v in blocking(loaded.report.hard)],
        accepted_problems=[v.message for v in accepted(loaded.report.hard)],
        rules=_rule_results(loaded),
        unmet_requests=unmet,
        unmet_request_count=unmet_count,
        notes=notes,
        history=_history(version),
        today=today,
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
        reasons=list(explanation.reasons),
        candidates=[
            CandidateOut(
                employee_id=c.employee,
                name=c.name,
                current=c.current,
                possible=c.possible,
                can_force=c.can_force,
                problems=list(c.blocked),
                clash=c.clash,
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
        can_force=result.can_force,
        problems=result.problems,
        warnings=result.warnings,
        before=_scores_out(result.before),
        after=_scores_out(result.after),
        clashes=[
            ClashOut(
                shift_id=c.shift_id,
                employee_id=c.employee,
                kind=c.kind,
                location_name=c.location_name,
                text=c.text,
                can_remove=c.can_remove,
                reason=c.reason,
            )
            for c in result.clashes
        ],
        problems_if_removed=result.problems_if_removed,
        ok_if_removed=result.ok_if_removed,
        can_force_if_removed=result.can_force_if_removed,
    )


def _managed_ids(ctx) -> set[str]:
    return {str(pk) for pk in ctx.managed_locations().values_list("pk", flat=True)}


@router.post(
    "/versions/{version_id}/check",
    response={200: CheckOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def check_schedule_changes(request, version_id: UUID, payload: ChangesIn):
    """Validate a manual change before saving it (e.g. while dragging): new problems, the new scores and the other
    shifts of the person at the same time (the screen asks whether to take the person off them)."""
    from apps.scheduling.editing import check_changes, load_version

    ctx, version = _version_context(request, version_id)
    result, _ = check_changes(load_version(version), _changes(ctx, payload), manages=_managed_ids(ctx))
    return _check_out(result)


@router.get(
    "/versions/{version_id}/shifts/{shift_id}/drops",
    response={200: list[DropCheckOut], 403: ErrorOut, 404: ErrorOut},
)
def shift_drop_checks(request, version_id: UUID, shift_id: UUID):
    """What dropping this shift's person on each other shift would do (swap or move): new problems and scores.
    Asked once when a drag starts, so the answer for every shift is there before the manager hovers over it."""
    from apps.scheduling.editing import check_drops, load_version

    ctx, version = _version_context(request, version_id)
    shift = ctx.get(Shift, pk=shift_id, version=version)
    results = check_drops(load_version(version), str(shift.pk), manages=_managed_ids(ctx))
    return [DropCheckOut(shift_id=target, **_check_out(result).dict()) for target, result in results.items()]


@router.patch(
    "/versions/{version_id}/assignments",
    response={200: CheckOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def change_assignments(request, version_id: UUID, payload: ChangesIn):
    """Save a manual change (one shift, or two for a swap), also on days that have passed. A change that breaks
    a hard rule is refused with the reasons, unless `force` is set: the manager has the last word. With
    `remove_clashes` the person is first taken off their other shifts at the same time."""
    from apps.scheduling.editing import apply_changes

    ctx, version = _version_context(request, version_id)
    ctx.require_writable()
    result = apply_changes(
        version,
        _changes(ctx, payload),
        ctx.user,
        force=payload.force,
        remove_clashes=payload.remove_clashes,
        manages=_managed_ids(ctx),
    )
    return _check_out(result)


@router.get(
    "/versions/{version_id}/employees/{employee_id}/fit",
    response={200: list[ShiftFitOut], 403: ErrorOut, 404: ErrorOut},
)
def employee_fit(request, version_id: UUID, employee_id: UUID, moving_shift_id: UUID | None = None):
    """Where one person could work in this schedule, for colouring the grid while the manager moves them: every
    shift of their positions that they do not hold, with their calendar mark. Calendar and overlaps only (fast);
    the rules are checked when the manager picks a shift. `moving_shift_id`: the shift the person is being
    dragged away from, so it does not count as "another shift at that time"."""
    from apps.scheduling.editing import load_version
    from engine.problem import AvailabilityState

    ctx, version = _version_context(request, version_id)
    profile = ctx.get(EmployeeProfile, pk=employee_id)
    loaded = load_version(version)
    problem = loaded.problem
    employee = problem.employee_by_id.get(str(profile.pk))
    if employee is None:
        return []
    ids = dict(ctx.qs(Shift).filter(version=version).values_list("slot_key", "pk"))
    busy = [
        (s.start_utc, s.end_utc)
        for s in problem.slots
        if loaded.schedule.get(s.id) == employee.id and ids[s.id] != moving_shift_id
    ] + [(e.start_utc, e.end_utc) for e in problem.external_shifts if e.employee == employee.id]
    result = []
    for slot in problem.slots:
        if slot.position not in employee.positions or loaded.schedule.get(slot.id) == employee.id:
            continue
        wish = problem.availability_for(employee.id, slot)
        if wish == AvailabilityState.CANNOT:
            fit, reason = "cannot", "ma zaznaczone „nie mogę”"
        elif any(start < slot.end_utc and slot.start_utc < end for start, end in busy):
            fit, reason = "cannot", "ma inną zmianę w tym czasie"
        elif wish == AvailabilityState.PREFER:
            fit, reason = "prefer", "chętnie"
        else:
            fit, reason = "can", "może"
        result.append(ShiftFitOut(shift_id=ids[slot.id], fit=fit, reason=reason))
    return result


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
    "/versions/{version_id}/seats",
    response={201: VersionShiftOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def add_schedule_seat(request, version_id: UUID, payload: SeatIn):
    """One more person needed on a shift that day: an empty place in the draft, kept when arranging again
    (the date's staffing in the location's settings gets the same number)."""
    from apps.scheduling.editing import add_seat, load_version

    ctx, version = _version_context(request, version_id)
    ctx.require_writable()
    location = version.period.location
    shift_type = ctx.get(ShiftType, pk=payload.shift_type_id, location=location)
    position = ctx.get(Position, pk=payload.position_id, location=location)
    shift = add_seat(version, payload.date, shift_type, position)
    return Status(201, _shift_rows(load_version(version), timezone.localdate())[shift.slot_key])


@router.delete(
    "/versions/{version_id}/shifts/{shift_id}",
    response={204: None, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def remove_schedule_seat(request, version_id: UUID, shift_id: UUID):
    """One person fewer needed on a shift that day: the place leaves the draft (with whoever had it) and the
    date's staffing gets the same number."""
    from apps.scheduling.editing import remove_seat

    ctx, version = _version_context(request, version_id)
    ctx.require_writable()
    remove_seat(version, str(ctx.get(Shift, pk=shift_id, version=version).pk))
    return Status(204, None)


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


@router.delete(
    "/versions/{version_id}", response={204: None, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut}
)
def delete_schedule_draft(request, version_id: UUID):
    """ "Usuń szkic": remove the chosen version if it was never published. After the newest draft the version before
    it is current again (an earlier draft is editable again, a published schedule stays); an older attempt just goes.
    With no version left the period goes back to collecting."""
    from apps.scheduling.editing import delete_draft

    ctx, version = _version_context(request, version_id)
    ctx.require_writable()
    delete_draft(version)
    return Status(204, None)


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
