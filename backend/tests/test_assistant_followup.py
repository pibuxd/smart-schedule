"""Regressions from the independent QA: preserved intent, factual reads and conversational corrections."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from apps.assistant import context, llm, services
from apps.assistant.management.commands.assistant_misses import _command_reason
from apps.assistant.models import AssistantCommand, ManagerInstruction
from apps.availability.models import AvailabilityDay, AvailabilitySubmission, TextRequest
from apps.scheduling.models import Assignment, ScheduleVersion, Shift
from apps.scheduling.problem_builder import build_problem
from tests.test_assistant import instruction, plan, reading, rule_change, run, send_request
from tests.test_assistant import shop as shop
from tests.test_assistant import with_key as with_key


def submit_and_read(api, shop, monkeypatch, answer, text="Prośba"):
    api.login(shop["worker"])
    monkeypatch.setattr(llm, "read_request", lambda text, context: answer)
    pk = send_request(api, shop, text).json()["id"]
    services.interpret_request(pk)
    return TextRequest.objects.get(pk=pk)


def test_work_on_a_specific_shift_survives_approval_and_reaches_engine(api, shop, with_key, monkeypatch):
    day = shop["period"].start.isoformat()
    AvailabilityDay.objects.create(employee=shop["employee"], date=day, state="cannot")
    api.login(shop["manager"])
    body = run(
        api,
        shop,
        monkeypatch,
        plan(
            reply="Anna na pewno będzie rano.",
            new_instructions=[
                instruction(
                    type="chce_pracowac",
                    other_person=None,
                    shift_type="Ranna",
                    dates=[day],
                )
            ],
        ),
    )
    assert "Ranna" in body["lines"][0]
    assert "na pewno" not in body["reply"]
    assert any("nie mogę" in n for n in body["notes"])
    assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 200
    [saved] = build_problem([shop["period"]]).problem.requests
    assert saved.type == "want_work" and saved.shift_type == str(shop["shift_type"].pk)


def test_incomplete_correction_does_not_remove_the_previous_instruction(api, shop, with_key, monkeypatch):
    old = ManagerInstruction.objects.create(
        employee=shop["employee"],
        location=shop["location"],
        position=1,
        data={"type": "wolne_dni", "weekdays": [4], "dates": []},
    )
    api.login(shop["manager"])
    body = run(
        api,
        shop,
        monkeypatch,
        plan(
            remove_instructions=[1],
            new_instructions=[
                instruction(
                    type="chce_pracowac",
                    other_person=None,
                    shift_type="Nieistniejąca",
                    dates=[str(shop["period"].start)],
                )
            ],
        ),
    )
    assert not body["can_apply"] and body["lines"] == []
    assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 409
    assert ManagerInstruction.objects.get().pk == old.pk


def test_partial_dates_and_unrepresentable_fields_are_not_silently_dropped(api, shop, with_key, monkeypatch):
    row = submit_and_read(
        api,
        shop,
        monkeypatch,
        reading(
            dates=[str(shop["period"].start), "2000-01-01"],
            weekdays=[],
        ),
    )
    assert row.status == "needs_manager"
    row = submit_and_read(api, shop, monkeypatch, reading(shift_type="Ranna"))
    assert row.status == "needs_manager"  # days off plus shift restriction cannot be represented


@pytest.mark.parametrize("invalid", ["rule", "removal", "question", "too_many"])
def test_one_unusable_part_blocks_all_changes(api, shop, with_key, monkeypatch, invalid):
    api.login(shop["manager"])
    changes = {"new_instructions": [instruction()]}
    if invalid == "rule":
        changes["rule_changes"] = [rule_change("unknown", enabled=True)]
    elif invalid == "removal":
        changes["remove_instructions"] = [42]
    elif invalid == "question":
        changes["question"] = "Czy na pewno?"
    else:
        changes["new_instructions"] *= services.MAX_ACTIONS + 1
    body = run(api, shop, monkeypatch, plan(**changes))
    assert not body["can_apply"] and not body["lines"]
    assert _command_reason(AssistantCommand.objects.get(pk=body["id"])).startswith("rejected_plan:")
    assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 409


def test_informational_command_is_not_reported_as_a_miss(api, shop, with_key, monkeypatch):
    api.login(shop["manager"])
    body = run(api, shop, monkeypatch, plan(informational=True, reply="Nie ma jeszcze publikacji."))
    assert not body["can_apply"] and body["reply"] == "Nie ma jeszcze publikacji."
    assert _command_reason(AssistantCommand.objects.get(pk=body["id"])) == ""


def test_information_is_shown_to_employee_but_not_a_solver_request(api, shop, with_key, monkeypatch):
    row = submit_and_read(
        api,
        shop,
        monkeypatch,
        reading(
            type="informacja",
            weekdays=[],
            summary="Nie ma jeszcze opublikowanego grafiku na ten okres.",
        ),
        "Kiedy pracuję?",
    )
    assert row.status == "answered"
    assert not build_problem([shop["period"]]).problem.requests
    mine = api.get(f"/api/me/requests?company_id={shop['company'].pk}&period_id={shop['period'].pk}").json()
    assert mine[0]["status"] == "answered" and mine[0]["summary"] == row.interpretation["summary"]
    api.login(shop["manager"])
    assert api.get(f"/api/periods/{shop['period'].pk}/requests").json() == []
    api.login(shop["worker"])
    assert api.patch(f"/api/me/requests/{row.pk}", {"understood": False}).json()["status"] == "needs_manager"
    api.login(shop["manager"])
    [forwarded] = api.get(f"/api/periods/{shop['period'].pk}/requests").json()
    assert forwarded["text"] == row.text


def test_correction_replaces_old_days_and_preserves_audit_and_manager_priority(api, shop, with_key, monkeypatch):
    days = [str(shop["period"].start + timedelta(days=n)) for n in (17, 18, 19)]
    old = submit_and_read(api, shop, monkeypatch, reading(dates=days, weekdays=[]), "Wolne 18–20.")
    old.manager_priority = "higher"
    old.save()
    seen = {}

    def corrected(text, ctx):
        seen["context"] = ctx
        return reading(dates=days[:2], weekdays=[], replaces_request=1)

    monkeypatch.setattr(llm, "read_request", corrected)
    pk = send_request(api, shop, "Wyjazd się skrócił: wolne tylko 18 i 19.").json()["id"]
    assert services.interpret_request(pk) == "interpreted"
    old.refresh_from_db()
    new = TextRequest.objects.get(pk=pk)
    assert "Wolne 18–20." in seen["context"]
    assert old.status == "superseded" and old.text == "Wolne 18–20."
    assert new.supersedes == old and new.manager_priority == "higher"
    [wish] = build_problem([shop["period"]]).problem.requests
    assert wish.id == pk and sorted(map(str, wish.dates)) == days[:2]
    assert services.interpret_request(pk) == "skipped"
    assert api.patch(f"/api/me/requests/{old.pk}", {"text": "Przywracam"}).status_code == 409
    api.login(shop["manager"])
    assert api.patch(f"/api/requests/{old.pk}", {"manager_rejected": True}).status_code == 409


@pytest.mark.parametrize("change", ["edit", "reject", "supersede", "delete"])
def test_stale_correction_cannot_override_concurrent_change(api, shop, with_key, monkeypatch, change):
    old = submit_and_read(api, shop, monkeypatch, reading(), "Poprzednia prośba")

    def answer(text, ctx):
        if change == "delete":
            old.delete()
        else:
            if change == "edit":
                old.text = "Nowa treść"
            elif change == "reject":
                old.manager_rejected = True
            else:
                old.status = "superseded"
            old.save()
        return reading(replaces_request=1)

    monkeypatch.setattr(llm, "read_request", answer)
    pk = send_request(api, shop, "Poprawiam poprzednią prośbę").json()["id"]
    assert services.interpret_request(pk) == "needs_manager"
    assert TextRequest.objects.get(pk=pk).supersedes_id is None


def test_correction_keeps_rejection_and_never_matches_another_employee(api, shop, with_key, monkeypatch):
    old = submit_and_read(api, shop, monkeypatch, reading())
    old.manager_rejected = True
    old.save()
    new = submit_and_read(api, shop, monkeypatch, reading(replaces_request=1))
    assert new.manager_rejected and not build_problem([shop["period"]]).problem.requests
    new.employee = shop["kasia"]
    new.save()
    attempt = submit_and_read(api, shop, monkeypatch, reading(replaces_request=1))
    assert attempt.status == "needs_manager" and attempt.supersedes_id is None


def test_inflight_read_does_not_overwrite_employee_edit(api, shop, with_key, monkeypatch):
    api.login(shop["worker"])
    pk = send_request(api, shop).json()["id"]

    def answer(text, ctx):
        api.patch(f"/api/me/requests/{pk}", {"text": "Nowa treść"})
        return reading()

    monkeypatch.setattr(llm, "read_request", answer)
    assert services.interpret_request(pk) == "skipped"
    row = TextRequest.objects.get(pk=pk)
    assert row.status == "new" and row.text == "Nowa treść"


def test_manager_decision_during_read_is_preserved_without_leaving_request_queued(api, shop, with_key, monkeypatch):
    api.login(shop["worker"])
    pk = send_request(api, shop).json()["id"]

    def answer(text, ctx):
        api.login(shop["manager"])
        api.patch(f"/api/requests/{pk}", {"manager_rejected": True, "manager_priority": "higher"})
        return reading()

    monkeypatch.setattr(llm, "read_request", answer)
    assert services.interpret_request(pk) == "interpreted"
    row = TextRequest.objects.get(pk=pk)
    assert row.manager_rejected and row.manager_priority == "higher"
    assert not build_problem([shop["period"]]).problem.requests


@pytest.mark.parametrize("changed", ["instruction", "shift", "employee"])
def test_changed_plan_dependencies_cannot_be_approved(api, shop, with_key, monkeypatch, changed):
    old = ManagerInstruction.objects.create(
        employee=shop["employee"],
        location=shop["location"],
        position=1,
        data={"type": "wolne_dni", "weekdays": [4], "dates": []},
    )
    api.login(shop["manager"])
    body = run(
        api,
        shop,
        monkeypatch,
        plan(
            remove_instructions=[1],
            new_instructions=[
                instruction(
                    type="chce_pracowac",
                    shift_type="Ranna",
                    dates=[str(shop["period"].start)],
                )
            ],
        ),
    )
    assert body["can_apply"]
    if changed == "instruction":
        old.delete()
    elif changed == "shift":
        shop["shift_type"].delete()
    else:
        shop["employee"].is_active = False
        shop["employee"].save()
    assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 409
    assert AssistantCommand.objects.get(pk=body["id"]).status == "ready"
    assert not ManagerInstruction.objects.filter(data__type="chce_pracowac").exists()


def test_history_is_scoped_to_same_period_or_month_and_month_marks_are_read(shop):
    month = (shop["period"].end + timedelta(days=32)).replace(day=1)
    old = TextRequest.objects.create(
        employee=shop["employee"], period=shop["period"], text="Inny okres", status="interpreted"
    )
    own = TextRequest.objects.create(employee=shop["employee"], month=month, text="Własny miesiąc")
    AvailabilityDay.objects.create(employee=shop["employee"], date=month, state="cannot")
    assert context.prior_requests(own) == []
    sent, _, _ = services.request_context(own, timezone.localdate())
    assert old.text not in sent and str(month) in sent and '"state": "cannot"' in sent


def add_shift(shop, version, employee, *, hours=8, day_offset=0):
    start = datetime.combine(shop["period"].start + timedelta(days=day_offset), datetime.min.time(), tzinfo=UTC)
    shift = Shift.objects.create(
        version=version,
        location=shop["location"],
        date=start.date(),
        shift_type=shop["shift_type"],
        position=shop["position"],
        start_at=start,
        end_at=start + timedelta(hours=hours),
        slot_key=f"s{Shift.objects.count()}",
    )
    Assignment.objects.create(shift=shift, employee=employee)
    return shift


def snapshot(shop, **kwargs):
    return json.loads(context.location_snapshot(shop["location"], timezone.localdate(), **kwargs).split("\n", 1)[1])


def test_read_context_separates_drafts_private_data_and_company(api, shop, make_company):
    published = ScheduleVersion.objects.create(period=shop["period"], number=1, status="published")
    draft = ScheduleVersion.objects.create(period=shop["period"], number=2)
    add_shift(shop, published, shop["employee"])
    add_shift(shop, published, shop["kasia"])
    add_shift(shop, draft, shop["employee"], hours=10)
    AvailabilityDay.objects.create(employee=shop["kasia"], date=shop["period"].start, state="cannot")
    AvailabilitySubmission.objects.create(employee=shop["employee"], period=shop["period"])
    other = make_company("SecretCompany")
    AvailabilityDay.objects.create(employee=other["employee"], date=shop["period"].start, state="prefer")
    private = TextRequest.objects.create(employee=shop["kasia"], period=shop["period"], text="Private medical reason")
    own = TextRequest.objects.create(employee=shop["employee"], period=shop["period"], text="Ile godzin?")
    employee = snapshot(shop, employee=shop["employee"])
    [p] = employee["periods"]
    [schedule] = p["schedules"]
    assert schedule["status"] == "published" and schedule["hours"] == {"Ty": 8}
    assert schedule["shifts"][0]["coworkers"] == ["Kasia"]
    assert p["availability"] == [] and p["submitted"] == {"Ty": True}
    sent, _, _ = services.request_context(own, timezone.localdate())
    assert private.text not in sent and "SecretCompany" not in sent and "+48" not in sent
    assert "manager_priority" not in sent and "manager_rejected" not in sent and "experience" not in sent
    manager = snapshot(shop)
    assert [s["status"] for s in manager["periods"][0]["schedules"]] == ["published", "draft"]
    assert manager["periods"][0]["schedules"][1]["hours"] == {"Anna": 10}
    assert manager["periods"][0]["availability"][0]["person"] == "Kasia"


def test_truncated_snapshot_does_not_present_partial_totals(shop, monkeypatch):
    version = ScheduleVersion.objects.create(period=shop["period"], number=1, status="published")
    add_shift(shop, version, shop["employee"])
    add_shift(shop, version, shop["employee"], day_offset=1)
    monkeypatch.setattr(context, "MAX_ROWS", 1)
    data = snapshot(shop)["periods"][0]["schedules"][0]
    assert data["hours"] is None and data["unfilled_slots"] is None and data["details_truncated"]


def test_command_history_is_only_same_author_location_and_recent(shop, make_company):
    now = timezone.now()
    base = {"location": shop["location"], "created_by": shop["manager"], "status": "ready"}
    AssistantCommand.objects.create(**base, text="Moja poprzednia", created_at=now - timedelta(minutes=1))
    AssistantCommand.objects.create(**base, text="Zbyt stara", created_at=now - timedelta(days=2))
    AssistantCommand.objects.create(**{**base, "created_by": shop["worker"]}, text="Cudza")
    other = make_company("Inna")
    AssistantCommand.objects.create(
        location=other["location"], created_by=shop["manager"], status="ready", text="Inny lokal"
    )
    current = AssistantCommand.objects.create(**base, text="Teraz", created_at=now)
    history = context.command_history(current)
    assert "Moja poprzednia" in history
    assert all(text not in history for text in ("Zbyt stara", "Cudza", "Inny lokal", "Teraz"))
