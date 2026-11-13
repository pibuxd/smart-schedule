# ruff: noqa: F811  (the `shop` fixture is imported from test_generation)
"""Giving away a shift: who is told, "Biorę", the manager's decision, history, notifications, other companies."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.availability.models import AvailabilityDay
from apps.marketplace.models import ShiftClaim, ShiftOffer
from apps.notifications.models import Notification
from apps.scheduling.editing import publish, start_draft
from apps.scheduling.generation import request_generation, run_generation
from apps.scheduling.models import Assignment, AssignmentEvent
from apps.staffing.models import Position
from apps.tenancy.models import Location
from tests.test_generation import FAST, MON, _ctx, add_employee, shop  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


@pytest.fixture
def market(shop):
    """The shop's week published, plus a second location with a seller ("sprzedawca", other case) and a baker."""
    run = run_generation(request_generation(_ctx(shop), [shop["period"]])[0].pk, **FAST)
    assert run.status == "succeeded", run.error
    version = publish(run.versions.get(), shop["manager"], notify=False)
    company = shop["company"]
    other = Location.objects.create(company=company, name="Rynek")
    elsewhere = add_employee(company, other, [Position.objects.create(location=other, name="sprzedawca")], "Ala")
    baker = add_employee(company, other, [Position.objects.create(location=other, name="Piekarz")], "Bogdan")
    monday = list(Assignment.objects.filter(shift__version=version, shift__date=MON).order_by("shift__slot_key"))
    working = {a.employee_id for a in monday}
    free = next(p for p in shop["people"] if p.pk not in working)
    giver_row, busy_row = monday
    return {
        **shop,
        "version": version,
        "other": other,
        "elsewhere": elsewhere,
        "baker": baker,
        "row": giver_row,
        "giver": giver_row.employee,
        "busy": busy_row.employee,
        "free": free,
    }


def user_of(profile):
    return profile.membership.user


def offer(api, m):
    api.login(user_of(m["giver"]))
    return api.post(f"/api/me/shifts/{m['row'].pk}/offer")


def told(kind):
    return set(Notification.objects.filter(kind=kind).values_list("user", flat=True))


def test_offer_tells_everyone_who_could_take_the_shift(api, market):
    m = market
    response = offer(api, m)

    assert response.status_code == 201 and response.json()["status"] == "open"
    # The free seller and the seller of the other location (same position name); not the one already working
    # that morning, not the baker, not the giver.
    assert told("shift_offered") == {user_of(m["free"]).pk, user_of(m["elsewhere"]).pk}
    assert response.json()["notified"] == 2
    mine = api.get(f"/api/me/schedule?company_id={m['company'].id}").json()
    shift = next(s for s in mine["shifts"] if s["id"] == str(m["row"].pk))
    assert shift["offer_status"] == "open" and shift["offer_id"] == response.json()["id"]
    assert offer(api, m).status_code == 409  # already offered


def test_cannot_day_keeps_a_person_off_the_list(api, market):
    m = market
    AvailabilityDay.objects.create(employee=m["free"], date=MON, state="cannot")

    offer(api, m)

    assert told("shift_offered") == {user_of(m["elsewhere"]).pk}
    api.login(user_of(m["free"]))
    assert api.get(f"/api/me/offers?company_id={m['company'].id}").json() == []
    offer_id = ShiftOffer.objects.get().pk
    refused = api.post(f"/api/offers/{offer_id}/claim")
    assert refused.status_code == 409 and "nie mogę" in refused.json()["detail"]


def test_only_my_own_published_future_shift_can_be_given_away(api, market):
    m = market
    api.login(user_of(m["free"]))
    assert api.post(f"/api/me/shifts/{m['row'].pk}/offer").status_code == 404  # not mine

    draft = start_draft(m["version"], m["manager"])
    draft_row = Assignment.objects.get(shift__version=draft, shift__slot_key=m["row"].shift.slot_key)
    api.login(user_of(m["giver"]))
    assert api.post(f"/api/me/shifts/{draft_row.pk}/offer").status_code == 409  # a draft, not published

    m["row"].shift.__class__.objects.filter(pk=m["row"].shift_id).update(
        start_at=timezone.now() - timedelta(hours=1), end_at=timezone.now() + timedelta(hours=7)
    )
    assert offer(api, m).status_code == 409  # already started


