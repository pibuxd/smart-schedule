"""The assistant answers questions about Grafikomat and the location through the app's own API (19.11.2026)."""

import json
import re
from datetime import UTC, datetime, time, timedelta
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
from apps.staffing.models import Position
from tests.test_assistant import command, plan, question, reading, rule_change, run, send_request
from tests.test_assistant import shop as shop
from tests.test_assistant import with_key as with_key


def my_requests(api, shop):
    return api.get(f"/api/me/requests?company_id={shop['company'].pk}&period_id={shop['period'].pk}").json()


def offer(days, **fields):
    """One entry of `cannot_marks` as the API gives it."""
    return {
        "days": [d if isinstance(d, str) else d.isoformat() for d in days],
        "from_time": None,
        "to_time": None,
        "hours": [],
        "windows": [],
        "prefer_days": [],
        "one_shift_days": [],
        "dropped": [],
        "whole_day": False,
        "own": [],
        **fields,
    }


def window(start, end):
    return {"start": start, "end": end}


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

    def test_a_wrong_argument_is_an_error_the_model_can_correct(self, shop):
        """Codex on #48: tools are not strict, and `hours_report` with `employee_name` instead of `person` answered
        about everyone. The call never reaches the endpoint now."""
        api_month = f"{shop['period'].start:%Y-%m}"
        box = tools.manager_toolbox(shop["manager"], shop["company"].pk, shop["location"].pk)
        text, error = box.run("hours_report", {"month": api_month, "employee_name": "Kasia"})
        assert error and text == ("Błąd: nieznany parametr employee_name. To narzędzie przyjmuje: month, person.")
        assert box.run("hours_report", {"person": "Kasia"}) == ("Błąd: brakuje parametru month.", True)
        assert box.run("hours_report", {"month": 11}) == ("Błąd: parametr month musi być typu string.", True)
        assert box.run("hours_report", ["2026-11"])[1]
        assert box.calls == [{"tool": "hours_report", "status": 400}] * 4
        text, error = box.run("hours_report", {"month": api_month, "person": "Kasia"})
        assert not error and box.calls[-1] == {"tool": "hours_report", "status": 200}

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
        # Since 23.11.2026 the assistant works out earnings: pay, hourly rates and supplements reach it (Piotr).
        month = {"month": "2026-12", "hours": 8, "pay": 251.2, "supplements_pay": 12, "unpriced_hours": 0}
        months = {"months": [month]}
        assert tools.clean(months) == months
        settings = {"positions": [{"name": "Kasa", "rates": [{"hourly_rate": 35}]}], "supplements": [{"value": 6}]}
        assert tools.clean(settings) == settings


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
    monkeypatch.setattr(llm, "anthropic_client", lambda: client)


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

    def test_writing_has_no_limits_by_default(self, api, shop, with_key, monkeypatch, settings):
        # Piotr, 20.11.2026: the limits are off unless a number is set in the environment.
        assert settings.TEXT_REQUESTS_PER_PERIOD == settings.ASSISTANT_MESSAGES_PER_DAY == 0
        for n in range(12):
            TextRequest.objects.create(
                employee=shop["employee"], period=shop["period"], text=f"{n}", status="interpreted"
            )
        refused = TextRequest.objects.create(
            employee=shop["employee"], period=shop["period"], text="pogoda", status="rejected"
        )
        for n in range(45):
            TextRequest.objects.create(
                employee=shop["employee"], period=shop["period"], text=f"q{n}", status="answered"
            )
        status, row, _ = read(api, shop, monkeypatch, reading(), "Wolne w piątki")
        assert status == "interpreted" and row.interpretation is not None
        assert str(row.pk) in {r.id for r in build_problem([shop["period"]]).problem.requests}
        assert api.patch(f"/api/me/requests/{refused.pk}", {"understood": False}).status_code == 200

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
        assert mine["cannot_marks"] == [offer(days[1:])]
        # A screen loaded before 26.11.2026 reads only these (it marks them "nie mogę").
        assert mine["unmarked_days"] == [days[1].isoformat(), days[2].isoformat()]
        assert any("„Chętnie”" in note for note in mine["notes"])
        api.client.put(
            "/api/me/calendar",
            {
                "company_id": str(shop["company"].pk),
                "days": [{"date": d, "state": "cannot"} for d in mine["cannot_marks"][0]["days"]],
            },
            content_type="application/json",
        )
        [mine] = my_requests(api, shop)
        assert mine["cannot_marks"] == [] and mine["notes"] == []

    def test_cannot_in_some_hours_marks_the_rest_of_the_day_as_can(self, api, shop, with_key, monkeypatch):
        # "We wtorki nie mogę od 9:00 do 11:00" once became five whole days off (tests 25.11.2026). "Nie mogę" is
        # always a whole day (Piotr, 25.11.2026), so those days get "mogę" (or keep "chętnie") only outside the hours.
        start = shop["period"].start
        days = [start + timedelta(days=n) for n in (0, 7, 14, 21)]
        AvailabilityDay.objects.create(employee=shop["employee"], date=days[0], state="cannot")  # an earlier reading
        AvailabilityDay.objects.create(
            employee=shop["employee"], date=days[2], state="neutral", from_time=time(14), to_time=time(22)
        )
        AvailabilityDay.objects.create(employee=shop["employee"], date=days[3], state="prefer")
        answer = reading(
            weekdays=[], dates=[d.isoformat() for d in days], cannot=True, from_time="9:00", to_time="11:00"
        )
        status, row, _ = read(api, shop, monkeypatch, answer, "We wtorki nie mogę od 9:00 do 11:00.")
        assert status == "interpreted"
        assert (row.interpretation["from_time"], row.interpretation["to_time"]) == ("09:00", "11:00")
        assert row.interpretation["summary"].endswith("„Mogę” tylko do 9:00 i od 11:00 (nie może 9:00–11:00).")
        # Not a wish for the generator: only the calendar keeps it.
        assert str(row.pk) not in {r.id for r in build_problem([shop["period"]]).problem.requests}
        [mine] = my_requests(api, shop)
        rest = [{"start": "00:00", "end": "09:00"}, {"start": "11:00", "end": "00:00"}]
        # The day with "mogę tylko 14–22" is the person's own setting and stays; the whole-day mark may be opened.
        hours = {"from_time": "09:00", "to_time": "11:00", "hours": [window("09:00", "11:00")], "windows": rest}
        assert mine["cannot_marks"] == [
            offer([days[0]], **hours, whole_day=True),
            offer([days[1], days[3]], **hours, prefer_days=[days[3].isoformat()]),
        ]
        assert mine["unmarked_days"] == []  # an old screen would mark them "nie mogę" for the whole day
        assert mine["notes"] == []  # "chętnie" stays, so there is nothing to correct
        refused = api.client.put(
            "/api/me/calendar",
            {
                "company_id": str(shop["company"].pk),
                "days": [{"date": days[1].isoformat(), "state": "cannot", "from_time": "09:00", "to_time": "11:00"}],
            },
            content_type="application/json",
        )
        assert refused.status_code == 400
        saved = api.client.put(
            "/api/me/calendar",
            {
                "company_id": str(shop["company"].pk),
                "days": [
                    {
                        "date": d,
                        "state": "prefer" if d in mark["prefer_days"] else "neutral",
                        "from_time": "00:00",
                        "to_time": "09:00",
                        "from_time_2": "11:00",
                        "to_time_2": "00:00",
                    }
                    for mark in mine["cannot_marks"]
                    for d in mark["days"]
                ],
            },
            content_type="application/json",
        )
        assert saved.status_code == 204, saved.content
        [mine] = my_requests(api, shop)
        assert mine["cannot_marks"] == []
        marked = AvailabilityDay.objects.get(employee=shop["employee"], date=days[0])
        assert (marked.state, marked.from_time, marked.to_time, marked.from_time_2, marked.to_time_2) == (
            "neutral",
            time(0),
            time(9),
            time(11),
            time(0),
        )
        assert AvailabilityDay.objects.get(employee=shop["employee"], date=days[3]).state == "prefer"

    def test_hours_someone_only_prefers_not_to_work_go_to_the_manager(self, api, shop, with_key, monkeypatch):
        start = shop["period"].start
        answer = reading(weekdays=[], dates=[start.isoformat()], cannot=False, from_time="9:00", to_time="11:00")
        status, _, _ = read(api, shop, monkeypatch, answer, "Wolę nie pracować od 9 do 11.")
        assert status == "needs_manager"

    def test_all_the_hours_someone_cannot_work_on_a_day_make_one_offer(self, api, shop, with_key, monkeypatch):
        # Tests of PR #82 (26.11.2026): with 9–11 and 14–16 the same day only the first was offered, so a shift at
        # 14:00 stayed possible. Three windows left do not fit in the calendar's two: the shortest is given up
        # (only hours taken away), and the screen says so.
        day = shop["period"].start + timedelta(days=6)
        answer = reading(weekdays=[], dates=[day.isoformat()], cannot=True, from_time="9:00", to_time="11:00")
        answer.preferences.append(
            reading(weekdays=[], dates=[day.isoformat()], cannot=True, from_time="14:00", to_time="16:00").preferences[
                0
            ]
        )
        status, _, _ = read(api, shop, monkeypatch, answer, "Nie mogę od 9 do 11 i od 14 do 16.")
        assert status == "interpreted"
        [mine] = my_requests(api, shop)
        assert mine["cannot_marks"] == [
            offer(
                [day],
                from_time="09:00",
                to_time="11:00",
                hours=[window("09:00", "11:00"), window("14:00", "16:00")],
                windows=[window("00:00", "09:00"), window("16:00", "00:00")],
                dropped=[window("11:00", "14:00")],
            )
        ]
        # Overlapping hours just join: 9–11 and 10–12 leave "do 9:00 i od 12:00".
        answer = reading(weekdays=[], dates=[day.isoformat()], cannot=True, from_time="9:00", to_time="11:00")
        answer.preferences.append(
            reading(weekdays=[], dates=[day.isoformat()], cannot=True, from_time="10:00", to_time="12:00").preferences[
                0
            ]
        )
        read(api, shop, monkeypatch, answer, "Nie mogę od 9 do 11, a też od 10 do 12.")
        [joined] = [r for r in my_requests(api, shop) if r["text"].endswith("a też od 10 do 12.")]
        [mark] = joined["cannot_marks"]
        assert (mark["windows"], mark["dropped"]) == ([window("00:00", "09:00"), window("12:00", "00:00")], [])

    def test_hours_someone_cannot_work_cut_their_own_hours_only_after_the_button(
        self, api, shop, with_key, monkeypatch
    ):
        # Tests of PR #82 (26.11.2026): with "mogę 8:00–18:00" in the calendar, "nie mogę od 9 do 11" gave no offer
        # and no note, and the generator could still give work at 10:00.
        start = shop["period"].start
        days = [start + timedelta(days=n) for n in (0, 1, 2)]
        own = {"state": "neutral", "from_time": time(8), "to_time": time(18)}
        AvailabilityDay.objects.create(employee=shop["employee"], date=days[0], **own)
        AvailabilityDay.objects.create(
            employee=shop["employee"], date=days[1], state="prefer", from_time=time(14), to_time=time(22)
        )
        AvailabilityDay.objects.create(
            employee=shop["employee"], date=days[2], state="neutral", from_time=time(9), to_time=time(11)
        )
        dates = [d.isoformat() for d in days]
        answer = reading(weekdays=[], dates=dates, cannot=True, from_time="9:00", to_time="11:00")
        read(api, shop, monkeypatch, answer, "Nie mogę od 9 do 11.")
        [mine] = my_requests(api, shop)
        hours = {"from_time": "09:00", "to_time": "11:00", "hours": [window("09:00", "11:00")]}
        # 14–22 keeps clear of 9–11 and stays; only 9–11 left to work means no work that day at all.
        assert mine["cannot_marks"] == [
            offer(
                [days[0]],
                **hours,
                windows=[window("08:00", "09:00"), window("11:00", "18:00")],
                own=[window("08:00", "18:00")],
            ),
            offer([days[2]], **hours, own=[window("09:00", "11:00")]),
        ]
        # The person's own hours stay as they are until the button is pressed.
        kept = AvailabilityDay.objects.get(employee=shop["employee"], date=days[0])
        assert (kept.from_time, kept.to_time, kept.from_time_2) == (time(8), time(18), None)

    def test_hours_someone_cannot_work_last_only_on_weekdays(self, api, shop, with_key, monkeypatch):
        # Piotr, 26.11.2026: such hours on concrete days have no "Na stałe", and the API refuses it.
        answer = reading(
            weekdays=[], dates=[shop["period"].start.isoformat()], cannot=True, from_time="9:00", to_time="11:00"
        )
        _, row, _ = read(api, shop, monkeypatch, answer, "We wtorek nie mogę od 9 do 11.")
        [mine] = my_requests(api, shop)
        assert mine["can_last"] is False
        assert mine["parts"] == [{"summary": row.interpretation["summary"], "calendar_only": True, "can_last": False}]
        refused = api.patch(f"/api/me/requests/{row.pk}", {"lasting": True})
        assert refused.status_code == 409
        assert refused.json()["detail"] == "Ta prośba dotyczy tylko konkretnych dni, więc nie może być na stałe."
        row.refresh_from_db()
        assert row.lasting is False
        # 27.11.2026: on weekdays they may last; each later month offers to mark them in its calendar.
        tuesdays = reading(weekdays=[2], cannot=True, from_time="9:00", to_time="11:00")
        _, row, _ = read(api, shop, monkeypatch, tuesdays, "We wtorki nie mogę od 9 do 11.")
        assert row.status == "interpreted" and row.can_last
        assert api.patch(f"/api/me/requests/{row.pk}", {"lasting": True}).json()["lasting"] is True

    def test_a_mixed_request_lasts_only_in_its_wish_about_a_position(self, api, shop, with_key, monkeypatch):
        # Piotr, 26.11.2026: "w piątki wolę salę, a we wtorki nie mogę od 9 do 11" may last in its position wish;
        # the screen shows which part is only for this period.
        shop["employee"].positions.add(Position.objects.create(location=shop["location"], name="Bar"))
        answer = reading(weekdays=[5], type="stanowisko", position="Bar", rather=True, level="mile_widziane")
        answer.preferences.append(reading(weekdays=[2], cannot=True, from_time="9:00", to_time="11:00").preferences[0])
        _, row, _ = read(api, shop, monkeypatch, answer, "W piątki wolę bar, a we wtorki nie mogę od 9 do 11.")
        [mine] = my_requests(api, shop)
        assert mine["can_last"] is True
        assert mine["parts"] == [
            {
                "summary": "Chętniej stanowisko „Bar” w piątki (inne też mogą być).",
                "calendar_only": False,
                "can_last": True,
            },
            {
                "summary": "We wtorki „Mogę” tylko do 9:00 i od 11:00 (nie może 9:00–11:00).",
                "calendar_only": True,
                "can_last": True,
            },
        ]
        response = api.patch(f"/api/me/requests/{row.pk}", {"lasting": True})
        assert response.status_code == 200 and response.json()["lasting"] is True
        row.refresh_from_db()
        assert row.interpretation["lasting"] is True and row.interpretation["more"][0]["lasting"] is True
        # The next period gets the position wish for the generator, and the hours as an offer for its calendar.
        start = shop["period"].end + timedelta(days=1)
        later = SchedulePeriod.objects.create(
            location=shop["location"],
            start=start,
            end=(start + timedelta(days=32)).replace(day=1) - timedelta(days=1),
            availability_requested_at=timezone.now(),
        )
        [carried] = build_problem([later]).problem.requests
        assert carried.id == str(row.pk) and carried.type == "position"
        [there] = api.get(f"/api/me/requests?company_id={shop['company'].pk}&period_id={later.pk}").json()
        assert there["carried_from"] == shop["period"].start.isoformat()
        tuesdays = [later.start + timedelta(days=n) for n in range((later.end - later.start).days + 1)]
        [mark] = there["cannot_marks"]
        assert mark["days"] == [d.isoformat() for d in tuesdays if d.weekday() == 1]
        assert [(w["start"], w["end"]) for w in mark["windows"]] == [("00:00", "09:00"), ("11:00", "00:00")]
        # Ended from that period, it offers nothing there.
        api.post(
            f"/api/me/requests/{row.pk}/end",
            {"company_id": str(shop["company"].pk), "period_id": str(later.pk), "ended": True},
        )
        [there] = api.get(f"/api/me/requests?company_id={shop['company'].pk}&period_id={later.pk}").json()
        assert there["ended"] is True and there["cannot_marks"] == []

    def test_weekdays_of_the_period_someone_cannot_work_in_some_hours_count_as_days(
        self, api, shop, with_key, monkeypatch
    ):
        # Retest 26.11.2026: next to "w piątki wolę salę" the model gave the Tuesdays as weekdays, not dates, and the
        # whole message went to the manager without an answer.
        shop["employee"].positions.add(Position.objects.create(location=shop["location"], name="Bar"))
        period = shop["period"]
        days = [period.start + timedelta(days=n) for n in range((period.end - period.start).days + 1)]
        fridays = [d.isoformat() for d in days if d.weekday() == 4]
        tuesdays = [d.isoformat() for d in days if d.weekday() == 1]
        answer = reading(
            weekdays=[5], dates=fridays, type="stanowisko", position="Bar", rather=True, level="mile_widziane"
        )
        answer.preferences.append(reading(weekdays=[2], cannot=True, from_time="9:00", to_time="11:00").preferences[0])
        text = "W piątki wolę bar, a we wtorki nie mogę od 9:00 do 11:00."
        status, row, _ = read(api, shop, monkeypatch, answer, text)
        assert status == "interpreted"
        # The Fridays listed next to "w piątki" say nothing more.
        assert row.interpretation["summary"] == (
            "Chętniej stanowisko „Bar” w piątki (inne też mogą być); "
            "we wtorki „Mogę” tylko do 9:00 i od 11:00 (nie może 9:00–11:00)."
        )
        [mark] = my_requests(api, shop)[0]["cannot_marks"]
        assert mark["days"] == tuesdays and not mark["whole_day"]
        # Every Tuesday for good (27.11.2026): saved as lasting, its days offered in each month.
        for_good = reading(weekdays=[2], cannot=True, from_time="9:00", to_time="11:00", lasting=True)
        status, row, _ = read(api, shop, monkeypatch, for_good, "Na stałe we wtorki nie mogę od 9 do 11.")
        assert status == "interpreted" and row.lasting and row.interpretation["cannot"] is True

    def test_rather_a_position_is_not_only_that_position(self, api, shop, with_key, monkeypatch):
        second = Position.objects.create(location=shop["location"], name="Bar")
        shop["employee"].positions.add(second)
        answer = reading(weekdays=[5], type="stanowisko", position="Bar", rather=True, level="mile_widziane")
        status, row, _ = read(api, shop, monkeypatch, answer, "W piątki wolę pracować na barze.")
        assert status == "interpreted" and row.interpretation["rather"] is True
        assert row.interpretation["summary"] == "Chętniej stanowisko „Bar” w piątki (inne też mogą być)."
        only = reading(weekdays=[5], type="stanowisko", position="Bar", level="wazne")
        status, row, _ = read(api, shop, monkeypatch, only, "W piątki tylko bar.")
        assert row.interpretation["summary"] == "Tylko stanowisko „Bar” w piątki."

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
    nights = {"type": "limit_zmian", "max_shifts": 3, "hours_period": "week", "shift_type": "n1"}
    assert (
        readings.describe(nights, "Roman", {}, {"n1": "Nocna"}) == "Roman: najwyżej 3 zmiany „Nocna” w każdym tygodniu"
    )
    one = {"type": "limit_zmian", "max_shifts": 1, "hours_period": "day"}
    assert readings.describe(one, "Ewa", {}, {}) == "Ewa: najwyżej 1 zmiana dziennie"
    five = {"type": "limit_zmian", "max_shifts": 5, "hours_period": "period"}
    assert readings.describe(five, "Ewa", {}, {}) == "Ewa: najwyżej 5 zmian w okresie grafiku"
    closing = {"type": "unikaj_osoby", "subject_employee": "z1", "shift_type": "c1"}
    assert (
        readings.describe(closing, "Natalia", {"z1": "Zuzanna"}, {"c1": "Popołudniowa"})
        == "Natalia i Zuzanna: nie razem na zmianie „Popołudniowa”"
    )
    shifts = {"Nocna": "n1"}
    assert readings.clean(type="limit_zmian", max_shifts=None, people={}, shift_types=shifts) is None
    assert readings.clean(type="limit_zmian", max_shifts=-1, people={}, shift_types=shifts) is None
    assert readings.clean(type="limit_zmian", max_shifts=3, shift_type="Dzienna", people={}, shift_types=shifts) is None
    assert readings.clean(type="limit_godzin", max_hours=6, max_shifts=3, people={}, shift_types={}) is None


