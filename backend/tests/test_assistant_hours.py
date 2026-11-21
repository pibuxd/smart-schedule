# ruff: noqa: F811  (the `bakery` fixture is imported from test_worktime)
"""The assistant and other hours of a published shift: an employee's message becomes a report to send with one
button, and the manager's message approves, rejects or sets hours once the manager accepts the plan."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.assistant import llm, services, tools
from apps.assistant.models import AssistantCommand, AssistantRuleSet
from apps.availability.models import TextRequest
from apps.notifications.models import Notification
from apps.scheduling.models import SchedulePeriod
from apps.worktime.models import HoursChange
from apps.worktime.services import SAME_HOURS, TOO_OLD
from tests.test_worktime import bakery, hours_of, report, user_of  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


@pytest.fixture
def with_key(settings):
    settings.OPENROUTER_API_KEY = "test-key"


def day_words(day) -> str:
    return f"{('pon.', 'wt.', 'śr.', 'czw.', 'pt.', 'sob.', 'niedz.')[day.weekday()]} {day:%d.%m}"


# ----------------------------------------------------------------------------------------------- the employee


def employee_reply(*hours: llm.HoursReport, answer: str = "", preferences=()) -> llm.EmployeeReply:
    return llm.EmployeeReply(
        topic="app",
        answer=answer,
        preferences=list(preferences),
        leave_to_manager=False,
        replaces_request=None,
        hours_changes=list(hours),
    )


def hours(day, start="", end="", reason="") -> llm.HoursReport:
    return llm.HoursReport(date=day.isoformat(), start_time=start, end_time=end, reason=reason)


def write(api, b, monkeypatch, reply, text="Źle się czuję, wyjdę dziś o 11.", who=None):
    """The employee writes in the chat; the worker reads the message with the given answer of the model."""
    seen = {}

    def fake(text, context, toolbox=None):
        seen["context"] = context
        return reply

    monkeypatch.setattr(llm, "read_request", fake)
    api.login(user_of(who or b["ola"]))
    month = b["today"].replace(day=1)
    sent = api.post("/api/me/requests", {"company_id": str(b["company"].pk), "month": str(month), "text": text})
    assert sent.status_code == 201, sent.json()
    services.interpret_request(sent.json()["id"])
    [row] = [
        r
        for r in api.get(f"/api/me/requests?company_id={b['company'].pk}&month={month}").json()
        if r["id"] == sent.json()["id"]
    ]
    return row, seen


class TestEmployeeChat:
    def test_a_report_from_the_chat_is_sent_only_with_the_button(self, api, bakery, with_key, monkeypatch):
        b = bakery
        shift = b["shift"](b["ola"], b["today"])

        row, seen = write(api, b, monkeypatch, employee_reply(hours(b["today"], end="11:00", reason="źle się czuje")))

        assert "Teraz: " in seen["context"]  # "wychodzę teraz" needs the location's clock
        assert row["status"] == "answered" and row["reply"] == services.HOURS_READY_REPLY
        [proposal] = row["hours_reports"]
        assert proposal["assignment_id"] == str(shift.pk) and proposal["sent_status"] is None
        assert (proposal["start_time"], proposal["end_time"]) == ("06:00", "11:00")  # empty start = unchanged
        assert proposal["difference_minutes"] == -180 and proposal["reason"] == "źle się czuje"
        assert not HoursChange.objects.exists()  # nothing goes to the manager by itself
        assert TextRequest.objects.get().status == TextRequest.Status.ANSWERED  # and it is no request either

        sent = api.post(
            "/api/me/hours-changes",
            {
                "assignment_id": proposal["assignment_id"],
                "start_time": proposal["start_time"],
                "end_time": proposal["end_time"],
                "reason": proposal["reason"],
                "request_id": row["id"],
            },
        )

        assert sent.status_code == 201, sent.json()
        change = HoursChange.objects.get()
        assert change.source_request_id is not None and str(change.source_request_id) == row["id"]
        month = b["today"].replace(day=1)
        listed = api.get(f"/api/me/requests?company_id={b['company'].pk}&month={month}").json()
        assert listed[0]["hours_reports"][0]["sent_status"] == "pending"

        api.login(b["manager"])
        assert api.post(f"/api/hours-changes/{change.pk}/approve").status_code == 200
        api.login(user_of(b["ola"]))
        listed = api.get(f"/api/me/requests?company_id={b['company'].pk}&month={month}").json()
        assert listed[0]["hours_reports"][0]["sent_status"] == "approved"

    def test_reports_the_app_cannot_send_are_explained_not_prepared(self, api, bakery, with_key, monkeypatch):
        b = bakery
        old = b["today"] - timedelta(days=20)
        b["shift"](b["ola"], old)
        b["shift"](b["ola"], b["today"])
        free = b["today"] + timedelta(days=2)

        row, _ = write(
            api,
            b,
            monkeypatch,
            employee_reply(
                hours(old, end="16:00"),
                hours(free, end="16:00"),
                hours(b["today"], "06:00", "14:00"),
                hours(b["today"], "6 rano", "14:00"),
            ),
        )

        assert row["status"] == "answered" and row["hours_reports"] == []
        reply = row["reply"]
        assert f"na {day_words(old)}: {TOO_OLD[:1].lower()}{TOO_OLD[1:]}" in reply
        assert f"na {day_words(free)}: nie widzę Twojej zmiany tego dnia" in reply
        assert SAME_HOURS[:1].lower() + SAME_HOURS[1:] in reply
        assert "najwyżej 3 zgłoszenia" in reply  # the fourth is not even read
        assert not HoursChange.objects.exists()

    def test_a_preference_and_a_report_in_one_message_are_both_kept(self, api, bakery, with_key, monkeypatch):
        b = bakery
        b["shift"](b["ola"], b["today"])
        free_saturdays = llm.Preference(
            type="wolne_dni",
            person=None,
            shift_type=None,
            avoid_shift_type=False,
            max_hours=None,
            max_shifts=None,
            hours_period="period",
            min_days=None,
            shifts_per_day=None,
            dates=[],
            weekdays=[5],
            cannot=False,
            level="wazne",
            confidence=0.9,
        )

        row, _ = write(
            api,
            b,
            monkeypatch,
            employee_reply(hours(b["today"], end="15:00"), preferences=[free_saturdays]),
            text="Zostanę dziś do 15. I wolałabym wolne piątki.",
        )

        assert row["status"] == "interpreted" and "piątki" in row["summary"]
        assert [(p["end_time"], p["difference_minutes"]) for p in row["hours_reports"]] == [("15:00", 60)]

    def test_a_message_of_someone_else_cannot_be_the_source(self, api, bakery, with_key, monkeypatch):
        b = bakery
        shift = b["shift"](b["ola"], b["today"])
        b["shift"](b["ewa"], b["today"])
        row, _ = write(api, b, monkeypatch, employee_reply(hours(b["today"], end="13:00")), who=b["ewa"])

        api.login(user_of(b["ola"]))
        sent = api.post(
            "/api/me/hours-changes",
            {"assignment_id": str(shift.pk), "start_time": "06:00", "end_time": "13:00", "request_id": row["id"]},
        )

        assert sent.status_code == 404 and not HoursChange.objects.exists()


# ----------------------------------------------------------------------------------------------- the manager


def manager_plan(**changes) -> llm.CommandPlan:
    values = {
        "topic": "app",
        "reply": "Gotowe.",
        "question": None,
        "rule_changes": [],
        "new_instructions": [],
        "remove_instructions": [],
    }
    return llm.CommandPlan(**{**values, **changes})


def set_hours(person, day, start="", end="", reason="") -> llm.HoursSet:
    return llm.HoursSet(person=person, date=day.isoformat(), start_time=start, end_time=end, reason=reason)


def ask(api, b, monkeypatch, answer, text="Ewa wyszła dziś o 12, źle się czuła."):
    """The manager writes; the worker plans with the given answer of the model."""
    seen = {}

    def fake(text, context, toolbox=None):
        seen["context"] = context
        return answer

    monkeypatch.setattr(llm, "plan_command", fake)
    api.login(b["manager"])
    created = api.post(f"/api/locations/{b['location'].pk}/assistant-commands", {"text": text})
    assert created.status_code == 201, created.json()
    assert services.run_command(created.json()["id"]) == "ready"
    return api.get(f"/api/assistant-commands/{created.json()['id']}").json(), seen


def next_period(b):
    """The manager asked for availability for the next period: the chat's agreements belong to it."""
    return SchedulePeriod.objects.create(
        location=b["location"],
        start=b["period"].end + timedelta(days=1),
        end=b["period"].end + timedelta(days=30),
        availability_requested_at=timezone.now(),
    )


