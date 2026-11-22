# ruff: noqa: F811  (the `bakery` fixture is imported from test_worktime)
"""Pay next to the hours: rates of positions and people's own rates, each from a day on, supplements for hours at a
time of day, the employee's month in "Mój grafik", the manager's "Godziny" report and its CSV, and who may set them."""

from datetime import timedelta
from decimal import Decimal

import pytest

from apps.pay.models import PaySupplement, PersonalRate, PositionRate
from apps.staffing.models import Position
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


def days(b):
    """Days of this month: the 1st, the 10th, the 20th, and its first Saturday and Sunday."""
    first = b["today"].replace(day=1)
    saturday = first + timedelta(days=(5 - first.weekday()) % 7)
    return first, first + timedelta(days=9), first + timedelta(days=19), saturday, saturday + timedelta(days=1)


def rate(position, value, valid_from=None):
    return PositionRate.objects.create(position=position, valid_from=valid_from, hourly_rate=Decimal(value))


def night(b, value="6", **fields):
    return PaySupplement.objects.create(
        location=b["location"], name="Noc", start_time="22:00", end_time="06:00", value=Decimal(value), **fields
    )


def csv_lines(api, b, day):
    text = api.get(f"/api/reports/hours.csv?company_id={b['company'].id}&month={day:%Y-%m}").content
    header, *lines = text.decode("utf-8-sig").strip().splitlines()
    return header, {line.split(";")[0]: line.split(";") for line in lines}


# --------------------------------------------------------------------------------------------- rates from a day


def test_a_position_rate_changes_only_from_its_day(api, bakery):
    b = bakery
    seller = b["position"]
    first, tenth, _, _, _ = days(b)
    b["shift"](b["ola"], first)
    b["shift"](b["ola"], tenth)
    api.login(b["manager"])
    path = f"/api/positions/{seller.id}/rates"

    started = api.post(path, {"hourly_rate": 30})  # the first rate: for every shift
    assert started.status_code == 200, started.json()
    assert [(s["valid_from"], s["hourly_rate"]) for s in started.json()["rates"]] == [(None, 30)]
    assert row_of(report(api, b, first), "Pracownik")["pay"] == 16 * 30

    raised = api.post(path, {"hourly_rate": 34.004, "valid_from": f"{tenth}"})
    assert [(s["valid_from"], s["hourly_rate"]) for s in raised.json()["rates"]] == [(None, 30), (f"{tenth}", 34)]
    assert row_of(report(api, b, first), "Pracownik")["pay"] == 8 * 30 + 8 * 34  # the 1st keeps the old rate
    again = api.post(path, {"hourly_rate": 35, "valid_from": f"{tenth}"})  # the same day: replaced
    assert [s["hourly_rate"] for s in again.json()["rates"]] == [30, 35]
    settings = api.get(f"/api/locations/{b['location'].id}/pay-settings").json()
    assert settings["positions"][0]["name"] == "Sprzedawca" and len(settings["positions"][0]["rates"]) == 2

    step = again.json()["rates"][1]["id"]
    assert api.client.delete(f"/api/position-rates/{step}").status_code == 200
    assert row_of(report(api, b, first), "Pracownik")["pay"] == 16 * 30  # a mistake removed: the old rate again

    api.post(path, {"hourly_rate": None, "valid_from": f"{tenth}"})  # no rate from the 10th
    ola = row_of(report(api, b, first), "Pracownik")
    assert (ola["pay"], ola["unpriced_hours"]) == (8 * 30, 8)
    for bad in (0, -5, 0.001, 20_000):
        refused = api.post(path, {"hourly_rate": bad, "valid_from": f"{tenth}"})
        assert refused.status_code == 400 and "większa od zera" in refused.json()["detail"]


