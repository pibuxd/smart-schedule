"""The request types added on 27.11.2026 on the assistant's side (docs/plan.md section 49): what a reading may say,
how it is described, and what the generator gets from it."""

from datetime import time, timedelta

import pytest
from django.utils import timezone

from apps.assistant import llm, readings
from apps.assistant.models import ManagerInstruction
from apps.notifications.models import Notification
from apps.notifications.services import notification_text
from apps.scheduling.models import SchedulePeriod
from apps.scheduling.problem_builder import build_problem
from apps.staffing.models import ShiftType
from apps.tenancy.models import Location
from tests.test_assistant import instruction, plan, reading, run
from tests.test_assistant import shop as shop
from tests.test_assistant import with_key as with_key
from tests.test_assistant_answers import my_requests, read

SHIFTS = {"Ranna": "s1", "Nocna": "s2", "Zamykająca": "s3"}
PEOPLE = {"Kasia": "p1"}
NAMES = {"s1": "Ranna", "s2": "Nocna", "s3": "Zamykająca", "p1": "Kasia"}


def clean(**values):
    return readings.clean(**{"people": PEOPLE, "shift_types": SHIFTS, **values})


def said(**values) -> str:
    data = clean(**values)
    assert data is not None, values
    return readings.describe(data, "Ola", NAMES, NAMES)


