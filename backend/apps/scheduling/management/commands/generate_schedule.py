"""Arrange a schedule right here, without the queue (for trying the generator on demo data).

    uv run python manage.py generate_schedule --company 6a1e0000-0000-4000-8000-000000000001
    uv run python manage.py generate_schedule --period <uuid> [--period <uuid> ...] [--time-limit 10] [--publish]

With `--company`, every location of the company is generated (separately) for its newest period.
The result is saved as draft versions, as from the worker, but does not count toward the monthly limit.
`--publish` publishes the new version at once, so the employee's "Mój grafik" has something to show
(until publishing from the manager's screens arrives in stage 8).
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.scheduling.generation import run_generation
from apps.scheduling.models import GenerationRun, SchedulePeriod, ScheduleVersion


def publish_version(version: ScheduleVersion) -> None:
    """Make `version` the published one of its period; the previous published version becomes history."""
    with transaction.atomic():
        version.period.versions.filter(status=ScheduleVersion.Status.PUBLISHED).update(
            status=ScheduleVersion.Status.SUPERSEDED
        )
        version.status = ScheduleVersion.Status.PUBLISHED
        version.published_at = timezone.now()
        version.save(update_fields=["status", "published_at"])
        version.period.status = SchedulePeriod.Status.PUBLISHED
        version.period.save(update_fields=["status"])


class Command(BaseCommand):
    help = "Ułóż grafik od razu, bez kolejki (do sprawdzenia generatora na danych przykładowych)."

    def add_arguments(self, parser):
        parser.add_argument("--period", action="append", default=[], help="Id okresu (można podać kilka).")
        parser.add_argument("--company", help="Id firmy: wszystkie grupy i lokale, najnowszy okres.")
        parser.add_argument("--time-limit", type=float, default=None, help="Limit czasu w sekundach.")
        parser.add_argument("--publish", action="store_true", help="Od razu opublikuj nową wersję.")

    def handle(self, *args, **options):
        if options["period"]:
            periods = list(SchedulePeriod.objects.filter(pk__in=options["period"]).select_related("location"))
        elif options["company"]:
            periods = self._newest_periods(options["company"])
        else:
            raise CommandError("Podaj --period albo --company.")
        if not periods:
            raise CommandError("Nie znaleziono okresów.")
        for period in periods:  # locations are independent: one run each
            run = GenerationRun.objects.create(company_id=period.company_id, location=period.location)
            run.periods.set([period])
            run = run_generation(run.pk, time_limit_s=options["time_limit"])
            self.stdout.write(f"{period.location.name}: {run.status} ({run.solver_status or '-'}, {run.time_ms} ms)")
            if run.error:
                self.stdout.write(f"  {run.error}")
            for version in run.versions.select_related("period__location").order_by("period__location__name"):
                s = version.scores
                self.stdout.write(
                    f"  {version.period.location.name} v{version.number}: dziury {s['holes']}/{s['slots']}, "
                    f"zasady {s['manager_rules']} %, prośby {s['employee_requests']} %"
                )
                if options["publish"]:
                    publish_version(version)
                    self.stdout.write("  opublikowano")

    def _newest_periods(self, company_id):
        periods = SchedulePeriod.objects.for_company(company_id).select_related("location").order_by("-start")
        newest: dict = {}
        for period in periods:
            newest.setdefault(period.location_id, period)
        return sorted(newest.values(), key=lambda p: p.location.name)
