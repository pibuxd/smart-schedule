"""Test data for a thorough manual test of the deployed app (e.g. by an external tester).

Three separate test companies with fixed ids and their own phone numbers, so they never touch real or demo data:

- A "Smaczek (firma testowa)": two bakeries in a group (one with "przejęcie bez zatwierdzania") and a café with weekly
  periods. A published schedule for the current month (current week in the café), the next period collecting
  availability (bakery 1: before the deadline, bakery 2: after it, with days changed late), a café draft with
  a pinned shift, given-away shifts in every state, text requests in every state, manager instructions, invitations.
- B "Hotel Pod Wawelem (firma testowa)": access ends in a few days (banner); used to check company isolation.
- C "Bistro Zamknięte (firma testowa)": access has ended (read-only mode).

Dates are relative to the day the command runs. Phone numbers: A +48 510 …, B +48 520 …, C +48 530 …;
+48 510 999 001–005 have no account (for registering a new company). See `seed_test_data` for the account list.
"""

from __future__ import annotations

import calendar
import random
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from apps.accounts.models import LoginCode, User
from apps.assistant.models import ManagerInstruction
from apps.availability.models import (
    AvailabilityDay,
    AvailabilityPattern,
    AvailabilityState,
    AvailabilitySubmission,
    TextRequest,
)
from apps.billing.codes import format_code, generate_code, hash_code
from apps.billing.models import AccessCode, Subscription
from apps.core.demo_data import BakerySpec, _bakery_settings, days_between
from apps.marketplace.models import ShiftOffer
from apps.marketplace.services import approve_claim, claim_offer, offer_shift, reject_claim
from apps.notifications.models import Notification
from apps.rules.models import RuleSetting, WeightProfile
from apps.scheduling.editing import publish, set_pinned
from apps.scheduling.generation import run_generation
from apps.scheduling.models import Assignment, GenerationRun, SchedulePeriod, ScheduleVersion
from apps.staffing.models import (
    EmployeeProfile,
    Experience,
    LocationClosure,
    Position,
    PositionExperience,
    ShiftType,
    StaffingRule,
)
from apps.tenancy.models import Company, Invitation, InvitationStatus, Location, LocationGroup, Membership, Role

COMPANY_A = uuid.UUID("7e570000-0000-4000-8000-00000000000a")
COMPANY_B = uuid.UUID("7e570000-0000-4000-8000-00000000000b")
COMPANY_C = uuid.UUID("7e570000-0000-4000-8000-00000000000c")
TEST_COMPANY_IDS = (COMPANY_A, COMPANY_B, COMPANY_C)

OWNER_A = "+48510000001"
CAFE_MANAGER_A = "+48510000002"
WORKING_MANAGER_A = "+48510000003"
MANAGER_B = "+48520000001"
MANAGER_C = "+48530000001"
# No account and no invitation: for "Załóż firmę" (registering a new manager). Removed again by --reset.
REGISTER_PHONES = [f"+48510999{i:03d}" for i in range(1, 6)]
INVITED_ONLY_PHONES = [f"+48510009{i:03d}" for i in range(1, 6)]
# Companies registered by the tester from REGISTER_PHONES are removed by --reset too.

E, S, B = Experience.EXPERIENCED, Experience.SKILLED, Experience.BEGINNER
SOLVER_SECONDS = 20


@dataclass
class Person:
    """One employee. `key` names the person in this module; `note` goes to the account list."""

    key: str
    first: str
    last: str
    positions: list[str]
    experience: int = S
    max_hours: int | None = None
    target_hours: int | None = None
    note: str = ""
    submitted: bool = True  # availability for the next period sent ("Gotowe")
    levels: dict[str, int] = field(default_factory=dict)  # experience on one position
    active: bool = True


RYNEK = [
    Person(
        "anna",
        "Anna",
        "Nowak",
        ["Kierownik zmiany", "Sprzedawca"],
        E,
        184,
        168,
        "oddaje zmianę, jedna osoba się zgłosiła (czeka na kierownika)",
    ),
    Person(
        "bartosz",
        "Bartosz",
        "Wiśniewski",
        ["Kierownik zmiany", "Sprzedawca"],
        E,
        160,
        140,
        "oddał zmianę, kierownik zatwierdził osobę, która ją wzięła (historia zmiany)",
    ),
    Person(
        "celina",
        "Celina",
        "Zając",
        ["Kierownik zmiany", "Sprzedawca"],
        S,
        160,
        None,
        "samodzielna, ale przy sprzedaży ma osobny stopień: początkująca",
        levels={"Sprzedawca": B},
    ),
    Person(
        "dariusz",
        "Dariusz",
        "Kowalczyk",
        ["Piekarz"],
        E,
        184,
        168,
        "dyspozycje z dwoma przedziałami dnia (lub / albo) i nocką",
    ),
    Person(
        "ewa",
        "Ewa",
        "Lewandowska",
        ["Sprzedawca"],
        S,
        140,
        100,
        "chce wziąć zmianę Anny (czeka na kierownika), jeśli wypis komendy nie mówi inaczej",
    ),
    Person(
        "filip",
        "Filip",
        "Mazur",
        ["Sprzedawca"],
        B,
        100,
        80,
        "student: co tydzień 'nie mogę' we wtorki i czwartki; kilka próśb tekstem, też na miesiąc bez okresu",
    ),
    Person(
        "grazyna",
        "Grażyna",
        "Brzęczyszczykiewicz-Szczebrzeszyńska",
        ["Sprzedawca"],
        S,
        120,
        None,
        "bardzo długie nazwisko (test układu ekranu); 'nie mogę' tylko w części dnia",
    ),
    Person(
        "henryk", "Henryk", "Wójcik", ["Kierowca", "Sprzedawca"], E, 168, 140, "dwa stanowiska: kierowca i sprzedawca"
    ),
    Person(
        "anna2",
        "Anna",
        "Kamińska",
        ["Sprzedawca"],
        S,
        120,
        100,
        "druga Anna w lokalu (prośby z samym imieniem są niejednoznaczne)",
    ),
    Person(
        "igor",
        "Igor",
        "Dąbrowski",
        ["Piekarz"],
        S,
        160,
        None,
        "NIE wysłał dyspozycji na następny okres (lista brakujących)",
        submitted=False,
    ),
    Person(
        "jolanta",
        "Jolanta",
        "Krawczyk",
        ["Sprzedawca"],
        S,
        note="dezaktywowana (nie pracuje już w lokalu)",
        active=False,
        submitted=False,
    ),
    Person("kamil", "Kamil", "Pawlak", ["Sprzedawca"], S, 140, 120, "oddał zmianę, nikt jej jeszcze nie wziął"),
    Person("lena", "Lena", "Sowa", ["Piekarz"], B, 120, None, "zgłosiła się do zmiany Marka, kierownik odmówił"),
    Person("marek", "Marek", "Olszewski", ["Piekarz"], S, 168, 150),
    Person("nina", "Nina", "Rybak", ["Sprzedawca"], S, 120, 100, submitted=False),
    Person("oskar", "Oskar", "Kubiak", ["Sprzedawca"], E, 168, 150),
    Person("patrycja", "Patrycja", "Wilk", ["Sprzedawca"], S, 140, None),
    Person("radek", "Radosław", "Lis", ["Kierowca"], S, 120, None),
]

