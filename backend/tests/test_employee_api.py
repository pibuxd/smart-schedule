"""The employee's screens: "Kiedy mogę" (availability, repeats, copying, requests) and "Mój grafik"."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.availability.api import previous_month_day
from apps.availability.models import AvailabilityDay, AvailabilityPattern, AvailabilitySubmission, TextRequest
from apps.scheduling.models import Assignment, SchedulePeriod, ScheduleVersion, Shift
from apps.staffing.models import EmployeeProfile
from apps.tenancy.models import Membership
from tests.conftest import next_phone

WARSAW = ZoneInfo("Europe/Warsaw")


@pytest.fixture
def shop(make_company, subscribe):
    data = make_company("Złoty Kłos")
    subscribe(data["company"])
    today = timezone.localdate()
    start = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    data["period"] = SchedulePeriod.objects.create(location=data["location"], start=start, end=end)
    return data


def path(url, company):
    return f"{url}?company_id={company.pk}"


def put(api, payload):
    return api.client.put("/api/me/availability", payload, content_type="application/json")


class TestAvailability:
    def test_nearest_collecting_period_with_deadline(self, api, shop):
        api.login(shop["worker"])
        response = api.get(path("/api/me/availability", shop["company"]))
        assert response.status_code == 200
        body = response.json()
        assert body["period"]["id"] == str(shop["period"].pk)
        assert body["period"]["deadline"] == str(shop["period"].start - timedelta(days=7))
        assert body["period"]["editable"] is True
        assert body["days"] == [] and body["submitted_at"] is None

    def test_no_open_period_gives_empty_screen(self, api, shop):
        shop["period"].status = SchedulePeriod.Status.DRAFT
        shop["period"].save()
        api.login(shop["worker"])
        body = api.get(path("/api/me/availability", shop["company"])).json()
        assert body == {"period": None, "days": [], "submitted_at": None}

    def test_save_days_with_hours_and_overwrite(self, api, shop):
        api.login(shop["worker"])
        start = shop["period"].start
        payload = {
            "company_id": str(shop["company"].pk),
            "period_id": str(shop["period"].pk),
            "days": [
                {"date": str(start), "state": "cannot"},
                {"date": str(start + timedelta(days=1)), "state": "prefer", "from_time": "22:00", "to_time": "06:00"},
            ],
        }
        assert put(api, payload).status_code == 200
        payload["days"] = [{"date": str(start), "state": "neutral"}]
        body = put(api, payload).json()
        assert [(d["date"], d["state"], d["from_time"], d["to_time"]) for d in body["days"]] == [
            (str(start), "neutral", None, None),
            (str(start + timedelta(days=1)), "prefer", "22:00:00", "06:00:00"),
        ]

    def test_prefer_not_is_no_longer_accepted(self, api, shop):
        api.login(shop["worker"])
        payload = {
            "company_id": str(shop["company"].pk),
            "period_id": str(shop["period"].pk),
            "days": [{"date": str(shop["period"].start), "state": "prefer_not"}],
        }
        assert put(api, payload).status_code == 422

    def test_days_outside_period_or_empty_hours_are_refused(self, api, shop):
        api.login(shop["worker"])
        base = {"company_id": str(shop["company"].pk), "period_id": str(shop["period"].pk)}
        outside = put(api, {**base, "days": [{"date": str(shop["period"].end + timedelta(days=1)), "state": "cannot"}]})
        assert outside.status_code == 400
        empty = {"date": str(shop["period"].start), "state": "prefer", "from_time": "10:00", "to_time": "10:00"}
        assert put(api, {**base, "days": [empty]}).status_code == 400
        assert AvailabilityDay.objects.count() == 0

    def test_closed_period_cannot_be_changed(self, api, shop):
        shop["period"].status = SchedulePeriod.Status.DRAFT
        shop["period"].save()
        api.login(shop["worker"])
        payload = {
            "company_id": str(shop["company"].pk),
            "period_id": str(shop["period"].pk),
            "days": [{"date": str(shop["period"].start), "state": "cannot"}],
        }
        response = put(api, payload)
        assert response.status_code == 409
        assert "Termin" in response.json()["detail"]

    def test_read_only_company_cannot_change(self, api, shop, subscribe):
        subscribe(shop["company"], days=-1)
        api.login(shop["worker"])
        payload = {
            "company_id": str(shop["company"].pk),
            "period_id": str(shop["period"].pk),
            "days": [{"date": str(shop["period"].start), "state": "cannot"}],
        }
        assert put(api, payload).status_code == 402
        assert api.get(path("/api/me/availability", shop["company"])).status_code == 200

    def test_repeat_every_week_until_a_date(self, api, shop):
        api.login(shop["worker"])
        period = shop["period"]
        until = period.end + timedelta(days=30)
        response = api.post(
            "/api/me/availability/pattern",
            {
                "company_id": str(shop["company"].pk),
                "period_id": str(period.pk),
                "weekdays": [1, 3],
                "state": "cannot",
                "repeat_until": str(until),
            },
        )
        assert response.status_code == 200
        marked = AvailabilityDay.objects.filter(employee=shop["employee"])
        assert marked.count() > 0
        assert {d.date.weekday() for d in marked} == {1, 3}
        assert max(d.date for d in marked) <= until
        assert min(d.date for d in marked) >= period.start
        assert {d.source for d in marked} == {"pattern"}
        assert AvailabilityPattern.objects.filter(employee=shop["employee"]).count() == 2
        in_period = [d for d in response.json()["days"]]
        assert all(period.start <= date.fromisoformat(d["date"]) <= period.end for d in in_period)

    def test_copy_from_previous_month_keeps_weekdays(self, api, shop):
        period = shop["period"]
        earlier = period.start - timedelta(days=28)
        AvailabilityDay.objects.create(employee=shop["employee"], date=earlier, state="prefer", from_time=time(14))
        api.login(shop["worker"])
        response = api.post(
            "/api/me/availability/copy-previous",
            {"company_id": str(shop["company"].pk), "period_id": str(period.pk)},
        )
        assert response.status_code == 200
        copied = AvailabilityDay.objects.get(employee=shop["employee"], date=period.start)
        assert (copied.state, copied.from_time, copied.source) == ("prefer", time(14), "copy")
        assert copied.date.weekday() == earlier.weekday()

    def test_copy_with_nothing_earlier_says_so(self, api, shop):
        api.login(shop["worker"])
        response = api.post(
            "/api/me/availability/copy-previous",
            {"company_id": str(shop["company"].pk), "period_id": str(shop["period"].pk)},
        )
        assert response.status_code == 400

    def test_submit_is_idempotent(self, api, shop):
        api.login(shop["worker"])
        payload = {"company_id": str(shop["company"].pk), "period_id": str(shop["period"].pk)}
        first = api.post("/api/me/availability/submit", payload).json()
        second = api.post("/api/me/availability/submit", payload).json()
        assert first["submitted_at"] and first["submitted_at"] == second["submitted_at"]
        assert AvailabilitySubmission.objects.count() == 1


def test_previous_month_day_is_same_weekday_before_the_period():
    start = date(2026, 12, 1)
    for offset in range(31):
        day = start + timedelta(days=offset)
        source = previous_month_day(day, start)
        assert source < start and source.weekday() == day.weekday()


class TestRequests:
    def test_write_list_and_take_back(self, api, shop):
        api.login(shop["worker"])
        created = api.post(
            "/api/me/requests",
            {
                "company_id": str(shop["company"].pk),
                "period_id": str(shop["period"].pk),
                "text": "  Nie chcę dwóch nocek pod rząd.  ",
            },
        )
        assert created.status_code == 201
        assert created.json()["text"] == "Nie chcę dwóch nocek pod rząd."
        listed = api.get(f"/api/me/requests?company_id={shop['company'].pk}&period_id={shop['period'].pk}").json()
        assert [r["id"] for r in listed] == [created.json()["id"]]
        deleted = api.client.delete(f"/api/me/requests/{created.json()['id']}")
        assert deleted.status_code == 204
        assert TextRequest.objects.count() == 0

    def test_cannot_take_back_a_colleagues_request(self, api, shop):
        colleague = Membership.objects.create(company=shop["company"], user=_user())
        profile = EmployeeProfile.objects.create(membership=colleague, home_location=shop["location"])
        theirs = TextRequest.objects.create(employee=profile, period=shop["period"], text="Proszę o ranne zmiany.")
        api.login(shop["worker"])
        assert api.client.delete(f"/api/me/requests/{theirs.pk}").status_code == 404
        assert TextRequest.objects.filter(pk=theirs.pk).exists()


def _user(first="Anna", last="Wróbel"):
    from apps.accounts.models import User

    return User.objects.create_user(next_phone(), first_name=first, last_name=last)


class TestOtherCompanies:
    def test_other_companys_period_and_company_are_hidden(self, api, shop, make_company, subscribe):
        other = make_company("Kawiarnia")
        subscribe(other["company"])
        other_period = SchedulePeriod.objects.create(
            location=other["location"], start=shop["period"].start, end=shop["period"].end
        )
        api.login(shop["worker"])
        assert api.get(path("/api/me/availability", other["company"])).status_code == 404
        assert api.get(path("/api/me/schedule", other["company"])).status_code == 404
        payload = {
            "company_id": str(shop["company"].pk),
            "period_id": str(other_period.pk),
            "days": [{"date": str(other_period.start), "state": "cannot"}],
        }
        assert put(api, payload).status_code == 404
        assert (
            api.get(f"/api/me/availability?company_id={shop['company'].pk}&period_id={other_period.pk}").status_code
            == 404
        )
        theirs = TextRequest.objects.create(employee=other["employee"], period=other_period, text="Proszę o wolne.")
        assert api.client.delete(f"/api/me/requests/{theirs.pk}").status_code == 404

    def test_manager_without_employee_profile_gets_a_clear_404(self, api, shop):
        api.login(shop["manager"])
        response = api.get(path("/api/me/availability", shop["company"]))
        assert response.status_code == 404
        assert "pracownikiem" in response.json()["detail"]


def _shift(version, location, position, shift_type, day, start, end, employee, slot):
    start_at = datetime.combine(day, start, WARSAW)
    end_day = day + timedelta(days=1) if end <= start else day
    shift = Shift.objects.create(
        version=version,
        location=location,
        date=day,
        shift_type=shift_type,
        position=position,
        start_at=start_at,
        end_at=datetime.combine(end_day, end, WARSAW),
        slot_key=slot,
    )
    Assignment.objects.create(shift=shift, employee=employee)
    return shift


class TestMySchedule:
    def test_published_shifts_coworkers_and_hours(self, api, shop):
        today = timezone.localdate()
        location, position, shift_type = shop["location"], shop["position"], shop["shift_type"]
        period = SchedulePeriod.objects.create(
            location=location, start=today - timedelta(days=3), end=today + timedelta(days=20)
        )
        version = ScheduleVersion.objects.create(period=period, number=1, status=ScheduleVersion.Status.PUBLISHED)
        draft = ScheduleVersion.objects.create(period=period, number=2)
        anna = EmployeeProfile.objects.create(
            membership=Membership.objects.create(company=shop["company"], user=_user()), home_location=location
        )
        me = shop["employee"]
        _shift(version, location, position, shift_type, today - timedelta(days=1), time(6), time(14), me, "past")
        tomorrow = today + timedelta(days=1)
        _shift(version, location, position, shift_type, tomorrow, time(6), time(14), me, "a")
        _shift(version, location, position, shift_type, tomorrow, time(10), time(18), anna, "b")
        _shift(version, location, position, shift_type, tomorrow, time(14), time(22), None, "hole")
        _shift(version, location, position, None, today + timedelta(days=2), time(22), time(6), me, "night")
        _shift(draft, location, position, shift_type, today + timedelta(days=3), time(6), time(14), me, "draft")

        api.login(shop["worker"])
        body = api.get(path("/api/me/schedule", shop["company"])).json()
        shifts = body["shifts"]
        assert [s["date"] for s in shifts] == [str(tomorrow), str(today + timedelta(days=2))]
        assert shifts[0]["start_time"] == "06:00" and shifts[0]["end_time"] == "14:00"
        assert shifts[0]["coworkers"] == ["Anna Wróbel"]
        assert shifts[0]["position_name"] == "Sprzedawca" and shifts[0]["shift_type_name"] == "Ranna"
        assert shifts[1]["hours"] == 8 and shifts[1]["end_time"] == "06:00" and shifts[1]["away"] is False
        months = {m["month"] for m in body["months"]}
        mine = [today - timedelta(days=1), tomorrow, today + timedelta(days=2)]
        expected = sum(8 for d in mine if d.strftime("%Y-%m") in months)  # past days count, drafts do not
        assert sum(m["hours"] for m in body["months"]) == expected
        assert body["months"][0]["month"] == today.strftime("%Y-%m")

    def test_empty_when_nothing_is_published(self, api, shop):
        api.login(shop["worker"])
        body = api.get(path("/api/me/schedule", shop["company"])).json()
        assert body["shifts"] == []
        assert body["months"] == [{"month": timezone.localdate().strftime("%Y-%m"), "hours": 0.0}]
        assert body["home_location_name"] == shop["location"].name


def test_publish_helper_supersedes_the_previous_version(shop):
    from apps.scheduling.management.commands.generate_schedule import publish_version

    period = shop["period"]
    old = ScheduleVersion.objects.create(period=period, number=1, status=ScheduleVersion.Status.PUBLISHED)
    new = ScheduleVersion.objects.create(period=period, number=2)
    publish_version(new)
    old.refresh_from_db()
    period.refresh_from_db()
    assert (old.status, new.status, period.status) == ("superseded", "published", "published")
