# ruff: noqa: F811  (the `shop` fixture is imported from test_generation)
"""The manager's schedule: a version with scores, explanations, manual changes checked by the validator,
pins, publishing with history, and correcting a published schedule."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.availability.models import AvailabilityDay
from apps.notifications.models import Notification
from apps.scheduling.generation import request_generation, run_generation
from apps.scheduling.models import Assignment, AssignmentEvent, SchedulePeriod, ScheduleVersion, Shift
from tests.test_generation import FAST, MON, _ctx, shop  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


@pytest.fixture
def draft(shop):
    run = run_generation(request_generation(_ctx(shop), [shop["period"]])[0].pk, **FAST)
    assert run.status == "succeeded", run.error
    return run.versions.get()


def url(version, rest=""):
    return f"/api/versions/{version.id}{rest}"


def shift_of(version, day, employee=None):
    rows = Assignment.objects.filter(shift__version=version, shift__date=day).select_related("shift")
    if employee is not None:
        rows = rows.filter(employee=employee)
    return rows.order_by("shift__slot_key").first()


def free_person(shop, version, day):
    busy = set(Assignment.objects.filter(shift__version=version, shift__date=day).values_list("employee", flat=True))
    return next(p for p in shop["people"] if p.pk not in busy)


def test_version_shows_the_grid_scores_rules_and_history(api, shop, draft):
    api.login(shop["manager"])

    body = api.get(url(draft)).json()

    assert body["status"] == "draft" and body["editable"] is True and body["number"] == 1
    assert len(body["shifts"]) == 12 and body["scores"]["holes"] == 0
    first = body["shifts"][0]
    assert (first["start_time"], first["end_time"], first["hours"]) == ("06:00", "14:00", 8)
    assert first["position_name"] == "Sprzedawca" and first["employee_name"]
    assert {e["name"] for e in body["employees"]} == {"Pracownik", "Ewa Nowak", "Jan Nowak"}
    assert sum(e["shifts"] for e in body["employees"]) == 12
    assert body["hard_problems"] == []
    assert [h["number"] for h in body["history"]] == [1] and body["history"][0]["generated"] is True
    assert body["period"]["latest_version_status"] == "draft"


def test_explanation_lists_who_could_take_the_shift(api, shop, draft):
    api.login(shop["manager"])
    taken = shift_of(draft, MON)

    body = api.get(url(draft, f"/shifts/{taken.shift_id}/explain")).json()

    assert body["shift"]["id"] == str(taken.shift_id)
    assert body["candidates"][0]["current"] is True
    assert body["candidates"][0]["employee_id"] == str(taken.employee_id)
    others = body["candidates"][1:]
    # Monday needs 2 of 3 sellers: one other person is free, the other already works that morning.
    assert sorted(c["possible"] for c in others) == [False, True]
    blocked = next(c for c in others if not c["possible"])
    assert "dwie zmiany" in blocked["problems"][0]
    assert body["summary"]


def test_manual_change_is_checked_saved_and_scored(api, shop, draft):
    api.login(shop["manager"])
    taken = shift_of(draft, MON)
    Assignment.objects.filter(pk=taken.pk).update(pinned=True)  # the old person was pinned
    free = free_person(shop, draft, MON)
    change = {"changes": [{"shift_id": str(taken.shift_id), "employee_id": str(free.pk)}]}

    check = api.post(url(draft, "/check"), change).json()
    assert check["ok"] is True and check["problems"] == []
    taken.refresh_from_db()
    assert taken.employee_id != free.pk  # checking saves nothing

    saved = api.patch(url(draft, "/assignments"), change)

    assert saved.status_code == 200
    taken.refresh_from_db()
    assert taken.employee_id == free.pk and taken.manual is True and taken.pinned is False
    periods = api.get(f"/api/locations/{shop['location'].id}/periods").json()
    assert periods[0]["manual_changes"] == 1  # arranging again would drop it


def test_change_that_breaks_a_hard_rule_is_refused_with_the_reason(api, shop, draft):
    api.login(shop["manager"])
    a, b = Assignment.objects.filter(shift__version=draft, shift__date=MON).order_by("shift__slot_key")
    change = {"changes": [{"shift_id": str(a.shift_id), "employee_id": str(b.employee_id)}]}

    check = api.post(url(draft, "/check"), change).json()
    refused = api.patch(url(draft, "/assignments"), change)

    assert check["ok"] is False and "dwie zmiany" in check["problems"][0]
    assert refused.status_code == 409 and "dwie zmiany" in refused.json()["detail"]
    a.refresh_from_db()
    assert a.employee_id != b.employee_id and a.manual is False


def test_cannot_day_blocks_a_manual_change(api, shop, draft):
    api.login(shop["manager"])
    taken = shift_of(draft, MON)
    free = free_person(shop, draft, MON)
    AvailabilityDay.objects.create(employee=free, date=MON, state="cannot")

    refused = api.patch(
        url(draft, "/assignments"), {"changes": [{"shift_id": str(taken.shift_id), "employee_id": str(free.pk)}]}
    )

    assert refused.status_code == 409 and "nie mogę" in refused.json()["detail"]


def test_swap_two_people_in_one_change(api, shop, draft):
    api.login(shop["manager"])
    rows = list(Assignment.objects.filter(shift__version=draft).select_related("shift"))
    days = {(r.employee_id, r.shift.date) for r in rows}
    first, second = next(
        (a, b)
        for a in rows
        for b in rows
        if a.employee_id != b.employee_id
        and (a.employee_id, b.shift.date) not in days
        and (b.employee_id, a.shift.date) not in days
    )
    change = [
        {"shift_id": str(first.shift_id), "employee_id": str(second.employee_id)},
        {"shift_id": str(second.shift_id), "employee_id": str(first.employee_id)},
    ]

    response = api.patch(url(draft, "/assignments"), {"changes": change})

    assert response.status_code == 200, response.json()
    people = (first.employee_id, second.employee_id)
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.employee_id, second.employee_id) == (people[1], people[0])


def test_leaving_a_shift_empty_makes_a_hole(api, shop, draft):
    api.login(shop["manager"])
    taken = shift_of(draft, MON)

    body = api.patch(url(draft, "/assignments"), {"changes": [{"shift_id": str(taken.shift_id)}]}).json()

    assert body["after"]["holes"] == 1 and body["after"]["is_complete"] is False
    draft.refresh_from_db()
    assert draft.is_complete is False and draft.scores["holes"] == 1


def test_pins_survive_arranging_again(api, shop, draft):
    api.login(shop["manager"])
    taken = shift_of(draft, MON)

    pinned = api.post(url(draft, f"/shifts/{taken.shift_id}/pin"), {"pinned": True})
    assert pinned.status_code == 200 and pinned.json()["pinned"] is True

    api.patch(
        url(draft, "/assignments"), {"changes": [{"shift_id": str(shift_of(draft, MON + timedelta(1)).shift_id)}]}
    )
    hole = Assignment.objects.get(shift__version=draft, employee__isnull=True)
    assert api.post(url(draft, f"/shifts/{hole.shift_id}/pin"), {"pinned": True}).status_code == 400

    run = run_generation(request_generation(_ctx(shop), [shop["period"]])[0].pk, **FAST)
    second = run.versions.get()
    again = Assignment.objects.get(shift__version=second, shift__slot_key=taken.shift.slot_key)
    assert again.employee_id == taken.employee_id and again.pinned is True
    draft.refresh_from_db()
    assert draft.status == ScheduleVersion.Status.SUPERSEDED  # the older draft is history now


def test_publishing_records_history_and_notifies_employees(api, shop, draft):
    api.login(shop["manager"])

    response = api.post(url(draft, "/publish"))

    assert response.status_code == 200 and response.json()["status"] == "published"
    draft.refresh_from_db()
    shop["period"].refresh_from_db()
    assert draft.status == "published" and draft.published_at is not None
    assert shop["period"].status == SchedulePeriod.Status.PUBLISHED
    events = AssignmentEvent.objects.filter(period=shop["period"])
    assert events.count() == 12 and set(events.values_list("reason", flat=True)) == {"generated"}
    notified = set(Notification.objects.filter(kind="schedule_published").values_list("user", flat=True))
    assert notified == {p.membership.user_id for p in shop["people"]}
    assert api.get(url(draft)).json()["editable"] is False
    assert (
        api.patch(
            url(draft, "/assignments"), {"changes": [{"shift_id": str(shift_of(draft, MON).shift_id)}]}
        ).status_code
        == 409
    )


def test_correcting_a_published_schedule_starts_a_draft_copy(api, shop, draft):
    api.login(shop["manager"])
    api.post(url(draft, "/publish"))

    copy = api.post(url(draft, "/draft"))
    assert copy.status_code == 201 and copy.json()["number"] == 2 and copy.json()["status"] == "draft"
    assert api.post(url(draft, "/draft")).json()["id"] == copy.json()["id"]  # the same draft again
    corrected = ScheduleVersion.objects.get(pk=copy.json()["id"])
    assert Shift.objects.filter(version=corrected).count() == 12

    taken = shift_of(corrected, MON)
    free = free_person(shop, corrected, MON)
    assert api.get(url(corrected)).json()["changed_people"] == []
    api.patch(
        url(corrected, "/assignments"), {"changes": [{"shift_id": str(taken.shift_id), "employee_id": str(free.pk)}]}
    )
    changed = api.get(url(corrected)).json()["changed_people"]
    assert len(changed) == 2 and api.get(url(draft)).json()["changed_people"] == []
    assert api.post(url(corrected, "/publish")).status_code == 200

    draft.refresh_from_db()
    assert draft.status == "superseded"
    manual = AssignmentEvent.objects.filter(reason="manual")
    assert manual.count() == 1 and manual.get().to_employee_id == free.pk
    assert manual.get().from_employee_id == taken.employee_id
    assert Notification.objects.filter(kind="schedule_published", payload__changed=True).exists()


def test_days_that_have_passed_cannot_be_changed(api, shop, draft, monkeypatch):
    api.login(shop["manager"])
    monkeypatch.setattr(timezone, "localdate", lambda *args, **kwargs: MON + timedelta(days=2))
    taken = shift_of(draft, MON)

    refused = api.patch(url(draft, "/assignments"), {"changes": [{"shift_id": str(taken.shift_id)}]})

    assert refused.status_code == 409 and "minął" in refused.json()["detail"]
    assert api.get(url(draft)).json()["shifts"][0]["past"] is True


def test_read_only_company_can_look_but_not_change(api, shop, draft, subscribe):
    subscribe(shop["company"], days=-1)
    api.login(shop["manager"])
    taken = shift_of(draft, MON)

    assert api.get(url(draft)).json()["editable"] is False
    assert api.patch(url(draft, "/assignments"), {"changes": [{"shift_id": str(taken.shift_id)}]}).status_code == 402
    assert api.post(url(draft, "/publish")).status_code == 402
    assert api.post(url(draft, f"/shifts/{taken.shift_id}/pin"), {"pinned": True}).status_code == 402


def test_other_company_gets_404_everywhere(api, shop, draft, make_company):
    other = make_company("Inna")
    api.login(other["manager"])
    taken = shift_of(draft, MON)
    change = {"changes": [{"shift_id": str(taken.shift_id)}]}

    assert api.get(url(draft)).status_code == 404
    assert api.get(url(draft, f"/shifts/{taken.shift_id}/explain")).status_code == 404
    assert api.post(url(draft, "/check"), change).status_code == 404
    assert api.patch(url(draft, "/assignments"), change).status_code == 404
    assert api.post(url(draft, f"/shifts/{taken.shift_id}/pin"), {"pinned": True}).status_code == 404
    assert api.post(url(draft, "/draft")).status_code == 404
    assert api.post(url(draft, "/publish")).status_code == 404


def test_person_from_another_company_cannot_be_put_in(api, shop, draft, make_company):
    other = make_company("Inna")
    api.login(shop["manager"])
    taken = shift_of(draft, MON)

    response = api.patch(
        url(draft, "/assignments"),
        {"changes": [{"shift_id": str(taken.shift_id), "employee_id": str(other["employee"].pk)}]},
    )

    assert response.status_code == 404


def test_employee_cannot_see_the_draft(api, shop, draft):
    api.login(shop["worker"])

    assert api.get(url(draft)).status_code == 403
