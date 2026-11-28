"""The location for the closed test of the phone apps (apps/tenancy/testers.py, docs/mobile.md).

    python manage.py tester_location --name "Kawiarnia Testowa"   # create it (empty), then set TESTERS_LOCATION_ID
    python manage.py tester_location                               # how many places are taken
    python manage.py tester_location --days 60                     # access for 60 more days from today

Run it again after setting REVIEW_LOGIN_PHONE: the reviewers' account becomes a manager of the location.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.login import review_phone
from apps.tenancy import testers


class Command(BaseCommand):
    help = "Lokal do testów zamkniętych aplikacji: tworzy go (pusty) albo pokazuje, ile miejsc zajęto."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="", help="Nazwa nowego lokalu (i firmy).")
        parser.add_argument("--days", type=int, default=None, help="Dostęp na tyle dni od dziś (nowy lokal: 90).")

    def handle(self, *args, name="", days=None, **options):
        if days is not None and days <= 0:
            raise CommandError("--days musi być większe od zera.")
        if not settings.TESTERS_LOCATION_ID and not name.strip():
            raise CommandError('Testy są wyłączone. Utwórz lokal: --name "Nazwa lokalu".')
        try:
            setup = testers.set_up(name, days)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        location = setup.location
        places = testers.places(location)
        if setup.created:
            self.stdout.write(self.style.SUCCESS(f"Utworzono pusty lokal „{location.name}”."))
        else:
            self.stdout.write(f"Lokal testerów: „{location.name}”.")
        self.stdout.write(
            f"Kierownicy: {places.managers} z {settings.TESTERS_MANAGERS}, "
            f"pracownicy: {places.employees} z {settings.TESTERS_EMPLOYEES}."
        )
        if setup.access_until:
            self.stdout.write(f"Dostęp do {setup.access_until:%d.%m.%Y}.")
        if str(location.pk) != settings.TESTERS_LOCATION_ID:
            self.stdout.write(self.style.WARNING("Nowe numery dołączą dopiero po dopisaniu do .env i restarcie api:"))
            self.stdout.write(f"TESTERS_LOCATION_ID={location.pk}")
        if setup.reviewer is not None:
            self.stdout.write(
                f"Konto recenzenta (kierownik tego lokalu): {review_phone()}, kod {settings.REVIEW_LOGIN_CODE}."
            )
