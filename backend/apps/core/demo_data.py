"""Demo data: a bakery chain with 4 locations in one group, and a separate café company for isolation checks.

Everything is deterministic (fixed random seed), so every run produces the same people and requests.
Dates are relative to "today": availability and requests are for the next calendar month.
"""

import calendar
import random
import uuid
from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.availability.models import (
    AvailabilityDay,
    AvailabilityPattern,
    AvailabilityState,
    AvailabilitySubmission,
    TextRequest,
)
from apps.billing.models import Subscription
from apps.rules.models import RuleSetting, WeightProfile
from apps.scheduling.models import SchedulePeriod
from apps.staffing.models import Contract, EmployeeProfile, Position, ShiftType, StaffingException, StaffingRule
from apps.tenancy.models import Company, Invitation, InvitationStatus, Location, LocationGroup, Membership, Role

BAKERY_COMPANY_ID = uuid.UUID("6a1e0000-0000-4000-8000-000000000001")
CAFE_COMPANY_ID = uuid.UUID("6a1e0000-0000-4000-8000-000000000002")
DEMO_COMPANY_IDS = (BAKERY_COMPANY_ID, CAFE_COMPANY_ID)

BAKERY_MANAGER_PHONE = "+48500100100"
CAFE_MANAGER_PHONE = "+48500200200"

