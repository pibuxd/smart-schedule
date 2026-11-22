# ruff: noqa: F811  (the `bakery` fixture is imported from test_worktime)
"""Estimated pay next to the hours: rates of positions and people's own rates, the employee's month in "Mój grafik",
the manager's "Godziny" report and its CSV, and who may set the rates."""

from decimal import Decimal

import pytest

from apps.staffing.models import PersonalRate, Position
from tests.test_generation import add_employee
from tests.test_worktime import bakery, user_of  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db


def report(api, b, day):
    return api.get(f"/api/reports/hours?company_id={b['company'].id}&month={day:%Y-%m}").json()


def row_of(body, name):
    return next(r for r in body["rows"] if r["name"] == name)


def my_month(api, b, day):
    body = api.get(f"/api/me/schedule?company_id={b['company'].id}").json()
    return next(m for m in body["months"] if m["month"] == f"{day:%Y-%m}")


# --------------------------------------------------------------------------------------------- setting rates


def test_the_manager_sets_clears_and_keeps_a_position_rate(api, bakery):
    b = bakery
    api.login(b["manager"])

    made = api.post(f"/api/locations/{b['location'].id}/positions", {"name": "Piekarz", "hourly_rate": 36})
    assert made.status_code == 201 and made.json()["hourly_rate"] == 36
    seller = b["position"]

    changed = api.patch(f"/api/positions/{seller.id}", {"name": "Sprzedawca", "hourly_rate": 31.404})
    assert changed.status_code == 200 and changed.json()["hourly_rate"] == 31.4  # rounded to the grosz
    assert api.patch(f"/api/positions/{seller.id}", {"name": "Sprzedawczyni"}).json()["hourly_rate"] == 31.4  # kept
    setup = api.get(f"/api/locations/{b['location'].id}/setup").json()
    assert {p["name"]: p["hourly_rate"] for p in setup["positions"]} == {"Piekarz": 36, "Sprzedawczyni": 31.4}

    cleared = api.patch(f"/api/positions/{seller.id}", {"name": "Sprzedawczyni", "hourly_rate": None})
    assert cleared.json()["hourly_rate"] is None
    for bad in (0, -5, 0.001, 20_000):
        refused = api.patch(f"/api/positions/{seller.id}", {"name": "Sprzedawczyni", "hourly_rate": bad})
        assert refused.status_code == 400 and "większa od zera" in refused.json()["detail"]


def test_only_the_locations_manager_sets_rates(api, bakery, make_company):
    b = bakery
    seller = b["position"]
    api.login(b["worker"])
    assert api.patch(f"/api/positions/{seller.id}", {"name": "Sprzedawca", "hourly_rate": 50}).status_code == 403
    api.login(b["rynek_manager"])
    assert api.patch(f"/api/positions/{seller.id}", {"name": "Sprzedawca", "hourly_rate": 50}).status_code == 403
    api.login(make_company("Obca")["manager"])
    assert api.patch(f"/api/positions/{seller.id}", {"name": "Sprzedawca", "hourly_rate": 50}).status_code == 404
    assert Position.objects.get(pk=seller.pk).hourly_rate is None


def test_a_person_gets_an_own_rate_on_their_position(api, bakery):
    b = bakery
    seller, ola = b["position"], b["ola"]
    baker = Position.objects.create(location=b["location"], name="Piekarz", hourly_rate=Decimal("36"))
    other = Position.objects.create(location=b["rynek"], name="Kasa")
    api.login(b["manager"])
    path = f"/api/employees/{ola.id}"
    listed = next(e for e in api.get(f"/api/locations/{b['location'].id}/employees").json() if e["id"] == str(ola.id))
    assert listed["position_rates"] == []

    saved = api.patch(
        path,
        {
            "revision": listed["revision"],
            "location_id": str(b["location"].id),
            "position_ids": [str(seller.id), str(baker.id)],
            "position_rates": [
                {"position_id": str(seller.id), "hourly_rate": 34.5},
                {"position_id": str(baker.id), "hourly_rate": None},
            ],
        },
    )

    assert saved.status_code == 200, saved.json()
    assert saved.json()["position_rates"] == [{"position_id": str(seller.id), "hourly_rate": 34.5}]
    assert saved.json()["revision"] != listed["revision"]  # a rate is part of what another manager could overwrite
    assert api.patch(path, {"revision": listed["revision"], "location_id": str(b["location"].id)}).status_code == 409

    for wrong in (baker, other):  # not the person's position here / another location's position
        if wrong is baker:
            api.patch(path, {"location_id": str(b["location"].id), "position_ids": [str(seller.id)]})
        refused = api.patch(
            path,
            {
                "location_id": str(b["location"].id),
                "position_rates": [{"position_id": str(wrong.id), "hourly_rate": 40}],
            },
        )
        assert refused.status_code == 400, refused.json()

    back = api.patch(
        path,
        {
            "location_id": str(b["location"].id),
            "position_rates": [{"position_id": str(seller.id), "hourly_rate": None}],
        },
    )
    assert back.json()["position_rates"] == [] and not PersonalRate.objects.exists()


