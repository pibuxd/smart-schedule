"""The assistant answers questions about Grafikomat and the location through the app's own API (19.11.2026)."""

import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import anthropic
import httpx2
import pytest
from anthropic import Anthropic, DefaultHttpxClient
from django.conf import settings as django_settings
from django.urls import resolve
from django.utils import timezone

from apps.assistant import llm, readings, services, tools
from apps.assistant.management.commands.assistant_misses import misses
from apps.assistant.models import AssistantCommand
from apps.availability.models import AvailabilityDay, TextRequest
from apps.notifications.models import Notification
from apps.notifications.services import notification_text
from apps.rules.api import preview_version
from apps.scheduling.models import Assignment, SchedulePeriod, ScheduleVersion, Shift
from apps.scheduling.problem_builder import build_problem
from tests.test_assistant import command, plan, question, reading, rule_change, run, send_request
from tests.test_assistant import shop as shop
from tests.test_assistant import with_key as with_key


def my_requests(api, shop):
    return api.get(f"/api/me/requests?company_id={shop['company'].pk}&period_id={shop['period'].pk}").json()


def read(api, shop, monkeypatch, answer, text="Kiedy mam następną zmianę?"):
    api.login(shop["worker"])
    seen = {}

    def fake(text, context, toolbox=None):
        seen.update(context=context, toolbox=toolbox)
        return answer

    monkeypatch.setattr(llm, "read_request", fake)
    pk = send_request(api, shop, text).json()["id"]
    status = services.interpret_request(pk)
    return status, TextRequest.objects.get(pk=pk), seen


def add_shift(shop, version, employee, day, hours=8):
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=6)
    shift = Shift.objects.create(
        version=version,
        location=shop["location"],
        date=day,
        shift_type=shop["shift_type"],
        position=shop["position"],
        start_at=start,
        end_at=start + timedelta(hours=hours),
        slot_key=f"s{Shift.objects.count()}",
    )
    Assignment.objects.create(shift=shift, employee=employee)
    return shift


def schema_counts(schema: dict) -> tuple[int, int]:
    """(union-typed parameters, optional parameters) of a JSON schema, $defs included, as the API counts them."""
    unions = optional = 0
    stack = [schema, *(schema.get("$defs") or {}).values()]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        required = set(node.get("required", []))
        for name, sub in (node.get("properties") or {}).items():
            unions += "anyOf" in sub or isinstance(sub.get("type"), list)
            optional += name not in required
            stack.append(sub)
        stack.extend([node.get("items"), *node.get("anyOf", [])])
    return unions, optional


# ----------------------------------------------------------------- tools: the app's own GET endpoints


