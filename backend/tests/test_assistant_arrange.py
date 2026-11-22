"""The manager asks the assistant for another schedule: the plan says so, and arranging starts only on acceptance."""

import pytest
from django.utils import timezone
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.assistant import services
from apps.assistant.models import AssistantCommand, ManagerInstruction
from apps.scheduling.models import GenerationRun, SchedulePeriod, ScheduleVersion
from tests.test_assistant import instruction, plan, run
from tests.test_assistant import shop as shop
from tests.test_assistant import with_key as with_key

pytestmark = pytest.mark.django_db


def label(period) -> str:
    return f"{period.start:%d.%m}–{period.end:%d.%m.%Y}"


@pytest.fixture
def drafted(shop):
    ScheduleVersion.objects.create(period=shop["period"], number=1)
    return shop


def test_another_schedule_with_a_change_starts_arranging_only_on_acceptance(api, drafted, with_key, monkeypatch):
    shop = drafted
    api.login(shop["manager"])
    body = run(
        api,
        shop,
        monkeypatch,
        plan(new_instructions=[instruction()], arrange="different"),
        text="Ten grafik mi nie pasuje. Ułóż inny, Anna i Kasia osobno.",
    )

    assert body["can_apply"] and body["arranges"] and body["changes_agreements"]
    assert body["lines"] == [
        "Nowe polecenie: Anna i Kasia: osobno, nie na tej samej zmianie.",
        f"Po zatwierdzeniu ułożę nowy grafik na okres {label(shop['period'])}, wyraźnie inny niż obecny.",
    ]
    assert body["notes"][1].startswith("Przypięte zmiany, osoby wpisane mimo przeszkód i minione dni zostają")
    assert "nie uruchamia układania" not in body["notes"][0]
    assert body["run_id"] is None and not GenerationRun.objects.exists()

    applied = api.post(f"/api/assistant-commands/{body['id']}/apply")

    assert applied.status_code == 200, applied.json()
    run_row = GenerationRun.objects.get()
    assert applied.json()["run_id"] == str(run_row.pk)
    assert run_row.different and run_row.status == GenerationRun.Status.QUEUED
    assert list(run_row.periods.all()) == [shop["period"]]
    assert ProcrastinateJob.objects.filter(task_name="scheduling.solve_schedule").count() == 1
    assert ManagerInstruction.objects.count() == 1
    assert api.get(f"/api/generation-runs/{run_row.pk}").json()["different"] is True


def test_arranging_again_alone_keeps_the_agreements_as_they_are(api, drafted, with_key, monkeypatch):
    shop = drafted
    api.login(shop["manager"])
    body = run(api, shop, monkeypatch, plan(arrange="again"), text="Ułóż grafik jeszcze raz.")

    assert body["lines"] == [f"Po zatwierdzeniu ułożę grafik na okres {label(shop['period'])} od nowa."]
    assert body["can_apply"] and not body["changes_agreements"] and not body["hours_only"]

    assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 200

    assert not GenerationRun.objects.get().different
    assert AssistantCommand.objects.get(pk=body["id"]).rule_set.rules is None  # the location's rules still apply


def test_a_period_without_a_schedule_blocks_the_whole_plan(api, shop, with_key, monkeypatch):
    api.login(shop["manager"])
    body = run(api, shop, monkeypatch, plan(new_instructions=[instruction()], arrange="different"))

    assert not body["can_apply"] and body["lines"] == []
    assert any("nie jest jeszcze ułożony" in note for note in body["notes"])
    assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 409
    assert not ManagerInstruction.objects.exists() and not GenerationRun.objects.exists()


def test_agreements_waiting_for_a_period_cannot_arrange(api, drafted, with_key, monkeypatch):
    shop = drafted
    shop["period"].availability_requested_at = None
    shop["period"].save()
    api.login(shop["manager"])
    body = run(api, shop, monkeypatch, plan(arrange="different"))

    assert not body["can_apply"]
    assert services.ARRANGE_NO_PERIOD in body["notes"]


def test_a_published_schedule_is_arranged_differently_with_the_button_not_the_chat(api, drafted, with_key, monkeypatch):
    shop = drafted
    ScheduleVersion.objects.filter(period=shop["period"]).update(published_at=timezone.now())
    shop["period"].status = SchedulePeriod.Status.PUBLISHED
    shop["period"].save()
    api.login(shop["manager"])
    body = run(api, shop, monkeypatch, plan(arrange="different"), text="Ułóż inny grafik.")

    assert not body["can_apply"] and body["lines"] == []
    assert services.ARRANGE_PUBLISHED.format(label=label(shop["period"])) in body["notes"]


def test_arranging_already_under_way_blocks_the_plan(api, drafted, with_key, monkeypatch):
    shop = drafted
    busy = GenerationRun.objects.create(location=shop["location"])
    busy.periods.set([shop["period"]])
    api.login(shop["manager"])
    body = run(api, shop, monkeypatch, plan(arrange="different"))

    assert not body["can_apply"] and services.ARRANGE_BUSY in body["notes"]


def test_when_arranging_cannot_start_on_acceptance_nothing_is_saved(api, drafted, with_key, monkeypatch):
    shop = drafted
    api.login(shop["manager"])
    body = run(api, shop, monkeypatch, plan(new_instructions=[instruction()], arrange="different"))
    busy = GenerationRun.objects.create(location=shop["location"])
    busy.periods.set([shop["period"]])

    response = api.post(f"/api/assistant-commands/{body['id']}/apply")

    assert response.status_code == 409 and "już się układa" in response.json()["detail"]
    assert response.json()["detail"].endswith(services.NOTHING_SAVED)
    assert not ManagerInstruction.objects.exists() and list(GenerationRun.objects.all()) == [busy]
    assert AssistantCommand.objects.get(pk=body["id"]).status == AssistantCommand.Status.READY


def test_a_question_and_an_arrangement_cannot_be_accepted_together(api, drafted, with_key, monkeypatch):
    shop = drafted
    api.login(shop["manager"])
    body = run(api, shop, monkeypatch, plan(arrange="different", question="O który tydzień chodzi?"))

    assert not body["can_apply"] and body["lines"] == []
    assert body["question"] == "O który tydzień chodzi?"


def test_without_being_asked_nothing_is_arranged(api, drafted, with_key, monkeypatch):
    shop = drafted
    api.login(shop["manager"])
    body = run(api, shop, monkeypatch, plan(new_instructions=[instruction()]))

    assert not body["arranges"]
    assert api.post(f"/api/assistant-commands/{body['id']}/apply").status_code == 200
    assert not GenerationRun.objects.exists()
    assert api.get(f"/api/assistant-commands/{body['id']}").json()["run_id"] is None