DWORCOWA = [
    Person("leszek", "Leszek", "Maj", ["Kierownik zmiany", "Sprzedawca"], E, 184, 168),
    Person(
        "marta",
        "Marta",
        "Sikora",
        ["Sprzedawca"],
        S,
        140,
        120,
        "oddała zmianę; w tym lokalu 'Weź zmianę' działa od razu (bez zatwierdzania)",
    ),
    Person("natalia", "Natalia", "Baran", ["Sprzedawca"], S, 140, 120, "zmieniła dyspozycje po terminie"),
    Person("olek", "Aleksander", "Górski", ["Kierownik zmiany", "Sprzedawca"], E, 168, 150),
    Person("paulina", "Paulina", "Witkowska", ["Kierownik zmiany", "Sprzedawca"], S, 160, None),
    Person("roman", "Roman", "Kaczmarek", ["Piekarz"], E, 184, 168),
    Person("sylwia", "Sylwia", "Pietrzak", ["Piekarz"], S, 160, 140),
    Person("tadeusz", "Tadeusz", "Urban", ["Piekarz"], B, 140, None),
    Person("urszula", "Urszula", "Wrona", ["Piekarz"], S, 160, None),
    Person("wiktor", "Wiktor", "Zalewski", ["Sprzedawca"], E, 160, 140),
    Person("zuzanna", "Zuzanna", "Kot", ["Sprzedawca"], B, 100, 80),
    Person("adam", "Adam", "Bielecki", ["Sprzedawca"], S, 140, None, submitted=False),
    Person("beata", "Beata", "Czajka", ["Sprzedawca"], S, 120, 100),
    Person("cezary", "Cezary", "Domański", ["Sprzedawca"], S, 160, 120),
]

KAWIARNIA = [
    Person("jan", "Jan", "Kos", ["Barista"], E),
    Person("klara", "Klara", "Sobczak", ["Barista"], S),
    Person("ludwik", "Ludwik", "Szulc", ["Barista", "Kelner"], S, note="barista i kelner"),
    Person("magda", "Magdalena", "Pawłowska", ["Kelner"], E),
    Person("oliwia", "Oliwia", "Zawadzka", ["Kelner"], B, note="nowa osoba, początkująca"),
    Person("piotrek", "Piotr", "Wróbel", ["Kelner"], B),
    Person("roza", "Róża", "Adamczyk", ["Kelner"], S, submitted=False),
]

HOTEL = [
    Person("h1", "Kinga", "Lewicka", ["Recepcja"], E, note="ma też zaproszenie do kawiarni firmy A"),
    Person("h2", "Szymon", "Nowicki", ["Recepcja"], S),
    Person("h3", "Teresa", "Bąk", ["Recepcja"], S),
    Person("h4", "Wojciech", "Sadowski", ["Portier"], S),
    Person("h5", "Jadwiga", "Michalak", ["Portier"], B, submitted=False),
]

BISTRO = [
    Person("c1", "Mateusz", "Ostrowski", ["Kucharz"], E),
    Person("c2", "Joanna", "Zielińska", ["Kelner"], S),
    Person("c3", "Kacper", "Duda", ["Kelner"], S),
    Person("c4", "Weronika", "Głowacka", ["Kucharz"], S),
]


def _month_bounds(day: date) -> tuple[date, date]:
    first = day.replace(day=1)
    return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])


def _next_month(day: date) -> date:
    return (day.replace(day=1) + timedelta(days=32)).replace(day=1)


@dataclass
class Periods:
    """Monthly: the published one contains today (stretched over next month when fewer than 10 days are left),
    then the next one. Weekly: this week, the next (draft), the one after (collecting)."""

    published: tuple[date, date]
    next: tuple[date, date]
    later_month: date  # a month without a period yet (requests "na dowolny miesiąc")
    week0: tuple[date, date]
    week1: tuple[date, date]
    week2: tuple[date, date]

    @classmethod
    def around(cls, today: date) -> Periods:
        start, end = _month_bounds(today)
        if (end - today).days < 10:
            end = _month_bounds(_next_month(today))[1]
        nxt = _month_bounds(end + timedelta(days=1))
        monday = today - timedelta(days=today.weekday())
        weeks = [(monday + timedelta(days=7 * i), monday + timedelta(days=7 * i + 6)) for i in range(3)]
        return cls((start, end), nxt, _next_month(nxt[0]), *weeks)


