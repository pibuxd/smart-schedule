# ruff: noqa: F811  (the `shop` fixture is imported from test_generation)
"""One phone number in several locations of a company (docs/plan.md, section 24): a main location plus extra ones,
shared availability, and shifts in one location counted when arranging and editing another."""

from datetime import timedelta

import pytest

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


def test_editing_warns_about_another_draft_and_refuses_a_published_clash(api, two):
    market = arrange(two, two["market_period"])
    bakery = arrange(two, two["period"])
    monday = Assignment.objects.filter(shift__version=bakery, shift__date=MON).first()
    change = {"changes": [{"shift_id": str(monday.shift_id), "employee_id": str(two["kasia"].pk)}]}
    api.login(two["manager"])

    body = api.post(f"/api/versions/{bakery.pk}/check", change).json()
    assert body["ok"]
    assert any("szkicu lokalu Rynek" in w for w in body["warnings"])

    publish(market, two["manager"], notify=False)
    body = api.post(f"/api/versions/{bakery.pk}/check", change).json()
    assert not body["ok"]  # two shifts at the same time stay blocked once the other one is published


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
    # Switching the person off belongs to the manager of the main location.
    off = api.patch(f"/api/employees/{kasia.pk}", {"location_id": str(two["market"].id), "is_active": False})
    assert off.status_code == 409
    assert EmployeeProfile.objects.get(pk=kasia.pk).is_active


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
