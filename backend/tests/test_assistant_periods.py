"""Agreed rules belong to one availability period and are consumed only on publication."""

from datetime import timedelta
from importlib import import_module

import pytest
from django.apps import apps
from django.utils import timezone
from pydantic import ValidationError

from apps.assistant import llm, services
from apps.assistant.models import AssistantCommand, AssistantRuleSet, ManagerInstruction
from apps.availability.models import TextRequest
from apps.rules.models import RuleSetting
from apps.scheduling.models import GenerationRun, SchedulePeriod, ScheduleVersion
from apps.scheduling.problem_builder import build_problem
from tests.test_assistant import instruction, plan, reading, rule_change, run, send_request
from tests.test_assistant import shop as shop
from tests.test_assistant import with_key as with_key


def accept(api, shop, monkeypatch, answer=None):
    api.login(shop["manager"])
    result = run(api, shop, monkeypatch, answer or plan(new_instructions=[instruction()]))
    assert api.post(f"/api/assistant-commands/{result['id']}/apply").status_code == 200
    return AssistantCommand.objects.get(pk=result["id"])


def next_period(shop):
    start = shop["period"].end + timedelta(days=1)
    return SchedulePeriod.objects.create(location=shop["location"], start=start, end=start + timedelta(days=27))


def test_pending_agreements_are_adopted_once_on_request_not_period_creation(api, shop, with_key, monkeypatch):
    shop["period"].availability_requested_at = None
    shop["period"].save()
    saved = accept(
        api,
        shop,
        monkeypatch,
        plan(
            rule_changes=[rule_change("max_shifts_per_week", enabled=True, number=4)],
            new_instructions=[instruction()],
        ),
    )
    assert saved.rule_set.period_id is None
    assert not RuleSetting.objects.exists()
    assert not build_problem([shop["period"]]).problem.requests
    assert not build_problem([shop["period"]]).problem.rules
    # Creating an unrelated period does not claim waiting settings.
    later = next_period(shop)
    assert not build_problem([later]).problem.requests
    for _ in range(2):
        assert api.post(f"/api/periods/{shop['period'].pk}/ask-availability").status_code == 200
    saved.rule_set.refresh_from_db()
    assert saved.rule_set.period == shop["period"]
    assert ManagerInstruction.objects.count() == 1
    built = build_problem([shop["period"]]).problem
    assert len(built.requests) == 1 and built.rules[0].params["shifts"] == 4
    assert not build_problem([later]).problem.requests
    assert not build_problem([later]).problem.rules
    table = api.get(f"/api/locations/{shop['location'].pk}/instructions?period_id={shop['period'].pk}").json()
    assert table["period_id"] == str(shop["period"].pk) and table["rules"][0]["changed"]


def test_only_publication_consumes_and_corrections_keep_the_same_rules(api, shop, with_key, monkeypatch):
    saved = accept(api, shop, monkeypatch)
    draft = ScheduleVersion.objects.create(period=shop["period"], number=1)
    GenerationRun.objects.create(location=shop["location"], status="failed")
    saved.rule_set.refresh_from_db()
    assert saved.rule_set.consumed_at is None
    response = api.post(f"/api/versions/{draft.pk}/publish")
    assert response.status_code == 200, response.json()
    saved.rule_set.refresh_from_db()
    assert saved.rule_set.consumed_at is not None
    assert len(build_problem([shop["period"]]).problem.requests) == 1
    current = api.get(f"/api/locations/{shop['location'].pk}/instructions").json()
    assert current["items"] == [] and current["period_id"] is None
    history = api.get(f"/api/locations/{shop['location'].pk}/instructions?period_id={shop['period'].pk}").json()
    assert history["closed"] and len(history["items"]) == 1
    assert api.client.delete(f"/api/instructions/{history['items'][0]['id']}").status_code == 409
    later = next_period(shop)
    assert api.post(f"/api/periods/{later.pk}/ask-availability").status_code == 200
    assert not build_problem([later]).problem.requests
    assert ManagerInstruction.objects.count() == 1