class TestTools:
    def test_every_tool_is_an_existing_endpoint_with_a_closed_schema(self):
        for tool in (*tools.EMPLOYEE_TOOLS, *tools.MANAGER_TOOLS):
            resolve(re.sub(r"\{[a-z_]+\}", str(uuid4()), tool.path))  # raises when there is no such endpoint
            schema = tool.schema()["input_schema"]
            assert schema["additionalProperties"] is False and schema["required"] == list(schema["properties"])
            assert not set(schema["properties"]) & {"company_id", "location_id"}  # filled by the server only

    @pytest.mark.parametrize(
        "toolset, output", [(tools.MANAGER_TOOLS, llm.CommandPlan), (tools.EMPLOYEE_TOOLS, llm.EmployeeReply)]
    )
    def test_each_request_stays_within_the_structured_output_limits(self, toolset, output):
        """The API refuses a request whose strict schemas together have more than 16 union-typed parameters,
        24 optional ones or 20 strict tools ("Schema is too complex for compilation"), and then every message
        fails. Strict schemas here are the answer schema plus any tool marked strict."""
        definitions = [tool.schema() for tool in toolset]
        strict = [d["input_schema"] for d in definitions if d.get("strict")]
        unions, optional = 0, 0
        for schema in [anthropic.transform_schema(output.model_json_schema()), *strict]:
            u, o = schema_counts(schema)
            unions, optional = unions + u, optional + o
        assert len(strict) <= 20 and unions <= 16 and optional <= 24, (len(strict), unions, optional)

    def test_an_employee_reads_only_their_published_schedule_without_phones(self, shop):
        day = shop["period"].start
        published = ScheduleVersion.objects.create(period=shop["period"], number=1, status="published")
        draft = ScheduleVersion.objects.create(period=shop["period"], number=2)
        add_shift(shop, published, shop["employee"], day)
        add_shift(shop, published, shop["kasia"], day)
        add_shift(shop, draft, shop["employee"], day + timedelta(days=1))
        box = tools.employee_toolbox(shop["worker"], shop["company"].pk)
        text, error = box.run("my_schedule", {"date_from": None, "date_to": None})
        assert not error and "+48" not in text
        data = json.loads(text)
        assert [s["date"] for s in data["shifts"]] == [day.isoformat()]  # the draft stays with the manager
        assert data["shifts"][0]["coworkers"] == ["Kasia"]
        assert data["shifts"][0]["weekday"] == tools.WEEKDAYS[day.weekday()]  # the model never counts weekdays
        assert box.calls == [{"tool": "my_schedule", "status": 200}]

    def test_an_employee_has_no_manager_tools_and_manager_endpoints_refuse_them(self, shop):
        box = tools.employee_toolbox(shop["worker"], shop["company"].pk)
        assert box.run("availability_grid", {"period_id": str(shop["period"].pk)}) == (
            "Nie ma takiego narzędzia.",
            True,
        )
        as_manager = tools.manager_toolbox(shop["worker"], shop["company"].pk, shop["location"].pk)
        text, error = as_manager.run("availability_grid", {"period_id": str(shop["period"].pk)})
        assert error and text.startswith("Błąd 403")

    def test_another_companys_data_is_not_found(self, shop, make_company):
        other = make_company("Inna firma")
        foreign = SchedulePeriod.objects.create(
            location=other["location"], start=shop["period"].start, end=shop["period"].end
        )
        box = tools.manager_toolbox(shop["manager"], shop["company"].pk, shop["location"].pk)
        text, error = box.run("availability_grid", {"period_id": str(foreign.pk)})
        assert error and text.startswith("Błąd 404")
        text, error = box.run("availability_grid", {"period_id": str(shop["period"].pk)})
        assert not error and "Kasia" in text and "+48" not in text

    def test_every_date_gets_its_weekday(self):
        cleaned = tools.clean({"date": "2026-11-21", "shift": {"date": "2026-11-23"}, "start": "2026-11-21T06:00"})
        assert cleaned["weekday"] == "sobota" and cleaned["shift"]["weekday"] == "poniedziałek"
        assert tools.clean({"date": "nie data"}) == {"date": "nie data"}

    def test_long_results_are_narrowed_and_cut_with_a_note(self):
        tool = next(t for t in tools.MANAGER_TOOLS if t.name == "schedule_version")
        body = {
            "shifts": [
                {"date": f"2026-12-{n:02d}", "employee_name": "Anna Nowak" if n % 2 else None} for n in range(1, 31)
            ]
        }
        narrowed = tools.narrowed(tool, json.loads(json.dumps(body)), {"date_from": "2026-12-10", "person": "anna"})
        assert {s["date"] for s in narrowed["shifts"]} == {f"2026-12-{n}" for n in range(11, 31, 2)}
        text = tools.fit(body, limit=400)
        assert len(text) < 600 and "Wynik przycięty" in text
        assert tools.clean({"phone": "+48 500", "name": "A", "x": None, "y": []}) == {"name": "A"}


# ----------------------------------------------------------------- the conversation with the model