# ----------------------------------------------------------------------------------------------------- phones


def _phones(prefix: str, people: list[Person]) -> dict[str, str]:
    return {p.key: f"+48{prefix}{i:03d}" for i, p in enumerate(people, start=1)}


PHONES = {
    "rynek": _phones("510001", RYNEK),
    "dworcowa": _phones("510002", DWORCOWA),
    "kawiarnia": _phones("510003", KAWIARNIA),
    "hotel": _phones("520001", HOTEL),
    "bistro": _phones("530001", BISTRO),
}


def all_account_phones() -> list[str]:
    phones = [OWNER_A, CAFE_MANAGER_A, WORKING_MANAGER_A, MANAGER_B, MANAGER_C]
    for group in PHONES.values():
        phones += group.values()
    return phones


# ------------------------------------------------------------------------------------------- exists / delete


def test_data_exists() -> bool:
    return Company.objects.filter(id__in=TEST_COMPANY_IDS).exists()


def foreign_phone_conflicts() -> list[str]:
    """Numbers this data needs that already belong to someone outside the test companies."""
    ours = Membership.objects.filter(company_id__in=TEST_COMPANY_IDS).values("user_id")
    return sorted(
        User.objects.filter(phone_e164__in=all_account_phones())
        .exclude(id__in=ours)
        .values_list("phone_e164", flat=True)
    )


def delete_test_data() -> int:
    """Remove the test companies, companies registered from REGISTER_PHONES, their own accounts and login codes."""
    registered = Company.objects.filter(created_by__phone_e164__in=REGISTER_PHONES).values_list("id", flat=True)
    company_ids = [*TEST_COMPANY_IDS, *registered]
    user_ids = set(Membership.objects.filter(company_id__in=company_ids).values_list("user_id", flat=True))
    user_ids |= set(User.objects.filter(phone_e164__in=REGISTER_PHONES).values_list("id", flat=True))
    phones = set(User.objects.filter(id__in=user_ids).values_list("phone_e164", flat=True))
    deleted = Company.objects.filter(id__in=company_ids).count()
    Company.objects.filter(id__in=company_ids).delete()
    User.objects.filter(id__in=user_ids, memberships__isnull=True).delete()
    AccessCode.objects.filter(note__startswith="Dane testowe", redemptions__isnull=True).delete()
    LoginCode.objects.filter(phone_e164__in=phones | set(REGISTER_PHONES) | set(INVITED_ONLY_PHONES)).delete()
    return deleted


# ----------------------------------------------------------------------------------------------- building


def _user(phone: str, first: str, last: str) -> User:
    return User.objects.create_user(phone, first_name=first, last_name=last)


def _staff(company, location, people: list[Person], phones: dict[str, str]) -> dict[str, EmployeeProfile]:
    positions = {p.name: p for p in Position.objects.filter(location=location)}
    profiles = {}
    for person in people:
        user = _user(phones[person.key], person.first, person.last)
        membership = Membership.objects.create(company=company, user=user, role=Role.EMPLOYEE)
        profile = EmployeeProfile.objects.create(
            membership=membership,
            home_location=location,
            experience=person.experience,
            max_hours_month=person.max_hours,
            target_hours_month=person.target_hours,
            is_active=person.active,
        )
        profile.positions.set([positions[name] for name in person.positions])
        for name, level in person.levels.items():
            PositionExperience.objects.create(employee=profile, position=positions[name], level=level)
        profiles[person.key] = profile
    return profiles


def _random_days(rng, profile, start: date, end: date, *, cannot=0.15, prefer=0.15) -> list[AvailabilityDay]:
    days = []
    for day in days_between(start, end):
        roll = rng.random()
        if roll < cannot:
            state = AvailabilityState.CANNOT
        elif roll < cannot + prefer:
            state = AvailabilityState.PREFER
        else:
            continue  # no row = "mogę"
        days.append(AvailabilityDay(company_id=profile.company_id, employee=profile, date=day, state=state))
    return days


def _availability(
    rng,
    profiles: dict[str, EmployeeProfile],
    people: list[Person],
    period: SchedulePeriod,
    *,
    submitted_only: bool,
    submitted_at=None,
) -> None:
    rows, submissions = [], []
    for person in people:
        profile = profiles[person.key]
        if not person.active or (submitted_only and not person.submitted):
            continue
        rows += _random_days(rng, profile, period.start, period.end)
        if submitted_only:
            submissions.append(
                AvailabilitySubmission(
                    company_id=profile.company_id,
                    employee=profile,
                    period=period,
                    submitted_at=submitted_at or timezone.now(),
                )
            )
    AvailabilityDay.objects.bulk_create(rows, ignore_conflicts=True)
    AvailabilitySubmission.objects.bulk_create(submissions)


def _set_day(profile, day: date, state, **hours) -> None:
    AvailabilityDay.objects.update_or_create(
        employee=profile,
        date=day,
        defaults={"company_id": profile.company_id, "state": state, **hours},
    )


def _first_weekday(start: date, weekday: int) -> date:
    return start + timedelta(days=(weekday - start.weekday()) % 7)


