"""People with several positions: "w trzecim tygodniu stycznia nie chcę być sprzedawcą" becomes a preference the
generator keeps (Piotr, 23.11.2026); with one position the assistant explains instead of saving it."""

from datetime import timedelta

import pytest

from apps.assistant import llm, services
from apps.assistant.models import ManagerInstruction
from apps.availability.models import TextRequest
from apps.core.holidays import easter, polish_holidays
from apps.scheduling.problem_builder import build_problem
from apps.staffing.models import Position
from tests.test_assistant import instruction, plan, reading, run, send_request
from tests.test_assistant import shop as shop
from tests.test_assistant import with_key as with_key


@pytest.fixture
def waiter(shop):
    """Anna sells and waits tables."""
    position = Position.objects.create(location=shop["location"], name="Kelner")
    shop["employee"].positions.add(position)
    return position


def third_week(shop) -> list[str]:
    start = shop["period"].start
    return [(start + timedelta(days=14 + n)).isoformat() for n in range(7)]


def read(api, shop, monkeypatch, answer, text="W trzecim tygodniu nie chcę być sprzedawcą.") -> dict:
    seen = {}

    def fake(message, context, toolbox=None):
        seen["context"] = context
        return answer

    monkeypatch.setattr(llm, "read_request", fake)
    api.login(shop["worker"])
    request_id = send_request(api, shop, text).json()["id"]
    services.interpret_request(request_id)
    row = TextRequest.objects.get(pk=request_id)
    return {"row": row, "context": seen.get("context", "")}


def position_reading(name="Sprzedawca", avoid=True, dates=None, **changes):
    return reading(type="stanowisko", position=name, avoid_position=avoid, dates=dates or [], weekdays=[], **changes)


class TestEmployee:
    def test_not_as_a_seller_in_one_week_reaches_the_generator(self, api, shop, with_key, monkeypatch, waiter):
        days = third_week(shop)
        got = read(api, shop, monkeypatch, position_reading(dates=days))
        row = got["row"]
        assert "Twoje stanowiska: Kelner, Sprzedawca." in got["context"]
        assert row.status == TextRequest.Status.INTERPRETED
        assert row.interpretation["positions"] == [str(shop["position"].pk)]
        assert row.interpretation["summary"].startswith("Bez stanowiska „Sprzedawca”")
        [request] = build_problem([shop["period"]]).problem.requests
        assert request.type == "position" and request.avoid
        assert request.positions == frozenset({str(shop["position"].pk)})
        assert sorted(d.isoformat() for d in request.dates) == days

    def test_only_one_of_several_positions(self, api, shop, with_key, monkeypatch, waiter):
        row = read(api, shop, monkeypatch, position_reading("kelner", avoid=False), "Chcę być tylko kelnerem.")["row"]
        assert row.status == TextRequest.Status.INTERPRETED
        assert row.interpretation["summary"] == "Tylko stanowisko „Kelner”."
        [request] = build_problem([shop["period"]]).problem.requests
        assert request.type == "position" and not request.avoid and request.positions == {str(waiter.pk)}

    def test_with_several_positions_an_unknown_one_is_asked_about(self, api, shop, with_key, monkeypatch, waiter):
        row = read(api, shop, monkeypatch, position_reading("Kucharz"), "Nie chcę być kucharzem.")["row"]
        assert row.status == TextRequest.Status.ANSWERED
        assert row.question == "O które stanowisko chodzi: Kelner czy Sprzedawca?"

    def test_with_one_position_not_on_it_asks_about_days_off(self, api, shop, with_key, monkeypatch):
        row = read(api, shop, monkeypatch, position_reading(dates=third_week(shop)))["row"]
        assert row.status == TextRequest.Status.ANSWERED and row.interpretation is None
        assert row.question.startswith("Masz tylko jedno stanowisko: „Sprzedawca”")
        assert "wolne" in row.question

    def test_with_one_position_only_on_it_saves_nothing(self, api, shop, with_key, monkeypatch):
        answer = position_reading(avoid=False, answer="")
        row = read(api, shop, monkeypatch, answer, "Chcę być tylko sprzedawcą.")["row"]
        assert row.status == TextRequest.Status.ANSWERED and row.interpretation is None
        assert "i tak pracujesz tylko na nim" in row.reply and "nie zapisuję" in row.reply

    def test_with_one_position_another_one_goes_to_the_manager(self, api, shop, with_key, monkeypatch):
        row = read(api, shop, monkeypatch, position_reading("Kelner", avoid=False), "Chcę być kelnerem.")["row"]
        assert row.status == TextRequest.Status.NEEDS_MANAGER
        assert row.reply.startswith("Twoje stanowisko: „Sprzedawca”. Inne stanowisko może Ci dodać tylko kierownik")


class TestManager:
    def test_an_instruction_about_a_position(self, api, shop, with_key, monkeypatch, waiter):
        api.login(shop["manager"])
        answer = plan(
            new_instructions=[instruction(type="stanowisko", position="Sprzedawca", avoid_position=True, place=None)]
        )
        body = run(api, shop, monkeypatch, answer, "Anna ma nie być sprzedawcą.")
        assert body["lines"] == ["Nowe polecenie: Anna: bez stanowiska „Sprzedawca”."]
        assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 200
        assert ManagerInstruction.objects.get().data["positions"] == [str(shop["position"].pk)]
        [request] = build_problem([shop["period"]]).problem.requests
        assert request.by_manager and request.type == "position" and request.avoid

    def test_a_position_the_person_does_not_hold_is_not_proposed(self, api, shop, with_key, monkeypatch, waiter):
        api.login(shop["manager"])
        answer = plan(new_instructions=[instruction(type="stanowisko", person="Kasia", position="Kelner")])
        body = run(api, shop, monkeypatch, answer, "Kasia tylko jako kelner.")
        assert body["can_apply"] is False
        assert "nie pracuje na stanowisku „Kelner” (ma: „Sprzedawca”)" in " ".join(body["notes"])


def test_polish_holidays():
    assert easter(2026).isoformat() == "2026-04-05" and easter(2027).isoformat() == "2027-03-28"
    days = dict(polish_holidays(2027))
    assert len(days) == 14
    assert {d.isoformat(): name for d, name in days.items()}["2027-05-27"] == "Boże Ciało"
    assert any(name == "Wigilia" for name in days.values())


def test_the_employee_assistant_knows_the_holidays(api, shop, with_key, monkeypatch):
    got = read(api, shop, monkeypatch, reading(), "Jakie są święta w Polsce?")
    year = shop["period"].start.year
    assert "Dni ustawowo wolne od pracy w Polsce: " in got["context"] and f"{year}:" in got["context"]
    assert "Boże Narodzenie" in got["context"]
