"""Stage 10: the assistant reads employees' requests and the manager's commands (with a fake API client)."""

import json
from datetime import timedelta

import httpx2
import pytest
from anthropic import Anthropic, DefaultHttpxClient
from django.utils import timezone
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.accounts.models import User
from apps.assistant import llm, readings, services
from apps.assistant.models import AssistantCommand, ManagerInstruction
from apps.availability.models import TextRequest
from apps.rules.models import RuleSetting
from apps.scheduling.models import SchedulePeriod
from apps.scheduling.problem_builder import build_problem
from apps.staffing.models import EmployeeProfile, ShiftType
from apps.tenancy.models import Membership
from tests.conftest import next_phone


def add_worker(shop, first_name, last_name=""):
    user = User.objects.create_user(next_phone(), first_name=first_name, last_name=last_name)
    membership = Membership.objects.create(company=shop["company"], user=user)
    profile = EmployeeProfile.objects.create(membership=membership, home_location=shop["location"])
    profile.positions.add(shop["position"])
    return profile


@pytest.fixture
def shop(make_company, subscribe):
    data = make_company("Złoty Kłos")
    subscribe(data["company"])
    data["worker"].first_name = "Anna"
    data["worker"].save()
    data["employee"].positions.add(data["position"])
    data["kasia"] = add_worker(data, "Kasia")
    today = timezone.localdate()
    start = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    data["period"] = SchedulePeriod.objects.create(location=data["location"], start=start, end=end)
    return data


@pytest.fixture
def with_key(settings):
    settings.ANTHROPIC_API_KEY = "test-key"


def reading(**changes) -> llm.RequestReading:
    values = {
        "type": "wolne_dni",
        "person": None,
        "shift_type": None,
        "avoid_shift_type": False,
        "max_hours": None,
        "dates": [],
        "weekdays": [5],
        "level": "wazne",
        "confidence": 0.9,
        "summary": "Wolne w piątki, jeśli się da.",
    }
    return llm.RequestReading(**{**values, **changes})


def plan(**changes) -> llm.CommandPlan:
    values = {
        "reply": "Gotowe.",
        "question": None,
        "rule_changes": [],
        "new_instructions": [],
        "remove_instructions": [],
    }
    return llm.CommandPlan(**{**values, **changes})


def instruction(**changes) -> llm.NewInstruction:
    values = {
        "type": "unikaj_osoby",
        "person": "Anna",
        "other_person": "Kasia",
        "shift_type": None,
        "avoid_shift_type": False,
        "max_hours": None,
        "dates": [],
        "weekdays": [],
        "place": 1,
    }
    return llm.NewInstruction(**{**values, **changes})


def rule_change(code, **changes) -> llm.RuleChange:
    values = {
        "enabled": None,
        "no_exceptions": None,
        "number": None,
        "position": None,
        "shift_type": None,
        "place": None,
    }
    return llm.RuleChange(code=code, **{**values, **changes})


def send_request(api, shop, text="Wolałabym nie pracować w piątki."):
    return api.post(
        "/api/me/requests",
        {"company_id": str(shop["company"].pk), "period_id": str(shop["period"].pk), "text": text},
    )


# ----------------------------------------------------------------- employee requests