def test_an_hours_target_is_about_this_many_hours_rather_on_some_days():
    """ "W pierwszym tygodniu chcę wyrobić 30 godzin, najlepiej pod koniec tygodnia" (Piotr, 26.11)."""

    def clean(**kwargs):
        return readings.clean(type="cel_godzin", people={}, shift_types={}, **kwargs)

    week = [f"2027-02-0{d}" for d in range(1, 8)]
    first = clean(target_hours=30, hours_period="week", dates=week, prefer_weekdays=[4, 5, 6, 7])
    assert first == {
        "type": "cel_godzin",
        "dates": week,
        "weekdays": [],
        "target_hours": 30.0,
        "hours_period": "week",
        "prefer_weekdays": [3, 4, 5, 6],
    }
    assert (
        readings.describe(first, "Ola", {}, {})
        == "Ola: około 30 godz. w tygodniu 1.02–7.02, najlepiej od czwartku do niedzieli"
    )
    every_week = clean(target_hours=20, hours_period="week", prefer_weekdays=[6, 7])
    assert readings.describe(every_week, "Ola", {}, {}) == "Ola: około 20 godz. w każdym tygodniu, najlepiej w weekendy"
    month = clean(target_hours=120)
    assert (
        "prefer_weekdays" not in month
        and readings.describe(month, "Ola", {}, {}) == "Ola: około 120 godz. w okresie grafiku"
    )
    assert "prefer_weekdays" not in clean(target_hours=20, prefer_weekdays=list(range(1, 8)))  # every day: no wish
    at_least = clean(target_hours=16, hours_period="week", at_least=True)
    assert at_least["at_least"] is True and "at_least" not in clean(target_hours=16, at_least=False)
    assert readings.describe(at_least, "Ola", {}, {}) == "Ola: co najmniej 16 godz. w każdym tygodniu"
    assert readings.clean(type="limit_godzin", max_hours=20, at_least=True, people={}, shift_types={}) is None
    assert clean(target_hours=0) is None and clean(target_hours=None) is None
    assert clean(target_hours=200, hours_period="week") is None and clean(target_hours=25, hours_period="day") is None
    assert clean(target_hours=20, prefer_weekdays=[8]) is None
    assert readings.clean(type="limit_godzin", max_hours=20, target_hours=20, people={}, shift_types={}) is None
    assert readings.clean(type="wolne_dni", weekdays=[1], prefer_weekdays=[2], people={}, shift_types={}) is None
    assert readings.hour_scope("period", "Chcę wyrobić 30 godzin w tygodniu", 30) == "week"
    # A model on OpenRouter may write null for the fields of other types.
    limit = reading(type="limit_godzin", max_hours=8).preferences[0].model_dump()
    nulls = llm.Preference.model_validate(
        {**limit, "target_hours": None, "prefer_weekdays": None, "hours_meaning": None}
    )
    assert (nulls.target_hours, nulls.prefer_weekdays, nulls.hours_meaning) == (0, [], "unsaid")


