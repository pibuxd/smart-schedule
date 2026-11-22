"""What the assistant costs, per company, location and person (docs/plan.md section 38)."""

import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import User
from apps.assistant import costs, llm, services
from apps.assistant.models import AssistantUsage
from apps.availability.models import TextRequest
from apps.scheduling.models import GenerationRun, SchedulePeriod
from apps.tenancy.models import Location, LocationGroup
from tests.test_assistant import command, plan, reading, send_request
from tests.test_assistant import shop as shop
from tests.test_assistant import with_key as with_key
from tests.test_assistant_openrouter import READ, StubBox, answer, chat
from tests.test_assistant_openrouter import fake_openrouter as fake_openrouter

MONTH = date(2026, 11, 1)


def at(day: int, hour: int = 12) -> datetime:
    return timezone.make_aware(datetime(2026, 11, day, hour))


# ----------------------------------------------------------------- what one answer cost


class TestTracking:
    def test_every_round_adds_its_tokens_and_dollars(self, fake_openrouter):
        fake_openrouter(
            chat(calls=[READ], provider="Alibaba", cost=0.00012),
            chat(calls=[answer(reading())], provider="InferenceNet", cost=0.0003),
        )
        usage = llm.Usage()
        with llm.tracking(usage):
            llm.read_request("Kiedy pracuję?", "Okres: …", StubBox())
        assert (usage.backend, usage.model) == ("openrouter", llm.settings.OPENROUTER_MODEL)
        assert usage.calls == 2 and usage.providers == ["Alibaba", "InferenceNet"]
        assert (usage.input_tokens, usage.output_tokens) == (200, 20)
        assert usage.cost == Decimal("0.00042") and not usage.failed

    def test_an_answer_that_fails_still_counts_what_it_cost(self, fake_openrouter):
        fake_openrouter(chat(calls=[(llm.ANSWER_TOOL, {"preferences": "zła"})], cost=0.001))
        usage = llm.Usage()
        with pytest.raises(llm.AssistantError), llm.tracking(usage):
            llm.read_request("x", "y")
        assert usage.failed and usage.calls == llm.MAX_TOOL_ROUNDS + 1
        assert usage.cost == Decimal("0.001") * (llm.MAX_TOOL_ROUNDS + 1)

    def test_without_tracking_nothing_is_collected_and_the_answer_is_the_same(self, fake_openrouter):
        fake_openrouter(chat(calls=[answer(reading())]))
        assert llm.read_request("x", "y") == reading()

    def test_claude_gives_tokens_but_no_price(self, settings, monkeypatch):
        import httpx2
        from anthropic import Anthropic, DefaultHttpxClient

        settings.ANTHROPIC_API_KEY = "test-key"
        body = {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": settings.ANTHROPIC_MODEL,
            "content": [{"type": "text", "text": reading().model_dump_json()}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 7},
        }
        transport = httpx2.MockTransport(lambda request: httpx2.Response(200, json=body))
        client = Anthropic(api_key="test-key", http_client=DefaultHttpxClient(transport=transport))
        monkeypatch.setattr(llm, "anthropic_client", lambda: client)
        usage = llm.Usage()
        with llm.tracking(usage):
            llm.read_request("x", "y")
        assert (usage.backend, usage.calls, usage.input_tokens, usage.output_tokens) == ("anthropic", 1, 100, 7)
        assert usage.cost is None


# ----------------------------------------------------------------- one row per message