class TestRequests:
    def test_without_a_key_the_request_goes_to_the_manager_as_written(self, api, shop):
        api.login(shop["worker"])
        body = send_request(api, shop).json()
        assert body["status"] == "needs_manager" and body["summary"] is None
        assert not ProcrastinateJob.objects.filter(task_name="assistant.interpret_text_request").exists()
        built = build_problem([shop["period"]])
        assert [r.type for r in built.problem.requests] == ["other"]  # left to the manager, not scored

    def test_with_a_key_the_request_is_saved_and_queued_together(self, api, shop, with_key):
        api.login(shop["worker"])
        body = send_request(api, shop).json()
        assert body["status"] == "new"
        job = ProcrastinateJob.objects.get(task_name="assistant.interpret_text_request")
        assert job.queue_name == "default" and job.args["request_id"] == body["id"]

    def test_understood_request_reaches_the_generator(self, api, shop, with_key, monkeypatch):
        seen = {}

        def fake(text, context):
            seen.update(text=text, context=context)
            return reading()

        monkeypatch.setattr(llm, "read_request", fake)
        api.login(shop["worker"])
        request_id = send_request(api, shop).json()["id"]
        assert services.interpret_request(request_id) == "interpreted"

        # Only the text, the period and first names of this location are sent: no surnames, phones or own name.
        assert seen["text"] == "Wolałabym nie pracować w piątki."
        assert "Kasia" in seen["context"] and "Anna" not in seen["context"] and "+48" not in seen["context"]
        [mine] = api.get(f"/api/me/requests?company_id={shop['company'].pk}&period_id={shop['period'].pk}").json()
        assert mine["status"] == "interpreted" and mine["summary"] == "Wolne w piątki, jeśli się da."
        [request] = build_problem([shop["period"]]).problem.requests
        assert request.type == "days_off" and request.level == "wazne"
        assert request.dates and all(d.weekday() == 4 for d in request.dates)
        api.login(shop["manager"])
        [listed] = api.get(f"/api/periods/{shop['period'].pk}/requests").json()
        assert listed["summary"] == "Wolne w piątki, jeśli się da."

    @pytest.mark.parametrize(
        "answer",
        [
            reading(confidence=0.3),
            reading(type="inne", weekdays=[]),
            reading(type="unikaj_osoby", person="Zenon", weekdays=[]),  # nobody of that name here
            reading(type="typ_zmiany", shift_type="Nocna", weekdays=[]),  # no such shift here
            reading(weekdays=[], dates=["2020-01-01"]),  # outside the period
        ],
    )
    def test_unsure_or_unusable_reading_goes_to_the_manager_without_interpretation(
        self, api, shop, with_key, monkeypatch, answer
    ):
        monkeypatch.setattr(llm, "read_request", lambda text, context: answer)
        api.login(shop["worker"])
        request_id = send_request(api, shop).json()["id"]
        assert services.interpret_request(request_id) == "needs_manager"
        row = TextRequest.objects.get(pk=request_id)
        assert row.interpretation is None

    def test_a_failed_call_leaves_the_request_to_the_manager(self, api, shop, with_key, monkeypatch):
        def broken(text, context):
            raise llm.AssistantError("connection")

        monkeypatch.setattr(llm, "read_request", broken)
        api.login(shop["worker"])
        request_id = send_request(api, shop).json()["id"]
        assert services.interpret_request(request_id) == "needs_manager"
        assert services.interpret_request(request_id) == "skipped"  # a second run does nothing

    def test_person_and_shift_names_become_ids(self, api, shop, with_key, monkeypatch):
        answer = reading(type="unikaj_osoby", person="kasia", weekdays=[], summary="Bez zmian z Kasią.")
        monkeypatch.setattr(llm, "read_request", lambda text, context: answer)
        api.login(shop["worker"])
        request_id = send_request(api, shop, "Nie chcę zmian z Kasią").json()["id"]
        services.interpret_request(request_id)
        data = TextRequest.objects.get(pk=request_id).interpretation
        assert data["subject_employee"] == str(shop["kasia"].pk) and data["type"] == "unikaj_osoby"

    def test_employee_says_it_was_misunderstood_or_rewrites(self, api, shop, with_key, monkeypatch):
        monkeypatch.setattr(llm, "read_request", lambda text, context: reading())
        api.login(shop["worker"])
        request_id = send_request(api, shop).json()["id"]
        services.interpret_request(request_id)

        body = api.patch(f"/api/me/requests/{request_id}", {"understood": False}).json()
        assert body["status"] == "needs_manager" and body["summary"] is None
        assert TextRequest.objects.get(pk=request_id).employee_corrected is True

        body = api.patch(f"/api/me/requests/{request_id}", {"text": "Wolałabym wolne w soboty."}).json()
        assert body["status"] == "new" and body["text"] == "Wolałabym wolne w soboty."
        jobs = ProcrastinateJob.objects.filter(task_name="assistant.interpret_text_request")
        assert jobs.count() == 2
        # The job of the old wording does nothing; the new one reads the new text.
        assert services.interpret_request(request_id, text="Wolałabym nie pracować w piątki.") == "skipped"
        assert services.interpret_request(request_id, text="Wolałabym wolne w soboty.") == "interpreted"

    def test_cannot_change_a_colleagues_request_or_another_companys(self, api, shop, make_company):
        theirs = TextRequest.objects.create(employee=shop["kasia"], period=shop["period"], text="x")
        api.login(shop["worker"])
        assert api.patch(f"/api/me/requests/{theirs.pk}", {"understood": False}).status_code == 404
        other = make_company("Inna")
        api.login(other["worker"])
        assert api.patch(f"/api/me/requests/{theirs.pk}", {"understood": False}).status_code == 404

    def test_limit_of_requests_per_period(self, api, shop, settings):
        settings.TEXT_REQUESTS_PER_PERIOD = 2
        api.login(shop["worker"])
        assert send_request(api, shop).status_code == 201
        assert send_request(api, shop).status_code == 201
        assert send_request(api, shop).status_code == 400