def test_days_off_may_name_hours():
    def clean(**kwargs):
        return readings.clean(type="wolne_dni", weekdays=[2], people={}, shift_types={}, **kwargs)

    assert clean(from_time="9:00", to_time="11.00") == {
        "type": "wolne_dni",
        "dates": [],
        "weekdays": [1],
        "from_time": "09:00",
        "to_time": "11:00",
    }
    assert clean(from_time="18:00")["from_time"] == "18:00" and "to_time" not in clean(from_time="18:00")
    assert "from_time" not in clean(to_time="24:00") and "to_time" not in clean(to_time="24:00")  # the whole day
    assert clean(from_time="18:00", to_time="24:00") == clean(from_time="18:00")
    assert clean(from_time="9:00", to_time="9:00") is None  # an empty window
    assert clean(from_time="dziewiąta") is None
    assert readings.clean(type="limit_godzin", max_hours=6, from_time="9:00", people={}, shift_types={}) is None
    morning = {"type": "wolne_dni", "weekdays": [1], "from_time": "09:00", "to_time": "11:00", "cannot": True}
    assert readings.calendar_only(morning) and not readings.calendar_only(
        {**morning, "from_time": None, "to_time": None}
    )
    assert readings.describe(morning, "Borys", {}, {}) == (
        "Borys: we wtorki „Mogę” tylko do 9:00 i od 11:00 (nie może 9:00–11:00)"
    )
    assert readings.describe({**morning, "to_time": None}, "Ola", {}, {}) == (
        "Ola: we wtorki „Mogę” tylko do 9:00 (nie może od 9:00)"
    )