def test_claim_and_approval_move_the_shift_with_history(api, market):
    m = market
    offer_id = offer(api, m).json()["id"]
    api.login(user_of(m["elsewhere"]))
    listed = api.get(f"/api/me/offers?company_id={m['company'].id}").json()
    assert [o["id"] for o in listed] == [offer_id] and listed[0]["away"] is True
    claimed = api.post(f"/api/offers/{offer_id}/claim")
    assert claimed.status_code == 201 and claimed.json()["my_claim_status"] == "pending"
    api.login(user_of(m["free"]))
    second = api.post(f"/api/offers/{offer_id}/claim").json()["my_claim_id"]
    assert told("shift_claimed") == {m["manager"].pk}
    assert ShiftOffer.objects.get().status == "claimed"

    api.login(m["manager"])
    listing = api.get(f"/api/manager/offers?company_id={m['company'].id}").json()
    assert listing["waiting"] == 2
    claims = listing["offers"][0]["claims"]
    assert {c["name"] for c in claims} == {"Ala Nowak", user_of(m["free"]).full_name} and all(
        c["problems"] == [] for c in claims
    )
    first = next(c["id"] for c in claims if c["name"] == "Ala Nowak")
    approved = api.post(f"/api/claims/{first}/approve")

    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    row = Assignment.objects.get(pk=m["row"].pk)
    assert row.employee_id == m["elsewhere"].pk and row.borrowed and row.pinned and row.manual
    event = AssignmentEvent.objects.get(reason="offer")
    assert (event.from_employee_id, event.to_employee_id, event.by_id) == (
        m["giver"].pk,
        m["elsewhere"].pk,
        m["manager"].pk,
    )
    assert ShiftClaim.objects.get(pk=second).status == "rejected"
    assert told("claim_approved") == {user_of(m["elsewhere"]).pk}
    assert told("offer_taken") == {user_of(m["giver"]).pk}
    assert told("claim_rejected") == {user_of(m["free"]).pk}
    # The shift is now in the taker's "Mój grafik" (in another location) and gone from the giver's.
    api.login(user_of(m["elsewhere"]))
    theirs = api.get(f"/api/me/schedule?company_id={m['company'].id}").json()["shifts"]
    assert [s["id"] for s in theirs] == [str(row.pk)] and theirs[0]["away"] is True
    api.login(user_of(m["giver"]))
    gone = api.get(f"/api/me/schedule?company_id={m['company'].id}").json()["shifts"]
    assert str(row.pk) not in {s["id"] for s in gone}
    # The manager sees who held the shift in the explanation.
    api.login(m["manager"])
    history = api.get(f"/api/versions/{m['version'].pk}/shifts/{row.shift_id}/explain").json()["history"]
    assert history[0]["reason"] == "offer" and history[0]["to_name"] == "Ala Nowak"
    # The published schedule with the borrowed seller is still valid (position matched by name).
    assert api.get(f"/api/versions/{m['version'].pk}").json()["hard_problems"] == []


def test_approval_also_moves_the_newest_draft(api, market):
    m = market
    offer_id = offer(api, m).json()["id"]
    draft = start_draft(m["version"], m["manager"])
    api.login(user_of(m["free"]))
    claim_id = api.post(f"/api/offers/{offer_id}/claim").json()["my_claim_id"]
    api.login(m["manager"])

    assert api.post(f"/api/claims/{claim_id}/approve").status_code == 200

    row = Assignment.objects.get(shift__version=draft, shift__slot_key=m["row"].shift.slot_key)
    assert row.employee_id == m["free"].pk and row.borrowed is False
    publish(draft, m["manager"], notify=False)  # nothing new to record for that slot
    assert AssignmentEvent.objects.filter(slot_key=m["row"].shift.slot_key).count() == 2  # generated + offer


def test_rejecting_reopens_and_cancelling_tells_the_volunteers(api, market):
    m = market
    offer_id = offer(api, m).json()["id"]
    api.login(user_of(m["free"]))
    claim_id = api.post(f"/api/offers/{offer_id}/claim").json()["my_claim_id"]
    api.login(m["manager"])
    assert api.post(f"/api/claims/{claim_id}/reject").status_code == 204
    assert ShiftOffer.objects.get().status == "open" and told("claim_rejected") == {user_of(m["free"]).pk}
    api.login(user_of(m["free"]))
    assert api.post(f"/api/offers/{offer_id}/claim").status_code == 409  # already turned down
    assert api.get(f"/api/me/offers?company_id={m['company'].id}").json() == []

    api.login(user_of(m["elsewhere"]))
    api.post(f"/api/offers/{offer_id}/claim")
    api.login(user_of(m["giver"]))
    assert api.post(f"/api/offers/{offer_id}/cancel").json()["status"] == "cancelled"
    assert ShiftClaim.objects.get(employee=m["elsewhere"]).status == "withdrawn"
    assert told("offer_cancelled") == {user_of(m["elsewhere"]).pk}
    assert Assignment.objects.get(pk=m["row"].pk).employee_id == m["giver"].pk


