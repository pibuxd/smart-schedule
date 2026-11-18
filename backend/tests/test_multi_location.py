# ruff: noqa: F811  (the `shop` fixture is imported from test_generation)
"""One phone number in several locations of a company (docs/plan.md, section 24): a main location plus extra ones,
shared availability, and shifts in one location counted when arranging and editing another."""

from datetime import timedelta

import pytest

from apps.accounts.models import User
from apps.availability.models import AvailabilitySubmission
from apps.scheduling.editing import publish
from apps.scheduling.generation import request_generation, run_generation
from apps.scheduling.models import Assignment, SchedulePeriod
from apps.staffing.models import EmployeeProfile, Position, ShiftType, StaffingRule
from apps.tenancy.models import Location
from tests.test_generation import FAST, MON, _ctx, add_employee, shop  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


@pytest.fixture
def two(shop):
    """The shop plus "Rynek" (one seller every morning, same hours) and Kasia: main location the shop, extra Rynek."""
    company = shop["company"]
    market = Location.objects.create(company=company, name="Rynek")
    seller = Position.objects.create(location=market, name="Sprzedawca")
    morning = ShiftType.objects.create(
        location=market, name="Ranna", start_time=shop["shift_type"].start_time, end_time=shop["shift_type"].end_time
    )
    StaffingRule.objects.bulk_create(
        StaffingRule(company=company, location=market, weekday=d, shift_type=morning, position=seller, count=1)
        for d in range(7)
    )
    kasia = add_employee(company, shop["location"], [shop["position"]], "Kasia")
    kasia.extra_locations.add(market)
    kasia.positions.add(seller)
    period = SchedulePeriod.objects.create(location=market, start=MON, end=MON + timedelta(days=6))
    return {**shop, "market": market, "market_seller": seller, "kasia": kasia, "market_period": period}


def arrange(data, period):
    run = run_generation(request_generation(_ctx(data), [period])[0].pk, **FAST)
    assert run.status == "succeeded", run.error
    return run.versions.get()


def people_on(version):
    return list(Assignment.objects.filter(shift__version=version).values_list("employee_id", flat=True))


def test_generator_uses_a_person_in_their_extra_location(two):
    version = arrange(two, two["market_period"])

    assert set(people_on(version)) == {two["kasia"].pk}  # nobody else works at Rynek
    assert not Assignment.objects.filter(shift__version=version, borrowed=True).exists()


def test_draft_of_another_location_counts_as_taken_when_arranging(two):
    market = arrange(two, two["market_period"])
    bakery = arrange(two, two["period"])

    # Same hours in both places: Kasia already works every Rynek morning (draft), so the shop does not use her.
    assert two["kasia"].pk not in people_on(bakery)
    assert set(people_on(market)) == {two["kasia"].pk}


def put_kasia_on_monday(api, two, bakery, **extra):
    monday = Assignment.objects.filter(shift__version=bakery, shift__date=MON).order_by("shift__slot_key").first()
    change = {"changes": [{"shift_id": str(monday.shift_id), "employee_id": str(two["kasia"].pk)}], **extra}
    return monday, api.post(f"/api/versions/{bakery.pk}/check", change), change


def market_monday(version):
    return Assignment.objects.get(shift__version=version, shift__date=MON)


def test_clash_with_another_draft_asks_and_takes_the_person_off_it(api, two):
    market = arrange(two, two["market_period"])
    bakery = arrange(two, two["period"])
    api.login(two["manager"])

    monday, check, change = put_kasia_on_monday(api, two, bakery)

    body = check.json()
    assert body["ok"]  # a draft is not binding yet, but the manager is still asked
    (clash,) = body["clashes"]
    assert clash["kind"] == "draft" and clash["location_name"] == "Rynek" and clash["can_remove"]
    assert "w szkicu grafiku lokalu Rynek: pon. 07.12, 06:00–14:00" in clash["text"]
    assert body["ok_if_removed"]
    response = api.patch(f"/api/versions/{bakery.pk}/assignments", {**change, "remove_clashes": True})
    assert response.status_code == 200, response.json()
    monday.refresh_from_db()
    assert monday.employee_id == two["kasia"].pk
    there = market_monday(market)
    assert there.employee_id is None and there.manual  # a hole in the Rynek draft


