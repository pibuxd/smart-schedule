"""What the assistant cost in a month, as CSV: per person, location or company (docs/plan.md section 38).

    python manage.py assistant_costs [--month 2026-11] [--by person|location|company] > costs.csv

Dollars come from OpenRouter (`usage.cost` of every response); Claude gives no price, so its messages are only
counted (`unpriced_messages`). Schedule arranging runs on our own server, so it is counted as runs and solver
minutes, not money. The last line is the whole month. For the superadmin only.
"""

import csv

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.assistant import costs


class Command(BaseCommand):
    help = "CSV of what the assistant cost in a month, per person, location or company."

    def add_arguments(self, parser):
        parser.add_argument("--month", help="Month as YYYY-MM (default: this month).")
        parser.add_argument("--by", choices=costs.BY_CHOICES, default="person", help="Line per person (default).")

    def handle(self, *args, month: str | None, by: str, **options):
        try:
            first = costs.parse_month(month) if month else timezone.localdate().replace(day=1)
        except ValueError as exc:
            raise CommandError("Podaj miesiąc jako RRRR-MM, np. 2026-11.") from exc
        out = csv.writer(self.stdout)
        for line in costs.csv_rows(first, by):
            out.writerow(line)