def test_only_the_locations_manager_sees_and_sets_rates(api, bakery, make_company):
    b = bakery
    seller, location = b["position"], b["location"]
    supplement = {"name": "Noc", "start_time": "22:00", "end_time": "06:00", "weekdays": [0], "value": 6}
    step = rate(seller, "30")
    own = PersonalRate.objects.create(employee=b["ola"], position=seller, hourly_rate=Decimal("35"))
    made = night(b)
    calls = [
        lambda: api.client.delete(f"/api/position-rates/{step.id}"),
        lambda: api.client.delete(f"/api/personal-rates/{own.id}"),
        lambda: api.patch(f"/api/supplements/{made.id}", {**supplement, "change_from": "2026-12-01"}),
        lambda: api.client.delete(f"/api/supplements/{made.id}"),
        lambda: api.get(f"/api/locations/{location.id}/pay-settings"),
        lambda: api.get(f"/api/locations/{location.id}/personal-rates"),
        lambda: api.post(f"/api/positions/{seller.id}/rates", {"hourly_rate": 50}),
        lambda: api.post(f"/api/employees/{b['ola'].id}/rates", {"position_id": str(seller.id), "hourly_rate": 50}),
        lambda: api.post(f"/api/locations/{location.id}/supplements", supplement),
    ]
    for who, status in ((b["worker"], 403), (b["rynek_manager"], 403), (make_company("Obca")["manager"], 404)):
        api.login(who)
        assert [call().status_code for call in calls] == [status] * len(calls)
    assert PositionRate.objects.count() == PersonalRate.objects.count() == PaySupplement.objects.count() == 1
    assert PaySupplement.objects.get().weekdays == 0b1111111


def test_a_longer_record_gets_an_own_rate_from_a_day(api, bakery):
    b = bakery
    seller, ewa = b["position"], b["ewa"]
    first, tenth, twentieth, _, _ = days(b)
    rate(seller, "30")
    for day in (first, tenth, twentieth):
        b["shift"](ewa, day)
    api.login(b["manager"])
    path = f"/api/employees/{ewa.id}/rates"

    raised = api.post(path, {"position_id": str(seller.id), "hourly_rate": 35, "valid_from": f"{tenth}"})
    assert raised.status_code == 200, raised.json()
    assert [(s["valid_from"], s["hourly_rate"]) for s in raised.json()] == [(f"{tenth}", 35)]
    back = api.post(path, {"position_id": str(seller.id), "hourly_rate": None, "valid_from": f"{twentieth}"})
    assert [s["hourly_rate"] for s in back.json()] == [35, None]  # from the 20th the position's rate again

    assert row_of(report(api, b, first), "Ewa Nowak")["pay"] == 8 * 30 + 8 * 35 + 8 * 30
    listed = api.get(f"/api/locations/{b['location'].id}/personal-rates").json()
    assert {(s["employee_id"], s["valid_from"]) for s in listed} == {
        (str(ewa.id), f"{tenth}"),
        (str(ewa.id), f"{twentieth}"),
    }

    baker = Position.objects.create(location=b["location"], name="Piekarz")  # not hers
    refused = api.post(path, {"position_id": str(baker.id), "hourly_rate": 40})
    assert refused.status_code == 400 and "na którym ta osoba pracuje" in refused.json()["detail"]
    assert api.client.delete(f"/api/personal-rates/{listed[0]['id']}").status_code == 204
    assert row_of(report(api, b, first), "Ewa Nowak")["pay"] == 24 * 30


def test_an_own_rate_stays_for_past_shifts_when_the_position_goes(api, bakery):
    b = bakery
    seller, ola = b["position"], b["ola"]
    rate(seller, "30")
    PersonalRate.objects.create(employee=ola, position=seller, hourly_rate=Decimal("35"))
    day = b["today"]
    b["shift"](ola, day)
    api.login(b["manager"])

    gone = api.patch(f"/api/employees/{ola.id}", {"location_id": str(b["location"].id), "position_ids": []})

    assert gone.status_code == 200
    assert row_of(report(api, b, day), "Pracownik")["pay"] == 8 * 35


# --------------------------------------------------------------------------------------------- counting pay


