# ruff: noqa: F811  (the `shop` fixture is imported from test_generation)
"""Hours report from published schedules, and its CSV."""

import pytest

from apps.scheduling.editing import publish
from apps.scheduling.generation import request_generation, run_generation
from tests.test_generation import FAST, _ctx, shop  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


@pytest.fixture
def published(shop):
    run = run_generation(request_generation(_ctx(shop), [shop["period"]])[0].pk, **FAST)
    return publish(run.versions.get(), shop["manager"], notify=False)


def test_hours_per_person_and_location(api, shop, published):
    api.login(shop["manager"])

    body = api.get(f"/api/reports/hours?company_id={shop['company'].id}&month=2026-12").json()

    assert [loc["name"] for loc in body["locations"]] == [shop["location"].name]
    assert body["total"] == 12 * 8
    assert sum(r["shifts"] for r in body["rows"]) == 12
    assert all(r["total"] == r["by_location"][0]["hours"] for r in body["rows"])


def test_drafts_and_other_months_do_not_count(api, shop):
    run_generation(request_generation(_ctx(shop), [shop["period"]])[0].pk, **FAST)  # a draft only
    api.login(shop["manager"])

    body = api.get(f"/api/reports/hours?company_id={shop['company'].id}&month=2026-12").json()

    assert body["rows"] == [] and body["total"] == 0


def test_csv_opens_in_a_polish_spreadsheet(api, shop, published):
    api.login(shop["manager"])

    response = api.get(f"/api/reports/hours.csv?company_id={shop['company'].id}&month=2026-12")

    assert response.status_code == 200
    assert response["Content-Disposition"] == 'attachment; filename="godziny-2026-12.csv"'
    text = response.content.decode("utf-8-sig")
    header, *lines = text.strip().splitlines()
    assert header.startswith("Osoba;Lokal domowy;Zmiany;")
    assert header.endswith(";Razem;Uwagi")
    assert len(lines) == 3 and all(line.split(";")[-2].endswith(",00") for line in lines)


def test_bad_month_and_other_companies(api, shop, published, make_company):
    api.login(shop["manager"])
    assert api.get(f"/api/reports/hours?company_id={shop['company'].id}&month=grudzien").status_code == 400

    other = make_company("Inna")
    api.login(other["manager"])
    assert api.get(f"/api/reports/hours?company_id={shop['company'].id}&month=2026-12").status_code == 404
    api.login(shop["worker"])
    assert api.get(f"/api/reports/hours.csv?company_id={shop['company'].id}&month=2026-12").status_code == 403


def test_a_total_is_marked_when_the_person_also_works_elsewhere(api, shop, published):
    from apps.accounts.models import User
    from apps.scheduling.models import Assignment, Shift
    from apps.tenancy.models import Location, Membership, Role
    from tests.conftest import next_phone

    other = Location.objects.create(company=shop["company"], name="Drugi lokal")
    moved = Assignment.objects.filter(shift__version=published, employee__isnull=False).first()
    Shift.objects.filter(pk=moved.shift_id).update(location=other)  # a borrowed shift in a location she doesn't run
    user = User.objects.create_user(next_phone(), first_name="Teresa")
    membership = Membership.objects.create(company=shop["company"], user=user, role=Role.MANAGER)
    membership.locations.add(shop["location"])
    api.login(user)

    body = api.get(f"/api/reports/hours?company_id={shop['company'].id}&month=2026-12").json()
    marked = [r for r in body["rows"] if r["elsewhere"]]
    assert [r["employee_id"] for r in marked] == [str(moved.employee_id)]
    csv_text = api.get(f"/api/reports/hours.csv?company_id={shop['company'].id}&month=2026-12").content.decode()
    assert "suma niepełna" in csv_text

    api.login(shop["manager"])  # the owner runs both locations: nothing is missing
    body = api.get(f"/api/reports/hours?company_id={shop['company'].id}&month=2026-12").json()
    assert not any(r["elsewhere"] for r in body["rows"])