def test_withdrawing_my_claim_reopens_the_offer(api, market):
    m = market
    offer_id = offer(api, m).json()["id"]
    api.login(user_of(m["free"]))
    claim_id = api.post(f"/api/offers/{offer_id}/claim").json()["my_claim_id"]

    assert api.post(f"/api/claims/{claim_id}/withdraw").status_code == 204
    assert ShiftOffer.objects.get().status == "open"
    again = api.post(f"/api/offers/{offer_id}/claim")
    assert again.status_code == 201 and ShiftOffer.objects.get().status == "claimed"


def test_approval_is_refused_when_the_taker_can_no_longer_work(api, market):
    m = market
    offer_id = offer(api, m).json()["id"]
    api.login(user_of(m["free"]))
    claim_id = api.post(f"/api/offers/{offer_id}/claim").json()["my_claim_id"]
    AvailabilityDay.objects.create(employee=m["free"], date=MON, state="cannot")
    api.login(m["manager"])

    listing = api.get(f"/api/manager/offers?company_id={m['company'].id}").json()
    assert "nie mogę" in listing["offers"][0]["claims"][0]["problems"][0]
    refused = api.post(f"/api/claims/{claim_id}/approve")

    assert refused.status_code == 409 and "nie mogę" in refused.json()["detail"]
    assert Assignment.objects.get(pk=m["row"].pk).employee_id == m["giver"].pk


def test_new_publication_keeps_or_ends_open_offers(api, market):
    m = market
    offer_id = offer(api, m).json()["id"]
    draft = start_draft(m["version"], m["manager"])
    publish(draft, m["manager"], notify=False)  # the giver keeps the shift
    moved = ShiftOffer.objects.get(pk=offer_id)
    assert moved.status == "open" and moved.assignment.shift.version_id == draft.pk

    api.login(user_of(m["free"]))
    api.post(f"/api/offers/{offer_id}/claim")
    third = start_draft(draft, m["manager"])
    Assignment.objects.filter(shift__version=third, shift__slot_key=m["row"].shift.slot_key).update(employee=None)
    publish(third, m["manager"], notify=False)  # the manager took the giver off that shift

    ended = ShiftOffer.objects.get(pk=offer_id)
    assert ended.status == "expired"
    assert told("offer_expired") == {user_of(m["giver"]).pk, user_of(m["free"]).pk}


def test_read_only_company_cannot_give_away(api, market, subscribe):
    subscribe(market["company"], days=-1)
    assert offer(api, market).status_code == 402


def test_other_companies_cannot_see_or_decide(api, market, make_company, subscribe):
    m = market
    offer_id = offer(api, m).json()["id"]
    api.login(user_of(m["free"]))
    claim_id = api.post(f"/api/offers/{offer_id}/claim").json()["my_claim_id"]
    stranger = make_company("Obca")
    subscribe(stranger["company"])

    api.login(stranger["manager"])
    assert api.post(f"/api/claims/{claim_id}/approve").status_code == 404
    assert api.post(f"/api/claims/{claim_id}/reject").status_code == 404
    assert api.get(f"/api/manager/offers?company_id={m['company'].id}").status_code == 404
    api.login(stranger["worker"])
    assert api.post(f"/api/offers/{offer_id}/claim").status_code == 404
    assert api.post(f"/api/me/shifts/{m['row'].pk}/offer").status_code == 404
    assert api.get(f"/api/me/notifications?company_id={m['company'].id}").status_code == 404
    # An employee of the same company cannot decide either.
    api.login(user_of(m["busy"]))
    assert api.post(f"/api/claims/{claim_id}/approve").status_code == 403


def test_notifications_list_and_mark_read(api, market):
    m = market
    offer(api, m)
    api.login(user_of(m["free"]))
    url = f"/api/me/notifications?company_id={m['company'].id}"

    body = api.get(url).json()

    assert body["unread"] == 1
    note = body["notifications"][0]
    assert note["kind"] == "shift_offered" and note["link"] == "schedule" and note["read"] is False
    assert note["text"].startswith(f"{user_of(m['giver']).full_name} oddaje zmianę: pon. 07.12, 06:00–14:00")
    assert api.post("/api/me/notifications/read", {"company_id": str(m["company"].id)}).status_code == 204
    assert api.get(url).json()["unread"] == 0
    # Someone else's notifications are not touched.
    assert Notification.objects.filter(user=user_of(m["elsewhere"]), read_at__isnull=True).count() == 1