class TestReadings:
    @pytest.mark.parametrize(
        ("values", "sentence"),
        [
            ({"type": "pora_dnia", "from_time": "10:00"}, "Ola: zmiany najlepiej od 10:00"),
            ({"type": "pora_dnia", "to_time": "18:00"}, "Ola: zmiany najlepiej do 18:00"),
            (
                {"type": "pora_dnia", "from_time": "8:00", "to_time": "16:00"},
                "Ola: zmiany najlepiej w godzinach 8:00–16:00",
            ),
            (
                {"type": "pora_dnia", "from_time": "12:00", "to_time": "14:00", "avoid": True},
                "Ola: najlepiej bez pracy w godzinach 12:00–14:00",
            ),
            ({"type": "pora_dnia", "from_time": "22:00", "avoid": True}, "Ola: najlepiej bez pracy po 22:00"),
            ({"type": "dni_z_rzedu", "count": 3}, "Ola: najwyżej 3 dni pracy z rzędu"),
            ({"type": "dni_z_rzedu", "count": 2, "shift_type": "Nocna"}, "Ola: najwyżej 2 zmiany „Nocna” z rzędu"),
            ({"type": "dni_z_rzedu", "count": 2, "closing": True}, "Ola: najwyżej 2 zamknięcia z rzędu"),
            (
                {"type": "wolne_z_rzedu", "count": 2, "hours_period": "week"},
                "Ola: co najmniej 2 dni wolnego z rzędu w każdym tygodniu",
            ),
            ({"type": "wolne_z_rzedu", "count": 4}, "Ola: co najmniej 4 dni wolnego z rzędu w okresie grafiku"),
            ({"type": "po_zmianie", "shift_type": "Nocna"}, "Ola: po zmianie „Nocna” dzień wolny"),
            ({"type": "po_zmianie", "shift_type": "Nocna", "count": 2}, "Ola: po zmianie „Nocna” 2 dni wolnego"),
            (
                {"type": "po_zmianie", "closing": True, "next_shift_type": "Ranna", "count": 1},
                "Ola: po zamknięciu bez zmiany „Ranna” następnego dnia",
            ),
            ({"type": "wolne_weekendy", "count": 1, "out_of": 2}, "Ola: wolny co drugi weekend"),
            ({"type": "wolne_weekendy", "count": 2, "out_of": 3}, "Ola: 2 z każdych 3 kolejnych weekendów wolne"),
            ({"type": "wolne_weekendy", "count": 1}, "Ola: co najmniej 1 wolny weekend w okresie grafiku"),
            ({"type": "stala_pora"}, "Ola: cały tydzień ta sama pora zmian"),
            ({"type": "dlugosc_zmiany", "shift_hours": 6}, "Ola: zmiany nie krótsze niż 6 godz."),
            ({"type": "nie_sam", "closing": True}, "Ola: nie w pojedynkę na zamknięciu"),
            ({"type": "nie_sam"}, "Ola: nie w pojedynkę na zmianie"),
            ({"type": "unikaj_osoby", "person": "Kasia", "same_day": True}, "Ola i Kasia: nie w te same dni"),
            (
                {"type": "preferuj_osobe", "person": "Kasia", "same_day": True},
                "Ola i Kasia: te same dni pracy i te same dni wolne",
            ),
            ({"type": "unikaj_osoby", "person": "Kasia", "closing": True}, "Ola i Kasia: nie razem na zamknięciu"),
            (
                {"type": "limit_zmian", "max_shifts": 2, "closing": True, "hours_period": "week"},
                "Ola: najwyżej 2 zamknięcia w każdym tygodniu",
            ),
            (
                {"type": "wolne_dni", "weekdays": [6, 7], "min_days": 1, "hours_period": "week"},
                "Ola: wolne w weekendy (jeden z tych dni w każdym tygodniu)",
            ),
            (
                {"type": "wolne_dni", "dates": ["2026-12-24", "2026-12-31"], "min_days": 1},
                "Ola: wolne 24.12, 31.12 (jeden z tych dni)",
            ),
            (
                {"type": "chce_pracowac", "weekdays": [1, 2, 3, 4, 5, 6, 7], "min_days": 4, "hours_period": "week"},
                "Ola: praca od poniedziałku do niedzieli (4 z tych dni w każdym tygodniu)",
            ),
        ],
    )
    def test_each_new_reading_reads_as_one_sentence(self, values, sentence):
        assert said(**values) == sentence

    def test_a_location_is_one_of_the_persons_own(self):
        places = {"Rynek": ["l1"], "Dworcowa": ["l2"]}
        data = clean(type="lokal", location="rynek", locations=places)
        assert data["locations"] == ["l1"] and data["location_name"] == "Rynek" and data["avoid"] is False
        assert readings.describe(data, "Ola", NAMES, NAMES) == "Ola: tylko lokal „Rynek”"
        rather = clean(type="lokal", location="Rynek", rather=True, locations=places)
        assert readings.describe(rather, "Ola", NAMES, NAMES) == "Ola: chętniej lokal „Rynek” (inne też mogą być)"
        avoid = clean(type="lokal", location="Dworcowa", avoid=True, locations=places)
        assert readings.describe(avoid, "Ola", NAMES, NAMES) == "Ola: bez lokalu „Dworcowa”"
        assert clean(type="lokal", location="Kraków", locations=places) is None

    @pytest.mark.parametrize(
        "values",
        [
            {"type": "pora_dnia"},  # no hours
            {"type": "pora_dnia", "from_time": "25:00"},
            {"type": "pora_dnia", "from_time": "10:00", "to_time": "10:00"},
            {"type": "dni_z_rzedu", "count": 0},
            {"type": "dni_z_rzedu", "count": 14},
            {"type": "wolne_z_rzedu", "count": 7, "hours_period": "week"},
            {"type": "po_zmianie", "count": 1},  # after which shift?
            {"type": "po_zmianie", "shift_type": "Nocna", "next_shift_type": "Popołudniowa"},
            {"type": "wolne_weekendy", "count": 2, "out_of": 2},
            {"type": "wolne_weekendy", "count": 1, "out_of": 9},
            {"type": "dlugosc_zmiany", "shift_hours": 0},
            {"type": "dlugosc_zmiany", "shift_hours": 30},
            {"type": "lokal", "location": "Rynek"},  # no locations of the person
            {"type": "unikaj_osoby", "person": "Kasia", "same_day": True, "shift_type": "Nocna"},
            {"type": "typ_zmiany", "shift_type": "Nocna", "closing": True},
            {"type": "wolne_dni", "weekdays": [5], "count": 2},
            {"type": "limit_godzin", "max_hours": 30, "shift_hours": 6},
            {"type": "wolne_dni", "weekdays": [2], "min_days": 1, "from_time": "9:00"},
            {"type": "stala_pora", "location": "Rynek"},
            # "Nie więcej niż inni" goes to the manager, who sets fair shares in the rules (Piotr, 27.11.2026).
            {"type": "nie_wiecej_niz_inni", "closing": True},
        ],
    )
    def test_what_cannot_be_kept_is_refused(self, values):
        assert clean(**values) is None

    def test_a_count_of_all_the_days_off_means_all_of_them(self):
        assert "min_days" not in clean(type="wolne_dni", dates=["2026-12-24", "2026-12-31"], min_days=2)
        assert "min_days" not in clean(type="wolne_dni", weekdays=[6, 7], min_days=2, hours_period="week")

    def test_a_day_window_means_the_period_for_runs_of_days_off(self):
        assert clean(type="wolne_z_rzedu", count=2, hours_period="day")["hours_period"] == "period"
        assert "hours_period" not in clean(type="chce_pracowac", weekdays=[1], hours_period="week")


