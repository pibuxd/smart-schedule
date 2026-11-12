"""Schedule periods and generating a schedule (the solver runs in the worker; the frontend polls the run)."""

from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID

from django.db import transaction
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.core.schemas import ErrorOut
from apps.scheduling.generation import request_generation
from apps.scheduling.models import GenerationRun, SchedulePeriod, ScheduleVersion
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
    # One period, or the periods with the same dates of several locations of one group.
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
        202: GenerationRunOut,
        400: ErrorOut,
        402: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        409: ErrorOut,
        429: ErrorOut,
    },
)
def generate_schedule(request, payload: GenerateIn):
    """Start arranging a schedule. Answers at once; poll `GET /generation-runs/{id}` for the result."""
    ids = list(dict.fromkeys(payload.period_ids))
    ctx, first = context_for(request, SchedulePeriod, ids[0])
    periods = [first] + [ctx.get(SchedulePeriod, pk=pk) for pk in ids[1:]]
    run = request_generation(ctx, periods)
    return Status(202, _run_out(run))


@router.get("/generation-runs/{run_id}", response={200: GenerationRunOut, 403: ErrorOut, 404: ErrorOut})
def generation_run(request, run_id: UUID):
    ctx, run = context_for(request, GenerationRun, run_id)
    for period in run.periods.select_related("location"):
        ctx.require_manager_of(period.location)
    return _run_out(run)