# ----------------------------------------------------------------- manager commands


def command(api, shop, text="Anna i Kasia nie mogą pracować razem."):
    return api.post(f"/api/locations/{shop['location'].pk}/assistant-commands", {"text": text})


def run(api, shop, monkeypatch, answer, text="Anna i Kasia nie mogą pracować razem."):
    monkeypatch.setattr(llm, "plan_command", lambda text, context: answer)
    created = command(api, shop, text).json()
    assert services.run_command(created["id"]) == "ready"
    return api.get(f"/api/assistant-commands/{created['id']}").json()


class TestCommands:
    def test_without_a_key_the_assistant_is_off(self, api, shop):
        api.login(shop["manager"])
        response = command(api, shop)
        assert response.status_code == 201 and response.json()["status"] == "unavailable"
        assert api.get(f"/api/locations/{shop['location'].pk}/instructions").json()["assistant_enabled"] is False
        assert not ProcrastinateJob.objects.filter(task_name="assistant.plan_assistant_command").exists()

    def test_command_is_saved_and_queued_together(self, api, shop, with_key):
        api.login(shop["manager"])
        body = command(api, shop).json()
        assert body["status"] == "queued" and body["can_apply"] is False
        job = ProcrastinateJob.objects.get(task_name="assistant.plan_assistant_command")
        assert job.queue_name == "default" and job.args == {"command_id": body["id"]}

    def test_plan_changes_nothing_until_accepted(self, api, shop, with_key, monkeypatch):
        api.login(shop["manager"])
        body = run(api, shop, monkeypatch, plan(new_instructions=[instruction()]))
        assert body["status"] == "ready" and body["can_apply"] is True
        assert body["lines"] == ["Nowe polecenie: Anna i Kasia: osobno, nie na tej samej zmianie."]
        assert ManagerInstruction.objects.count() == 0

        applied = api.post(f"/api/assistant-commands/{body['id']}/apply")
        assert applied.status_code == 200 and applied.json()["status"] == "applied"
        row = ManagerInstruction.objects.get()
        assert row.employee == shop["employee"] and row.data["subject_employee"] == str(shop["kasia"].pk)
        assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 409  # only once

        listed = api.get(f"/api/locations/{shop['location'].pk}/instructions").json()
        assert [i["text"] for i in listed["items"]] == ["Anna i Kasia: osobno, nie na tej samej zmianie"]
        [request] = build_problem([shop["period"]]).problem.requests
        assert request.by_manager and request.rank == 1 and request.type == "avoid_person"

    def test_dismissed_plan_changes_nothing(self, api, shop, with_key, monkeypatch):
        api.login(shop["manager"])
        body = run(api, shop, monkeypatch, plan(new_instructions=[instruction()]))
        assert api.post(f"/api/assistant-commands/{body['id']}/dismiss").json()["status"] == "dismissed"
        assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 409
        assert ManagerInstruction.objects.count() == 0

    def test_rule_changes_go_through_the_rule_list(self, api, shop, with_key, monkeypatch):
        RuleSetting.objects.create(location=shop["location"], rule_code="fair_weekends", position=1)
        api.login(shop["manager"])
        answer = plan(
            rule_changes=[
                rule_change("max_shifts_per_week", enabled=True, number=4, place=1),
                rule_change("fair_weekends", enabled=False),
                rule_change("no_such_rule", enabled=True),
            ]
        )
        body = run(api, shop, monkeypatch, answer, "Najwyżej 4 zmiany w tygodniu, to najważniejsze.")
        assert body["lines"] == [
            "Zasada „Zmiany w tygodniu”: włączę, liczba zmian: 4, miejsce 1 na liście zasad.",
            "Zasada „Równy podział weekendów”: wyłączę.",
        ]
        assert body["notes"] == ["Pominąłem zmianę zasady, której nie ma na liście zasad."]
        assert RuleSetting.objects.filter(location=shop["location"], rule_code="max_shifts_per_week").count() == 0

        assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 200
        first = RuleSetting.objects.get(location=shop["location"], position=1)
        assert first.rule_code == "max_shifts_per_week" and first.enabled and first.params == {"shifts": 4}
        items = api.get(f"/api/scopes/location/{shop['location'].pk}/rules").json()["items"]
        assert items[0]["code"] == "max_shifts_per_week"
        assert next(i for i in items if i["code"] == "fair_weekends")["enabled"] is False

    def test_importance_is_a_place_and_no_exceptions_get_a_warning(self, api, shop, with_key, monkeypatch):
        api.login(shop["manager"])
        answer = plan(
            rule_changes=[
                rule_change(code, enabled=True, no_exceptions=True)
                for code in ("min_rest_between_shifts", "max_consecutive_days", "max_hours_per_day")
            ]
        )
        body = run(api, shop, monkeypatch, answer, "Wszystko jest bardzo ważne i bez wyjątków!")
        assert any("Będziesz mieć 3 zasady „bez wyjątków”" in note for note in body["notes"])

    def test_unknown_names_are_dropped_not_guessed(self, api, shop, with_key, monkeypatch):
        api.login(shop["manager"])
        answer = plan(
            new_instructions=[
                instruction(person="Zenon"),
                instruction(type="typ_zmiany", other_person=None, shift_type="Nocna"),
                instruction(type="wolne_dni", other_person=None),  # no days
            ]
        )
        body = run(api, shop, monkeypatch, answer)
        assert body["lines"] == [] and body["can_apply"] is False and len(body["notes"]) == 3

    def test_a_question_is_shown_when_the_command_is_unclear(self, api, shop, with_key, monkeypatch):
        api.login(shop["manager"])
        body = run(api, shop, monkeypatch, plan(reply="Nie wiem, o kogo chodzi.", question="Która Anna?"))
        assert body["question"] == "Która Anna?" and body["can_apply"] is False

    def test_a_failed_call_is_reported(self, api, shop, with_key, monkeypatch):
        def broken(text, context):
            raise llm.AssistantError("rate limit")

        monkeypatch.setattr(llm, "plan_command", broken)
        api.login(shop["manager"])
        created = command(api, shop).json()
        assert services.run_command(created["id"]) == "failed"
        assert services.run_command(created["id"]) == "skipped"
        assert api.get(f"/api/assistant-commands/{created['id']}").json()["status"] == "failed"

    def test_instructions_have_an_order_and_can_be_removed(self, api, shop, with_key, monkeypatch):
        api.login(shop["manager"])
        morning = ShiftType.objects.get(location=shop["location"])
        first = run(api, shop, monkeypatch, plan(new_instructions=[instruction()]))
        api.post(f"/api/assistant-commands/{first['id']}/apply")
        answer = plan(
            new_instructions=[
                instruction(person="Kasia", type="typ_zmiany", other_person=None, shift_type=morning.name)
            ]
        )
        second = run(api, shop, monkeypatch, answer, "Kasia tylko rano, to ważniejsze.")
        api.post(f"/api/assistant-commands/{second['id']}/apply")
        url = f"/api/locations/{shop['location'].pk}/instructions"
        items = api.get(url).json()["items"]
        assert [i["text"] for i in items] == [
            "Kasia: tylko zmiana „Ranna”",
            "Anna i Kasia: osobno, nie na tej samej zmianie",
        ]
        assert [r.rank for r in build_problem([shop["period"]]).problem.requests] == [1, 2]

        order = {"ids": [items[1]["id"], items[0]["id"]]}
        swapped = api.client.put(f"{url}/order", order, content_type="application/json")
        assert [i["id"] for i in swapped.json()["items"]] == order["ids"]
        bad = api.client.put(f"{url}/order", {"ids": order["ids"][:1]}, content_type="application/json")
        assert bad.status_code == 400

        assert api.client.delete(f"/api/instructions/{items[0]['id']}").status_code == 204
        assert [r.position for r in ManagerInstruction.objects.all()] == [1]

        # The assistant can remove one by its number on the list.
        third = run(api, shop, monkeypatch, plan(remove_instructions=[1, 7]), "Usuń polecenie o Annie.")
        assert third["lines"] == ["Usunę polecenie: Anna i Kasia: osobno, nie na tej samej zmianie."]
        api.post(f"/api/assistant-commands/{third['id']}/apply")
        assert ManagerInstruction.objects.count() == 0

    def test_monthly_limit(self, api, shop, with_key, settings):
        settings.ASSISTANT_COMMANDS_MONTHLY_LIMIT = 1
        api.login(shop["manager"])
        assert command(api, shop).status_code == 201
        assert command(api, shop).status_code == 429

    def test_read_only_company_cannot_use_the_assistant(self, api, shop, subscribe):
        subscribe(shop["company"], days=-1)
        api.login(shop["manager"])
        assert command(api, shop).status_code == 402

    def test_employees_and_other_companies_are_kept_out(self, api, shop, make_company, with_key, monkeypatch):
        api.login(shop["manager"])
        body = run(api, shop, monkeypatch, plan(new_instructions=[instruction()]))
        api.post(f"/api/assistant-commands/{body['id']}/apply")
        row = ManagerInstruction.objects.get()
        location = shop["location"].pk
        order = {"ids": [str(row.pk)]}

        def attempts():
            return [
                command(api, shop).status_code,
                api.get(f"/api/assistant-commands/{body['id']}").status_code,
                api.post(f"/api/assistant-commands/{body['id']}/apply").status_code,
                api.post(f"/api/assistant-commands/{body['id']}/dismiss").status_code,
                api.get(f"/api/locations/{location}/instructions").status_code,
                api.client.put(
                    f"/api/locations/{location}/instructions/order", order, content_type="application/json"
                ).status_code,
                api.client.delete(f"/api/instructions/{row.pk}").status_code,
            ]

        api.login(shop["worker"])
        assert set(attempts()) == {403}
        api.login(make_company("Inna")["manager"])
        assert set(attempts()) == {404}
        assert ManagerInstruction.objects.count() == 1 and AssistantCommand.objects.count() == 1


