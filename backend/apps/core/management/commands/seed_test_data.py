"""Test data for a thorough manual test of the deployed app (three separate test companies, see apps.core.test_data).

    python manage.py seed_test_data            # create (refuses when it already exists)
    python manage.py seed_test_data --reset    # delete the test companies (and companies registered from the
                                               # test numbers) and create them again
    python manage.py seed_test_data --delete   # only delete

Touches nothing outside the test companies: demo data and real companies stay as they are.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.core import test_data as td
from apps.scheduling.models import SchedulePeriod


class Command(BaseCommand):
    help = "Dane do testów ręcznych: trzy firmy testowe (numery +48 510…, 520…, 530…)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Usuń dane testowe i utwórz je od nowa.")
        parser.add_argument("--delete", action="store_true", help="Tylko usuń dane testowe.")
        parser.add_argument("--seconds", type=float, default=td.SOLVER_SECONDS, help="Limit czasu układania.")

    def handle(self, *args, reset=False, delete=False, seconds=td.SOLVER_SECONDS, **options):
        if delete or reset:
            self.stdout.write(f"Usunięto firm testowych: {td.delete_test_data()}")
            if delete:
                return
        elif td.test_data_exists():
            raise CommandError("Dane testowe już są. Użyj --reset, żeby utworzyć je od nowa.")
        conflicts = td.foreign_phone_conflicts()
        if conflicts:
            raise CommandError("Te numery mają już konta spoza firm testowych: " + ", ".join(conflicts))

        built = td.create_base()
        self.stdout.write("Firmy, lokale, ludzie, dyspozycje i prośby utworzone. Układam grafiki (ok. 2 min)…")
        for period in built.to_publish:
            user = built.manager_c if period.company_id == td.COMPANY_C else built.owner_a
            self.stdout.write("  " + td.generate(period, publish_it=True, user=user, seconds=seconds))
        for period in built.to_draft:
            self.stdout.write("  " + td.generate(period, publish_it=False, user=None, seconds=seconds))
            self.stdout.write("  " + td.pin_draft(SchedulePeriod.objects.get(pk=period.pk)))
        for line in td.create_offers(built):
            self.stdout.write("  " + line)

        p = built.periods
        self.stdout.write(self.style.SUCCESS("\nDane testowe gotowe."))
        self.stdout.write(
            f"Okres opublikowany: {p.published[0]:%d.%m}–{p.published[1]:%d.%m.%Y}, "
            f"następny: {p.next[0]:%d.%m}–{p.next[1]:%d.%m.%Y}, kawiarnia: tygodnie od {p.week0[0]:%d.%m}."
        )
        self.stdout.write("Kody dostępu (wpisuje kierownik w Ustawieniach; pokazane tylko teraz):")
        labels = {
            "ok_30": "30 dni, 3 użycia",
            "ok_60": "60 dni, 1 użycie",
            "expired": "przeterminowany",
            "used_up": "już wykorzystany",
        }
        for key, code in built.codes.items():
            self.stdout.write(f"  {code}  ({labels[key]})")