def test_clash_with_a_published_schedule_takes_the_person_off_and_tells_them(api, two):
    from apps.marketplace.models import ShiftOffer
    from apps.notifications.models import Notification
    from apps.notifications.services import notification_text
    from apps.scheduling.models import AssignmentEvent
    from apps.tenancy.models import Membership, Role
    from tests.conftest import next_phone

    market = arrange(two, two["market_period"])
    publish(market, two["manager"], notify=False)
    bakery = arrange(two, two["period"])
    offer = ShiftOffer.objects.create(assignment=market_monday(market), offered_by=two["kasia"])
    market_manager = Membership.objects.create(
        company=two["company"], user=User.objects.create_user(next_phone(), first_name="Ala"), role=Role.MANAGER
    )
    two["market"].managers.add(market_manager)
    api.login(two["manager"])

    monday, check, change = put_kasia_on_monday(api, two, bakery)

    body = check.json()
    assert not body["ok"]  # two shifts at the same time
    assert [c["kind"] for c in body["clashes"]] == ["published"]
    assert "w grafiku lokalu Rynek" in body["clashes"][0]["text"] and body["ok_if_removed"]
    assert api.patch(f"/api/versions/{bakery.pk}/assignments", change).status_code == 409  # not without asking
    people = api.get(f"/api/versions/{bakery.pk}/shifts/{monday.shift_id}/explain").json()["candidates"]
    kasia = next(c for c in people if c["employee_id"] == str(two["kasia"].pk))
    assert not kasia["possible"] and kasia["clash"]  # the shift panel offers to move her
    response = api.patch(f"/api/versions/{bakery.pk}/assignments", {**change, "remove_clashes": True})
    assert response.status_code == 200, response.json()
    monday.refresh_from_db()
    assert monday.employee_id == two["kasia"].pk
    assert market_monday(market).employee_id is None  # changed in place, like an approved handover
    event = AssignmentEvent.objects.get(location=two["market"], from_employee=two["kasia"])
    assert event.to_employee is None and event.reason == AssignmentEvent.Reason.MANUAL
    offer.refresh_from_db()
    assert offer.status == ShiftOffer.Status.EXPIRED
    told = {(n.user_id, n.kind): n for n in Notification.objects.filter(kind__in=["shift_removed", "shift_emptied"])}
    removed = told[(two["kasia"].membership.user_id, "shift_removed")]
    assert "pracujesz w lokalu " + two["location"].name in notification_text(removed.kind, removed.payload)
    emptied = told[(market_manager.user_id, "shift_emptied")]
    assert "Kasia" in notification_text(emptied.kind, emptied.payload)
    assert (two["manager"].pk, "shift_emptied") not in told  # the one who did it knows


def test_manager_of_one_location_cannot_take_people_off_another(api, two):
    from apps.tenancy.models import Membership, Role
    from tests.conftest import next_phone

    market = arrange(two, two["market_period"])
    publish(market, two["manager"], notify=False)
    bakery = arrange(two, two["period"])
    user = User.objects.create_user(next_phone(), first_name="Ola")
    shop_manager = Membership.objects.create(company=two["company"], user=user, role=Role.MANAGER)
    two["location"].managers.add(shop_manager)
    api.login(user)

    _, check, change = put_kasia_on_monday(api, two, bakery)

    (clash,) = check.json()["clashes"]
    assert not clash["can_remove"] and "Nie prowadzisz lokalu Rynek" in clash["reason"]
    assert not check.json()["ok_if_removed"]
    response = api.patch(f"/api/versions/{bakery.pk}/assignments", {**change, "remove_clashes": True})
    assert response.status_code == 409 and "Nie prowadzisz lokalu Rynek" in response.json()["detail"]
    assert market_monday(market).employee_id == two["kasia"].pk