# ----------------------------------------------------------------- small pieces


def test_labels_send_first_names_and_tell_namesakes_apart():
    people = [("1", "Anna", "Kowalska"), ("2", "Anna", "Nowak"), ("3", "Ewa", "Lis"), ("4", "Anna", "Kot")]
    assert readings.labels(people) == {"Anna K.": "4", "Anna K. (2)": "1", "Anna N.": "2", "Ewa": "3"}


def test_past_dates_make_an_instruction_inactive():
    today = timezone.localdate()
    assert readings.is_over({"dates": [str(today - timedelta(days=1))]}, today)
    assert not readings.is_over({"dates": [str(today)]}, today)
    assert not readings.is_over({"weekdays": [0], "dates": [str(today - timedelta(days=1))]}, today)


def test_the_sdk_call_sends_a_schema_and_reads_the_structured_answer(settings, monkeypatch):
    """The real SDK code path against a fake HTTP transport: no network, no real key."""
    settings.ANTHROPIC_API_KEY = "test-key"
    sent = {}
    answer = reading().model_dump()

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.update(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": settings.ANTHROPIC_MODEL,
                "content": [{"type": "text", "text": json.dumps(answer)}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 10},
            },
        )

    client = Anthropic(api_key="test-key", http_client=DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(llm, "get_client", lambda: client)

    result = llm.read_request("Wolałabym nie pracować w piątki.", "Okres grafiku: …")

    assert result == reading()
    assert sent["model"] == settings.ANTHROPIC_MODEL
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert "Wolałabym nie pracować w piątki." in sent["messages"][0]["content"]


def test_a_refusal_or_cut_off_answer_is_an_error(settings, monkeypatch):
    settings.ANTHROPIC_API_KEY = "test-key"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": settings.ANTHROPIC_MODEL,
                "content": [],
                "stop_reason": "refusal",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 0},
            },
        )

    client = Anthropic(api_key="test-key", http_client=DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(llm, "get_client", lambda: client)
    with pytest.raises(llm.AssistantError):
        llm.plan_command("x", "y")