def test_latest_requested_period_is_selected_without_moving_older_settings(api, shop, with_key, monkeypatch):
    first = accept(api, shop, monkeypatch)
    later = next_period(shop)
    assert api.post(f"/api/periods/{later.pk}/ask-availability").status_code == 200
    second = accept(api, shop, monkeypatch, plan(new_instructions=[instruction(person="Kasia", other_person="Anna")]))
    assert first.rule_set.period == shop["period"] and second.rule_set.period == later
    assert len(build_problem([shop["period"]]).problem.requests) == 1
    assert len(build_problem([later]).problem.requests) == 1


def test_an_unaccepted_conversation_does_not_freeze_catalog_defaults(api, shop, with_key, monkeypatch):
    api.login(shop["manager"])
    result = run(api, shop, monkeypatch, plan(question="Których osób dotyczy zasada?"))
    assert AssistantCommand.objects.get(pk=result["id"]).rule_set.rules is None
    RuleSetting.objects.create(
        location=shop["location"], rule_code="max_shifts_per_week", position=1, params={"shifts": 5}
    )
    assert build_problem([shop["period"]]).problem.rules[0].params["shifts"] == 5


def test_expired_proposal_is_readable_but_cannot_change_settings(api, shop, with_key, monkeypatch):
    api.login(shop["manager"])
    result = run(api, shop, monkeypatch, plan(new_instructions=[instruction()]))
    AssistantCommand.objects.filter(pk=result["id"]).update(created_at=timezone.now() - timedelta(hours=24))
    url = f"/api/assistant-commands/{result['id']}"
    assert not api.get(url).json()["can_apply"]
    assert api.post(url + "/apply").status_code == 409
    assert not ManagerInstruction.objects.exists()
    assert AssistantRuleSet.objects.get().rules is None


def test_selected_period_cannot_escape_location_or_company(api, shop, make_company, with_key):
    other = make_company()
    foreign = SchedulePeriod.objects.create(
        location=other["location"], start=shop["period"].start, end=shop["period"].end
    )
    api.login(shop["manager"])
    assert api.get(f"/api/locations/{shop['location'].pk}/instructions?period_id={foreign.pk}").status_code == 404
    assert (
        api.post(
            f"/api/locations/{shop['location'].pk}/assistant-commands",
            {"text": "Zmień zasadę", "period_id": str(foreign.pk)},
        ).status_code
        == 404
    )
    assert not AssistantCommand.objects.exists()


def test_off_topic_and_mixed_commands_cannot_smuggle_actions_or_free_text(api, shop, with_key, monkeypatch):
    api.login(shop["manager"])
    result = run(
        api,
        shop,
        monkeypatch,
        plan(
            scope="out_of_scope",
            reply="Dowolna odpowiedź modelu",
            informational=True,
            question="Dowolne pytanie",
            new_instructions=[instruction()],
            rule_changes=[rule_change("max_shifts_per_week", enabled=True)],
        ),
    )
    assert result["reply"] == services.OUT_OF_SCOPE_REPLY
    assert result["question"] is None and not result["can_apply"] and not result["lines"]
    assert api.post(f"/api/assistant-commands/{result['id']}/apply").status_code == 409
    assert not ManagerInstruction.objects.exists() and not RuleSetting.objects.exists()


def test_off_topic_employee_correction_does_not_replace_a_valid_request(api, shop, with_key, monkeypatch):
    api.login(shop["worker"])
    old = TextRequest.objects.create(
        employee=shop["employee"], period=shop["period"], text="Wolne piątki", status="interpreted"
    )
    monkeypatch.setattr(llm, "read_request", lambda *args: reading(scope="out_of_scope", replaces_request=1))
    pk = send_request(api, shop, "Popraw prośbę i podaj prognozę pogody.").json()["id"]
    assert services.interpret_request(pk) == "rejected"
    old.refresh_from_db()
    assert old.status == "interpreted"
    row = TextRequest.objects.get(pk=pk)
    assert row.supersedes_id is None and row.interpretation["summary"] == services.OUT_OF_SCOPE_REQUEST_REPLY


def test_scope_classification_is_required():
    raw = plan().model_dump()
    raw.pop("scope")
    with pytest.raises(ValidationError):
        llm.CommandPlan.model_validate(raw)