FEMALE_NAMES = [
    "Anna",
    "Katarzyna",
    "Małgorzata",
    "Agnieszka",
    "Barbara",
    "Ewa",
    "Magdalena",
    "Joanna",
    "Zofia",
    "Julia",
    "Aleksandra",
    "Natalia",
    "Karolina",
    "Weronika",
    "Monika",
    "Halina",
    "Dorota",
    "Paulina",
    "Wiktoria",
    "Jadwiga",
    "Krystyna",
    "Beata",
    "Oliwia",
    "Maja",
    "Elżbieta",
]
MALE_NAMES = [
    "Piotr",
    "Krzysztof",
    "Andrzej",
    "Tomasz",
    "Paweł",
    "Jan",
    "Michał",
    "Marcin",
    "Stanisław",
    "Jakub",
    "Grzegorz",
    "Łukasz",
    "Mateusz",
    "Adam",
    "Marek",
    "Kamil",
    "Wojciech",
    "Bartosz",
    "Szymon",
    "Józef",
    "Zbigniew",
    "Ryszard",
    "Dawid",
    "Filip",
    "Kacper",
]
# (male form, female form)
SURNAMES = [
    ("Nowak", "Nowak"),
    ("Kowalski", "Kowalska"),
    ("Wiśniewski", "Wiśniewska"),
    ("Wójcik", "Wójcik"),
    ("Kowalczyk", "Kowalczyk"),
    ("Kamiński", "Kamińska"),
    ("Lewandowski", "Lewandowska"),
    ("Zieliński", "Zielińska"),
    ("Szymański", "Szymańska"),
    ("Woźniak", "Woźniak"),
    ("Dąbrowski", "Dąbrowska"),
    ("Kozłowski", "Kozłowska"),
    ("Jankowski", "Jankowska"),
    ("Mazur", "Mazur"),
    ("Kwiatkowski", "Kwiatkowska"),
    ("Krawczyk", "Krawczyk"),
    ("Piotrowski", "Piotrowska"),
    ("Grabowski", "Grabowska"),
    ("Nowakowski", "Nowakowska"),
    ("Pawłowski", "Pawłowska"),
    ("Michalski", "Michalska"),
    ("Nowicki", "Nowicka"),
    ("Adamczyk", "Adamczyk"),
    ("Dudek", "Dudek"),
    ("Zając", "Zając"),
    ("Wieczorek", "Wieczorek"),
    ("Jabłoński", "Jabłońska"),
    ("Król", "Król"),
    ("Majewski", "Majewska"),
    ("Olszewski", "Olszewska"),
    ("Jaworski", "Jaworska"),
    ("Wróbel", "Wróbel"),
    ("Malinowski", "Malinowska"),
    ("Pawlak", "Pawlak"),
    ("Witkowski", "Witkowska"),
    ("Walczak", "Walczak"),
    ("Stępień", "Stępień"),
    ("Górski", "Górska"),
    ("Rutkowski", "Rutkowska"),
    ("Michalak", "Michalak"),
    ("Sikora", "Sikora"),
    ("Ostrowski", "Ostrowska"),
    ("Baran", "Baran"),
    ("Duda", "Duda"),
    ("Szewczyk", "Szewczyk"),
    ("Tomaszewski", "Tomaszewska"),
    ("Pietrzak", "Pietrzak"),
    ("Marciniak", "Marciniak"),
    ("Wróblewski", "Wróblewska"),
    ("Zalewski", "Zalewska"),
    ("Jakubowski", "Jakubowska"),
    ("Jasiński", "Jasińska"),
    ("Zawadzki", "Zawadzka"),
    ("Sadowski", "Sadowska"),
    ("Bąk", "Bąk"),
    ("Chmielewski", "Chmielewska"),
    ("Włodarczyk", "Włodarczyk"),
    ("Borkowski", "Borkowska"),
    ("Czarnecki", "Czarnecka"),
    ("Sawicki", "Sawicka"),
    ("Sokołowski", "Sokołowska"),
    ("Urbański", "Urbańska"),
    ("Kubiak", "Kubiak"),
    ("Maciejewski", "Maciejewska"),
    ("Szczepański", "Szczepańska"),
    ("Kucharski", "Kucharska"),
    ("Wilk", "Wilk"),
    ("Kalinowski", "Kalinowska"),
    ("Lis", "Lis"),
    ("Mazurek", "Mazurek"),
    ("Wysocki", "Wysocka"),
    ("Adamski", "Adamska"),
    ("Kaźmierczak", "Kaźmierczak"),
    ("Wasilewski", "Wasilewska"),
    ("Sobczak", "Sobczak"),
    ("Czerwiński", "Czerwińska"),
    ("Andrzejewski", "Andrzejewska"),
    ("Cieślak", "Cieślak"),
    ("Głowacki", "Głowacka"),
    ("Zakrzewski", "Zakrzewska"),
    ("Kołodziej", "Kołodziej"),
    ("Sikorski", "Sikorska"),
    ("Krajewski", "Krajewska"),
    ("Gajewski", "Gajewska"),
    ("Szulc", "Szulc"),
    ("Szymczak", "Szymczak"),
    ("Baranowski", "Baranowska"),
    ("Laskowski", "Laskowska"),
    ("Brzeziński", "Brzezińska"),
    ("Makowski", "Makowska"),
    ("Ziółkowski", "Ziółkowska"),
    ("Przybylski", "Przybylska"),
]

# Fixed-date public holidays in Poland (Christmas Eve is a public holiday since 2025). Easter-based ones are skipped.
FIXED_HOLIDAYS = {
    (1, 1): "Nowy Rok",
    (1, 6): "Trzech Króli",
    (5, 1): "Święto Pracy",
    (5, 3): "Święto Konstytucji 3 Maja",
    (8, 15): "Wniebowzięcie NMP",
    (11, 1): "Wszystkich Świętych",
    (11, 11): "Święto Niepodległości",
    (12, 24): "Wigilia",
    (12, 25): "Boże Narodzenie",
    (12, 26): "Drugi dzień świąt",
}


@dataclass(frozen=True)
class BakerySpec:
    name: str
    address: str
    employees: int  # 15-25 per location (spec)
    bakers: int
    shift_leads: int
    drivers: int = 0


BAKERIES = [
    BakerySpec(
        "Wieliczka – Rynek", "Rynek Górny 4, 32-020 Wieliczka", employees=22, bakers=6, shift_leads=3, drivers=2
    ),
    BakerySpec(
        "Niepołomice – Kościuszki", "ul. Kościuszki 12, 32-005 Niepołomice", employees=18, bakers=5, shift_leads=2
    ),
    BakerySpec("Skawina – Mickiewicza", "ul. Mickiewicza 30, 32-050 Skawina", employees=16, bakers=4, shift_leads=2),
    BakerySpec("Zielonki – Krakowska", "ul. Krakowska 51, 32-087 Zielonki", employees=20, bakers=5, shift_leads=3),
]