def test_location_list_shows_people_from_other_locations_with_their_positions_here(api, two):
    api.login(two["manager"])

    rows = {r["id"]: r for r in api.get(f"/api/locations/{two['market'].id}/employees").json()}

    kasia = rows[str(two["kasia"].pk)]
    assert kasia["is_home"] is False
    assert kasia["home_location_name"] == two["location"].name
    assert kasia["position_ids"] == [str(two["market_seller"].pk)]
    home_rows = {r["id"]: r for r in api.get(f"/api/locations/{two['location'].id}/employees").json()}
    assert home_rows[str(two["kasia"].pk)]["is_home"] is True
    assert home_rows[str(two["kasia"].pk)]["position_ids"] == [str(two["position"].pk)]


def test_positions_change_only_in_the_edited_location(api, two):
    api.login(two["manager"])
    baker = Position.objects.create(location=two["market"], name="Piekarz")
    kasia = two["kasia"]

    response = api.patch(
        f"/api/employees/{kasia.pk}", {"location_id": str(two["market"].id), "position_ids": [str(baker.pk)]}
    )

    assert response.status_code == 200, response.json()
    assert response.json()["position_ids"] == [str(baker.pk)]
    assert set(kasia.positions.all()) == {two["position"], baker}  # the shop's position stays
    # Experience, hours and switching off are shared: they belong to the manager of the main location.
    market = str(two["market"].id)
    for change in ({"is_active": False}, {"experience": 3}, {"max_hours_month": 40}):
        response = api.patch(f"/api/employees/{kasia.pk}", {"location_id": market, **change})
        assert response.status_code == 409
        assert "lokalu głównego" in response.json()["detail"]
    profile = EmployeeProfile.objects.get(pk=kasia.pk)
    assert profile.is_active and profile.experience == 2 and profile.max_hours_month is None
    # Sending the unchanged values (as the form does) is fine.
    assert api.patch(f"/api/employees/{kasia.pk}", {"location_id": market, "experience": 2}).status_code == 200
    assert api.patch(f"/api/employees/{kasia.pk}", {"max_hours_month": 40}).status_code == 200  # main location


def test_add_myself_in_a_second_location_makes_it_an_extra_location(api, two):
    api.login(two["manager"])
    assert api.post(f"/api/locations/{two['location'].id}/employees/me").status_code == 200

    response = api.post(f"/api/locations/{two['market'].id}/employees/me")

    assert response.status_code == 200, response.json()
    profile = EmployeeProfile.objects.get(membership__user=two["manager"])
    assert profile.home_location == two["location"]
    assert set(profile.extra_locations.all()) == {two["market"]}
    assert response.json()["position_ids"] == [str(two["market_seller"].pk)]


def test_employee_marks_availability_once_for_all_their_locations(api, two):
    kasia = two["kasia"]
    company = str(two["company"].id)
    api.login(kasia.membership.user)

    market = api.get(f"/api/me/availability?company_id={company}&period_id={two['market_period'].id}")
    assert market.status_code == 200
    assert market.json()["period"]["location_name"] == "Rynek"

    done = api.post("/api/me/availability/submit", {"company_id": company, "period_id": str(two["period"].id)})

    assert done.status_code == 200
    # Same days in both locations: "Gotowe" answers both.
    assert set(AvailabilitySubmission.objects.filter(employee=kasia).values_list("period_id", flat=True)) == {
        two["period"].pk,
        two["market_period"].pk,
    }


def test_other_company_cannot_see_or_change_the_person(api, two, make_company):
    other = make_company("Inna")
    api.login(other["manager"])

    assert api.get(f"/api/locations/{two['market'].id}/employees").status_code == 404
    response = api.patch(f"/api/employees/{two['kasia'].pk}", {"location_id": str(other["location"].id)})
    assert response.status_code == 404
