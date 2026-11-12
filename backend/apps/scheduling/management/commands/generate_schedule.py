"""Arrange a schedule right here, without the queue (for trying the generator on demo data).

    uv run python manage.py generate_schedule --company 6a1e0000-0000-4000-8000-000000000001
    uv run python manage.py generate_schedule --period <uuid> [--period <uuid> ...] [--time-limit 10]

With `--company`, every group of the company is generated for its newest common period, and every location
without a group on its own. The result is saved as draft versions, as from the worker, but does not count
toward the monthly limit.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from apps.scheduling.generation import run_generation
from apps.scheduling.models import GenerationRun, SchedulePeriod


class Command(BaseCommand):
    help = "Ułóż grafik od razu, bez kolejki (do sprawdzenia generatora na danych przykładowych)."

    def add_arguments(self, parser):
        parser.add_argument("--period", action="append", default=[], help="Id okresu (można podać kilka).")
        parser.add_argument("--company", help="Id firmy: wszystkie grupy i lokale, najnowszy okres.")
        parser.add_argument("--time-limit", type=float, default=None, help="Limit czasu w sekundach.")

    def handle(self, *args, **options):
        batches = []
        if options["period"]:
            batches.append(list(SchedulePeriod.objects.filter(pk__in=options["period"]).select_related("location")))
        elif options["company"]:
            batches = self._company_batches(options["company"])
        else:
            raise CommandError("Podaj --period albo --company.")
        if not batches or not all(batches):
            raise CommandError("Nie znaleziono okresów.")
        for periods in batches:
            first = periods[0].location
            run = GenerationRun.objects.create(
                company_id=first.company_id,
                location=first if len(periods) == 1 else None,
                group_id=None if len(periods) == 1 else first.group_id,
            )
            run.periods.set(periods)
            run = run_generation(run.pk, time_limit_s=options["time_limit"])
            names = ", ".join(p.location.name for p in periods)
            self.stdout.write(f"{names}: {run.status} ({run.solver_status or '-'}, {run.time_ms} ms)")
            if run.error:
                self.stdout.write(f"  {run.error}")
            for version in run.versions.select_related("period__location").order_by("period__location__name"):
                s = version.scores
                self.stdout.write(
                    f"  {version.period.location.name} v{version.number}: dziury {s['holes']}/{s['slots']}, "
                    f"zasady {s['manager_rules']} %, prośby {s['employee_requests']} %"
                )

    def _company_batches(self, company_id):
        periods = SchedulePeriod.objects.for_company(company_id).select_related("location").order_by("-start")
        newest: dict = {}
        for period in periods:
            newest.setdefault(period.location_id, period)
        by_scope = defaultdict(list)
        for period in newest.values():
            group = period.location.group_id
            by_scope[(group, period.start, period.end) if group else (period.location_id,)].append(period)
        return list(by_scope.values())