REQUEST_TEMPLATES = [
    ("Nie chcę mieć zmian razem z {other}, ciągle się kłócimy przy kasie.", "unikaj_osoby", "wazne"),
    (
        "Jeśli się da, chciałabym pracować razem z {other}, dojeżdżamy jednym autem z Krakowa.",
        "preferuj_osobe",
        "mile_widziane",
    ),
    ("W tym miesiącu wolę tylko ranne zmiany, po południu mam zajęcia na uczelni.", "typ_zmiany", "bardzo_wazne"),
    ("Potrzebuję w tym miesiącu maksymalnie 80 godzin, mam sesję.", "limit_godzin", "bardzo_wazne"),
    ("Proszę nie dawać mi dwóch nocek pod rząd, potem nie mogę dojść do siebie.", "inne", "wazne"),
    ("{day} mam wesele siostry, najlepiej wolny cały weekend.", "inne", "bardzo_wazne"),
    ("Chętnie wezmę więcej godzin, zbieram na wakacje.", "limit_godzin", "mile_widziane"),
    ("Nie mogę zamykać w piątki, odbieram dziecko z przedszkola o 17.", "typ_zmiany", "bardzo_wazne"),
    ("Wolałbym nie pracować z {other} na nocce, nie dogadujemy się co do pieca.", "unikaj_osoby", "wazne"),
    ("Proszę o zmiany popołudniowe, rano zawożę mamę na rehabilitację.", "typ_zmiany", "wazne"),
    ("Mogę pracować najwyżej 3 dni w tygodniu, bo mam drugą pracę.", "limit_godzin", "bardzo_wazne"),
    ("Byłoby super, gdybym miała zmiany z {other}, uczy mnie obsługi ekspresu.", "preferuj_osobe", "mile_widziane"),
    ("Od połowy miesiąca mam praktyki, wtedy tylko weekendy.", "inne", "bardzo_wazne"),
    ("Nie dawajcie mi proszę zamknięć, wracam ostatnim autobusem.", "typ_zmiany", "wazne"),
]

TIME = time  # alias to keep the tables below short


def next_month_bounds(today: date) -> tuple[date, date]:
    first = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return first, last