def _weekly_pattern(profile, weekdays: list[int], start: date, until: date) -> None:
    for weekday in weekdays:
        AvailabilityPattern.objects.create(
            company_id=profile.company_id,
            employee=profile,
            weekday=weekday,
            state=AvailabilityState.CANNOT,
            repeat_until=until,
        )
    for day in days_between(start, until):
        if day.weekday() in weekdays:
            AvailabilityDay.objects.update_or_create(
                employee=profile,
                date=day,
                defaults={
                    "company_id": profile.company_id,
                    "state": AvailabilityState.CANNOT,
                    "source": AvailabilityDay.Source.PATTERN,
                },
            )


def _rules(group: LocationGroup | None, location: Location | None, codes: list[tuple[str, dict, bool]]) -> None:
    owner = {"group": group} if group else {"location": location}
    company_id = (group or location).company_id
    RuleSetting.objects.bulk_create(
        RuleSetting(company_id=company_id, rule_code=code, params=params, is_hard=hard, position=i, **owner)
        for i, (code, params, hard) in enumerate(codes, start=1)
    )


def _simple_location(company, name, address, *, positions, shifts, staffing, period_kind="month", deadline_days=7):
    location = Location.objects.create(
        company=company,
        name=name,
        address=address,
        schedule_period=period_kind,
        availability_deadline_days=deadline_days,
    )
    pos = {n: Position.objects.create(location=location, name=n) for n in positions}
    types = {}
    for shift_name, start, end, closing in shifts:
        types[shift_name] = ShiftType.objects.create(
            location=location, name=shift_name, start_time=time(start), end_time=time(end), is_closing=closing
        )
    StaffingRule.objects.bulk_create(
        StaffingRule(
            company=company, location=location, weekday=d, shift_type=types[s], position=pos[p], count=c, experienced=x
        )
        for d in range(7)
        for s, p, c, x in staffing(d)
    )
    return location, pos, types


def _interpretation(kind: str, summary: str, *, level="wazne", confidence=0.9, **data) -> dict:
    return {
        "type": kind,
        "dates": [],
        "weekdays": [],
        **data,
        "level": level,
        "confidence": confidence,
        "summary": summary,
    }


# --------------------------------------------------------------------------------------------- company A


@dataclass
class Built:
    """What later steps (generation, given-away shifts) need, and what the command prints."""

    periods: Periods
    to_publish: list[SchedulePeriod] = field(default_factory=list)
    to_draft: list[SchedulePeriod] = field(default_factory=list)
    owner_a: User | None = None
    cafe_manager: User | None = None
    manager_c: User | None = None
    profiles: dict[str, EmployeeProfile] = field(default_factory=dict)
    ids: dict[str, str] = field(default_factory=dict)
    codes: dict[str, str] = field(default_factory=dict)


@transaction.atomic
def create_base(today: date | None = None) -> Built:
    today = today or timezone.localdate()
    rng = random.Random(1711)  # noqa: S311 - fixed test data, not security
    built = Built(Periods.around(today))
    _company_a(rng, built)
    _company_b(rng, built)
    _company_c(rng, built)
    _access_codes(built)
    return built