class TestRecording:
    def test_an_employee_message_is_charged_to_the_person_and_the_period_location(self, api, shop, fake_openrouter):
        fake_openrouter(chat(calls=[answer(reading())], provider="Alibaba", cost=0.0021))
        api.login(shop["worker"])
        request_id = send_request(api, shop).json()["id"]
        assert services.interpret_request(request_id) == "interpreted"
        usage = AssistantUsage.objects.get()
        assert usage.kind == AssistantUsage.Kind.EMPLOYEE and str(usage.message_id) == request_id
        assert (usage.company, usage.location, usage.user) == (shop["company"], shop["location"], shop["worker"])
        assert usage.cost_usd == Decimal("0.0021") and usage.calls == 1 and usage.providers == "Alibaba"
        assert not usage.failed and usage.model == llm.settings.OPENROUTER_MODEL

    def test_a_month_request_goes_to_the_home_location(self, api, shop, fake_openrouter):
        fake_openrouter(chat(calls=[answer(reading())]))
        api.login(shop["worker"])
        month = (shop["period"].start + timedelta(days=40)).replace(day=1)
        created = api.post(
            "/api/me/requests", {"company_id": str(shop["company"].pk), "month": str(month), "text": "Nie w piątki."}
        ).json()
        services.interpret_request(created["id"])
        assert TextRequest.objects.get(pk=created["id"]).period_id is None
        assert AssistantUsage.objects.get().location == shop["employee"].home_location

    def test_a_failed_manager_message_is_charged_too(self, api, shop, fake_openrouter):
        error = {"id": "gen-1", "object": "chat.completion", "created": 0, "model": "m", "provider": "Fake"}
        fake_openrouter({**error, "error": {"message": "upstream"}, "usage": {"prompt_tokens": 50, "cost": 0.0004}})
        api.login(shop["manager"])
        created = command(api, shop).json()
        assert services.run_command(created["id"]) == "failed"
        usage = AssistantUsage.objects.get()
        assert usage.kind == AssistantUsage.Kind.MANAGER and usage.failed
        assert (usage.location, usage.user, usage.cost_usd) == (shop["location"], shop["manager"], Decimal("0.0004"))

    def test_a_message_changed_while_the_model_read_it_is_still_charged(self, api, shop, fake_openrouter, monkeypatch):
        fake_openrouter(chat(calls=[answer(reading())], cost=0.002))
        api.login(shop["worker"])
        request_id = send_request(api, shop).json()["id"]
        read = llm.read_request

        def edited_meanwhile(text, context, toolbox=None):
            result = read(text, context, toolbox)
            TextRequest.objects.filter(pk=request_id).update(text="Jednak w soboty.")
            return result

        monkeypatch.setattr(llm, "read_request", edited_meanwhile)
        assert services.interpret_request(request_id) == "skipped"  # the newer job reads the new text
        assert AssistantUsage.objects.get().cost_usd == Decimal("0.002")

    def test_nothing_is_saved_when_no_answer_came_back(self, api, shop, with_key, monkeypatch):
        monkeypatch.setattr(llm, "plan_command", lambda text, context, toolbox=None: plan())
        api.login(shop["manager"])
        assert services.run_command(command(api, shop).json()["id"]) == "ready"
        assert not AssistantUsage.objects.exists()

    def test_a_cost_that_cannot_be_saved_does_not_lose_the_answer(self, api, shop, fake_openrouter, monkeypatch):
        fake_openrouter(chat(calls=[answer(reading())]))

        def broken(*args, **kwargs):
            raise RuntimeError("database")

        monkeypatch.setattr(AssistantUsage.objects, "for_company", broken)
        api.login(shop["worker"])
        request_id = send_request(api, shop).json()["id"]
        assert services.interpret_request(request_id) == "interpreted"


# ----------------------------------------------------------------- the month's summary


def usage(company, location, user, kind, cost, *, when=None, failed=False):
    return AssistantUsage.objects.create(
        company=company,
        location=location,
        user=user,
        kind=kind,
        message_id="6a1e0000-0000-4000-8000-000000000001",
        backend="openrouter" if cost is not None else "anthropic",
        model="m",
        calls=1,
        input_tokens=100,
        output_tokens=10,
        cost_usd=None if cost is None else Decimal(cost),
        failed=failed,
        duration_ms=1000,
        created_at=when or at(10),
    )


def generation(location, user, seconds, *, periods=(), group=None, day=10, started=True):
    run = GenerationRun.objects.create(
        company=(group or location).company,
        location=None if group else location,
        group=group,
        requested_by=user,
        created_at=at(day),
        started_at=at(day) if started else None,
        time_ms=seconds * 1000,
    )
    run.periods.add(*periods)
    return run


@pytest.fixture
def month_data(shop, make_company):
    """Two locations of one company (a group), a second company, and a month of messages and arranging."""
    company, first, manager, worker = shop["company"], shop["location"], shop["manager"], shop["worker"]
    group = LocationGroup.objects.create(company=company, name="Miasto")
    second = Location.objects.create(company=company, name="Drugi lokal", group=group)
    first.group = group
    first.save()
    p1 = shop["period"]
    p2 = SchedulePeriod.objects.create(location=second, start=p1.start, end=p1.end)
    kasia = shop["kasia"].membership.user
    E, M = AssistantUsage.Kind.EMPLOYEE, AssistantUsage.Kind.MANAGER
    usage(company, first, worker, E, "0.001")
    usage(company, first, worker, E, "0.002", failed=True)
    usage(company, second, kasia, E, "0.0005")
    usage(company, first, manager, M, "0.004")
    usage(company, second, manager, M, None)  # Claude: no price
    usage(company, first, worker, E, "0.5", when=timezone.make_aware(datetime(2026, 10, 31, 23, 30)))  # October
    generation(first, manager, 120, periods=[p1])
    generation(None, manager, 60, periods=[p1, p2], group=group)
    generation(first, manager, 999, periods=[p1], started=False)  # queued and cancelled: never ran
    other = make_company("Inna firma")
    usage(other["company"], other["location"], other["manager"], M, "0.01")
    return {"company": company, "first": first, "second": second, "kasia": kasia, "other": other}