def kinds(kind):
    return [n.user_id for n in Notification.objects.filter(kind=kind)]


class TestManagerChat:
    def test_waiting_reports_are_numbered_and_decided_from_the_chat(self, api, bakery, with_key, monkeypatch):
        b = bakery
        yesterday = b["today"] - timedelta(days=1)
        ola = b["shift"](b["ola"], yesterday)
        ewa = b["shift"](b["ewa"], b["today"])
        assert report(api, b, ola, "06:00", "15:00", "Dostawa").status_code == 201
        assert report(api, b, ewa, "06:00", "12:00", who=b["ewa"]).status_code == 201

        answer = manager_plan(
            hours_decisions=[llm.HoursDecision(report=1, approve=True), llm.HoursDecision(report=2, approve=False)]
        )
        body, seen = ask(api, b, monkeypatch, answer, text="Zatwierdź nadgodziny Oli, a Ewie odrzuć.")

        context = seen["context"]
        assert "Zgłoszenia innych godzin czekające na decyzję" in context
        assert f"1. Pracownik, {day_words(yesterday)}, 06:00–15:00 zamiast 06:00–14:00" in context
        assert "Powód: Dostawa." in context
        assert f"2. Ewa Nowak, {day_words(b['today'])}, 06:00–12:00 zamiast 06:00–14:00 (krócej o 2 h)" in context
        assert body["lines"] == [
            f"Zatwierdzę zgłoszenie: Pracownik, {day_words(yesterday)}, 06:00–15:00 zamiast 06:00–14:00 "
            "(nadgodziny: +1 h).",
            f"Odrzucę zgłoszenie: Ewa Nowak, {day_words(b['today'])}, 06:00–12:00 zamiast 06:00–14:00 (krócej o 2 h).",
        ]
        assert body["notes"] == [services.HOURS_NOTE]
        assert body["can_apply"] and body["has_hours"] and body["hours_only"]
        assert set(HoursChange.objects.values_list("status", flat=True)) == {"pending"}  # nothing before accepting

        applied = api.post(f"/api/assistant-commands/{body['id']}/apply")

        assert applied.status_code == 200 and applied.json()["status"] == "applied"
        assert HoursChange.objects.get(employee=b["ola"]).status == "approved"
        assert HoursChange.objects.get(employee=b["ewa"]).status == "rejected"
        assert kinds("hours_approved") == [user_of(b["ola"]).pk] and kinds("hours_rejected") == [user_of(b["ewa"]).pk]
        assert hours_of(api, b, yesterday, "Pracownik")["total"] == 9

    def test_the_manager_sets_hours_and_it_still_works_once_the_period_is_published(
        self, api, bakery, with_key, monkeypatch
    ):
        b = bakery
        b["shift"](b["ewa"], b["today"])
        next_period(b)
        body, seen = ask(api, b, monkeypatch, manager_plan(hours_changes=[set_hours("Ewa", b["today"], end="12:00")]))

        assert "Teraz: " in seen["context"] and "(brak)" in seen["context"].split("Zgłoszenia innych godzin")[1]
        assert body["lines"] == [
            f"Godziny osoby Ewa: {day_words(b['today'])}, 06:00–12:00 zamiast 06:00–14:00 (krócej o 2 h)."
        ]
        assert body["hours_only"] and body["can_apply"]
        # The schedule of the agreements' period is published meanwhile: rules could not change, hours still can.
        AssistantRuleSet.objects.update(consumed_at=timezone.now())
        body = api.get(f"/api/assistant-commands/{body['id']}").json()
        assert body["consumed_at"] and body["can_apply"]

        applied = api.post(f"/api/assistant-commands/{body['id']}/apply")

        assert applied.status_code == 200, applied.json()
        change = HoursChange.objects.get()
        assert change.status == "approved" and change.by_manager and change.employee == b["ewa"]
        assert kinds("hours_set") == [user_of(b["ewa"]).pk]
        assert hours_of(api, b, b["today"], "Ewa Nowak")["total"] == 6

    def test_a_plan_with_rules_and_hours_closes_with_its_period(self, api, bakery, with_key, monkeypatch):
        b = bakery
        b["shift"](b["ewa"], b["today"])
        next_period(b)
        apart = llm.NewInstruction(
            type="unikaj_osoby",
            person="Ewa",
            other_person="Pracownik",
            shift_type=None,
            avoid_shift_type=False,
            max_hours=None,
            min_days=None,
            shifts_per_day=None,
            max_shifts=None,
            hours_period="period",
            dates=[],
            weekdays=[],
            place=None,
        )
        answer = manager_plan(hours_changes=[set_hours("Ewa", b["today"], end="12:00")], new_instructions=[apart])
        body, _ = ask(api, b, monkeypatch, answer)
        assert body["can_apply"] and body["has_hours"] and not body["hours_only"]

        AssistantRuleSet.objects.update(consumed_at=timezone.now())

        body = api.get(f"/api/assistant-commands/{body['id']}").json()
        assert not body["can_apply"]
        assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 409
        assert not HoursChange.objects.exists()

    def test_a_change_over_a_waiting_report_says_so_and_replaces_it(self, api, bakery, with_key, monkeypatch):
        b = bakery
        ola = b["shift"](b["ola"], b["today"])
        assert report(api, b, ola, "06:00", "15:00").status_code == 201

        body, _ = ask(
            api, b, monkeypatch, manager_plan(hours_changes=[set_hours("Pracownik", b["today"], "06:00", "14:30")])
        )

        assert body["lines"][0].endswith("Czekające zgłoszenie (06:00–15:00) przestanie czekać.")
        assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 200
        assert dict(HoursChange.objects.values_list("by_manager", "status")) == {False: "replaced", True: "approved"}

    def test_same_hours_change_nothing_and_unusable_parts_block_the_plan(self, api, bakery, with_key, monkeypatch):
        b = bakery
        b["shift"](b["ola"], b["today"])
        b["shift"](b["ewa"], b["today"])

        same, _ = ask(api, b, monkeypatch, manager_plan(hours_changes=[set_hours("Pracownik", b["today"], "06:00")]))
        assert same["lines"] == [] and not same["can_apply"]
        assert same["notes"] == [f"To już jest ustawione: godziny osoby Pracownik w {day_words(b['today'])}."]

        tomorrow = b["today"] + timedelta(days=1)
        blocked, _ = ask(
            api,
            b,
            monkeypatch,
            manager_plan(
                hours_changes=[
                    set_hours("Ewa", b["today"], end="12:00"),  # fine on its own
                    set_hours("Ewa", tomorrow, end="12:00"),
                    set_hours("Zenon", b["today"], end="12:00"),
                    set_hours("Pracownik", b["today"], "06:00", "07:00:00"),
                ],
                hours_decisions=[llm.HoursDecision(report=3, approve=True)],
            ),
        )
        assert blocked["reply"] == services.BLOCKED_REPLY and blocked["lines"] == [] and not blocked["can_apply"]
        notes = " ".join(blocked["notes"])
        assert f"Ewa nie ma zmiany w {day_words(tomorrow)} w opublikowanym grafiku tego lokalu." in notes
        assert "Nie znalazłem w tym lokalu osoby „Zenon”." in notes
        assert "Godziny osoby Pracownik: nie rozumiem dnia albo godzin." in notes
        assert "Nie znalazłem zgłoszenia godzin o tym numerze." in notes

    def test_overlapping_hours_are_refused_before_the_manager_accepts(self, api, bakery, with_key, monkeypatch):
        b = bakery
        b["shift"](b["ewa"], b["today"])
        b["shift"](b["ewa"], b["today"] + timedelta(days=1))

        # Into the next morning's shift.
        body, _ = ask(api, b, monkeypatch, manager_plan(hours_changes=[set_hours("Ewa", b["today"], "13:00", "07:00")]))

        assert not body["can_apply"]
        assert "Te godziny nachodzą na inną zmianę tej osoby" in " ".join(body["notes"])

    def test_a_plan_that_went_stale_saves_nothing(self, api, bakery, with_key, monkeypatch):
        b = bakery
        ola = b["shift"](b["ola"], b["today"])
        b["shift"](b["ewa"], b["today"])
        sent = report(api, b, ola, "06:00", "15:00")
        answer = manager_plan(
            hours_decisions=[llm.HoursDecision(report=1, approve=True)],
            hours_changes=[set_hours("Ewa", b["today"], end="12:00")],
        )
        body, _ = ask(api, b, monkeypatch, answer)
        assert body["can_apply"] and len(body["lines"]) == 2
        api.login(user_of(b["ola"]))
        assert api.post(f"/api/hours-changes/{sent.json()['id']}/cancel").status_code == 200  # taken back meanwhile

        api.login(b["manager"])
        applied = api.post(f"/api/assistant-commands/{body['id']}/apply")

        assert applied.status_code == 409
        assert "Nic z tego planu nie zapisałem." in applied.json()["detail"]
        assert list(HoursChange.objects.values_list("status", flat=True)) == ["cancelled"]  # Ewa's hours neither
        assert not Notification.objects.filter(kind__in=["hours_approved", "hours_set"]).exists()
        assert AssistantCommand.objects.get(pk=body["id"]).status == AssistantCommand.Status.READY

    def test_the_manager_tool_lists_waiting_reports(self, api, bakery):
        b = bakery
        ola = b["shift"](b["ola"], b["today"])
        b["shift"](b["ewa"], b["today"])
        assert report(api, b, ola, "06:00", "15:00", "Dostawa").status_code == 201

        box = tools.manager_toolbox(b["manager"], b["company"].pk, b["location"].pk)
        text, error = box.run("manager_hours_changes", {"date_from": None, "date_to": None, "person": "Pracownik"})

        assert not error and "+48" not in text
        data = json.loads(text)
        assert [(r["employee_name"], r["end_time"], r["reason"]) for r in data["pending"]] == [
            ("Pracownik", "15:00", "Dostawa")
        ]
        assert data["waiting"] == 1


def test_the_answer_schemas_carry_hours_and_null_means_unchanged():
    """On OpenRouter the answer is a tool call built from the models: the hours are in it, and a model that writes
    null for an hour that does not change is read as "unchanged", not refused."""
    employee = llm.answer_schema(llm.EmployeeReply)
    report_fields = employee["properties"]["hours_changes"]["items"]
    assert report_fields["required"] == ["date", "start_time", "end_time", "reason"]
    manager = llm.answer_schema(llm.CommandPlan)
    assert {"hours_changes", "hours_decisions"} <= set(manager["required"])

    raw = json.dumps(
        {
            "topic": "app",
            "answer": "",
            "preferences": [],
            "leave_to_manager": False,
            "replaces_request": None,
            "hours_changes": [{"date": "2026-11-21", "start_time": None, "end_time": "11:00", "reason": None}],
        }
    )
    [item] = llm.parse_answer(raw, llm.EmployeeReply, employee).hours_changes
    assert (item.start_time, item.end_time, item.reason) == ("", "11:00", "")