def _company_a(rng, built: Built) -> None:
    p = built.periods
    owner = _user(OWNER_A, "Magdalena", "Testowa")
    cafe_manager = _user(CAFE_MANAGER_A, "Paweł", "Rogalski")
    working_manager = _user(WORKING_MANAGER_A, "Olga", "Duda")
    built.owner_a, built.cafe_manager = owner, cafe_manager
    company = Company.objects.create(id=COMPANY_A, name="Smaczek (firma testowa)", created_by=owner)
    Subscription.objects.create(company=company, ends_at=timezone.now() + timedelta(days=60))
    owner_m = Membership.objects.create(company=company, user=owner, role=Role.OWNER)
    cafe_m = Membership.objects.create(company=company, user=cafe_manager, role=Role.MANAGER)
    working_m = Membership.objects.create(company=company, user=working_manager, role=Role.MANAGER)

    group = LocationGroup.objects.create(company=company, name="Piekarnie Smaczek")
    WeightProfile.objects.create(group=group, manager_share=Decimal("0.80"))
    span_start, span_end = p.published[0], p.next[1]

    rynek = Location.objects.create(
        company=company, group=group, name="Piekarnia Rynek", address="Rynek 1, 32-020 Wieliczka"
    )
    dworcowa = Location.objects.create(
        company=company,
        group=group,
        name="Piekarnia Dworcowa",
        address="ul. Dworcowa 7, 32-005 Niepołomice",
        handover_without_approval=True,
    )
    Location.objects.create(
        company=company,
        group=group,
        name="Piekarnia Targowa (zamknięta)",
        address="ul. Targowa 3, 32-050 Skawina",
        archived_at=timezone.now() - timedelta(days=20),
    )
    _bakery_settings(rynek, BakerySpec("", "", employees=18, bakers=4, shift_leads=3, drivers=2), span_start, span_end)
    _bakery_settings(dworcowa, BakerySpec("", "", employees=14, bakers=4, shift_leads=3), span_start, span_end)
    # More experienced sellers on Saturday mornings in Dworcowa than the location has: a warning before arranging.
    sat = ShiftType.objects.get(location=dworcowa, name="Ranna")
    StaffingRule.objects.filter(location=dworcowa, weekday=5, shift_type=sat, position__name="Sprzedawca").update(
        count=4, experienced=4
    )
    # Friday nights in Rynek: 3 bakers, one of them experienced.
    StaffingRule.objects.filter(location=rynek, weekday=4, shift_type__name="Nocna", position__name="Piekarz").update(
        experienced=1
    )
    closure = p.next[0] + timedelta(days=9)
    LocationClosure.objects.create(location=rynek, date=closure, note="Inwentaryzacja")

    cafe, cafe_pos, _ = _simple_location(
        company,
        "Kawiarnia Smaczek – Stare Miasto",
        "ul. Floriańska 20, 31-021 Kraków",
        positions=["Barista", "Kelner"],
        shifts=[("Otwarcie", 7, 15, False), ("Zamknięcie", 14, 22, True)],
        staffing=lambda d: [
            ("Otwarcie", "Barista", 1, 0),
            ("Zamknięcie", "Barista", 1, 0),
            ("Otwarcie", "Kelner", 1, 0),
            ("Zamknięcie", "Kelner", 2 if d >= 4 else 1, 1 if d >= 4 else 0),
        ],
        period_kind="week",
        deadline_days=3,
    )
    WeightProfile.objects.create(location=cafe, manager_share=Decimal("0.90"))

    owner_m.locations.add(rynek, dworcowa, cafe)
    cafe_m.locations.add(cafe)
    working_m.locations.add(dworcowa)

    profiles = {}
    profiles |= _staff(company, rynek, RYNEK, PHONES["rynek"])
    profiles |= _staff(company, dworcowa, DWORCOWA, PHONES["dworcowa"])
    profiles |= _staff(company, cafe, KAWIARNIA, PHONES["kawiarnia"])
    # The manager who also works shifts ("Dodaj mnie do grafiku").
    olga = EmployeeProfile.objects.create(membership=working_m, home_location=dworcowa, experience=E)
    olga.positions.set(Position.objects.filter(location=dworcowa, name__in=["Kierownik zmiany", "Sprzedawca"]))
    profiles["olga"] = olga
    built.profiles = profiles

    _rules(
        group,
        None,
        [
            ("min_rest_between_shifts", {"hours": 11}, False),
            ("personal_max_hours", {"tolerance_pct": 10}, True),
            ("target_hours", {}, False),
            ("fair_weekends", {}, False),
            ("max_consecutive_days", {"days": 5}, False),
            ("experience_mix", {}, False),
            ("fair_closings", {}, False),
            ("max_hours_per_day", {}, False),
            ("min_weekly_rest", {}, False),
        ],
    )
    lead = Position.objects.get(location=rynek, name="Kierownik zmiany")
    RuleSetting.objects.create(
        company=company,
        location=rynek,
        rule_code="min_position_on_closing",
        params={"position": str(lead.id), "count": 1},
        position=1,
    )
    RuleSetting.objects.create(company=company, location=dworcowa, rule_code="fair_weekends", enabled=False, position=3)
    _rules(
        None, cafe, [("fair_closings", {}, False), ("experience_mix", {"position": str(cafe_pos["Kelner"].id)}, False)]
    )

    # Periods.
    now = timezone.now()
    r0 = SchedulePeriod.objects.create(location=rynek, start=p.published[0], end=p.published[1])
    d0 = SchedulePeriod.objects.create(location=dworcowa, start=p.published[0], end=p.published[1])
    w0 = SchedulePeriod.objects.create(location=cafe, start=p.week0[0], end=p.week0[1])
    w1 = SchedulePeriod.objects.create(location=cafe, start=p.week1[0], end=p.week1[1])
    for period in (r0, d0, w0, w1):
        _availability(rng, profiles, RYNEK + DWORCOWA + KAWIARNIA, period, submitted_only=False)
    built.to_publish += [r0, d0, w0]
    built.to_draft.append(w1)

    # Rynek, next month: collecting, deadline in 5 days, the manager has asked for availability.
    r1 = SchedulePeriod.objects.create(
        location=rynek,
        start=p.next[0],
        end=p.next[1],
        availability_deadline=timezone.localdate() + timedelta(days=5),
        deadline_set_at=now - timedelta(days=3),
        availability_requested_at=now - timedelta(days=3),
    )
    _availability(rng, profiles, RYNEK, r1, submitted_only=True)
    _weekly_pattern(profiles["filip"], [1, 3], p.published[0], p.next[1] + timedelta(days=60))
    dar = profiles["dariusz"]
    mon, wed, fri = (_first_weekday(r1.start, d) for d in (0, 2, 4))
    _set_day(
        dar,
        mon,
        AvailabilityState.NEUTRAL,
        from_time=time(6),
        to_time=time(10),
        from_time_2=time(16),
        to_time_2=time(22),
        one_shift=False,
    )  # "6–10 lub 16–22"
    _set_day(
        dar,
        fri,
        AvailabilityState.PREFER,
        from_time=time(6),
        to_time=time(14),
        from_time_2=time(22),
        to_time_2=time(6),
        one_shift=True,
    )  # "albo rano, albo nocka"
    _set_day(dar, wed, AvailabilityState.PREFER, from_time=time(22), to_time=time(6))  # night only
    _set_day(
        profiles["grazyna"], mon + timedelta(days=7), AvailabilityState.CANNOT, from_time=time(14), to_time=time(22)
    )
    _ask(company, r1, [profiles[x.key] for x in RYNEK if x.active], read_by={"anna", "bartosz"}, profiles=profiles)

    # Dworcowa, next month: deadline yesterday, everything entered before it except Natalia's changes.
    deadline_set = now - timedelta(days=12)
    d1 = SchedulePeriod.objects.create(
        location=dworcowa,
        start=p.next[0],
        end=p.next[1],
        availability_deadline=timezone.localdate() - timedelta(days=1),
        deadline_set_at=deadline_set,
        availability_requested_at=deadline_set,
    )
    _availability(rng, profiles, DWORCOWA, d1, submitted_only=True, submitted_at=deadline_set + timedelta(days=2))
    AvailabilityDay.objects.filter(employee__home_location=dworcowa, date__gte=d1.start).update(
        updated_at=deadline_set + timedelta(days=2)
    )
    for offset, state in [(2, AvailabilityState.CANNOT), (3, AvailabilityState.CANNOT), (10, AvailabilityState.PREFER)]:
        _set_day(profiles["natalia"], d1.start + timedelta(days=offset), state)  # updated now = after the deadline
    _ask(company, d1, [profiles[x.key] for x in DWORCOWA], read_by=set(), profiles=profiles)

    # Café, the week after next: collecting, default deadline (3 days before).
    w2 = SchedulePeriod.objects.create(location=cafe, start=p.week2[0], end=p.week2[1], deadline_set_at=now)
    _availability(rng, profiles, KAWIARNIA, w2, submitted_only=True)

    _requests_a(built, r1, d1, w2)
    _instructions_a(company, rynek, profiles, owner)
    _invitations_a(rynek, dworcowa, cafe, owner)
    built.ids |= {"rynek_next": str(r1.id), "dworcowa_next": str(d1.id), "cafe_week2": str(w2.id)}