def days_between(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


class PhoneBook:
    """Valid, unique Polish mobile numbers for demo people."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.counter = 0

    def next(self) -> str:
        self.counter += 1
        return f"+48{self.prefix}{self.counter:03d}"


class NamePicker:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.used: set[tuple[str, str]] = set()

    def next(self) -> tuple[str, str]:
        while True:
            female = self.rng.random() < 0.55
            first = self.rng.choice(FEMALE_NAMES if female else MALE_NAMES)
            last = self.rng.choice(SURNAMES)[1 if female else 0]
            if (first, last) not in self.used:
                self.used.add((first, last))
                return first, last


def delete_demo_data() -> int:
    """Remove the demo companies and the accounts that belonged only to them. Returns deleted companies."""
    user_ids = set(Membership.objects.filter(company_id__in=DEMO_COMPANY_IDS).values_list("user_id", flat=True))
    deleted = Company.objects.filter(id__in=DEMO_COMPANY_IDS).count()
    # Locations, periods and people with history are RESTRICT-protected one by one, but deleting the whole
    # company removes everything (every company-owned row also cascades from the company).
    Company.objects.filter(id__in=DEMO_COMPANY_IDS).delete()
    User.objects.filter(id__in=user_ids, memberships__isnull=True).delete()
    return deleted


def demo_data_exists() -> bool:
    return Company.objects.filter(id__in=DEMO_COMPANY_IDS).exists()


@transaction.atomic
def create_demo_data(today: date | None = None) -> dict[str, object]:
    today = today or timezone.localdate()
    rng = random.Random(2026)
    period_start, period_end = next_month_bounds(today)
    summary: dict[str, object] = {"period": (period_start, period_end)}
    summary["bakery"] = _create_bakery_company(rng, period_start, period_end)
    summary["cafe"] = _create_cafe_company(rng, period_start, period_end)
    return summary


def _user(phone: str, first: str, last: str) -> User:
    return User.objects.create_user(phone, first_name=first, last_name=last)


def _create_bakery_company(rng: random.Random, start: date, end: date) -> dict[str, object]:
    manager = _user(BAKERY_MANAGER_PHONE, "Teresa", "Gawlik")
    company = Company.objects.create(id=BAKERY_COMPANY_ID, name="Piekarnia Złoty Kłos", created_by=manager)
    group = LocationGroup.objects.create(company=company, name="Piekarnie pod Krakowem")
    owner = Membership.objects.create(company=company, user=manager, role=Role.OWNER)
    Subscription.objects.create(company=company, ends_at=timezone.now() + timedelta(days=60))
    WeightProfile.objects.create(group=group, manager_share=Decimal("0.80"))

    names = NamePicker(rng)
    phones = PhoneBook("600100")
    locations, employees_total, requests_total = [], 0, 0
    for index, spec in enumerate(BAKERIES):
        location = Location.objects.create(company=company, group=group, name=spec.name, address=spec.address)
        owner.locations.add(location)
        positions = _bakery_settings(location, spec, start, end)
        employees = _bakery_employees(rng, names, phones, company, location, spec, positions)
        period = SchedulePeriod.objects.create(location=location, start=start, end=end)
        _availability(rng, employees, period, students=2)
        requests_total += _text_requests(rng, employees, period, count=[7, 6, 5, 6][index])
        employees_total += len(employees)
        locations.append(location)

    _bakery_rules(group, locations)

    Invitation.objects.create(location=locations[0], phone_e164=phones.next(), invited_by=manager)
    Invitation.objects.create(location=locations[2], phone_e164=phones.next(), invited_by=manager)
    Invitation.objects.create(
        location=locations[1],
        phone_e164=phones.next(),
        invited_by=manager,
        status=InvitationStatus.DECLINED,
        decided_at=timezone.now(),
    )
    return {
        "company": company,
        "manager_phone": BAKERY_MANAGER_PHONE,
        "locations": len(locations),
        "employees": employees_total,
        "requests": requests_total,
    }


def _bakery_settings(location: Location, spec: BakerySpec, start: date, end: date):
    positions = {
        name: Position.objects.create(location=location, name=name)
        for name in ["Sprzedawca", "Piekarz", "Kierownik zmiany", *(["Kierowca"] if spec.drivers else [])]
    }
    night = ShiftType.objects.create(location=location, name="Nocna", start_time=TIME(22), end_time=TIME(6))
    morning = ShiftType.objects.create(location=location, name="Ranna", start_time=TIME(6), end_time=TIME(14))
    afternoon = ShiftType.objects.create(
        location=location, name="Popołudniowa", start_time=TIME(13), end_time=TIME(21), is_closing=True
    )

    bigger = 1 if spec.employees >= 20 else 0
    rules = []
    for weekday in range(7):
        sunday, saturday = weekday == 6, weekday == 5
        sellers_morning = (2 if sunday else 3 if saturday else 2) + bigger
        sellers_afternoon = (1 if sunday else 2) + (bigger if not sunday else 0)
        bakers_night = 3 if weekday == 4 else 1 if weekday == 5 else 2  # Friday night bakes for Saturday
        rules += [
            (weekday, morning, positions["Sprzedawca"], sellers_morning),
            (weekday, afternoon, positions["Sprzedawca"], sellers_afternoon),
            (weekday, night, positions["Piekarz"], bakers_night),
            (weekday, morning, positions["Kierownik zmiany"], 1),
        ]
        if not sunday:
            rules.append((weekday, afternoon, positions["Kierownik zmiany"], 1))
    StaffingRule.objects.bulk_create(
        StaffingRule(
            company_id=location.company_id,
            location=location,
            weekday=weekday,
            shift_type=shift,
            position=position,
            count=count,
        )
        for weekday, shift, position, count in rules
    )
    if spec.drivers:
        deliveries = ShiftType.objects.create(location=location, name="Dostawy", kind=ShiftType.Kind.FLEXIBLE)
        StaffingRule.objects.bulk_create(
            StaffingRule(
                company_id=location.company_id,
                location=location,
                weekday=weekday,
                shift_type=deliveries,
                position=positions["Kierowca"],
                count=1,
                start_time=TIME(4),
                end_time=TIME(9, 30),
            )
            for weekday in range(6)
        )

    # Closed on public holidays (count 0 for every slot), more sellers the day before.
    exceptions = []
    for day in days_between(start, end):
        holiday = FIXED_HOLIDAYS.get((day.month, day.day))
        if holiday:
            exceptions += [
                StaffingException(
                    company_id=location.company_id,
                    location=location,
                    date=day,
                    shift_type=shift,
                    position=position,
                    count=0,
                    note=f"{holiday} – lokal zamknięty",
                )
                for weekday, shift, position, _ in rules
                if weekday == day.weekday()
            ]
            eve = day - timedelta(days=1)
            if eve >= start and (eve.month, eve.day) not in FIXED_HOLIDAYS:
                exceptions.append(
                    StaffingException(
                        company_id=location.company_id,
                        location=location,
                        date=eve,
                        shift_type=morning,
                        position=positions["Sprzedawca"],
                        count=4 + bigger,
                        note=f"Dzień przed świętem ({holiday})",
                    )
                )
    StaffingException.objects.bulk_create(exceptions)
    return positions


def _bakery_employees(rng, names, phones, company, location, spec: BakerySpec, positions) -> list[EmployeeProfile]:
    employees = []
    for i in range(spec.employees):
        first, last = names.next()
        user = _user(phones.next(), first, last)
        membership = Membership.objects.create(company=company, user=user, role=Role.EMPLOYEE)
        if i < spec.shift_leads:
            roles = ["Kierownik zmiany", "Sprzedawca"]
        elif i < spec.shift_leads + spec.bakers:
            roles = ["Piekarz"]
        elif i < spec.shift_leads + spec.bakers + spec.drivers:
            roles = ["Kierowca"]
        else:
            roles = ["Sprzedawca"]
        # One shift lead and one baker per location on an employment contract, everyone else on a civil one.
        employment = i == 0 or i == spec.shift_leads
        if employment:
            contract, max_hours, target = Contract.EMPLOYMENT, 184, 168
        else:
            contract = Contract.CIVIL
            max_hours = rng.choice([None, 120, 140, 160, 180])
            target = rng.choice([None, 60, 80, 100, 120])
            if max_hours is not None and target is not None and target > max_hours:
                target = max_hours
        profile = EmployeeProfile.objects.create(
            membership=membership,
            home_location=location,
            contract=contract,
            max_hours_month=max_hours,
            target_hours_month=target,
        )
        profile.positions.set([positions[name] for name in roles])
        employees.append(profile)
    return employees


AVAILABILITY_WEIGHTS = [
    (AvailabilityState.NEUTRAL, 45),
    (AvailabilityState.PREFER, 20),
    (AvailabilityState.PREFER_NOT, 15),
    (AvailabilityState.CANNOT, 20),
]


def _availability(rng: random.Random, employees, period: SchedulePeriod, students: int) -> None:
    """~85% of people submit; a few students use "repeat every week"; the rest are on the "missing" list."""
    states, weights = zip(*AVAILABILITY_WEIGHTS, strict=True)
    days, submissions, patterns = [], [], []
    student_ids = {e.id for e in rng.sample(employees, students)}
    for employee in employees:
        if rng.random() > 0.85:
            continue
        busy_weekdays = set(rng.sample(range(5), 2)) if employee.id in student_ids else set()
        for weekday in sorted(busy_weekdays):
            patterns.append(
                AvailabilityPattern(
                    company_id=employee.company_id,
                    employee=employee,
                    weekday=weekday,
                    state=AvailabilityState.CANNOT,
                    repeat_until=period.end + timedelta(days=60),
                )
            )
        for day in days_between(period.start, period.end):
            from_time = to_time = None
            if day.weekday() in busy_weekdays:
                state, source = AvailabilityState.CANNOT, AvailabilityDay.Source.PATTERN
            else:
                state, source = rng.choices(states, weights)[0], AvailabilityDay.Source.MANUAL
                if state == AvailabilityState.PREFER and rng.random() < 0.15:
                    from_time = TIME(14)  # "chętnie od 14:00"
                elif state == AvailabilityState.NEUTRAL and rng.random() < 0.05:
                    to_time = TIME(15)
            days.append(
                AvailabilityDay(
                    company_id=employee.company_id,
                    employee=employee,
                    date=day,
                    state=state,
                    from_time=from_time,
                    to_time=to_time,
                    source=source,
                )
            )
        submissions.append(AvailabilitySubmission(company_id=employee.company_id, employee=employee, period=period))
    AvailabilityPattern.objects.bulk_create(patterns)
    AvailabilityDay.objects.bulk_create(days)
    AvailabilitySubmission.objects.bulk_create(submissions)


def _text_requests(rng: random.Random, employees, period: SchedulePeriod, count: int) -> int:
    authors = rng.sample(employees, count)
    templates = rng.sample(REQUEST_TEMPLATES, count)
    requests = []
    for author, (template, kind, level) in zip(authors, templates, strict=True):
        other = rng.choice([e for e in employees if e.id != author.id])
        other_name = other.membership.user.full_name
        weekend = period.start + timedelta(days=(5 - period.start.weekday()) % 7 + 7 * rng.randint(0, 2))
        text = template.format(other=other_name, day=f"{weekend:%d.%m}")
        roll = rng.random()
        status, priority, rejected = TextRequest.Status.INTERPRETED, TextRequest.ManagerPriority.NORMAL, False
        if roll < 0.2:
            status = TextRequest.Status.NEW
        elif roll < 0.35:
            status = TextRequest.Status.NEEDS_MANAGER
        elif roll < 0.42:
            status, rejected = TextRequest.Status.REJECTED, True
        elif roll < 0.55:
            priority = TextRequest.ManagerPriority.HIGHER
        elif roll < 0.62:
            priority = TextRequest.ManagerPriority.LOWER
        # New requests are not interpreted yet; unclear ones (no API key or low confidence) go to the manager
        # as plain text, without an interpretation (spec, "LLM" section).
        interpretation = None
        if status not in (TextRequest.Status.NEW, TextRequest.Status.NEEDS_MANAGER):
            interpretation = {
                "type": kind,
                "subject_employee": str(other.id) if "{other}" in template else None,
                "dates": [f"{weekend:%Y-%m-%d}", f"{weekend + timedelta(days=1):%Y-%m-%d}"]
                if "{day}" in template
                else [],
                "level": level,
                "confidence": round(rng.uniform(0.75, 0.97), 2),
                "summary": text.split(",")[0].rstrip(".") + ".",
            }
        requests.append(
            TextRequest(
                company_id=author.company_id,
                employee=author,
                period=period,
                text=text,
                status=status,
                interpretation=interpretation,
                manager_priority=priority,
                manager_rejected=rejected,
            )
        )
    TextRequest.objects.bulk_create(requests)
    return len(requests)


def _bakery_rules(group: LocationGroup, locations: list[Location]) -> None:
    """Group rules in order of importance, plus location overrides. Some of them pull against each other:

    - "the same time of day all week" vs "fair split of closing shifts" and "rest between shifts";
    - in Wieliczka "at most 4 days in a row, no exceptions" vs "target hours" for full-time staff;
    - in Wieliczka bakers only on nights (no exceptions) vs "fair split of weekends".
    """
    group_rules = [
        ("min_rest_between_shifts", {"hours": 11}, False),
        ("target_hours", {}, False),
        ("fair_weekends", {}, False),
        ("max_consecutive_days", {"days": 5}, False),
        ("fair_closings", {}, False),
        ("same_shift_type_in_week", {}, False),
        ("personal_max_hours", {}, False),
    ]
    RuleSetting.objects.bulk_create(
        RuleSetting(company_id=group.company_id, group=group, rule_code=code, params=params, is_hard=hard, position=i)
        for i, (code, params, hard) in enumerate(group_rules, start=1)
    )
    wieliczka, _, skawina, zielonki = locations
    baker = Position.objects.get(location=wieliczka, name="Piekarz")
    night = ShiftType.objects.get(location=wieliczka, name="Nocna")
    lead = Position.objects.get(location=zielonki, name="Kierownik zmiany")
    RuleSetting.objects.bulk_create(
        [
            RuleSetting(
                company_id=group.company_id,
                location=wieliczka,
                rule_code="preferred_shift_type_for_position",
                params={"position": str(baker.id), "shift_type": str(night.id)},
                is_hard=True,
                position=1,
            ),
            RuleSetting(
                company_id=group.company_id,
                location=wieliczka,
                rule_code="max_consecutive_days",
                params={"days": 4},
                is_hard=True,
                position=2,
            ),
            RuleSetting(
                company_id=group.company_id,
                location=skawina,
                rule_code="fair_weekends",
                enabled=False,
                position=3,
            ),
            RuleSetting(
                company_id=group.company_id,
                location=zielonki,
                rule_code="min_position_on_closing",
                params={"position": str(lead.id), "count": 1},
                position=1,
            ),
        ]
    )


def _create_cafe_company(rng: random.Random, start: date, end: date) -> dict[str, object]:
    """A separate small company, used to check that companies never see each other's data."""
    manager = _user(CAFE_MANAGER_PHONE, "Rafał", "Kubacki")
    company = Company.objects.create(id=CAFE_COMPANY_ID, name="Kawiarnia Pod Lipami", created_by=manager)
    owner = Membership.objects.create(company=company, user=manager, role=Role.OWNER)
    Subscription.objects.create(company=company, ends_at=timezone.now() + timedelta(days=30))
    location = Location.objects.create(
        company=company,
        name="Kraków – Kazimierz",
        address="ul. Józefa 8, 31-056 Kraków",
        schedule_period="week",
        availability_deadline_days=3,
    )
    owner.locations.add(location)
    WeightProfile.objects.create(location=location, manager_share=Decimal("0.90"))
    barista = Position.objects.create(location=location, name="Barista")
    waiter = Position.objects.create(location=location, name="Kelner")
    opening = ShiftType.objects.create(location=location, name="Otwarcie", start_time=TIME(7), end_time=TIME(15))
    closing = ShiftType.objects.create(
        location=location, name="Zamknięcie", start_time=TIME(14), end_time=TIME(22), is_closing=True
    )
    StaffingRule.objects.bulk_create(
        StaffingRule(company=company, location=location, weekday=d, shift_type=s, position=p, count=c)
        for d in range(7)
        for s, p, c in [(opening, barista, 1), (closing, barista, 1), (opening, waiter, 1), (closing, waiter, 2)]
    )
    names = NamePicker(rng)
    phones = PhoneBook("700200")
    employees = []
    for i in range(7):
        first, last = names.next()
        membership = Membership.objects.create(company=company, user=_user(phones.next(), first, last))
        profile = EmployeeProfile.objects.create(membership=membership, home_location=location)
        profile.positions.set([barista] if i < 3 else [waiter])
        employees.append(profile)
    monday = start + timedelta(days=(7 - start.weekday()) % 7)  # weekly schedule: first full week of next month
    period = SchedulePeriod.objects.create(location=location, start=monday, end=monday + timedelta(days=6))
    _availability(rng, employees, period, students=1)
    _text_requests(rng, employees, period, count=2)
    RuleSetting.objects.create(location=location, rule_code="fair_closings", position=1)
    return {"company": company, "manager_phone": CAFE_MANAGER_PHONE, "employees": len(employees)}