def test_the_report_counts_pay_with_own_rates_overtime_and_missing_rates(api, bakery):
    b = bakery
    seller = b["position"]
    rate(seller, "31.40")
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
    assert body["pay"] == 580.3 and body["unpriced_hours"] == 4 and body["supplements_pay"] == 0
    header, cells = csv_lines(api, b, day)
    assert header.endswith(";Krótsze zmiany;Wypłata brutto, zł;W tym dodatki, zł;Godziny bez stawki;Uwagi")
    assert cells["Pracownik"][-4:-1] == ["298,30", "0,00", "0,00"]
    assert cells["Ewa Nowak"][-4:-1] == ["282,00", "0,00", "4,00"]


def test_without_rates_there_is_no_pay(api, bakery):
    b = bakery
    day = b["today"]
    b["shift"](b["ola"], day)
    night(b)  # a supplement alone pays nothing: it needs a rate
    api.login(b["manager"])

    body = report(api, b, day)

    assert body["pay"] is None and row_of(body, "Pracownik")["pay"] is None and body["supplements_pay"] is None
    assert body["unpriced_hours"] == 8
    assert csv_lines(api, b, day)[1]["Pracownik"][-4:-1] == ["", "", "8,00"]
    api.login(user_of(b["ola"]))
    month = my_month(api, b, day)
    assert (month["hours"], month["pay"], month["unpriced_hours"]) == (8, None, 8)


def test_the_employee_sees_the_pay_of_the_whole_month_in_every_location(api, bakery):
    b = bakery
    rate(b["position"], "31.40")
    till = Position.objects.create(location=b["rynek"], name="Kasa")
    rate(till, "40")
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
    rate(b["position"], "31.42")
    day = b["today"]
    for start, end in (((6, 0), (6, 20)), ((14, 20), (14, 40)), ((22, 40), (23, 0))):  # three shifts of 20 minutes
        b["shift"](b["ola"], day, start, end)
    api.login(user_of(b["ola"]))

    # 1 h × 31,42 zł; rounding each shift (10,47 zł) would give 31,41 zł.
    assert my_month(api, b, day)["pay"] == 31.42


# --------------------------------------------------------------------------------------------- supplements


def test_a_night_supplement_counts_only_the_hours_inside_it(api, bakery):
    b = bakery
    rate(b["position"], "30")
    night(b)  # every day, 22:00–06:00, +6 zł an hour
    first, tenth, _, _, _ = days(b)
    b["shift"](b["ola"], first, (20, 0), (4, 0))  # 6 of 8 hours at night
    b["shift"](b["ola"], tenth)  # 06:00–14:00: none
    api.login(user_of(b["ola"]))

    month = my_month(api, b, first)

    assert (month["pay"], month["supplements_pay"]) == (16 * 30 + 6 * 6, 36)
    api.login(b["manager"])
    assert csv_lines(api, b, first)[1]["Pracownik"][-4:-1] == ["516,00", "36,00", "0,00"]


def test_supplements_by_weekday_position_and_percent_add_up(api, bakery):
    b = bakery
    seller = b["position"]
    rate(seller, "30")
    driver = Position.objects.create(location=b["location"], name="Kierowca")
    rate(driver, "40")
    b["ola"].positions.add(driver)
    _, _, _, saturday, sunday = days(b)
    night(b, weekdays=1 << 5)  # Saturday nights only: Saturday 22:00 to Sunday 06:00
    sunday_bonus = PaySupplement.objects.create(
        location=b["location"],
        name="Niedziela",
        start_time="00:00",
        end_time="00:00",  # the whole day
        weekdays=1 << 6,
        kind=PaySupplement.Kind.PERCENT,
        value=Decimal(50),
        all_positions=False,
    )
    sunday_bonus.positions.set([seller])
    b["shift"](b["ola"], saturday, (22, 0), (6, 0))  # 8 h of Saturday night; 6 h of them on Sunday (+50%)
    b["shift"](b["ola"], sunday, (22, 0), (6, 0))  # Sunday night: 2 h of Sunday (+50%), no night supplement
    b["shift"](b["ola"], sunday, (8, 0), (12, 0), position=driver)  # not a seller: nothing extra
    api.login(user_of(b["ola"]))

    month = my_month(api, b, saturday)

    extra = 8 * 6 + 6 * 15 + 2 * 15
    assert (month["supplements_pay"], month["pay"]) == (extra, 16 * 30 + 4 * 40 + extra)


