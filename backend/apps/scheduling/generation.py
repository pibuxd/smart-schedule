"""Generating a schedule: asking for it (API), running it (worker) and saving the result as draft versions.

- `request_generation` checks the manager, the read-only mode and the monthly limit, then saves one queued
  `GenerationRun` per location and defers its solver job in one transaction (no job without a run, no run
  without a job). Locations are independent, so each is arranged on its own.
- `run_generation` is what the worker does: build the `Problem`, solve it within the time limit, check the result
  with the independent validator and save one draft `ScheduleVersion` per location. A schedule that breaks a hard
  rule is never saved. It is safe to run twice: only a queued run is started.
- A run that fails gives its generation back to the monthly limit.
- `cancel_generation` stops a queued or running run when the manager asks: the run is marked cancelled at once,
  the worker's solver notices within about a second, nothing is saved and the generation is given back.
- A `different` run ("Ułóż inaczej", docs/plan.md section 36) asks the solver to give at least `DIFFERENT_SHARE`
  of the person-shifts of each earlier version of the period (up to `COMPARED_VERSIONS`) to someone else, without more
  holes; the new draft's notes say how different it came out.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Sequence
from datetime import date, timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F, Max
from django.utils import timezone
from ninja.errors import HttpError

from apps.billing.models import GenerationUsage
from apps.scheduling.models import Assignment, GenerationRun, SchedulePeriod, ScheduleVersion, Shift
from apps.scheduling.problem_builder import BuildError, BuiltProblem, build_problem
from apps.tenancy.context import TenantContext
from apps.tenancy.models import Company
from engine.scoring import Scores, score
from engine.solver import SolveStatus, changed_shifts, solve
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
# "Ułóż inaczej": the share of person-shifts that should get someone else, compared with this many newest versions
# (more than one, so arranging differently again does not bring back the schedule from a moment ago).
DIFFERENT_SHARE = 0.3
COMPARED_VERSIONS = 100  # every version in practice; only a bound on the solver's work
ALREADY_FINISHED = "Układanie grafiku już się skończyło, więc nie ma czego anulować."


def _month(now=None) -> date:
    return timezone.localdate(now or timezone.now()).replace(day=1)


def request_generation(
    ctx: TenantContext, periods: Sequence[SchedulePeriod], *, different: bool = False
) -> list[GenerationRun]:
    """Queue one generation per period. Locations are independent: each is arranged on its own, with its own
    rules and weights, and each run counts toward the monthly limit ("arrange all" = one run per location).
    `different`: the result has to differ clearly from the period's latest versions ("Ułóż inaczej")."""
    periods = list({p.pk: p for p in periods}.values())
    for period in periods:
        ctx.require_manager_of(period.location)
        if period.location.archived_at is not None:
            raise HttpError(409, f"Lokal {period.location.name} jest w archiwum. Przywróć go, żeby ułożyć grafik.")
    ctx.require_writable()

    with transaction.atomic():
        # The company row serialises generations of one company (limit and "already running" checks).
        Company.objects.select_for_update().get(pk=ctx.company.pk)
        busy = ctx.qs(GenerationRun).filter(status__in=ACTIVE, periods__in=periods).exists()
        if busy:
            raise HttpError(409, "Grafik dla tego okresu już się układa. Poczekaj na wynik.")
        usage, _ = ctx.qs(GenerationUsage).get_or_create(company=ctx.company, month=_month())
        limit = settings.GENERATION_MONTHLY_LIMIT  # 0 = no limit
        if limit and usage.count + len(periods) > limit:
            left = max(0, limit - usage.count)
            raise HttpError(
                429,
                f"W tym miesiącu limit to {limit} ułożeń grafiku i zostało {left}, a potrzeba {len(periods)}. "
                "Nowe będą możliwe od pierwszego dnia kolejnego miesiąca.",
            )
        usage.count = F("count") + len(periods)
        usage.save(update_fields=["count"])

        from apps.scheduling.tasks import solve_schedule  # tasks import this module

        runs = []
        for period in periods:
            run = GenerationRun.objects.create(
                company=ctx.company, location=period.location, requested_by=ctx.user, different=different
            )
            run.periods.set([period])
            solve_schedule.defer(run_id=str(run.pk))
            runs.append(run)
    return runs