@pytest.mark.parametrize(
    ("hours", "rest"),
    [
        (("09:00", "11:00"), [("00:00", "09:00"), ("11:00", "00:00")]),
        (("18:00", None), [("00:00", "18:00")]),
        ((None, "10:00"), [("10:00", "00:00")]),
        (("22:00", "06:00"), [("06:00", "22:00")]),  # overnight
    ],
)
def test_the_rest_of_the_day_outside_hours_someone_cannot_work(hours, rest):
    from datetime import time as clock
    from importlib import import_module

    data = {"type": "wolne_dni", "from_time": hours[0], "to_time": hours[1]}
    assert readings.complement(data) == rest
    # The migration that turned saved "nie mogę" in some hours into "mogę" in the rest of the day agrees.
    migration = import_module("apps.availability.migrations.0014_cannot_whole_day")
    as_time = [clock.fromisoformat(value) if value else None for value in hours]
    assert migration.rest_of_day(*as_time) == [(clock.fromisoformat(a), clock.fromisoformat(b)) for a, b in rest]


@pytest.mark.parametrize("kind", ["request_for_manager"])
def test_new_notification_kinds_have_text(kind):
    assert notification_text(kind, {"employee_name": "Anna", "text": "x", "location_name": "Rynek"}).startswith("Nowa")
