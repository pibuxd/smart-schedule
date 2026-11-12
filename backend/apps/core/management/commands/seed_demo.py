from django.core.management.base import BaseCommand, CommandError

from apps.core.demo_data import create_demo_data, delete_demo_data, demo_data_exists


class Command(BaseCommand):
    help = "Create demo data: a bakery chain with 4 locations and a separate café (for isolation checks)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing demo data and create it again.")

    def handle(self, *args, reset: bool = False, **options):
        if demo_data_exists():
            if not reset:
                raise CommandError("Demo data already exists. Use --reset to recreate it.")
            delete_demo_data()
            self.stdout.write("Deleted previous demo data.")

        summary = create_demo_data()
        start, end = summary["period"]
        bakery, cafe = summary["bakery"], summary["cafe"]
        self.stdout.write(self.style.SUCCESS("Demo data created."))
        self.stdout.write(
            f"  {bakery['company']}: {bakery['locations']} locations, {bakery['employees']} employees, "
            f"{bakery['requests']} text requests, period {start:%Y-%m-%d} – {end:%Y-%m-%d}\n"
            f"    manager phone: {bakery['manager_phone']}\n"
            f"  {cafe['company']}: {cafe['employees']} employees\n"
            f"    manager phone: {cafe['manager_phone']}\n"
            "  Employee phones: +48 600 100 001 … (bakery), +48 700 200 001 … (café). "
            "Log in at /logowanie; the SMS code is printed by runserver."
        )