def _ask(company, period, people, *, read_by: set[str], profiles) -> None:
    note = {
        "period_id": str(period.pk),
        "location_name": period.location.name,
        "start": period.start.isoformat(),
        "end": period.end.isoformat(),
        "deadline": period.deadline.isoformat(),
    }
    read_ids = {profiles[k].membership.user_id for k in read_by}
    Notification.objects.bulk_create(
        Notification(
            company=company,
            user_id=p.membership.user_id,
            kind="availability_requested",
            payload=note,
            created_at=period.availability_requested_at,
            read_at=timezone.now() if p.membership.user_id in read_ids else None,
        )
        for p in people
    )


def _requests_a(built: Built, r1: SchedulePeriod, d1: SchedulePeriod, w2: SchedulePeriod) -> None:
    pr = built.profiles
    shift = {s.name: s for s in ShiftType.objects.filter(location=r1.location)}
    day12, day13 = r1.start + timedelta(days=11), r1.start + timedelta(days=12)
    st, rs = TextRequest.Status, TextRequest.UnreadReason
    rows = [
        (
            pr["filip"],
            r1,
            None,
            "Nie chcę mieć zmian razem z Ewą, ciągle się kłócimy przy kasie.",
            st.INTERPRETED,
            _interpretation("unikaj_osoby", "Filip nie chce pracować z Ewą.", subject_employee=str(pr["ewa"].id)),
            {},
        ),
        (
            pr["anna"],
            r1,
            None,
            "W tym miesiącu wolę tylko ranne zmiany, po południu mam zajęcia.",
            st.INTERPRETED,
            _interpretation(
                "typ_zmiany",
                "Anna woli tylko ranne zmiany.",
                level="bardzo_wazne",
                shift_type=str(shift["Ranna"].id),
                avoid=False,
            ),
            {"manager_priority": "higher"},
        ),
        (
            pr["grazyna"],
            r1,
            None,
            "Proszę o najwyżej 80 godzin, mam sesję!!!",
            st.INTERPRETED,
            _interpretation("limit_godzin", "Grażyna chce najwyżej 80 godzin.", max_hours=80.0),
            {},
        ),
        (
            pr["dariusz"],
            r1,
            None,
            f"Chcę pracować albo {day12:%d}, albo {day13:%d}, potrzebuję tego dnia wypłaty.",
            st.INTERPRETED,
            _interpretation(
                "chce_pracowac",
                f"Dariusz chce pracować {day12:%d.%m} albo {day13:%d.%m}.",
                dates=[day12.isoformat(), day13.isoformat()],
                min_days=1,
                shifts_per_day=1,
            ),
            {},
        ),
        (
            pr["henryk"],
            r1,
            None,
            "Wolałbym mieć wolne w ostatni weekend miesiąca, jadę na wesele.",
            st.NEEDS_MANAGER,
            None,
            {"unread_reason": rs.OFF},
        ),
        (
            pr["anna2"],
            r1,
            None,
            "Jestem po zabiegu kolana, przez dwa tygodnie nie mogę dźwigać blach.",
            st.NEEDS_MANAGER,
            None,
            {"unread_reason": rs.UNSURE},
        ),
        (pr["kamil"], r1, None, "Proszę nie dawać mi zmian z Anną.", st.NEW, None, {}),
        (
            pr["ewa"],
            r1,
            None,
            "Chcę mieć same weekendy wolne, cały miesiąc.",
            st.REJECTED,
            _interpretation("wolne_dni", "Ewa chce wolne we wszystkie weekendy.", weekdays=[5, 6]),
            {"manager_rejected": True},
        ),
        (
            pr["oskar"],
            r1,
            None,
            "Chętnie wezmę więcej godzin, zbieram na wakacje.",
            st.NEEDS_MANAGER,
            None,
            {"employee_corrected": True},
        ),
        (
            pr["patrycja"],
            r1,
            None,
            "Wolę nie pracować w poniedziałki.",
            st.INTERPRETED,
            _interpretation(
                "wolne_dni", "Patrycja woli nie pracować w poniedziałki.", level="mile_widziane", weekdays=[0]
            ),
            {"manager_priority": "lower"},
        ),
        (
            pr["filip"],
            None,
            built.periods.later_month,
            "W tym miesiącu mam sesję, proszę o mniej godzin.",
            st.NEEDS_MANAGER,
            None,
            {"unread_reason": rs.OFF},
        ),
        (
            pr["natalia"],
            d1,
            None,
            "Nie stawiajcie mnie z Zuzanną na zamknięciu, obie jesteśmy nowe na kasie.",
            st.INTERPRETED,
            _interpretation(
                "unikaj_osoby", "Natalia nie chce pracować z Zuzanną.", subject_employee=str(pr["zuzanna"].id)
            ),
            {},
        ),
        (
            pr["roman"],
            d1,
            None,
            "Mogę brać nocki, ale nie więcej niż trzy w tygodniu.",
            st.NEEDS_MANAGER,
            None,
            {"unread_reason": rs.FAILED},
        ),
        (
            pr["magda"],
            w2,
            None,
            "Chcę pracować z Oliwią, uczę ją obsługi sali.",
            st.INTERPRETED,
            _interpretation(
                "preferuj_osobe",
                "Magdalena chce pracować z Oliwią.",
                level="mile_widziane",
                subject_employee=str(pr["oliwia"].id),
            ),
            {},
        ),
    ]
    for employee, period, month, text, status, interpretation, extra in rows:
        TextRequest.objects.create(
            employee=employee,
            period=period,
            month=month,
            text=text,
            status=status,
            interpretation=interpretation,
            **extra,
        )