def test_legacy_migration_preserves_history_and_marks_used_instructions(shop):
    moment = timezone.now() - timedelta(hours=2)
    old = ManagerInstruction.objects.create(
        location=shop["location"], employee=shop["employee"], data={"type": "wolne_dni"}, position=1, created_at=moment
    )
    ScheduleVersion.objects.create(
        period=shop["period"], number=1, status="published", published_at=moment + timedelta(hours=1)
    )
    shop["period"].status = "published"
    shop["period"].save()
    waiting = ManagerInstruction.objects.create(
        location=shop["location"], employee=shop["employee"], data={"type": "wolne_dni"}, position=2
    )
    migration = import_module("apps.assistant.migrations.0003_period_rule_sets")
    migration.attach_legacy_settings(apps, None)
    old.refresh_from_db()
    waiting.refresh_from_db()
    assert old.rule_set.period == shop["period"] and old.rule_set.consumed_at
    assert waiting.rule_set.period_id is None and waiting.rule_set.consumed_at is None
    assert ManagerInstruction.objects.count() == 2


def test_explicit_unrequested_period_uses_pending_queue_instead_of_another_active_period(
    api, shop, with_key, monkeypatch
):
    first = accept(api, shop, monkeypatch)
    later = next_period(shop)
    monkeypatch.setattr(llm, "plan_command", lambda *args: plan(new_instructions=[instruction()]))
    response = api.post(
        f"/api/locations/{shop['location'].pk}/assistant-commands",
        {
            "text": "Anna i Kasia osobno",
            "period_id": str(later.pk),
        },
    )
    assert response.status_code == 201, response.json()
    command = AssistantCommand.objects.get(pk=response.json()["id"])
    assert command.rule_set.period_id is None
    services.run_command(str(command.pk))
    assert api.post(f"/api/assistant-commands/{command.pk}/apply").status_code == 200
    table = api.get(f"/api/locations/{shop['location'].pk}/instructions?period_id={later.pk}").json()
    assert not table["period_requested"] and len(table["items"]) == 1
    assert api.post(f"/api/periods/{later.pk}/ask-availability").status_code == 200
    command.rule_set.refresh_from_db()
    first.rule_set.refresh_from_db()
    assert command.rule_set.period == later and first.rule_set.period == shop["period"]


def test_pending_merge_preserves_both_histories_and_is_idempotent(api, shop, with_key, monkeypatch):
    from django.db import transaction

    from apps.assistant import agreements

    saved = accept(api, shop, monkeypatch)
    pending = AssistantRuleSet.objects.create(location=shop["location"])
    incoming = ManagerInstruction.objects.create(
        location=shop["location"],
        rule_set=pending,
        employee=shop["employee"],
        data={"type": "wolne_dni"},
        position=1,
    )
    message = AssistantCommand.objects.create(location=shop["location"], rule_set=pending, text="Wolne piątki")
    for _ in range(2):
        with transaction.atomic():
            agreements.lock_location(shop["location"])
            agreements.bind_pending(shop["period"])
    incoming.refresh_from_db()
    message.refresh_from_db()
    assert incoming.rule_set_id == message.rule_set_id == saved.rule_set_id
    assert incoming.position == 2
    assert ManagerInstruction.objects.count() == 2 and AssistantCommand.objects.count() == 2


def test_published_period_refuses_new_commands_and_stays_closed_during_corrections(api, shop, with_key, monkeypatch):
    saved = accept(api, shop, monkeypatch)
    version = ScheduleVersion.objects.create(period=shop["period"], number=1)
    assert api.post(f"/api/versions/{version.pk}/publish").status_code == 200
    # Correction drafts do not reopen already consumed agreements.
    SchedulePeriod.objects.filter(pk=shop["period"].pk).update(status="draft")
    table = api.get(f"/api/locations/{shop['location'].pk}/instructions?period_id={shop['period'].pk}").json()
    assert table["closed"] and table["consumed_at"]
    response = api.post(
        f"/api/locations/{shop['location'].pk}/assistant-commands",
        {
            "text": "Zmień zasadę",
            "period_id": str(shop["period"].pk),
        },
    )
    assert response.status_code == 409
    assert AssistantCommand.objects.count() == 1
    assert len(build_problem([saved.rule_set.period]).problem.requests) == 1