def test_a_supplement_changes_and_ends_from_a_day(api, bakery):
    b = bakery
    rate(b["position"], "30")
    first, tenth, twentieth, _, _ = days(b)
    for day in (first, tenth, twentieth):
        b["shift"](b["ola"], day, (22, 0), (6, 0))  # 8 h at night
    api.login(b["manager"])
    body = {"name": "Noc", "start_time": "22:00", "end_time": "06:00", "weekdays": list(range(7)), "value": 6}
    made = api.post(f"/api/locations/{b['location'].id}/supplements", body)
    assert made.status_code == 201, made.json()
    supplement = made.json()["id"]

    def extra():
        return row_of(report(api, b, first), "Pracownik")["supplements_pay"]

    assert extra() == 3 * 48
    renamed = api.patch(f"/api/supplements/{supplement}", {**body, "name": "Praca w nocy"})
    assert renamed.json()["id"] == supplement and renamed.json()["name"] == "Praca w nocy"  # in place
    no_day = api.patch(f"/api/supplements/{supplement}", {**body, "value": 8})
    assert no_day.status_code == 400 and "od którego dnia" in no_day.json()["detail"]

    raised = api.patch(f"/api/supplements/{supplement}", {**body, "value": 8, "change_from": f"{tenth}"})

    assert raised.status_code == 200 and raised.json()["id"] != supplement
    assert (raised.json()["valid_from"], raised.json()["value"]) == (f"{tenth}", 8)
    assert extra() == 48 + 2 * 64  # the 1st keeps 6 zł an hour
    settings = api.get(f"/api/locations/{b['location'].id}/pay-settings").json()
    assert [(s["valid_from"], s["valid_until"]) for s in settings["supplements"]] == [
        (None, f"{tenth - timedelta(days=1)}"),
        (f"{tenth}", None),
    ]
    assert api.client.delete(f"/api/supplements/{raised.json()['id']}?end_from={twentieth}").status_code == 204
    assert extra() == 48 + 64  # none from the 20th
    assert api.client.delete(f"/api/supplements/{raised.json()['id']}?end_from={tenth}").status_code == 204
    assert extra() == 48 and PaySupplement.objects.count() == 1  # it would start on that day: gone


def test_a_supplement_needs_days_an_amount_and_this_locations_positions(api, bakery):
    b = bakery
    api.login(b["manager"])
    path = f"/api/locations/{b['location'].id}/supplements"
    body = {"name": "Noc", "start_time": "22:00", "end_time": "06:00", "weekdays": [4, 5], "value": 6}
    till = Position.objects.create(location=b["rynek"], name="Kasa")
    for wrong, words in (
        ({"weekdays": []}, "dzień tygodnia"),
        ({"value": 0}, "większa od zera"),
        ({"kind": "percent", "value": 2000}, "od 1 do 1000"),
        ({"all_positions": False}, "Wybierz stanowiska"),
        ({"all_positions": False, "position_ids": [str(till.id)]}, "tego lokalu"),
    ):
        refused = api.post(path, {**body, **wrong})
        assert refused.status_code == 400 and words in refused.json()["detail"], (wrong, refused.json())

    made = api.post(path, {**body, "all_positions": False, "position_ids": [str(b["position"].id)]})

    assert made.status_code == 201 and made.json()["weekdays"] == [4, 5]
    assert made.json()["position_ids"] == [str(b["position"].id)]


def test_rates_do_not_cross_companies(bakery, make_company):
    from django.core.exceptions import ValidationError

    other = make_company("Obca")
    with pytest.raises(ValidationError):
        PersonalRate.objects.create(employee=other["employee"], position=bakery["position"], hourly_rate=Decimal("30"))
    stranger = add_employee(other["company"], other["location"], [other["position"]], "Zofia")
    with pytest.raises(ValidationError):
        PersonalRate.objects.create(employee=bakery["ola"], position=stranger.positions.get(), hourly_rate=Decimal(1))
    supplement = night(bakery)
    with pytest.raises(ValidationError):
        supplement.positions.add(other["position"])