def _instructions_a(company, rynek, profiles, owner) -> None:
    rows = [
        (
            profiles["celina"],
            {"type": "preferuj_osobe", "subject_employee": str(profiles["anna"].id)},
            "Celinę stawiaj z Anną Nowak, Anna uczy ją kasy.",
        ),
        (profiles["bartosz"], {"type": "wolne_dni", "weekdays": [6]}, "Bartosz ma mieć wolne w niedziele."),
    ]
    for position, (employee, data, text) in enumerate(rows, start=1):
        ManagerInstruction.objects.create(
            location=rynek,
            employee=employee,
            data={"dates": [], "weekdays": [], **data},
            position=position,
            source_text=text,
            created_by=owner,
        )


def _invitations_a(rynek, dworcowa, cafe, owner) -> None:
    pending = [
        (rynek, INVITED_ONLY_PHONES[0], "Zofia", "Nowicka", Role.EMPLOYEE),
        (dworcowa, INVITED_ONLY_PHONES[1], "Robert", "Zieliński", Role.MANAGER),
        (rynek, INVITED_ONLY_PHONES[2], "", "", Role.EMPLOYEE),
        (cafe, INVITED_ONLY_PHONES[2], "", "", Role.EMPLOYEE),  # the same number invited to two places
        (cafe, PHONES["hotel"]["h1"], "Kinga", "Lewicka", Role.EMPLOYEE),  # works in company B already
        # Works at Rynek already: accepting adds Dworcowa as an extra location (docs/plan.md, section 24).
        (dworcowa, PHONES["rynek"]["anna"], "", "", Role.EMPLOYEE),
    ]
    for location, phone, first, last, role in pending:
        Invitation.objects.create(
            location=location, phone_e164=phone, first_name=first, last_name=last, role=role, invited_by=owner
        )
    for phone, status in [
        (INVITED_ONLY_PHONES[3], InvitationStatus.DECLINED),
        (INVITED_ONLY_PHONES[4], InvitationStatus.CANCELLED),
    ]:
        Invitation.objects.create(
            location=rynek, phone_e164=phone, invited_by=owner, status=status, decided_at=timezone.now()
        )


# ---------------------------------------------------------------------------------------------- B and C


def _company_b(rng, built: Built) -> None:
    manager = _user(MANAGER_B, "Krzysztof", "Hotelowy")
    company = Company.objects.create(id=COMPANY_B, name="Hotel Pod Wawelem (firma testowa)", created_by=manager)
    Subscription.objects.create(company=company, ends_at=timezone.now() + timedelta(days=5))  # banner
    membership = Membership.objects.create(company=company, user=manager, role=Role.OWNER)
    location, _, _ = _simple_location(
        company,
        "Hotel Pod Wawelem – recepcja",
        "ul. Bernardyńska 2, 31-069 Kraków",
        positions=["Recepcja", "Portier"],
        shifts=[("Dzień", 7, 19, False), ("Noc", 19, 7, True)],
        staffing=lambda d: [("Dzień", "Recepcja", 1, 0), ("Noc", "Recepcja", 1, 0), ("Noc", "Portier", 1, 0)],
    )
    membership.locations.add(location)
    profiles = _staff(company, location, HOTEL, PHONES["hotel"])
    built.profiles |= profiles
    p = built.periods
    period = SchedulePeriod.objects.create(
        location=location, start=p.next[0], end=p.next[1], deadline_set_at=timezone.now()
    )
    _availability(rng, profiles, HOTEL, period, submitted_only=True)
    TextRequest.objects.create(
        employee=profiles["h2"],
        period=period,
        text="Proszę o same nocki, w dzień studiuję.",
        status=TextRequest.Status.NEEDS_MANAGER,
        unread_reason=TextRequest.UnreadReason.OFF,
    )
    built.ids["hotel_location"] = str(location.id)
    built.ids["hotel_period"] = str(period.id)


def _company_c(rng, built: Built) -> None:
    manager = _user(MANAGER_C, "Zenon", "Bistrowy")
    built.manager_c = manager
    company = Company.objects.create(id=COMPANY_C, name="Bistro Zamknięte (firma testowa)", created_by=manager)
    Subscription.objects.create(company=company, ends_at=timezone.now() - timedelta(days=1))  # read-only
    membership = Membership.objects.create(company=company, user=manager, role=Role.OWNER)
    location, _, _ = _simple_location(
        company,
        "Bistro na Kazimierzu",
        "ul. Szeroka 10, 31-053 Kraków",
        positions=["Kucharz", "Kelner"],
        shifts=[("Cały dzień", 10, 22, True)],
        staffing=lambda d: [("Cały dzień", "Kucharz", 1, 0), ("Cały dzień", "Kelner", 1, 0)],
    )
    membership.locations.add(location)
    profiles = _staff(company, location, BISTRO, PHONES["bistro"])
    built.profiles |= profiles
    p = built.periods
    period = SchedulePeriod.objects.create(location=location, start=p.published[0], end=p.published[1])
    _availability(rng, profiles, BISTRO, period, submitted_only=False)
    built.to_publish.append(period)