def fake_client(monkeypatch, responses, sent):
    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        content, stop = responses[min(len(sent), len(responses)) - 1]
        return httpx2.Response(
            200,
            json={
                "id": f"msg_{len(sent)}",
                "type": "message",
                "role": "assistant",
                "model": django_settings.ANTHROPIC_MODEL,
                "content": content,
                "stop_reason": stop,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 10},
            },
        )

    client = Anthropic(api_key="test-key", http_client=DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(llm, "get_client", lambda: client)


class StubBox:
    def __init__(self):
        self.calls = []

    def definitions(self):
        return [{"name": "my_schedule", "description": "x", "input_schema": {"type": "object", "properties": {}}}]

    def run(self, name, arguments):
        self.calls.append(name)
        return '{"shifts":[{"date":"2026-11-21"}]}', False


class TestConversation:
    def test_tool_results_go_back_to_the_model_before_the_answer(self, settings, monkeypatch):
        settings.ANTHROPIC_API_KEY = "test-key"
        sent = []
        use = {"type": "tool_use", "id": "toolu_1", "name": "my_schedule", "input": {}}
        final = question("W sobotę 21.11.").model_dump()
        fake_client(
            monkeypatch,
            [([use], "tool_use"), ([{"type": "text", "text": json.dumps(final)}], "end_turn")],
            sent,
        )
        box = StubBox()
        assert llm.read_request("Kiedy pracuję?", "Dzisiaj: …", box).answer == "W sobotę 21.11."
        assert box.calls == ["my_schedule"] and len(sent) == 2
        assert sent[0]["tools"][0]["name"] == "my_schedule" and "tool_choice" not in sent[0]
        [result] = sent[1]["messages"][2]["content"]
        assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_1"
        assert sent[0]["system"][0]["cache_control"] == {"type": "ephemeral"}

    def test_after_the_last_round_the_model_must_answer(self, settings, monkeypatch):
        settings.ANTHROPIC_API_KEY = "test-key"
        sent = []
        use = {"type": "tool_use", "id": "toolu_1", "name": "my_schedule", "input": {}}
        final = question().model_dump()
        responses = [([use], "tool_use")] * llm.MAX_TOOL_ROUNDS
        responses.append(([{"type": "text", "text": json.dumps(final)}], "end_turn"))
        fake_client(monkeypatch, responses, sent)
        llm.read_request("Kiedy pracuję?", "Dzisiaj: …", StubBox())
        assert len(sent) == llm.MAX_TOOL_ROUNDS + 1
        assert sent[-1]["tool_choice"] == {"type": "none"}

    def test_every_call_asks_for_low_effort_and_the_answer_logs_its_time(self, settings, monkeypatch, caplog):
        """Thinking is always on in the default model and each tool round is a full call: at the default effort
        an answer with tool rounds took about 40 s on 20.11.2026."""
        settings.ANTHROPIC_API_KEY, settings.ANTHROPIC_EFFORT = "test-key", "low"
        sent = []
        use = {"type": "tool_use", "id": "toolu_1", "name": "my_schedule", "input": {}}
        final = question().model_dump()
        fake_client(
            monkeypatch,
            [([use], "tool_use"), ([{"type": "text", "text": json.dumps(final)}], "end_turn")],
            sent,
        )
        with caplog.at_level("INFO", logger="apps.assistant.llm"):
            llm.read_request("Kiedy pracuję?", "Dzisiaj: …", StubBox())
        assert [request["output_config"]["effort"] for request in sent] == ["low", "low"]
        assert sent[0]["output_config"]["format"]["type"] == "json_schema"
        [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("assistant EmployeeReply")]
        assert "2 calls, tools my_schedule, 20 output tokens, effort low" in line

    @pytest.mark.parametrize("value", ["", "fast"])
    def test_an_empty_or_unknown_effort_leaves_the_model_default(self, settings, value, caplog):
        settings.ANTHROPIC_EFFORT = value
        with caplog.at_level("WARNING", logger="apps.assistant.llm"):
            config = llm.output_config(llm.EmployeeReply)
        assert "effort" not in config and "format" in config
        assert bool(caplog.records) == bool(value)


# ----------------------------------------------------------------- employee: answers and requests


class TestEmployee:
    def test_a_question_gets_an_answer_and_takes_no_place_in_the_limit(self, api, shop, with_key, monkeypatch):
        status, row, seen = read(api, shop, monkeypatch, question())
        assert status == "answered" and row.reply == "Masz zmianę w sobotę 21.11, 6:00–14:00."
        assert seen["toolbox"].user == shop["worker"] and seen["toolbox"].tools == tools.EMPLOYEE_TOOLS
        [mine] = my_requests(api, shop)
        assert mine["status"] == "answered" and mine["reply"] == row.reply
        assert not services.saved_requests(row).exists() and not build_problem([shop["period"]]).problem.requests
        api.login(shop["manager"])
        assert api.get(f"/api/periods/{shop['period'].pk}/requests").json() == []

    def test_questions_work_at_the_limit_and_a_new_request_is_not_saved(
        self, api, shop, with_key, monkeypatch, settings
    ):
        settings.TEXT_REQUESTS_PER_PERIOD = 2
        for n in range(2):
            TextRequest.objects.create(
                employee=shop["employee"], period=shop["period"], text=f"{n}", status="interpreted"
            )
        TextRequest.objects.create(employee=shop["employee"], period=shop["period"], text="pytanie", status="answered")
        assert read(api, shop, monkeypatch, question())[0] == "answered"
        status, row, _ = read(api, shop, monkeypatch, reading(), "Wolne w piątki")
        assert status == "answered" and row.interpretation is None and row.reply.startswith("Masz już 2 próśb")
        assert str(row.pk) not in {r.id for r in build_problem([shop["period"]]).problem.requests}

    def test_without_the_assistant_the_limit_counts_saved_requests_only(self, api, shop, settings):
        settings.TEXT_REQUESTS_PER_PERIOD = 1
        TextRequest.objects.create(employee=shop["employee"], period=shop["period"], text="x", status="rejected")
        api.login(shop["worker"])
        assert send_request(api, shop).status_code == 201
        assert send_request(api, shop).status_code == 400

    def test_messages_per_day_are_capped(self, api, shop, with_key, settings):
        settings.ASSISTANT_MESSAGES_PER_DAY = 2
        api.login(shop["worker"])
        assert [send_request(api, shop, f"{n}").status_code for n in range(3)] == [201, 201, 429]

    def test_one_message_can_answer_and_save_several_preferences(self, api, shop, with_key, monkeypatch):
        days_off = llm.Preference(**{**reading().preferences[0].model_dump(), "weekdays": [5]})
        hours = llm.Preference(
            **{
                **days_off.model_dump(),
                "type": "limit_godzin",
                "weekdays": [],
                "max_hours": 6,
                "hours_period": "day",
            }
        )
        answer = llm.EmployeeReply(
            topic="app", answer="Z Kasią.", preferences=[days_off, hours], leave_to_manager=False, replaces_request=None
        )
        status, row, _ = read(api, shop, monkeypatch, answer, "Wolne piątki, max 6 h dziennie. Z kim pracuję?")
        assert status == "interpreted" and row.reply == "Z Kasią."
        assert row.interpretation["summary"] == "Wolne w piątki; najwyżej 6 godz. dziennie."
        assert row.interpretation["more"][0]["hours_period"] == "day"
        requests = build_problem([shop["period"]]).problem.requests
        assert [r.id for r in requests] == [str(row.pk), f"{row.pk}:2"]
        assert requests[0].summary == "Wolne w piątki." and requests[1].daily_hours

    def test_cannot_offers_to_mark_the_calendar_and_conflicts_are_noted(self, api, shop, with_key, monkeypatch):
        start = shop["period"].start
        days = [start + timedelta(days=n) for n in range(3)]
        AvailabilityDay.objects.create(employee=shop["employee"], date=days[0], state="cannot")
        AvailabilityDay.objects.create(employee=shop["employee"], date=days[1], state="prefer")
        answer = reading(weekdays=[], dates=[d.isoformat() for d in days], cannot=True)
        status, row, _ = read(api, shop, monkeypatch, answer, "Mam sesję i nie mogę pracować.")
        assert status == "interpreted" and row.interpretation["cannot"] is True
        assert row.interpretation["summary"].endswith("(„nie mogę”).")
        [mine] = my_requests(api, shop)
        assert mine["unmarked_days"] == [days[1].isoformat(), days[2].isoformat()]
        assert any("„Chętnie”" in note for note in mine["notes"])
        api.client.put(
            "/api/me/calendar",
            {
                "company_id": str(shop["company"].pk),
                "days": [{"date": d, "state": "cannot"} for d in mine["unmarked_days"]],
            },
            content_type="application/json",
        )
        [mine] = my_requests(api, shop)
        assert mine["unmarked_days"] == [] and mine["notes"] == []

    def test_a_wish_the_app_cannot_set_is_left_to_the_manager_with_a_clear_reply(
        self, api, shop, with_key, monkeypatch
    ):
        answer = reading(type="inne", answer="Tego nie ustawię. Kierownik przeczyta to sam.")
        status, row, _ = read(api, shop, monkeypatch, answer, "Chcę co najmniej 120 godzin.")
        assert status == "needs_manager" and row.unread_reason == "unsure"
        assert my_requests(api, shop)[0]["reply"] == "Tego nie ustawię. Kierownik przeczyta to sam."

    def test_what_can_be_set_is_saved_and_the_rest_left_to_the_manager(self, api, shop, with_key, monkeypatch):
        answer = reading(leave_to_manager=True, answer="Wolne piątki zapisuję, resztę przeczyta kierownik.")
        status, row, _ = read(api, shop, monkeypatch, answer, "Wolne piątki i 120 godzin minimum.")
        assert status == "interpreted" and row.interpretation["partial"] is True
        assert services.PARTIAL_NOTE in my_requests(api, shop)[0]["notes"]
        api.login(shop["manager"])
        [seen] = api.get(f"/api/periods/{shop['period'].pk}/requests").json()
        assert seen["summary"].endswith("Resztę wiadomości asystent zostawił Tobie do przeczytania.")

    def test_an_unrelated_question_is_refused_with_app_copy(self, api, shop, with_key, monkeypatch):
        status, row, _ = read(api, shop, monkeypatch, reading(scope="out_of_scope"), "Jaka jutro pogoda?")
        assert status == "rejected" and row.interpretation["summary"] == services.UNRELATED_REQUEST_REPLY
        assert not services.saved_requests(row).exists()

    def test_forwarding_to_the_manager_notifies_the_managers(self, api, shop, with_key, monkeypatch):
        _, row, _ = read(api, shop, monkeypatch, question())
        response = api.patch(f"/api/me/requests/{row.pk}", {"understood": False})
        assert response.json()["status"] == "needs_manager"
        [note] = Notification.objects.filter(kind="request_for_manager")
        assert note.user == shop["manager"]
        assert "Kiedy mam następną zmianę?" in notification_text(note.kind, note.payload)
        # The pilot counts forwarded plain questions against real requests.
        [miss] = [m for m in misses(timezone.now() - timedelta(days=1)) if m[1] == "request"]
        assert miss[5] == "forwarded_answer"

    def test_a_message_never_stays_being_read(self, api, shop, with_key):
        api.login(shop["worker"])
        pk = send_request(api, shop).json()["id"]
        api.login(shop["manager"])
        queued = command(api, shop).json()["id"]
        assert services.fail_stale_messages() == 0
        assert services.fail_stale_messages(timezone.now() + timedelta(minutes=20)) == 2
        row = TextRequest.objects.get(pk=pk)
        assert row.status == "needs_manager" and row.unread_reason == "failed"
        assert AssistantCommand.objects.get(pk=queued).status == "failed"


# ----------------------------------------------------------------- manager: answers and plans


class TestManager:
    def test_the_manager_tools_run_as_the_manager_and_the_answer_is_shown(self, api, shop, with_key, monkeypatch):
        seen = {}

        def fake(text, context, toolbox=None):
            seen.update(context=context, toolbox=toolbox)
            return plan(reply="Dyspozycji nie wysłała jeszcze Kasia.")

        monkeypatch.setattr(llm, "plan_command", fake)
        api.login(shop["manager"])
        created = command(api, shop, "Kto nie wysłał dyspozycji?").json()
        assert services.run_command(created["id"]) == "ready"
        assert seen["toolbox"].user == shop["manager"]
        assert seen["toolbox"].ids["location_id"] == str(shop["location"].pk)
        assert f"period_id={shop['period'].pk}" in seen["context"]
        body = api.get(f"/api/assistant-commands/{created['id']}").json()
        assert body["reply"] == "Dyspozycji nie wysłała jeszcze Kasia." and not body["can_apply"]
        assert AssistantCommand.objects.get(pk=created["id"]).plan["informational"] is True
        assert body["informational"] is True

    def test_an_unrelated_message_gets_app_copy(self, api, shop, with_key, monkeypatch):
        api.login(shop["manager"])
        body = run(api, shop, monkeypatch, plan(scope="out_of_scope", reply="Słonecznie."))
        assert body["reply"] == services.UNRELATED_REPLY and not body["can_apply"] and not body["informational"]

    def test_a_rule_already_set_is_said_so(self, api, shop, with_key, monkeypatch):
        api.login(shop["manager"])
        current = next(
            i
            for i in services._rule_items(
                services.rules_scope(services._SystemContext(shop["company"]), shop["location"])
            )
            if i.code == "max_consecutive_days"
        )
        days = current.params["days"]
        answer = plan(reply="", rule_changes=[rule_change("max_consecutive_days", number=days)])
        body = run(api, shop, monkeypatch, answer)
        assert not body["can_apply"] and body["reply"] == "Nic się nie zmieniło."
        assert body["notes"][0].startswith("To już jest ustawione: „")

    def test_the_effect_is_measured_on_the_schedule_of_the_agreements_period(self, shop):
        later_start = shop["period"].end + timedelta(days=1)
        later = SchedulePeriod.objects.create(
            location=shop["location"], start=later_start, end=later_start + timedelta(days=27)
        )
        own = ScheduleVersion.objects.create(period=shop["period"], number=1, status="published")
        newest = ScheduleVersion.objects.create(period=later, number=6)
        sc = services.rules_scope(services._SystemContext(shop["company"]), shop["location"])
        assert preview_version(sc, shop["location"], shop["period"]) == own
        assert preview_version(sc, shop["location"]) == newest
        empty = SchedulePeriod.objects.create(
            location=shop["location"], start=later.end + timedelta(days=1), end=later.end + timedelta(days=28)
        )
        assert preview_version(sc, shop["location"], empty) == own  # nothing arranged yet: the newest published


def test_plain_descriptions():
    week = {"type": "wolne_dni", "dates": [], "weekdays": [0, 1, 2, 3, 4]}
    assert readings.describe(week, "Grażyna", {}, {}) == "Grażyna: tylko weekendy (wolne od poniedziałku do piątku)"
    days = ["2026-12-14", "2026-12-15", "2026-12-16", "2026-12-17", "2026-12-18", "2026-12-24"]
    assert (
        readings.describe({"type": "wolne_dni", "dates": days}, "Bartosz", {}, {})
        == "Bartosz: wolne 14.12–18.12, 24.12"
    )
    hours = {"type": "limit_godzin", "max_hours": 6, "hours_period": "day"}
    assert readings.describe(hours, "Ania", {}, {}) == "Ania: najwyżej 6 godz. dziennie"
    assert readings.hour_scope(None, "Nie chcę pracować dłużej niż 6 godzin dziennie", 6) == "day"
    assert readings.clean(type="limit_godzin", max_hours=6, hours_period="month", people={}, shift_types={}) is None


@pytest.mark.parametrize("kind", ["request_for_manager"])
def test_new_notification_kinds_have_text(kind):
    assert notification_text(kind, {"employee_name": "Anna", "text": "x", "location_name": "Rynek"}).startswith("Nowa")
