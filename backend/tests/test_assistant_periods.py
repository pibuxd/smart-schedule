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


def test_topic_classification_is_required():
    for model, raw in ((llm.CommandPlan, plan().model_dump()), (llm.EmployeeReply, reading().model_dump())):
        raw.pop("topic")
        with pytest.raises(ValidationError):
            model.model_validate(raw)


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


def test_manager_reverts_one_agreed_rule_to_the_location_setting(api, shop, make_company, with_key, monkeypatch):
    accept(api, shop, monkeypatch, plan(rule_changes=[rule_change("max_shifts_per_week", enabled=True, number=4)]))
    url = f"/api/locations/{shop['location'].pk}/agreed-rules/max_shifts_per_week"
    assert build_problem([shop["period"]]).problem.rules[0].params["shifts"] == 4

    other = make_company()
    api.login(other["manager"])
    assert api.client.delete(url).status_code == 404
    api.login(shop["worker"])
    assert api.client.delete(url).status_code == 403

    api.login(shop["manager"])
    assert api.client.delete(f"/api/locations/{shop['location'].pk}/agreed-rules/min_rest").status_code == 404
    response = api.client.delete(url)
    assert response.status_code == 200, response.json()
    assert not any(rule["changed"] for rule in response.json()["rules"])
    assert not build_problem([shop["period"]]).problem.rules
    assert api.client.delete(url).status_code == 404


def test_published_agreements_cannot_be_reverted(api, shop, with_key, monkeypatch):
    saved = accept(
        api, shop, monkeypatch, plan(rule_changes=[rule_change("max_shifts_per_week", enabled=True, number=4)])
    )
    draft = ScheduleVersion.objects.create(period=shop["period"], number=1)
    assert api.post(f"/api/versions/{draft.pk}/publish").status_code == 200
    url = f"/api/locations/{shop['location'].pk}/agreed-rules/max_shifts_per_week?period_id={shop['period'].pk}"
    assert api.client.delete(url).status_code == 409
    saved.rule_set.refresh_from_db()
    assert saved.rule_set.changed_codes == ["max_shifts_per_week"]


def agreed_then_published(api, shop, monkeypatch):
    """A published first period with one rule and two instructions, and a requested next period."""
    accept(
        api,
        shop,
        monkeypatch,
        plan(
            rule_changes=[rule_change("max_shifts_per_week", enabled=True, number=4)],
            new_instructions=[instruction(), instruction(person="Kasia", other_person="Anna")],
        ),
    )
    draft = ScheduleVersion.objects.create(period=shop["period"], number=1)
    assert api.post(f"/api/versions/{draft.pk}/publish").status_code == 200
    later = next_period(shop)
    assert api.post(f"/api/periods/{later.pk}/ask-availability").status_code == 200
    return later


def test_a_new_period_starts_empty_and_takes_only_the_ticked_agreements(api, shop, with_key, monkeypatch):
    later = agreed_then_published(api, shop, monkeypatch)
    url = f"/api/locations/{shop['location'].pk}/agreements"
    offer = api.get(f"{url}/previous?period_id={later.pk}").json()
    assert offer["period_label"].startswith(f"{shop['period'].start:%d.%m.%Y}")
    assert [r["code"] for r in offer["rules"]] == ["max_shifts_per_week"] and len(offer["items"]) == 2
    # Nothing moves by itself, and an empty choice copies nothing.
    assert not build_problem([later]).problem.requests and not build_problem([later]).problem.rules
    assert api.post(f"{url}/copy", {"period_id": str(later.pk)}).json()["items"] == []
    assert not build_problem([later]).problem.requests
    first = offer["items"][0]
    copied = api.post(f"{url}/copy", {"period_id": str(later.pk), "instruction_ids": [first["id"]]})
    assert copied.status_code == 200, copied.json()
    assert [i["text"] for i in copied.json()["items"]] == [first["text"]]
    built = build_problem([later]).problem
    assert len(built.requests) == 1 and not built.rules
    # The copy is a new row: the published period keeps its own two instructions.
    assert len(build_problem([shop["period"]]).problem.requests) == 2
    assert ManagerInstruction.objects.count() == 3
    offer = api.get(f"{url}/previous?period_id={later.pk}").json()
    assert len(offer["items"]) == 1 and len(offer["rules"]) == 1
    # What was copied is no longer offered, so sending it twice is refused instead of duplicated.
    assert api.post(f"{url}/copy", {"period_id": str(later.pk), "instruction_ids": [first["id"]]}).status_code == 409
    both = {"period_id": str(later.pk), "rule_codes": ["max_shifts_per_week"]}
    assert api.post(f"{url}/copy", both).json()["rules"][0]["changed"]
    assert build_problem([later]).problem.rules[0].params["shifts"] == 4
    assert api.post(f"{url}/copy", {"period_id": str(later.pk), "rule_codes": ["no_such_rule"]}).status_code == 409


def test_copy_skips_people_who_left_and_passed_days_and_needs_an_open_period(api, shop, with_key, monkeypatch):
    later = agreed_then_published(api, shop, monkeypatch)
    url = f"/api/locations/{shop['location'].pk}/agreements"
    passed = ManagerInstruction.objects.filter(rule_set__period=shop["period"]).first()
    passed.data = {**passed.data, "weekdays": [], "dates": ["2020-01-01"]}
    passed.save()
    shop["kasia"].is_active = False
    shop["kasia"].save()
    assert api.get(f"{url}/previous?period_id={later.pk}").json()["items"] == []
    # The published period itself takes no copies, and its own history offers nothing from later periods.
    assert api.get(f"{url}/previous?period_id={shop['period'].pk}").json()["period_label"] is None
    closed = api.post(f"{url}/copy", {"period_id": str(shop["period"].pk), "rule_codes": ["max_shifts_per_week"]})
    assert closed.status_code == 409


def test_previous_agreements_are_closed_to_other_companies_and_employees(api, shop, make_company, with_key):
    other = make_company("Obca")
    url = f"/api/locations/{shop['location'].pk}/agreements"
    for user in (other["manager"], shop["worker"]):
        api.login(user)
        assert api.get(f"{url}/previous").status_code in (403, 404)
        assert api.post(f"{url}/copy", {"rule_codes": ["max_shifts_per_week"]}).status_code in (403, 404)
    api.login(shop["manager"])
    foreign = SchedulePeriod.objects.create(
        location=other["location"], start=shop["period"].start, end=shop["period"].end
    )
    assert api.get(f"{url}/previous?period_id={foreign.pk}").status_code == 404
    assert api.post(f"{url}/copy", {"period_id": str(foreign.pk), "rule_codes": ["x"]}).status_code == 404