def _access_codes(built: Built) -> None:
    """Random codes (the repo is public, so they are never fixed); printed once by the command."""
    now = timezone.now()
    specs = [
        ("ok_30", AccessCode.Days.D30, 3, None),
        ("ok_60", AccessCode.Days.D60, 1, None),
        ("expired", AccessCode.Days.D30, 1, now - timedelta(days=1)),
        ("used_up", AccessCode.Days.D30, 1, None),
    ]
    for key, days, max_uses, valid_until in specs:
        code = generate_code()
        AccessCode.objects.create(
            code_hash=hash_code(code),
            prefix=code[:4],
            days=days,
            max_uses=max_uses,
            valid_until=valid_until,
            note=f"Dane testowe: {key}",
            **({"uses": 1} if key == "used_up" else {}),
        )
        built.codes[key] = format_code(code)


# ------------------------------------------------------------------------------------- generation and offers


def generate(period: SchedulePeriod, *, publish_it: bool, user, seconds: float = SOLVER_SECONDS) -> str:
    """Arrange one period as if it started today (so its past days are filled too). Returns a status line."""
    run = GenerationRun.objects.create(company_id=period.company_id, location=period.location)
    run.periods.set([period])
    run = run_generation(run.pk, time_limit_s=seconds, today=period.start)
    version = run.versions.first()
    if version is None:
        return f"{period}: nie ułożono ({run.error or run.status})"
    line = f"{period}: dziury {version.scores.get('holes')}/{version.scores.get('slots')}"
    if publish_it:
        try:
            publish(version, user)
            line += ", opublikowany"
        except HttpError as exc:
            line += f", NIE opublikowany ({exc})"
    return line


def _future_assignments(profile: EmployeeProfile, after: datetime, position: str | None):
    rows = Assignment.objects.filter(shift__position__name=position) if position else Assignment.objects.all()
    return (
        rows.filter(
            employee=profile,
            shift__version__status=ScheduleVersion.Status.PUBLISHED,
            shift__start_at__gt=after,
        )
        .exclude(offers__status__in=[ShiftOffer.Status.OPEN, ShiftOffer.Status.CLAIMED])
        .select_related("shift")
        .order_by("shift__start_at")
    )


def _offer(giver: EmployeeProfile, after: datetime, position: str | None = None):
    for assignment in _future_assignments(giver, after, position)[:10]:
        try:
            offer, _, _ = offer_shift(assignment, giver)
            return offer
        except HttpError:
            continue
    return None


def _claim(offer, takers: list[EmployeeProfile]):
    for taker in takers:
        try:
            return claim_offer(offer, taker)
        except HttpError:
            continue
    return None


@transaction.atomic
def create_offers(built: Built) -> list[str]:
    """Given-away shifts in every state. Done after publishing, through the same services as the screens."""
    pr = built.profiles
    soon = timezone.now() + timedelta(days=2)
    lines = []
    sellers_r = [pr[k] for k in ("ewa", "oskar", "patrycja", "anna2", "nina", "henryk", "filip", "grazyna")]
    sellers_r += [
        p for p in pr.values() if p.company_id == COMPANY_A and p.home_location_id != sellers_r[0].home_location_id
    ]

    offer = _offer(pr["anna"], soon, "Sprzedawca")  # waits for the manager
    claim = offer and _claim(offer, sellers_r)
    lines.append(
        f"Anna oddaje zmianę: {f'zgłosił(a) się {_who(claim)}, czeka na kierownika' if claim else 'bez chętnych'}"
    )

    offer = _offer(pr["bartosz"], soon, "Sprzedawca")  # approved (history)
    claim = offer and _claim(offer, [pr["celina"], *sellers_r])
    if not claim:
        lines.append("Bartosz oddaje zmianę, bez chętnych")
    else:
        try:
            approve_claim(claim, built.owner_a)
            lines.append(f"Bartosz oddał zmianę, kierownik zatwierdził: {_who(claim)} (historia)")
        except HttpError as exc:
            lines.append(f"Bartosz: nie zatwierdzono ({exc})")

    offer = _offer(pr["marek"], soon)  # a claim the manager refused; the offer is open again
    claim = offer and _claim(offer, [pr["lena"], pr["dariusz"], pr["igor"]])
    if claim:
        reject_claim(claim, built.owner_a)
        lines.append(f"Marek oddaje zmianę, kierownik odmówił: {_who(claim)} (zmiana znów do wzięcia)")

    if _offer(pr["kamil"], soon):
        lines.append("Kamil oddaje zmianę, nikt jeszcze nie wziął")
    if _offer(pr["marta"], soon):
        lines.append("Marta (Dworcowa, bez zatwierdzania) oddaje zmianę")
    if _offer(pr["klara"], soon):
        lines.append("Klara (kawiarnia) oddaje zmianę")
    return lines


def _who(claim) -> str:
    return EmployeeProfile.objects.get(pk=claim.employee_id).membership.user.full_name


def pin_draft(period: SchedulePeriod) -> str:
    version = ScheduleVersion.objects.filter(period=period, status=ScheduleVersion.Status.DRAFT).first()
    if version is None:
        return "brak szkicu do przypięcia"
    shifts = list(version.shifts.filter(assignment__isnull=False).order_by("start_at")[:2])
    for shift in shifts:
        set_pinned(version, str(shift.id), True)
    return f"przypięto {len(shifts)} zmiany w szkicu"
