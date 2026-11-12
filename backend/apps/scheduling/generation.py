"""Generating a schedule: asking for it (API), running it (worker) and saving the result as draft versions.

- `request_generation` checks the manager, the read-only mode and the monthly limit, then saves a queued
  `GenerationRun` and defers the solver job in one transaction (no job without a run, no run without a job).
- `run_generation` is what the worker does: build the `Problem`, solve it within the time limit, check the result
  with the independent validator and save one draft `ScheduleVersion` per location. A schedule that breaks a hard
  rule is never saved. It is safe to run twice: only a queued run is started.
- A run that fails gives its generation back to the monthly limit.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone
from ninja.errors import HttpError

from apps.billing.models import GenerationUsage
from apps.scheduling.models import Assignment, GenerationRun, SchedulePeriod, ScheduleVersion, Shift
from apps.scheduling.problem_builder import BuildError, BuiltProblem, build_problem, check_periods
from apps.tenancy.context import TenantContext
from apps.tenancy.models import Company
from engine.scoring import score
from engine.solver import solve
from engine.validator import validate

logger = logging.getLogger(__name__)

ACTIVE = (GenerationRun.Status.QUEUED, GenerationRun.Status.RUNNING)
# A run still "running" after this long lost its worker (restart, crash); queued ones wait longer for a worker.
STALE_RUNNING_AFTER = timedelta(minutes=10)
STALE_QUEUED_AFTER = timedelta(minutes=30)

INTERNAL_ERROR = "Nie udało się ułożyć grafiku z powodu błędu programu. Spróbuj ponownie za chwilę."
INVALID_RESULT = (
    "Ułożony grafik nie przeszedł końcowego sprawdzenia reguł, więc go nie zapisaliśmy. "
    "To błąd programu, nie ustawień. Spróbuj ponownie."
)
NO_SLOTS = "W tym okresie nie ma żadnych zmian do obsadzenia. Ustaw obsadę w ustawieniach lokalu."
STALE = "Układanie grafiku zostało przerwane. Spróbuj ponownie."


def _month(now=None) -> date:
    return timezone.localdate(now or timezone.now()).replace(day=1)


def request_generation(ctx: TenantContext, periods: Sequence[SchedulePeriod]) -> GenerationRun:
    """Queue a generation for one period, or for the same dates in several locations of one group."""
    try:
        check_periods(periods)
    except BuildError as exc:
        raise HttpError(400, str(exc)) from exc
    for period in periods:
        ctx.require_manager_of(period.location)
    ctx.require_writable()

    with transaction.atomic():
        # The company row serialises generations of one company (limit and "already running" checks).
        Company.objects.select_for_update().get(pk=ctx.company.pk)
        busy = ctx.qs(GenerationRun).filter(status__in=ACTIVE, periods__in=periods).exists()
        if busy:
            raise HttpError(409, "Grafik dla tego okresu już się układa. Poczekaj na wynik.")
        usage, _ = ctx.qs(GenerationUsage).get_or_create(company=ctx.company, month=_month())
        if usage.count >= settings.GENERATION_MONTHLY_LIMIT:
            raise HttpError(
                429,
                f"W tym miesiącu wykorzystano już limit {settings.GENERATION_MONTHLY_LIMIT} ułożeń grafiku. "
                "Nowe będą możliwe od pierwszego dnia kolejnego miesiąca.",
            )
        usage.count = F("count") + 1
        usage.save(update_fields=["count"])

        first = periods[0].location
        run = GenerationRun.objects.create(
            company=ctx.company,
            location=first if len(periods) == 1 else None,
            group_id=None if len(periods) == 1 else first.group_id,
            requested_by=ctx.user,
        )
        run.periods.set(periods)

        from apps.scheduling.tasks import solve_schedule  # tasks import this module

        solve_schedule.defer(run_id=str(run.pk))
    return run


def _give_back_generation(run: GenerationRun) -> None:
    GenerationUsage.objects.for_company(run.company_id).filter(month=_month(run.created_at), count__gt=0).update(
        count=F("count") - 1
    )


def _fail(run: GenerationRun, message: str, solver_status: str = "") -> GenerationRun:
    with transaction.atomic():
        run.status = GenerationRun.Status.FAILED
        run.error = message
        run.solver_status = solver_status
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "solver_status", "finished_at", "time_ms"])
        _give_back_generation(run)
    return run


def run_generation(
    run_id, *, time_limit_s: float | None = None, workers: int | None = None, today: date | None = None
) -> GenerationRun:
    """Solve a queued run and save its draft versions. Does nothing for a run that is not queued."""
    with transaction.atomic():
        run = GenerationRun.objects.select_for_update().filter(pk=run_id).first()
        if run is None or run.status != GenerationRun.Status.QUEUED:
            return run
        run.status = GenerationRun.Status.RUNNING
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at"])

    started = timezone.now()
    try:
        periods = list(run.periods.select_related("location"))
        built = build_problem(periods, today=today)
        if not built.problem.slots:
            return _fail(run, NO_SLOTS)
        result = solve(
            built.problem,
            time_limit_s=time_limit_s or settings.SOLVER_TIME_LIMIT_S,
            workers=workers or settings.SOLVER_WORKERS,
        )
        run.time_ms = result.time_ms
        if not result.has_schedule:
            return _fail(run, "\n".join(result.messages), result.status)
        report = validate(built.problem, result.schedule)
        if not report.ok:
            logger.error(
                "generation run %s: solver result breaks hard rules: %s",
                run.pk,
                "; ".join(v.message for v in report.hard[:20]),
            )
            return _fail(run, INVALID_RESULT, result.status)
        with transaction.atomic():
            _save_versions(run, built, result.schedule, report)
            run.status = GenerationRun.Status.SUCCEEDED
            run.solver_status = result.status
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "solver_status", "finished_at", "time_ms"])
        return run
    except BuildError as exc:
        return _fail(run, str(exc))
    except Exception:
        logger.exception("generation run %s failed", run.pk)
        run.time_ms = round((timezone.now() - started).total_seconds() * 1000)
        return _fail(run, INTERNAL_ERROR)


def _save_versions(run: GenerationRun, built: BuiltProblem, schedule, report) -> list[ScheduleVersion]:
    problem = built.problem
    home = {e.id: e.home_location for e in problem.employees}
    versions = []
    for period in built.periods:
        SchedulePeriod.objects.select_for_update().filter(pk=period.pk).first()  # numbers versions one at a time
        location_id = str(period.location_id)
        last = ScheduleVersion.objects.for_company(period.company_id).filter(period=period).aggregate(n=Max("number"))
        scores = score(problem, report, location=location_id)
        version = ScheduleVersion.objects.create(
            company_id=period.company_id,
            period=period,
            number=(last["n"] or 0) + 1,
            created_by=run.requested_by,
            from_run=run,
            scores={**scores.as_dict(), "notes": built.notes},
            is_complete=scores.is_complete,
        )
        slots = [s for s in problem.slots if s.location == location_id]
        shifts = Shift.objects.bulk_create(
            Shift(
                company_id=period.company_id,
                version=version,
                location_id=location_id,
                date=slot.date,
                shift_type_id=built.sources[slot.id].shift_type_id,
                position_id=built.sources[slot.id].position_id,
                start_at=slot.start,
                end_at=slot.end,
                slot_key=slot.id,
            )
            for slot in slots
        )
        Assignment.objects.bulk_create(
            Assignment(
                company_id=period.company_id,
                shift=shift,
                employee_id=schedule.get(shift.slot_key),
                pinned=shift.slot_key in problem.pinned,
                borrowed=schedule.get(shift.slot_key) is not None and home[schedule[shift.slot_key]] != location_id,
            )
            for shift in shifts
        )
        if period.status == SchedulePeriod.Status.COLLECTING:
            period.status = SchedulePeriod.Status.DRAFT
            period.save(update_fields=["status"])
        versions.append(version)
    return versions


def fail_stale_runs(now=None) -> int:
    """Runs whose worker vanished would be "in progress" forever; mark them failed and give the generation back."""
    now = now or timezone.now()
    stale = GenerationRun.objects.filter(  # all companies: a housekeeping job
        status=GenerationRun.Status.RUNNING, started_at__lt=now - STALE_RUNNING_AFTER
    ) | GenerationRun.objects.filter(status=GenerationRun.Status.QUEUED, created_at__lt=now - STALE_QUEUED_AFTER)
    count = 0
    for run_id in stale.values_list("pk", flat=True):
        with transaction.atomic():
            run = GenerationRun.objects.select_for_update().get(pk=run_id)
            if run.status in ACTIVE:
                _fail(run, STALE)
                count += 1
    return count
