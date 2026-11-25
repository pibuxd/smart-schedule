# ruff: noqa: F811  (the `shop` fixture is imported from test_generation)
"""Giving away a shift: who is told, "Biorę", the manager's decision, history, notifications, other companies."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.availability.models import AvailabilityDay
from apps.marketplace.models import ShiftClaim, ShiftOffer
from apps.notifications.models import Notification
from apps.notifications.services import notification_text
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
    assert response.json()["notified_here"] == 1  # the free seller works here, the other one elsewhere
    assert told("offer_made") == {m["manager"].pk}
    note = Notification.objects.get(kind="offer_made")
    assert note.payload["able"] == 2
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
    assert told("offer_claimed") == {user_of(m["giver"]).pk}  # the giver knows someone volunteered
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
    assert told("borrowed") == set()  # the owner manages both locations, so nobody else to tell
    # The shift is now in the taker's "Mój grafik" (in another location) and gone from the giver's.
    api.login(user_of(m["elsewhere"]))
    theirs = api.get(f"/api/me/schedule?company_id={m['company'].id}").json()["shifts"]
    assert [s["id"] for s in theirs] == [str(row.pk)] and theirs[0]["away"] is True
    company_id = str(m["company"].pk)
    calendar = api.get(f"/api/me/calendar?company_id={company_id}&start={MON}&end={MON}").json()
    assert calendar["locked"] == [MON.isoformat()]
    refused = api.client.put(
        "/api/me/calendar",
        {"company_id": company_id, "days": [{"date": MON.isoformat(), "state": "cannot"}]},
        content_type="application/json",
    )
    assert refused.status_code == 409
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


def test_home_manager_learns_about_borrowing(api, market):
    from apps.accounts.models import User
    from apps.tenancy.models import Membership
    from tests.conftest import next_phone

    m = market
    boss = User.objects.create_user(next_phone(), first_name="Kierownik Rynku")
    Membership.objects.create(company=m["company"], user=boss, role="manager").locations.set([m["other"]])
    offer_id = offer(api, m).json()["id"]
    api.login(user_of(m["elsewhere"]))
    claim_id = api.post(f"/api/offers/{offer_id}/claim").json()["my_claim_id"]
    api.login(m["manager"])

    assert api.post(f"/api/claims/{claim_id}/approve").status_code == 200
    assert told("borrowed") == {boss.pk}
    assert (
        "bierze zmianę w innym lokalu"
        in api.login(boss).get(f"/api/me/notifications?company_id={m['company'].id}").json()["notifications"][0]["text"]
    )


# --- "Przejęcie oddanej zmiany bez zatwierdzania" (a location rule) ----------------------------------------------


def switch_on_handover(api, m, value=True):
    api.login(m["manager"])
    response = api.patch(f"/api/locations/{m['location'].pk}", {"handover_without_approval": value})
    assert response.status_code == 200 and response.json()["handover_without_approval"] is value


def test_handover_rule_is_off_by_default_and_only_managers_switch_it(api, market):
    m = market
    assert Location.objects.get(pk=m["location"].pk).handover_without_approval is False
    api.login(user_of(m["free"]))
    refused = api.patch(f"/api/locations/{m['location'].pk}", {"handover_without_approval": True})
    assert refused.status_code in (403, 404)
    assert Location.objects.get(pk=m["location"].pk).handover_without_approval is False


def test_rule_hands_the_shift_over_at_once(api, market):
    m = market
    switch_on_handover(api, m)
    made = offer(api, m).json()
    assert made["at_once"] is True
    mine = api.get(f"/api/me/schedule?company_id={m['company'].id}").json()["shifts"]
    assert next(s for s in mine if s["id"] == str(m["row"].pk))["handover_at_once"] is True

    api.login(user_of(m["free"]))
    listed = api.get(f"/api/me/offers?company_id={m['company'].id}").json()
    assert [o["at_once"] for o in listed] == [True]
    taken = api.post(f"/api/offers/{made['id']}/claim")

    assert taken.status_code == 201 and taken.json()["my_claim_status"] == "approved"
    row = Assignment.objects.get(pk=m["row"].pk)
    assert row.employee_id == m["free"].pk and row.pinned and row.manual and not row.borrowed
    assert ShiftOffer.objects.get().status == "approved"
    claim = ShiftClaim.objects.get()
    assert claim.auto_approved and claim.decided_by_id is None
    event = AssignmentEvent.objects.get(reason="offer")
    assert (event.from_employee_id, event.to_employee_id, event.by_id) == (
        m["giver"].pk,
        m["free"].pk,
        user_of(m["free"]).pk,
    )
    # Everyone involved is told; nobody is asked to decide.
    assert told("claim_taken") == {user_of(m["free"]).pk}
    assert told("offer_taken_auto") == {user_of(m["giver"]).pk}
    assert told("handover_done") == {m["manager"].pk}
    assert told("shift_claimed") == set() and told("claim_approved") == set()
    # Nobody else can take it any more.
    api.login(user_of(m["elsewhere"]))
    assert api.get(f"/api/me/offers?company_id={m['company'].id}").json() == []
    assert api.post(f"/api/offers/{made['id']}/claim").status_code == 409
    # The manager sees it among decided offers, marked as taken without approval.
    api.login(m["manager"])
    listing = api.get(f"/api/manager/offers?company_id={m['company'].id}").json()
    assert listing["waiting"] == 0 and listing["offers"][0]["auto_approved"] is True
    assert api.get(f"/api/versions/{m['version'].pk}").json()["hard_problems"] == []


def test_rule_still_refuses_someone_who_cannot_take_it(api, market):
    m = market
    switch_on_handover(api, m)
    offer_id = offer(api, m).json()["id"]
    api.login(user_of(m["busy"]))  # already works at that time

    refused = api.post(f"/api/offers/{offer_id}/claim")

    assert refused.status_code == 409
    assert Assignment.objects.get(pk=m["row"].pk).employee_id == m["giver"].pk
    assert ShiftOffer.objects.get().status == "open"


def test_rule_keeps_a_volunteer_who_was_already_waiting_first(api, market):
    m = market
    offer_id = offer(api, m).json()["id"]
    api.login(user_of(m["elsewhere"]))
    api.post(f"/api/offers/{offer_id}/claim")  # waits for the manager
    switch_on_handover(api, m)

    api.login(user_of(m["free"]))
    listed = api.get(f"/api/me/offers?company_id={m['company'].id}").json()
    assert listed[0]["at_once"] is False
    later = api.post(f"/api/offers/{offer_id}/claim")

    assert later.json()["my_claim_status"] == "pending"  # the manager still decides between the two
    assert Assignment.objects.get(pk=m["row"].pk).employee_id == m["giver"].pk


def test_rule_tells_the_home_manager_of_a_borrowed_taker(api, market):
    from apps.accounts.models import User
    from apps.tenancy.models import Membership
    from tests.conftest import next_phone

    m = market
    boss = User.objects.create_user(next_phone(), first_name="Kierownik Rynku")
    Membership.objects.create(company=m["company"], user=boss, role="manager").locations.set([m["other"]])
    switch_on_handover(api, m)
    offer_id = offer(api, m).json()["id"]
    api.login(user_of(m["elsewhere"]))

    assert api.post(f"/api/offers/{offer_id}/claim").json()["my_claim_status"] == "approved"
    assert Assignment.objects.get(pk=m["row"].pk).borrowed
    assert told("borrowed") == {boss.pk}
    text = api.login(boss).get(f"/api/me/notifications?company_id={m['company'].id}").json()["notifications"][0]["text"]
    assert "bez zatwierdzania" in text


# --- The manager's own changes: another person, a swap, an offer on someone's behalf ------------------------------


def test_manager_puts_another_person_on_a_published_shift(api, market):
    m = market
    api.login(m["manager"])
    listed = api.get(f"/api/locations/{m['location'].pk}/handover-shifts").json()
    mine = next(s for s in listed if s["id"] == str(m["row"].pk))
    assert mine["employee_name"] == user_of(m["giver"]).full_name and mine["started"] is False
    candidates = api.get(f"/api/assignments/{m['row'].pk}/handover-candidates").json()
    by_name = {c["name"]: c for c in candidates}
    # The free seller and the seller from the other location can come; the one working that morning cannot.
    assert by_name[user_of(m["free"]).full_name]["problems"] == [] and by_name["Ala Nowak"]["here"] is False
    assert by_name[user_of(m["busy"]).full_name]["problems"]
    assert candidates[0]["problems"] == [] and candidates[-1]["problems"]  # people who can come are first

    done = api.post(f"/api/assignments/{m['row'].pk}/reassign", {"employee_id": str(m["free"].pk)})

    assert done.status_code == 200 and done.json()["employee_id"] == str(m["free"].pk)
    row = Assignment.objects.get(pk=m["row"].pk)
    assert row.employee_id == m["free"].pk and row.pinned and row.manual and not row.borrowed
    event = AssignmentEvent.objects.get(reason="manual", slot_key=row.shift.slot_key)
    assert (event.from_employee_id, event.to_employee_id, event.by_id) == (m["giver"].pk, m["free"].pk, m["manager"].pk)
    assert told("shift_assigned") == {user_of(m["free"]).pk}
    assert told("shift_unassigned") == {user_of(m["giver"]).pk}
    text = api.login(user_of(m["giver"])).get(f"/api/me/notifications?company_id={m['company'].id}").json()
    assert text["notifications"][0]["text"].startswith("Kierownik zdjął Cię ze zmiany pon. 07.12")


def test_manager_can_overrule_the_validator_but_the_shift_is_not_pinned(api, market):
    m = market
    AvailabilityDay.objects.create(employee=m["free"], date=MON, state="cannot")
    api.login(m["manager"])
    body = {"employee_id": str(m["free"].pk)}

    refused = api.post(f"/api/assignments/{m['row'].pk}/reassign", body)
    assert refused.status_code == 409 and "nie mogę" in refused.json()["detail"]
    assert Assignment.objects.get(pk=m["row"].pk).employee_id == m["giver"].pk

    forced = api.post(f"/api/assignments/{m['row'].pk}/reassign", {**body, "force": True})
    assert forced.status_code == 200
    row = Assignment.objects.get(pk=m["row"].pk)
    assert row.employee_id == m["free"].pk and row.manual and not row.pinned


def test_manager_can_correct_a_shift_that_has_already_started(api, market):
    m = market
    m["row"].shift.__class__.objects.filter(pk=m["row"].shift_id).update(
        start_at=timezone.now() - timedelta(hours=1), end_at=timezone.now() + timedelta(hours=7)
    )
    api.login(m["manager"])

    done = api.post(f"/api/assignments/{m['row'].pk}/reassign", {"employee_id": str(m["free"].pk), "force": True})

    assert done.status_code == 200 and done.json()["started"] is True
    assert Assignment.objects.get(pk=m["row"].pk).employee_id == m["free"].pk
    assert Notification.objects.get(kind="shift_assigned").payload["past"] is True
    assert api.post(f"/api/assignments/{m['row'].pk}/offer").status_code == 409  # too late to look for someone


def test_manager_choice_ends_the_offer_and_turns_down_the_volunteers(api, market):
    m = market
    offer_id = offer(api, m).json()["id"]
    api.login(user_of(m["elsewhere"]))
    api.post(f"/api/offers/{offer_id}/claim")
    api.login(m["manager"])
    candidates = api.get(f"/api/assignments/{m['row'].pk}/handover-candidates").json()
    assert candidates[0]["name"] == "Ala Nowak" and candidates[0]["wants"] is True  # the volunteer comes first

    assert api.post(f"/api/assignments/{m['row'].pk}/reassign", {"employee_id": str(m["free"].pk)}).status_code == 200

    assert ShiftOffer.objects.get(pk=offer_id).status == "approved"
    assert ShiftClaim.objects.get(employee=m["free"]).status == "approved"
    assert ShiftClaim.objects.get(employee=m["elsewhere"]).status == "rejected"
    assert told("claim_rejected") == {user_of(m["elsewhere"]).pk}
    listing = api.get(f"/api/manager/offers?company_id={m['company'].id}").json()
    assert listing["waiting"] == 0 and listing["offers"][0]["assignment_id"] == str(m["row"].pk)


def swappable(m):
    """Sunday's only shift, given to the seller who is free on Monday: swapping it with Monday's breaks nothing."""
    other = Assignment.objects.select_related("shift").get(shift__version=m["version"], shift__date=MON + timedelta(6))
    other.employee = m["free"]
    other.save(update_fields=["employee"])
    return other


def test_manager_swaps_two_people(api, market):
    m = market
    other = swappable(m)
    partner = m["free"]
    api.login(m["manager"])
    body = {"first_id": str(m["row"].pk), "second_id": str(other.pk)}
    checked = api.post("/api/shift-swaps/check", body)
    assert checked.status_code == 200
    problems = checked.json()["problems"]

    done = api.post("/api/shift-swaps", {**body, "force": bool(problems)})

    assert done.status_code == 204
    first, second = Assignment.objects.get(pk=m["row"].pk), Assignment.objects.get(pk=other.pk)
    assert (first.employee_id, second.employee_id) == (partner.pk, m["giver"].pk)
    assert first.pinned is (not problems) and first.manual and second.manual
    assert AssignmentEvent.objects.filter(reason="swap", by=m["manager"]).count() == 2
    assert told("shift_swapped") == {user_of(m["giver"]).pk, user_of(partner).pk}
    note = Notification.objects.get(kind="shift_swapped", user=user_of(m["giver"]))
    assert note.payload["date"] == other.shift.date.isoformat() and note.payload["given"]["date"] == MON.isoformat()
    text = api.login(user_of(m["giver"])).get(f"/api/me/notifications?company_id={m['company'].id}").json()
    assert "Zamiast pon. 07.12" in text["notifications"][0]["text"]
    # The same shift twice, or the same person on both, is refused.
    api.login(m["manager"])
    assert (
        api.post("/api/shift-swaps", {"first_id": body["first_id"], "second_id": body["first_id"]}).status_code == 409
    )


def test_swap_that_breaks_a_hard_rule_needs_force(api, market):
    m = market
    tuesday = swappable(m)
    AvailabilityDay.objects.create(employee=tuesday.employee, date=MON, state="cannot")
    api.login(m["manager"])
    body = {"first_id": str(m["row"].pk), "second_id": str(tuesday.pk)}

    assert "nie mogę" in api.post("/api/shift-swaps/check", body).json()["problems"][0]
    assert api.post("/api/shift-swaps", body).status_code == 409
    assert Assignment.objects.get(pk=m["row"].pk).employee_id == m["giver"].pk
    assert api.post("/api/shift-swaps", {**body, "force": True}).status_code == 204
    assert Assignment.objects.get(pk=m["row"].pk).pinned is False


def test_manager_offers_a_shift_for_an_employee_and_can_close_it(api, market):
    m = market
    api.login(m["manager"])

    made = api.post(f"/api/assignments/{m['row'].pk}/offer")

    assert made.status_code == 201 and made.json()["notified"] == 2
    assert told("shift_offered") == {user_of(m["free"]).pk, user_of(m["elsewhere"]).pk}
    assert told("offer_opened_for_you") == {user_of(m["giver"]).pk}
    assert told("offer_made") == set()  # the only manager did it himself
    listed = api.get(f"/api/locations/{m['location'].pk}/handover-shifts").json()
    assert next(s for s in listed if s["id"] == str(m["row"].pk))["offer_id"] == made.json()["id"]
    api.login(user_of(m["free"]))
    api.post(f"/api/offers/{made.json()['id']}/claim")
    api.login(m["manager"])

    closed = api.post(f"/api/offers/{made.json()['id']}/close")

    assert closed.status_code == 200 and closed.json()["status"] == "rejected"
    assert ShiftClaim.objects.get().status == "rejected"
    assert told("offer_cancelled") == {user_of(m["free"]).pk} and told("claim_rejected") == set()
    assert told("offer_closed") == {user_of(m["giver"]).pk}
    assert Assignment.objects.get(pk=m["row"].pk).employee_id == m["giver"].pk
    assert api.post(f"/api/offers/{made.json()['id']}/close").status_code == 409


def test_manager_changes_are_closed_to_others(api, market, make_company, subscribe):
    m = market
    offer_id = offer(api, m).json()["id"]
    other_row = Assignment.objects.filter(shift__version=m["version"]).exclude(pk=m["row"].pk).first()
    stranger = make_company("Obca")
    subscribe(stranger["company"])
    reassign = {"employee_id": str(m["free"].pk)}
    swap = {"first_id": str(m["row"].pk), "second_id": str(other_row.pk)}

    for user, status in ((stranger["manager"], 404), (user_of(m["busy"]), 403)):
        api.login(user)
        assert api.get(f"/api/locations/{m['location'].pk}/handover-shifts").status_code == status
        assert api.get(f"/api/assignments/{m['row'].pk}/handover-candidates").status_code == status
        assert api.post(f"/api/assignments/{m['row'].pk}/reassign", reassign).status_code == status
        assert api.post("/api/shift-swaps/check", swap).status_code == status
        assert api.post("/api/shift-swaps", swap).status_code == status
        assert api.post(f"/api/assignments/{m['row'].pk}/offer").status_code == status
        assert api.post(f"/api/offers/{offer_id}/close").status_code == status
    # A person of another company cannot be put on the shift.
    api.login(m["manager"])
    foreign = {"employee_id": str(stranger["employee"].pk), "force": True}
    assert api.post(f"/api/assignments/{m['row'].pk}/reassign", foreign).status_code == 404
    assert Assignment.objects.get(pk=m["row"].pk).employee_id == m["giver"].pk


def test_read_only_company_cannot_change_shifts_by_hand(api, market, subscribe):
    m = market
    subscribe(m["company"], days=-1)
    api.login(m["manager"])
    assert api.post(f"/api/assignments/{m['row'].pk}/reassign", {"employee_id": str(m["free"].pk)}).status_code == 402
    assert api.post(f"/api/assignments/{m['row'].pk}/offer").status_code == 402
    assert api.get(f"/api/assignments/{m['row'].pk}/handover-candidates").status_code == 200


def test_the_number_of_people_told_agrees_with_its_words():
    one = notification_text("offer_made", {"offered_by_name": "Anna", "able": 1})
    assert "Daliśmy znać jednej osobie, która może ją wziąć." in one
    assert "Daliśmy znać 3 osobom, które mogą ją wziąć." in notification_text("offer_made", {"able": 3})
    assert "Daliśmy znać jednej osobie." in notification_text("offer_opened_for_you", {"able": 1})