def test_an_own_rate_stays_for_past_shifts_when_the_position_goes(api, bakery):
    b = bakery
    seller, ola = b["position"], b["ola"]
    Position.objects.filter(pk=seller.pk).update(hourly_rate=Decimal("30"))
    PersonalRate.objects.create(employee=ola, position=seller, hourly_rate=Decimal("35"))
    day = b["today"]
    b["shift"](ola, day)
    api.login(b["manager"])

    gone = api.patch(f"/api/employees/{ola.id}", {"location_id": str(b["location"].id), "position_ids": []})

    assert gone.status_code == 200 and gone.json()["position_rates"] == []
    assert row_of(report(api, b, day), "Pracownik")["pay"] == 8 * 35


# --------------------------------------------------------------------------------------------- counting pay


def test_the_report_counts_pay_with_own_rates_overtime_and_missing_rates(api, bakery):
    b = bakery
    seller = b["position"]
    Position.objects.filter(pk=seller.pk).update(hourly_rate=Decimal("31.40"))
    driver = Position.objects.create(location=b["location"], name="Kierowca")  # no rate
    PersonalRate.objects.create(employee=b["ewa"], position=seller, hourly_rate=Decimal("35.25"))
    day = b["today"]
    row = b["shift"](b["ola"], day)  # 8 h
    b["shift"](b["ewa"], day)  # 8 h at her own rate
    b["ewa"].positions.add(driver)
    b["shift"](b["ewa"], day, (15, 0), (19, 0), position=driver)  # 4 h without a rate
    api.login(b["manager"])
    longer = api.post(
        f"/api/assignments/{row.pk}/hours",
        {"employee_id": str(b["ola"].id), "start_time": "06:00", "end_time": "15:30"},
    )
    assert longer.status_code == 200, longer.json()

    body = report(api, b, day)

    ola, ewa = row_of(body, "Pracownik"), row_of(body, "Ewa Nowak")
    assert (ola["total"], ola["pay"], ola["unpriced_hours"]) == (9.5, 298.3, 0)  # 9,5 h × 31,40 zł
    assert (ewa["total"], ewa["pay"], ewa["unpriced_hours"]) == (12, 282, 4)  # 8 h × 35,25 zł, 4 h without a rate
    assert body["pay"] == 580.3 and body["unpriced_hours"] == 4

    csv_text = api.get(f"/api/reports/hours.csv?company_id={b['company'].id}&month={day:%Y-%m}")
    header, *lines = csv_text.content.decode("utf-8-sig").strip().splitlines()
    assert header.endswith(";Krótsze zmiany;Wypłata brutto, zł (szacunek);Godziny bez stawki;Uwagi")
    cells = {line.split(";")[0]: line.split(";") for line in lines}
    assert cells["Pracownik"][-3:-1] == ["298,30", "0,00"]
    assert cells["Ewa Nowak"][-3:-1] == ["282,00", "4,00"]


def test_without_rates_there_is_no_pay(api, bakery):
    b = bakery
    day = b["today"]
    b["shift"](b["ola"], day)
    api.login(b["manager"])

    body = report(api, b, day)

    assert body["pay"] is None and row_of(body, "Pracownik")["pay"] is None
    assert body["unpriced_hours"] == 8
    csv_text = api.get(f"/api/reports/hours.csv?company_id={b['company'].id}&month={day:%Y-%m}").content.decode()
    assert csv_text.strip().splitlines()[1].split(";")[-3:-1] == ["", "8,00"]
    api.login(user_of(b["ola"]))
    month = my_month(api, b, day)
    assert (month["hours"], month["pay"], month["unpriced_hours"]) == (8, None, 8)


def test_the_employee_sees_the_pay_of_the_whole_month_in_every_location(api, bakery):
    b = bakery
    seller = b["position"]
    Position.objects.filter(pk=seller.pk).update(hourly_rate=Decimal("31.40"))
    till = Position.objects.create(location=b["rynek"], name="Kasa", hourly_rate=Decimal("40"))
    ola = b["ola"]
    ola.extra_locations.add(b["rynek"])
    ola.positions.add(till)
    day = b["today"]
    b["shift"](ola, day)  # 8 h × 31,40
    b["shift"](ola, day, (16, 0), (20, 0), location=b["rynek"], position=till)  # 4 h × 40
    b["shift"](b["ewa"], day)  # not hers
    api.login(user_of(ola))

    month = my_month(api, b, day)

    assert (month["hours"], month["pay"], month["unpriced_hours"]) == (12, 411.2, 0)


def test_pay_rounds_once_for_the_month(api, bakery):
    b = bakery
    Position.objects.filter(pk=b["position"].pk).update(hourly_rate=Decimal("31.42"))
    day = b["today"]
    for start, end in (((6, 0), (6, 20)), ((14, 20), (14, 40)), ((22, 40), (23, 0))):  # three shifts of 20 minutes
        b["shift"](b["ola"], day, start, end)
    api.login(user_of(b["ola"]))

    # 1 h × 31,42 zł; rounding each shift (10,47 zł) would give 31,41 zł.
    assert my_month(api, b, day)["pay"] == 31.42


def test_rates_do_not_cross_companies(bakery, make_company):
    from django.core.exceptions import ValidationError

    other = make_company("Obca")
    with pytest.raises(ValidationError):
        PersonalRate.objects.create(employee=other["employee"], position=bakery["position"], hourly_rate=Decimal("30"))
    stranger = add_employee(other["company"], other["location"], [other["position"]], "Zofia")
    with pytest.raises(ValidationError):
        PersonalRate.objects.create(employee=bakery["ola"], position=stranger.positions.get(), hourly_rate=Decimal(1))