def _give_back_generation(run: GenerationRun) -> None:
    GenerationUsage.objects.for_company(run.company_id).filter(month=_month(run.created_at), count__gt=0).update(
        count=F("count") - 1
    )


def cancel_generation(ctx: TenantContext, run: GenerationRun) -> GenerationRun:
    """Stop a queued or running generation. Nothing is saved; the generation does not count toward the limit."""
    for period in run.periods.select_related("location"):
        ctx.require_manager_of(period.location)
    ctx.require_writable()
    with transaction.atomic():
        run = ctx.qs(GenerationRun).select_for_update().get(pk=run.pk)
        if run.status not in ACTIVE:
            raise HttpError(409, ALREADY_FINISHED)
        run.status = GenerationRun.Status.CANCELLED
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])
        _give_back_generation(run)
    return run


def _cancelled(run_id) -> bool:
    return GenerationRun.objects.filter(pk=run_id, status=GenerationRun.Status.CANCELLED).exists()  # by run id


def _stop_check(run_id):
    """What the solver asks about once a second, mostly from its helper thread. That thread gets its own
    database connection, closed after every question so none is left open when the search ends."""
    caller = threading.get_ident()

    def should_stop() -> bool:
        try:
            return _cancelled(run_id)
        finally:
            if threading.get_ident() != caller:
                connection.close()

    return should_stop


def _still_active(run: GenerationRun) -> bool:
    """Lock the run and say whether its outcome may still be written (False once it was cancelled or ended)."""
    status = GenerationRun.objects.select_for_update().filter(pk=run.pk).values_list("status", flat=True).first()
    return status in ACTIVE


def _fail(run: GenerationRun, message: str, solver_status: str = "") -> GenerationRun:
    with transaction.atomic():
        if not _still_active(run):
            run.refresh_from_db()
            return run
        run.status = GenerationRun.Status.FAILED
        run.error = message
        run.solver_status = solver_status
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "solver_status", "finished_at", "time_ms"])
        _give_back_generation(run)
    return run


