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
from apps.scheduling.generation import request_generation
from apps.scheduling.models import Assignment, GenerationRun, SchedulePeriod, ScheduleVersion, Shift
from apps.staffing.me import employee_context
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


class PeriodOut(Schema):
    id: UUID
    location_id: UUID
    start: date
    end: date
    status: PeriodStatus
    published_version_id: UUID | None
    latest_version_id: UUID | None


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
    return PeriodOut(
        id=period.id,
        location_id=period.location_id,
        start=period.start,
        end=period.end,
        status=period.status,
        published_version_id=published,
        latest_version_id=versions[0][0] if versions else None,
    )


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
    with transaction.atomic():
        Location.objects.for_company(ctx.company).select_for_update().get(pk=location.pk)
        overlapping = ctx.qs(SchedulePeriod).filter(location=location, start__lte=payload.end, end__gte=payload.start)
        if overlapping.exists():
            raise HttpError(409, "Ten lokal ma już okres grafiku obejmujący część tych dni.")
        period = SchedulePeriod.objects.for_company(ctx.company).create(
            company=ctx.company, location=location, start=payload.start, end=payload.end
        )
    return Status(201, _period_out(period))


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