@pytest.fixture
def night(shop):
    return ShiftType.objects.create(location=shop["location"], name="Nocna", start_time=time(22), end_time=time(6))


class TestEmployeeRequests:
    def test_after_a_night_a_day_off_reaches_the_generator(self, api, shop, with_key, monkeypatch, night):
        answer = reading(type="po_zmianie", shift_type="Nocna", count=1, weekdays=[], lasting=True)
        status, row, seen = read(api, shop, monkeypatch, answer, "Po nocce chcę mieć dzień wolny.")
        assert status == "interpreted" and row.lasting
        assert row.interpretation["summary"] == "Po zmianie „Nocna” dzień wolny."
        assert "Twoje lokale" not in seen["context"]  # one location: nothing to choose
        [request] = build_problem([shop["period"]]).problem.requests
        assert request.type == "rest_after" and request.shift_type == str(night.pk) and request.days_after == 1

    @pytest.mark.parametrize(
        ("values", "kind", "fields"),
        [
            (
                {"type": "pora_dnia", "from_time": "10:00", "weekdays": []},
                "time_of_day",
                {"from_time": time(10), "to_time": None, "avoid": False},
            ),
            ({"type": "dni_z_rzedu", "count": 3, "weekdays": []}, "days_in_row", {"max_in_row": 3}),
            (
                {"type": "wolne_z_rzedu", "count": 2, "hours_period": "week", "weekdays": []},
                "days_off_in_row",
                {"free_in_row": 2, "weekly_hours": True},
            ),
            (
                {"type": "wolne_weekendy", "count": 1, "out_of": 2, "weekdays": []},
                "free_weekends",
                {"free_weekends": 1, "of_weekends": 2},
            ),
            ({"type": "stala_pora", "weekdays": []}, "same_shift_type", {}),
            ({"type": "dlugosc_zmiany", "shift_hours": 6, "weekdays": []}, "shift_length", {"min_shift_hours": 6.0}),
            ({"type": "nie_sam", "closing": True, "weekdays": []}, "not_alone", {"closing": True}),
            (
                {"type": "unikaj_osoby", "person": "Kasia", "same_day": True, "weekdays": []},
                "avoid_person",
                {"same_day": True},
            ),
            (
                {"type": "wolne_dni", "weekdays": [6, 7], "min_days": 1, "hours_period": "week"},
                "days_off",
                {"min_days": 1, "weekly_hours": True},
            ),
        ],
    )
    def test_each_reading_becomes_its_request(self, api, shop, with_key, monkeypatch, values, kind, fields):
        status, row, _ = read(api, shop, monkeypatch, reading(**values), "Prośba.")
        assert status == "interpreted", row.assistant_answer
        [request] = build_problem([shop["period"]]).problem.requests
        assert request.type == kind
        assert {name: getattr(request, name) for name in fields} == fields

    def test_a_location_wish_names_one_of_the_persons_locations(self, api, shop, with_key, monkeypatch):
        second = Location.objects.create(company=shop["company"], name="Rynek")
        shop["employee"].extra_locations.add(second)
        status, row, seen = read(
            api, shop, monkeypatch, reading(type="lokal", location="Rynek", weekdays=[]), "Wolę pracować w Rynku."
        )
        assert f"Twoje lokale: Rynek, {shop['location'].name}." in seen["context"]
        assert status == "interpreted" and row.interpretation["locations"] == [str(second.pk)]
        [request] = build_problem([shop["period"]]).problem.requests
        assert request.type == "location" and request.locations == {str(second.pk)} and not request.avoid
        # A location the person does not work in: the app asks which one.
        status, row, _ = read(
            api, shop, monkeypatch, reading(type="lokal", location="Dworcowa", weekdays=[]), "Tylko Dworcowa."
        )
        assert status == "answered" and row.question == f"O który lokal chodzi: Rynek czy {shop['location'].name}?"

    def test_with_one_location_a_location_wish_is_not_saved(self, api, shop, with_key, monkeypatch):
        answer = reading(type="lokal", location=shop["location"].name, weekdays=[])
        status, row, _ = read(api, shop, monkeypatch, answer, "Chcę pracować tylko tutaj.")
        assert status != "interpreted" and not row.interpretation

    def test_an_unknown_shift_after_another_gets_a_question(self, api, shop, with_key, monkeypatch, night):
        answer = reading(type="po_zmianie", shift_type="Nocna", next_shift_type="Otwierająca", weekdays=[])
        status, row, _ = read(api, shop, monkeypatch, answer, "Po nocce nie dawajcie mi otwarcia.")
        assert status == "answered" and row.question.startswith("Nie ma w lokalu zmiany „Otwierająca”.")

    def test_a_lasting_whole_day_cannot_is_offered_in_each_later_month(self, api, shop, with_key, monkeypatch):
        answer = reading(weekdays=[5], cannot=True, lasting=True)
        status, row, _ = read(api, shop, monkeypatch, answer, "W piątki nigdy nie mogę.")
        assert status == "interpreted" and row.lasting and row.interpretation["cannot"] is True
        start = shop["period"].end + timedelta(days=1)
        later = SchedulePeriod.objects.create(
            location=shop["location"],
            start=start,
            end=(start + timedelta(days=32)).replace(day=1) - timedelta(days=1),
            availability_requested_at=timezone.now(),
        )
        [there] = api.get(f"/api/me/requests?company_id={shop['company'].pk}&period_id={later.pk}").json()
        fridays = [later.start + timedelta(days=n) for n in range((later.end - later.start).days + 1)]
        [mark] = there["cannot_marks"]
        assert mark["days"] == [d.isoformat() for d in fridays if d.weekday() == 4] and mark["windows"] == []
        # Its own month offers the Fridays of that month, as before.
        [mine] = my_requests(api, shop)
        assert mine["cannot_marks"][0]["days"][0] >= shop["period"].start.isoformat()

    def test_asking_for_availability_reminds_of_a_lasting_cannot(self, api, shop, with_key, monkeypatch):
        answer = reading(weekdays=[2], cannot=True, lasting=True, from_time="9:00", to_time="11:00")
        status, row, _ = read(api, shop, monkeypatch, answer, "Na stałe we wtorki nie mogę od 9 do 11.")
        assert status == "interpreted" and row.lasting
        start = shop["period"].end + timedelta(days=1)
        later = SchedulePeriod.objects.create(
            location=shop["location"], start=start, end=(start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        )
        api.login(shop["manager"])
        assert api.post(f"/api/periods/{later.pk}/ask-availability").json()["notified"] == 2
        sent = {n.user_id: n.payload for n in Notification.objects.filter(kind="availability_requested")}
        assert sent[shop["worker"].pk]["lasting_cannot"] is True
        assert "lasting_cannot" not in sent[shop["kasia"].membership.user_id]
        assert notification_text("availability_requested", sent[shop["worker"].pk]).endswith(
            "Masz prośbę na stałe „nie mogę”. Zaznacz ją w kalendarzu przyciskiem w „Twoje prośby”."
        )

    def test_a_cannot_with_one_of_the_days_is_only_a_wish(self, api, shop, with_key, monkeypatch):
        period = shop["period"]
        days = [period.start.isoformat(), (period.start + timedelta(days=7)).isoformat()]
        answer = reading(weekdays=[], dates=days, min_days=1, cannot=True)
        status, row, _ = read(api, shop, monkeypatch, answer, "Nie mogę albo pierwszego, albo ósmego.")
        assert status == "interpreted" and "cannot" not in row.interpretation and row.interpretation["min_days"] == 1
        assert my_requests(api, shop)[0]["cannot_marks"] == []


class TestManagerInstructions:
    def test_a_rest_after_closing_instruction(self, api, shop, with_key, monkeypatch):
        closing = ShiftType.objects.create(
            location=shop["location"], name="Zamykająca", start_time=time(14), end_time=time(22), is_closing=True
        )
        api.login(shop["manager"])
        new = instruction(
            type="po_zmianie", other_person=None, closing=True, next_shift_type="Ranna", count=1, place=None
        )
        body = run(api, shop, monkeypatch, plan(new_instructions=[new]), "Ania po zamknięciu nie otwiera.")
        assert body["lines"] == ["Nowe polecenie: Anna: po zamknięciu bez zmiany „Ranna” następnego dnia."]
        assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 200
        assert ManagerInstruction.objects.get().data["closing"] is True
        [request] = build_problem([shop["period"]]).problem.requests
        assert (
            request.type == "rest_after" and request.closing and request.next_shift_type == str(shop["shift_type"].pk)
        )
        assert closing.is_closing

    def test_a_location_instruction_names_the_persons_location(self, api, shop, with_key, monkeypatch):
        api.login(shop["manager"])
        new = instruction(type="lokal", other_person=None, location="Rynek", place=None)
        body = run(api, shop, monkeypatch, plan(new_instructions=[new]), "Ania tylko w Rynku.")
        assert body["can_apply"] is False
        assert body["notes"] == [
            f"Osoba „Anna” nie pracuje w lokalu „Rynek” (pracuje w: „{shop['location'].name}”). Lokale osoby "
            "zmienisz w zakładce „Pracownicy”."
        ]

    def test_hours_of_a_day_off_are_no_manager_instruction(self, api, shop, with_key, monkeypatch):
        api.login(shop["manager"])
        new = instruction(type="wolne_dni", other_person=None, weekdays=[2], from_time="9:00", to_time="11:00")
        body = run(api, shop, monkeypatch, plan(new_instructions=[new]), "Ania we wtorki nie od 9 do 11.")
        assert body["lines"] == ["Nowe polecenie: Anna: wolne we wtorki."]


def test_the_answer_schemas_stay_within_the_limits():
    # The new fields have defaults instead of null (see test_each_request_stays_within_the_structured_output_limits).
    fields = llm.Preference.model_fields
    for name in ("count", "out_of", "next_shift_type", "location", "avoid", "same_day", "closing", "shift_hours"):
        assert not fields[name].is_required(), name
    assert (
        llm.Preference(
            type="stanowisko",
            person=None,
            shift_type=None,
            avoid_shift_type=False,
            max_hours=None,
            max_shifts=None,
            hours_period="period",
            min_days=None,
            shifts_per_day=None,
            dates=[],
            weekdays=[],
            level="wazne",
            confidence=0.9,
            count=None,
            closing=None,
            location=None,
        ).count
        == 0
    )