def run_generation(
    run_id,
    *,
    time_limit_s: float | None = None,
    workers: int | None = None,
    today: date | None = None,
    should_stop=None,
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
        earlier = _earlier_versions(periods) if run.different else {}
        result = solve(
            built.problem,
            time_limit_s=time_limit_s or settings.SOLVER_TIME_LIMIT_S,
            workers=workers or settings.SOLVER_WORKERS,
            should_stop=should_stop or _stop_check(run.pk),
            diversity_from=[schedule for versions in earlier.values() for _, schedule in versions],
            min_difference=DIFFERENT_SHARE,
        )
        run.time_ms = result.time_ms
        if result.status == SolveStatus.STOPPED:
            run.refresh_from_db()
            return run
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
            if not _still_active(run):  # cancelled while the result was being checked
                run.refresh_from_db()
                return run
            locations = {period.pk: str(period.location_id) for period in periods}
            notes = {
                pk: _difference_notes(
                    built, versions, result.schedule, score(built.problem, report, location=locations[pk])
                )
                for pk, versions in earlier.items()
            }
            _save_versions(run, built, result.schedule, report, notes)
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


def _earlier_versions(periods: Sequence[SchedulePeriod]) -> dict:
    """Period id -> its versions (newest first, at most COMPARED_VERSIONS) with their schedules (slot key -> employee
    id or None). All of them, so that clicking "Ułóż inaczej" again and again keeps giving new schedules."""
    earlier = {}
    for period in periods:
        versions = list(
            ScheduleVersion.objects.for_company(period.company_id)
            .filter(period=period)
            .order_by("-number")[:COMPARED_VERSIONS]
        )
        schedules: dict = {version.pk: {} for version in versions}
        rows = Assignment.objects.for_company(period.company_id).filter(shift__version__in=versions)
        for version_id, key, employee in rows.values_list("shift__version", "shift__slot_key", "employee"):
            schedules[version_id][key] = str(employee) if employee else None
        if versions:
            earlier[period.pk] = [(version, schedules[version.pk]) for version in versions]
    return earlier


def _difference_notes(built: BuiltProblem, versions, schedule, scores: Scores) -> list[str]:
    """What "Ułóż inaczej" achieved: compared with the version the manager saw, then with the older ones, and the
    scores that came out lower than in the version the manager saw (difference goes before rules and requests)."""
    version, before = versions[0]
    changed, total = changed_shifts(built.problem, before, schedule)
    if total == 0:
        return [
            f"Ułożony inaczej niż wersja {version.number}, ale nie było czego zmienić: wszystkie obsadzone zmiany "
            "są przypięte albo minęły."
        ]
    note = f"Ułożony inaczej niż wersja {version.number}: inne osoby na {changed} z {total} {_shifts_of(total)}."
    reached = changed >= math.ceil(DIFFERENT_SHARE * total)
    older = []
    for other, shifts in versions[1:]:
        other_changed, other_total = changed_shifts(built.problem, shifts, schedule)
        if other_total:
            older.append((other_changed / other_total, other.number, other_changed, other_total))
    if older:
        _share, number, least, out_of = min(older)
        if least >= math.ceil(DIFFERENT_SHARE * out_of):
            note += " Od starszych wersji też różni się co najmniej co trzecią zmianą."
        else:
            reached = False
            note += f" Od wersji {number} różni się mniej: inne osoby na {least} z {out_of} {_shifts_of(out_of)}."
    if not reached:
        note += " Bardziej się nie dało przy tych dyspozycjach i zasadach bez zostawiania zmian bez obsady."
    lower = [
        f"{label} {_percent(getattr(scores, key))} zamiast {_percent(before)}"
        for key, label in (("manager_rules", "zasady kierownika"), ("employee_requests", "prośby pracowników"))
        if (before := (version.scores or {}).get(key)) is not None and round(getattr(scores, key), 1) < round(before, 1)
    ]
    if lower:
        note += f" Słabiej niż w wersji {version.number}: {', '.join(lower)}."
    return [note]


def _percent(value: float) -> str:
    """Like the screen: one decimal at most, a decimal comma ("81,6 %", "90 %")."""
    return f"{round(value, 1):g}".replace(".", ",") + " %"


def _shifts_of(count: int) -> str:
    """After "z <count>": "z 1 zmiany", "z 2 zmian"."""
    return "zmiany" if count == 1 else "zmian"


def _save_versions(
    run: GenerationRun, built: BuiltProblem, schedule, report, extra_notes: dict | None = None
) -> list[ScheduleVersion]:
    problem = built.problem
    people = problem.employee_by_id
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
            scores={**scores.as_dict(), "notes": [*built.notes, *(extra_notes or {}).get(period.pk, [])]},
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
                needs_experienced=slot.needs_experienced,
            )
            for slot in slots
        )
        Assignment.objects.bulk_create(
            Assignment(
                company_id=period.company_id,
                shift=shift,
                employee_id=schedule.get(shift.slot_key),
                pinned=shift.slot_key in problem.pinned,
                forced=shift.slot_key in problem.forced
                and schedule.get(shift.slot_key) == problem.forced[shift.slot_key],
                borrowed=schedule.get(shift.slot_key) is not None
                and not people[schedule[shift.slot_key]].works_in(location_id),
            )
            for shift in shifts
        )
        # Older drafts become history: arranging again replaces them (pins were carried over by the builder).
        ScheduleVersion.objects.for_company(period.company_id).filter(
            period=period, status=ScheduleVersion.Status.DRAFT, number__lt=version.number
        ).update(status=ScheduleVersion.Status.SUPERSEDED)
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