class TestSummary:
    def test_per_company(self, shop, month_data):
        lines = {line.company: line for line in costs.summary(MONTH, "company")}
        mine = lines["Złoty Kłos"]
        assert (mine.employee_messages, mine.employee_cost) == (3, Decimal("0.0035"))
        assert (mine.manager_messages, mine.manager_cost) == (2, Decimal("0.004"))
        assert mine.cost == Decimal("0.0075") and mine.failed == 1 and mine.unpriced == 1
        assert (mine.arrangings, mine.solver_minutes) == (2, 3.0)
        assert lines["Inna firma"].cost == Decimal("0.01") and lines["Inna firma"].arrangings == 0

    def test_per_location_a_group_run_counts_in_each_location_and_shares_its_time(self, shop, month_data):
        lines = {line.location: line for line in costs.summary(MONTH, "location")}
        first, second = lines[month_data["first"].name], lines["Drugi lokal"]
        assert (first.employee_messages, first.manager_messages, first.cost) == (2, 1, Decimal("0.007"))
        assert (second.employee_messages, second.manager_messages, second.cost) == (1, 1, Decimal("0.0005"))
        assert (first.arrangings, first.solver_seconds) == (2, 150)
        assert (second.arrangings, second.solver_seconds) == (1, 30)

    def test_per_person_a_manager_has_chat_and_arranging_apart(self, shop, month_data):
        lines = {(line.company, line.person): line for line in costs.summary(MONTH, "person")}
        manager = lines[("Złoty Kłos", str(shop["manager"]))]
        assert manager.role == "właściciel" and manager.manager_messages == 2 and manager.employee_messages == 0
        assert manager.cost == Decimal("0.004") and (manager.arrangings, manager.solver_minutes) == (2, 3.0)
        worker = lines[("Złoty Kłos", str(shop["worker"]))]
        assert worker.role == "pracownik" and (worker.employee_messages, worker.cost) == (2, Decimal("0.003"))
        assert worker.arrangings == 0

    def test_a_deleted_person_or_location_keeps_the_cost(self, shop, month_data):
        month_data["kasia"].delete()
        SchedulePeriod.objects.filter(location=month_data["second"]).delete()
        month_data["second"].delete()
        people = {line.person: line.cost for line in costs.summary(MONTH, "person")}
        assert people[costs.NO_PERSON] == Decimal("0.0005")
        places = {line.location: line.cost for line in costs.summary(MONTH, "location")}
        assert places[costs.NO_LOCATION] == Decimal("0.0005")

    def test_the_total_counts_a_group_run_once(self, shop, month_data):
        whole = costs.total(MONTH)
        assert whole.cost == Decimal("0.0175") and whole.messages == 6 and whole.arrangings == 2

    def test_other_months_are_left_out(self, shop, month_data):
        assert costs.summary(date(2026, 10, 1), "company")[0].cost == Decimal("0.5")
        assert costs.summary(date(2026, 12, 1), "company") == []


class TestCsvAndAdmin:
    def test_the_command_writes_one_line_per_person_and_a_total(self, shop, month_data):
        out = io.StringIO()
        call_command("assistant_costs", "--month", "2026-11", "--by", "person", stdout=out)
        rows = list(csv.reader(io.StringIO(out.getvalue())))
        assert rows[0][:3] == ["company", "person", "role"] and "total_cost_usd" in rows[0]
        assert rows[-1][0] == "Razem" and rows[-1][rows[0].index("total_cost_usd")] == "0.017500"
        assert len(rows) == 2 + 4  # header, manager, worker, Kasia, other company's manager, total

    def test_a_wrong_month_is_refused(self, db):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            call_command("assistant_costs", "--month", "listopad", stdout=io.StringIO())

    def test_the_superadmin_sees_the_month_and_downloads_csv(self, client, shop, month_data):
        client.force_login(User.objects.create_superuser("+48500999998", "haslo-testowe-123"))
        page = client.get("/api/admin/assistant/assistantusage/summary/?month=2026-11")
        assert page.status_code == 200
        text = page.content.decode()
        assert "Złoty Kłos" in text and "Drugi lokal" in text and str(shop["manager"]) in text
        listing = client.get("/api/admin/assistant/assistantusage/")
        assert "Zestawienie miesiąca" in listing.content.decode()
        download = client.get("/api/admin/assistant/assistantusage/summary/?month=2026-11&csv=location")
        assert download["Content-Type"].startswith("text/csv")
        assert "koszty-asystenta-2026-11-location.csv" in download["Content-Disposition"]

    def test_people_of_a_company_never_see_costs(self, client, shop, month_data):
        client.force_login(shop["manager"])
        response = client.get("/api/admin/assistant/assistantusage/summary/")
        assert response.status_code == 302  # to the admin login
