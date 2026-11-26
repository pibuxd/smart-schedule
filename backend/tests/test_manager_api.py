"""The manager's screens (stage 7): locations, settings, employees, availability overview, requests, rules."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.availability.models import AvailabilityDay, AvailabilitySubmission, TextRequest
from apps.notifications.models import Notification
from apps.rules.models import RuleSetting
from apps.scheduling.models import Assignment, SchedulePeriod, ScheduleVersion, Shift
from apps.staffing.models import (
    EmployeeProfile,
    LocationClosure,
    Position,
    PositionExperience,
    ShiftType,
    StaffingException,
    StaffingRule,
)
from apps.tenancy.models import Location, LocationGroup, Membership, Role
from engine.rules_catalog import RULES
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
    data["employee"].positions.add(data["position"])
    return data


def as_manager(api, shop):
    return api.login(shop["manager"])


def put(api, path, data):
    return api.client.put(path, data, content_type="application/json")


class TestOverviewAndLocations:
    def test_overview_shows_period_and_who_is_missing(self, api, shop):
        AvailabilitySubmission.objects.create(employee=shop["employee"], period=shop["period"])
        ewa = User.objects.create_user(next_phone(), first_name="Ewa", last_name="Nowak")
        membership = Membership.objects.create(company=shop["company"], user=ewa)
        EmployeeProfile.objects.create(membership=membership, home_location=shop["location"])
        body = as_manager(api, shop).get(f"/api/manager/overview?company_id={shop['company'].pk}").json()
        assert body["role"] == "owner" and body["subscription"]["read_only"] is False
        [location] = body["locations"]
        assert location["employees"] == 2
        assert location["period"]["id"] == str(shop["period"].pk)
        assert location["period"]["submitted"] == 1
        assert location["period"]["missing"] == ["Ewa Nowak"]

    def test_employee_cannot_open_the_manager_panel(self, api, shop):
        response = api.login(shop["worker"]).get(f"/api/manager/overview?company_id={shop['company'].pk}")
        assert response.status_code == 403

    def test_overview_lists_what_a_new_location_still_needs(self, api, shop):
        as_manager(api, shop)
        overview = f"/api/manager/overview?company_id={shop['company'].pk}"
        [row] = api.get(overview).json()["locations"]
        assert row["setup_missing"] == ["staffing"]
        Location.objects.create(company=shop["company"], name="Nowy")
        rows = {r["name"]: r for r in api.get(overview).json()["locations"]}
        assert rows["Nowy"]["setup_missing"] == ["positions", "shift_types", "staffing", "employees"]

    def test_create_location_starts_with_good_practice_rules(self, api, shop):
        response = as_manager(api, shop).post(
            "/api/locations", {"company_id": str(shop["company"].pk), "name": "Skawina", "schedule_period": "week"}
        )
        assert response.status_code == 201
        location = Location.objects.get(pk=response.json()["id"])
        codes = list(
            RuleSetting.objects.filter(location=location).order_by("position").values_list("rule_code", flat=True)
        )
        assert codes == [
            "min_rest_between_shifts",
            "max_consecutive_days",
            "fair_weekends",
            "fair_closings",
            "experience_mix",
            "personal_max_hours",
            "max_hours_per_day",
            "min_weekly_rest",
        ]
        hard = RuleSetting.objects.get(location=location, rule_code="personal_max_hours")
        assert hard.is_hard  # Piotr's decision: the personal maximum is kept, with 10 % to spare
        again = api.post("/api/locations", {"company_id": str(shop["company"].pk), "name": "Skawina"})
        assert again.status_code == 409

    def test_archive_hides_the_location_and_blocks_generation(self, api, shop):
        as_manager(api, shop)
        response = api.patch(f"/api/locations/{shop['location'].pk}", {"archived": True})
        assert response.status_code == 200 and response.json()["archived"] is True
        body = api.get(f"/api/manager/overview?company_id={shop['company'].pk}").json()
        assert body["locations"] == [] and body["archived"][0]["id"] == str(shop["location"].pk)
        generate = api.post("/api/periods/generate", {"period_ids": [str(shop["period"].pk)]})
        assert generate.status_code == 409 and "archiwum" in generate.json()["detail"]
        api.patch(f"/api/locations/{shop['location'].pk}", {"archived": False})
        assert Location.objects.get(pk=shop["location"].pk).archived_at is None

    def test_manager_of_a_location_cannot_archive_it(self, api, shop):
        user = User.objects.create_user(next_phone(), first_name="Teresa")
        membership = Membership.objects.create(company=shop["company"], user=user, role=Role.MANAGER)
        membership.locations.add(shop["location"])
        api.login(user)
        assert api.patch(f"/api/locations/{shop['location'].pk}", {"name": "Nowa nazwa"}).status_code == 200
        assert api.patch(f"/api/locations/{shop['location'].pk}", {"archived": True}).status_code == 403

    def test_overview_groups_follow_managed_locations(self, api, shop):
        company = shop["company"]
        mine = LocationGroup.objects.create(company=company, name="Kawiarnie")
        LocationGroup.objects.create(company=company, name="Piekarnie")
        shop["location"].group = mine
        shop["location"].save(update_fields=["group"])
        user = User.objects.create_user(next_phone())
        member = Membership.objects.create(company=company, user=user, role=Role.MANAGER)
        member.locations.add(shop["location"])
        body = api.login(user).get(f"/api/manager/overview?company_id={company.pk}").json()
        assert body["groups"] == [{"id": str(mine.pk), "name": mine.name}]

    def test_groups(self, api, shop):
        as_manager(api, shop)
        response = api.post("/api/groups", {"company_id": str(shop["company"].pk), "name": "Piekarnie"})
        assert response.status_code == 201
        moved = api.patch(f"/api/locations/{shop['location'].pk}", {"group_id": response.json()["id"]})
        assert moved.json()["group_name"] == "Piekarnie"


class TestSettings:
    def test_setup_lists_everything(self, api, shop):
        body = as_manager(api, shop).get(f"/api/locations/{shop['location'].pk}/setup").json()
        assert [p["name"] for p in body["positions"]] == ["Sprzedawca"]
        assert body["positions"][0]["employees"] == 1
        assert body["shift_types"][0]["start_time"] == "06:00:00"
        assert body["staffing"] == [] and body["exceptions"] == []

    def test_positions(self, api, shop):
        as_manager(api, shop)
        url = f"/api/locations/{shop['location'].pk}/positions"
        created = api.post(url, {"name": "Piekarz"})
        assert created.status_code == 201
        assert api.post(url, {"name": "Piekarz"}).status_code == 409
        position_id = created.json()["id"]
        assert api.patch(f"/api/positions/{position_id}", {"name": "Piekarz nocny"}).json()["name"] == "Piekarz nocny"
        assert api.client.delete(f"/api/positions/{position_id}").status_code == 204

    def test_position_used_in_a_schedule_is_hidden_instead_of_deleted(self, api, shop):
        version = ScheduleVersion.objects.create(period=shop["period"], number=1)
        start = datetime.combine(shop["period"].start, time(6), WARSAW)
        Shift.objects.create(
            version=version,
            location=shop["location"],
            date=shop["period"].start,
            position=shop["position"],
            start_at=start,
            end_at=start + timedelta(hours=8),
            slot_key="x",
        )
        StaffingRule.objects.create(
            location=shop["location"], weekday=0, shift_type=shop["shift_type"], position=shop["position"], count=1
        )
        setup = f"/api/locations/{shop['location'].pk}/setup"
        response = as_manager(api, shop).client.delete(f"/api/positions/{shop['position'].pk}")
        assert response.status_code == 204
        # The schedule keeps the position; settings, staffing and people no longer have it.
        assert Shift.objects.filter(position=shop["position"]).exists()
        body = api.get(setup).json()
        assert body["positions"] == [] and body["staffing"] == []
        assert not shop["employee"].positions.exists()
        assert api.patch(f"/api/positions/{shop['position'].pk}", {"name": "Inna"}).status_code == 404
        # The name is free again.
        created = api.post(f"/api/locations/{shop['location'].pk}/positions", {"name": "Sprzedawca"})
        assert created.status_code == 201

    def test_shift_types_fixed_need_hours_overnight_allowed(self, api, shop):
        as_manager(api, shop)
        url = f"/api/locations/{shop['location'].pk}/shift-types"
        assert api.post(url, {"name": "Nocna", "kind": "fixed"}).status_code == 400
        night = api.post(url, {"name": "Nocna", "start_time": "22:00", "end_time": "06:00"})
        assert night.status_code == 201
        flexible = api.post(url, {"name": "Dostawa", "kind": "flexible"})
        assert flexible.status_code == 201 and flexible.json()["start_time"] is None
        same = api.patch(
            f"/api/shift-types/{night.json()['id']}", {"name": "Nocna", "start_time": "06:00", "end_time": "06:00"}
        )
        assert same.status_code == 400

    def test_staffing_table_replaces_the_week(self, api, shop):
        as_manager(api, shop)
        flexible = ShiftType.objects.create(location=shop["location"], name="Dostawa", kind="flexible")
        base = {"shift_type_id": str(shop["shift_type"].pk), "position_id": str(shop["position"].pk)}
        cells = [{**base, "weekday": d, "count": 2} for d in range(5)] + [{**base, "weekday": 6, "count": 0}]
        cells.append(
            {
                "weekday": 1,
                "shift_type_id": str(flexible.pk),
                "position_id": str(shop["position"].pk),
                "count": 1,
                "start_time": "04:00",
                "end_time": "09:00",
            }
        )
        url = f"/api/locations/{shop['location'].pk}/staffing"
        body = put(api, url, {"cells": cells}).json()
        assert len(body["staffing"]) == 6
        assert StaffingRule.objects.get(shift_type=flexible).start_time == time(4)
        put(api, url, {"cells": cells[:1]})
        assert StaffingRule.objects.filter(location=shop["location"]).count() == 1

    def test_staffing_refuses_another_locations_shift(self, api, shop, make_company):
        other = make_company("Inna")
        as_manager(api, shop)
        cell = {
            "weekday": 0,
            "shift_type_id": str(other["shift_type"].pk),
            "position_id": str(shop["position"].pk),
            "count": 1,
        }
        assert put(api, f"/api/locations/{shop['location'].pk}/staffing", {"cells": [cell]}).status_code == 400

    def test_day_staffing_keeps_only_what_differs_from_the_weekday(self, api, shop):
        as_manager(api, shop)
        location, st, position = shop["location"], shop["shift_type"], shop["position"]
        day = date(2026, 12, 24)
        StaffingRule.objects.filter(location=location).delete()
        StaffingRule.objects.create(location=location, weekday=day.weekday(), shift_type=st, position=position, count=2)
        url = f"/api/locations/{location.pk}/staffing-days/{day}"
        cell = {"shift_type_id": str(st.pk), "position_id": str(position.pk)}

        body = put(api, url, {"cells": [{**cell, "count": 0}], "note": " Wigilia "}).json()
        assert [(e["date"], e["count"], e["note"]) for e in body["exceptions"]] == [(str(day), 0, "Wigilia")]

        put(api, url, {"cells": [{**cell, "count": 3, "start_time": "08:00", "end_time": "12:00"}]})
        saved = StaffingException.objects.get()
        assert (saved.count, f"{saved.start_time:%H:%M}", f"{saved.end_time:%H:%M}") == (3, "08:00", "12:00")

        # The usual number with the usual hours is not an exception; neither is a pair left out.
        usual = {**cell, "count": 2, "start_time": str(st.start_time), "end_time": str(st.end_time)}
        assert put(api, url, {"cells": [usual]}).json()["exceptions"] == []
        put(api, url, {"cells": [{**cell, "count": 1}]})
        assert put(api, url, {"cells": []}).json()["exceptions"] == []

    def test_day_staffing_checks_the_cells(self, api, shop, make_company):
        other = make_company("Inna")
        as_manager(api, shop)
        cell = {"shift_type_id": str(shop["shift_type"].pk), "position_id": str(shop["position"].pk)}
        url = f"/api/locations/{shop['location'].pk}/staffing-days/"
        foreign = {**cell, "shift_type_id": str(other["shift_type"].pk), "count": 1}
        assert put(api, url + "2026-12-24", {"cells": [foreign]}).status_code == 400
        assert put(api, url + "2026-12-24", {"cells": [{**cell, "count": 1, "experienced": 2}]}).status_code == 400
        assert put(api, url + "2099-12-24", {"cells": [{**cell, "count": 1}]}).status_code == 400
        flexible = ShiftType.objects.create(location=shop["location"], name="Dostawa", kind="flexible")
        delivery = {**cell, "shift_type_id": str(flexible.pk), "count": 1}
        refused = put(api, url + "2026-12-24", {"cells": [delivery]})
        assert refused.status_code == 400 and "godziny" in refused.json()["detail"]
        assert not StaffingException.objects.exists()
        api.login(other["manager"])
        assert put(api, url + "2026-12-24", {"cells": []}).status_code == 404

    def test_closed_days(self, api, shop):
        as_manager(api, shop)
        url = f"/api/locations/{shop['location'].pk}/closures"
        day = shop["period"].start
        created = api.post(url, {"date": str(day), "note": "  Remont  "})
        assert created.status_code == 201 and created.json()["note"] == "Remont"
        assert api.post(url, {"date": str(day)}).json()["detail"] == "Ten dzień jest już na liście dni zamknięcia."
        assert api.post(url, {"date": "0001-01-01"}).status_code == 400
        setup = api.get(f"/api/locations/{shop['location'].pk}/setup").json()
        assert [c["date"] for c in setup["closures"]] == [str(day)]
        assert api.client.delete(f"/api/closures/{created.json()['id']}").status_code == 204
        assert not LocationClosure.objects.exists()

    def test_closed_day_with_people_in_the_draft(self, api, shop):
        day = shop["period"].start
        version = ScheduleVersion.objects.create(period=shop["period"], number=1)
        start = datetime.combine(day, time(6), WARSAW)
        shift = Shift.objects.create(
            version=version,
            location=shop["location"],
            date=day,
            shift_type=shop["shift_type"],
            position=shop["position"],
            start_at=start,
            end_at=start + timedelta(hours=8),
            slot_key=f"{day}/{shop['shift_type'].pk}/{shop['position'].pk}/1",
        )
        Assignment.objects.create(shift=shift, employee=shop["employee"])
        as_manager(api, shop)
        url = f"/api/locations/{shop['location'].pk}/closures"
        assert api.post(url, {"date": str(day)}).json()["in_draft"] is True
        assert api.post(url, {"date": str(day + timedelta(days=1))}).json()["in_draft"] is False
        setup = api.get(f"/api/locations/{shop['location'].pk}/setup").json()
        assert [c["in_draft"] for c in setup["closures"]] == [True, False]
        assert [c["in_published"] for c in setup["closures"]] == [False, False]
        version.status = ScheduleVersion.Status.PUBLISHED
        version.save()
        setup = api.get(f"/api/locations/{shop['location'].pk}/setup").json()
        assert [(c["in_draft"], c["in_published"]) for c in setup["closures"]] == [(False, True), (False, False)]
        past = timezone.localdate() - timedelta(days=3)
        Shift.objects.filter(pk=shift.pk).update(date=past)
        LocationClosure.objects.create(company=shop["location"].company, location=shop["location"], date=past)
        setup = api.get(f"/api/locations/{shop['location'].pk}/setup").json()
        assert not any(c["in_draft"] or c["in_published"] for c in setup["closures"])


class TestEmployees:
    def test_stale_employee_form_cannot_remove_a_new_limit(self, api, shop):
        employee = shop["employee"]
        employees = as_manager(api, shop).get(f"/api/locations/{shop['location'].pk}/employees").json()
        revision = next(row["revision"] for row in employees if row["id"] == str(employee.pk))
        url = f"/api/employees/{employee.pk}"
        assert api.patch(url, {"max_hours_month": 16, "revision": revision}).status_code == 200
        assert api.patch(url, {"max_hours_month": None, "revision": revision}).status_code == 409
        employee.refresh_from_db()
        assert employee.max_hours_month == 16

    def test_list_and_update(self, api, shop):
        as_manager(api, shop)
        [row] = api.get(f"/api/locations/{shop['location'].pk}/employees").json()
        assert row["first_name"] == "Pracownik" and row["position_ids"] == [str(shop["position"].pk)]
        baker = Position.objects.create(location=shop["location"], name="Piekarz")
        body = api.patch(
            f"/api/employees/{row['id']}",
            {
                "max_hours_month": 160,
                "target_hours_month": 120,
                "position_ids": [str(baker.pk)],
            },
        ).json()
        assert "contract" not in body and body["position_ids"] == [str(baker.pk)]
        assert body["max_hours_month"] == 160
        cleared = api.patch(f"/api/employees/{row['id']}", {"max_hours_month": None}).json()
        assert cleared["max_hours_month"] is None and cleared["target_hours_month"] == 120

    def test_name_can_be_corrected_but_not_the_login_number(self, api, shop, make_company):
        as_manager(api, shop)
        url = f"/api/employees/{shop['employee'].pk}"
        body = api.patch(url, {"first_name": " Anna ", "last_name": "Nowak", "phone": "600 100 200"}).json()
        assert (body["first_name"], body["last_name"]) == ("Anna", "Nowak")
        # The phone number is the login: only the superadmin changes it (spec), so it is ignored here.
        assert body["phone"] == shop["worker"].phone_e164
        assert api.patch(url, {"first_name": ""}).json()["detail"] == "Wpisz imię."
        assert api.get("/api/me").json()["companies"][0]["works_shifts"] is False  # no "Mój grafik" in the menu
        api.post(f"/api/locations/{shop['location'].pk}/employees/me")
        assert api.get("/api/me").json()["companies"][0]["works_shifts"] is True
        # A person who also works for another company changes their own name.
        other = make_company("Inna")
        Membership.objects.create(company=other["company"], user=shop["worker"])
        shared = api.patch(url, {"first_name": "Ania"})
        assert shared.status_code == 409 and "innej firmie" in shared.json()["detail"]
        assert api.patch(url, {"first_name": "Anna", "max_hours_month": 100}).status_code == 200  # unchanged name

    def test_experience_level_is_set_by_the_manager(self, api, shop):
        as_manager(api, shop)
        url = f"/api/employees/{shop['employee'].pk}"
        [row] = api.get(f"/api/locations/{shop['location'].pk}/employees").json()
        assert row["experience"] == 2  # samodzielny until the manager says otherwise
        assert api.patch(url, {"experience": 1}).json()["experience"] == 1
        assert EmployeeProfile.objects.get(pk=shop["employee"].pk).experience == 1
        assert api.patch(url, {"experience": 4}).status_code == 422

    def test_level_can_differ_on_one_position(self, api, shop):
        as_manager(api, shop)
        seller = shop["position"]
        baker = Position.objects.create(location=shop["location"], name="Piekarz")
        url = f"/api/employees/{shop['employee'].pk}"
        levels = lambda body: {i["position_id"]: i["experience"] for i in body["position_experience"]}  # noqa: E731
        body = api.patch(
            url,
            {
                "position_ids": [str(seller.pk), str(baker.pk)],
                "experience": 3,
                "position_experience": [
                    {"position_id": str(seller.pk), "experience": 3},
                    {"position_id": str(baker.pk), "experience": 1},
                ],
            },
        ).json()
        assert levels(body) == {str(seller.pk): 3, str(baker.pk): 1}
        # Only what differs from the default is kept.
        assert list(PositionExperience.objects.values_list("position_id", "level")) == [(baker.pk, 1)]
        [row] = api.get(f"/api/locations/{shop['location'].pk}/employees").json()
        assert levels(row) == {str(seller.pk): 3, str(baker.pk): 1}
        # The default moving to the same level, or the position going away, drops the row.
        assert levels(api.patch(url, {"experience": 1}).json()) == {str(seller.pk): 1, str(baker.pk): 1}
        assert not PositionExperience.objects.exists()
        api.patch(url, {"position_experience": [{"position_id": str(baker.pk), "experience": 3}]})
        assert levels(api.patch(url, {"position_ids": [str(seller.pk)]}).json()) == {str(seller.pk): 1}
        assert not PositionExperience.objects.exists()

    def test_level_only_on_a_position_the_person_has(self, api, shop):
        as_manager(api, shop)
        other = Position.objects.create(location=shop["location"], name="Piekarz")
        payload = {"position_experience": [{"position_id": str(other.pk), "experience": 3}]}
        response = api.patch(f"/api/employees/{shop['employee'].pk}", payload)
        assert response.status_code == 400 and "stanowisku" in response.json()["detail"]

    def test_staffing_can_ask_for_experienced_people(self, api, shop):
        as_manager(api, shop)
        base = {"shift_type_id": str(shop["shift_type"].pk), "position_id": str(shop["position"].pk)}
        url = f"/api/locations/{shop['location'].pk}/staffing"
        body = put(api, url, {"cells": [{**base, "weekday": 0, "count": 2, "experienced": 1}]}).json()
        assert body["staffing"][0]["experienced"] == 1
        assert StaffingRule.objects.get().experienced == 1
        too_many = put(api, url, {"cells": [{**base, "weekday": 0, "count": 2, "experienced": 3}]})
        assert too_many.status_code == 400 and "Doświadczonych" in too_many.json()["detail"]
        day = f"/api/locations/{shop['location'].pk}/staffing-days/{shop['period'].start}"
        assert put(api, day, {"cells": [{**base, "count": 3, "experienced": 4}]}).status_code == 400
        saved = put(api, day, {"cells": [{**base, "count": 3, "experienced": 2}]}).json()
        assert saved["exceptions"][0]["experienced"] == 2

    def test_employee_never_sees_the_experience_level(self, api, shop):
        EmployeeProfile.objects.filter(pk=shop["employee"].pk).update(experience=1)
        api.login(shop["worker"])
        company = f"?company_id={shop['company'].pk}"
        for url in (
            "/api/me",
            "/api/me/availability" + company,
            "/api/me/requests" + company + f"&period_id={shop['period'].pk}",
            "/api/me/schedule" + company,
        ):
            response = api.get(url)
            assert response.status_code == 200, url
            assert "experience" not in response.content.decode() and "początkując" not in response.content.decode()
        assert api.get(f"/api/locations/{shop['location'].pk}/employees").status_code == 403

    def test_manager_adds_themselves_as_an_employee(self, api, shop, make_company):
        api.login(shop["manager"])
        url = f"/api/locations/{shop['location'].pk}/employees/me"

        me = api.post(url)

        assert me.status_code == 200, me.content
        body = me.json()
        assert body["is_manager"] and body["is_active"]
        assert body["position_ids"] == [str(shop["position"].pk)]  # every position: stands in for anyone
        assert len(api.get(f"/api/locations/{shop['location'].pk}/employees").json()) == 2
        assert api.get(f"/api/me/schedule?company_id={shop['company'].pk}").status_code == 200
        assert api.post(url).status_code == 409  # already on the list
        # Switched off earlier: adding again switches the same profile back on.
        api.patch(f"/api/employees/{body['id']}", {"is_active": False})
        again = api.post(url).json()
        assert again["id"] == body["id"] and again["is_active"]

    def test_only_a_manager_of_the_location_can_add_themselves(self, api, shop, make_company, subscribe):
        url = f"/api/locations/{shop['location'].pk}/employees/me"
        api.login(shop["worker"])
        assert api.post(url).status_code == 403
        api.login(make_company("Obca")["manager"])
        assert api.post(url).status_code == 404
        subscribe(shop["company"], days=-1)
        api.login(shop["manager"])
        assert api.post(url).status_code == 402

    def test_target_above_max_is_refused(self, api, shop):
        response = as_manager(api, shop).patch(
            f"/api/employees/{shop['employee'].pk}", {"max_hours_month": 80, "target_hours_month": 100}
        )
        assert response.status_code == 400

    def test_switch_off_keeps_the_person(self, api, shop):
        as_manager(api, shop).patch(f"/api/employees/{shop['employee'].pk}", {"is_active": False})
        profile = EmployeeProfile.objects.get(pk=shop["employee"].pk)
        assert profile.is_active is False

    def test_positions_of_another_location_are_refused(self, api, shop):
        other = Location.objects.create(company=shop["company"], name="Inny lokal")
        foreign = Position.objects.create(location=other, name="Kasjer")
        response = as_manager(api, shop).patch(
            f"/api/employees/{shop['employee'].pk}", {"position_ids": [str(foreign.pk)]}
        )
        assert response.status_code == 400


class TestAvailabilityOverview:
    def test_grid_marks_changes_after_the_deadline(self, api, shop):
        period = shop["period"]
        on_time = AvailabilityDay.objects.create(employee=shop["employee"], date=period.start, state="cannot")
        late = AvailabilityDay.objects.create(
            employee=shop["employee"],
            date=period.start + timedelta(days=1),
            state="prefer",
            from_time=time(6),
            to_time=time(14),
        )
        deadline_end = datetime.combine(period.deadline + timedelta(days=1), time(0), WARSAW)
        AvailabilityDay.objects.filter(pk=on_time.pk).update(updated_at=deadline_end - timedelta(minutes=1))
        AvailabilityDay.objects.filter(pk=late.pk).update(updated_at=deadline_end + timedelta(hours=2))
        body = as_manager(api, shop).get(f"/api/periods/{period.pk}/availability").json()
        assert body["period"]["deadline"] == str(period.deadline)
        [person] = body["employees"]
        assert person["positions"] == ["Sprzedawca"] and person["submitted_at"] is None
        assert [(d["state"], d["late"]) for d in person["days"]] == [("cannot", False), ("prefer", True)]
        assert person["days"][1]["from_time"] == "06:00:00"
        assert person["late_days"] == 1

    def test_a_deadline_in_the_past_does_not_make_earlier_changes_late(self, api, shop):
        period = shop["period"]
        entered = AvailabilityDay.objects.create(employee=shop["employee"], date=period.start, state="cannot")
        AvailabilityDay.objects.filter(pk=entered.pk).update(updated_at=timezone.now() - timedelta(days=1))
        as_manager(api, shop)
        yesterday = timezone.localdate() - timedelta(days=3)
        assert api.patch(f"/api/periods/{period.pk}", {"availability_deadline": str(yesterday)}).status_code == 200
        [person] = api.get(f"/api/periods/{period.pk}/availability").json()["employees"]
        assert person["late_days"] == 0  # entered before the manager set the deadline
        AvailabilityDay.objects.filter(pk=entered.pk).update(updated_at=timezone.now() + timedelta(minutes=1))
        [person] = api.get(f"/api/periods/{period.pk}/availability").json()["employees"]
        assert person["late_days"] == 1  # changed after it

    def test_deadline_set_by_the_manager(self, api, shop):
        as_manager(api, shop)
        period = shop["period"]
        new = period.start - timedelta(days=2)
        response = api.patch(f"/api/periods/{period.pk}", {"availability_deadline": str(new)})
        assert response.status_code == 200 and response.json()["deadline"] == str(new)
        too_late = api.patch(
            f"/api/periods/{period.pk}", {"availability_deadline": str(period.start + timedelta(days=1))}
        )
        assert too_late.status_code == 400
        employee_view = api.login(shop["worker"]).get(f"/api/me/availability?company_id={shop['company'].pk}").json()
        assert employee_view["period"]["deadline"] == str(new)

    def test_create_period_with_deadline(self, api, shop):
        start = shop["period"].end + timedelta(days=1)
        response = as_manager(api, shop).post(
            f"/api/locations/{shop['location'].pk}/periods",
            {
                "start": str(start),
                "end": str(start + timedelta(days=6)),
                "availability_deadline": str(start - timedelta(days=3)),
            },
        )
        assert response.status_code == 201 and response.json()["deadline"] == str(start - timedelta(days=3))

    @pytest.mark.parametrize(
        ("start", "end"), [("0001-01-02", "0001-01-03"), ("9999-12-30", "9999-12-31"), ("2010-01-01", "2010-01-07")]
    )
    def test_period_dates_far_from_today_are_refused(self, api, shop, start, end):
        url = f"/api/locations/{shop['location'].pk}/periods"
        response = as_manager(api, shop).post(url, {"start": start, "end": end})
        assert response.status_code == 400 and "Sprawdź rok" in response.json()["detail"]
        assert api.get(url).status_code == 200

    def test_deadline_far_before_the_period_is_refused(self, api, shop):
        period = shop["period"]
        response = as_manager(api, shop).patch(f"/api/periods/{period.pk}", {"availability_deadline": "0001-01-01"})
        assert response.status_code == 400

    def test_ask_for_availability_notifies_everyone_or_only_missing(self, api, shop):
        ewa = User.objects.create_user(next_phone(), first_name="Ewa")
        EmployeeProfile.objects.create(
            membership=Membership.objects.create(company=shop["company"], user=ewa), home_location=shop["location"]
        )
        url = f"/api/periods/{shop['period'].pk}/ask-availability"
        body = as_manager(api, shop).post(url, {}).json()
        assert body["notified"] == 2 and body["period"]["availability_requested_at"]
        note = Notification.objects.filter(user=ewa).get()
        assert note.kind == "availability_requested" and note.payload["deadline"] == str(shop["period"].deadline)
        AvailabilitySubmission.objects.create(employee=shop["employee"], period=shop["period"])
        assert api.post(url, {"only_missing": True}).json()["notified"] == 1
        shop["period"].status = SchedulePeriod.Status.DRAFT
        shop["period"].save()
        assert api.post(url, {}).status_code == 409

        # The notification opens "Kiedy mogę" on the period's month, and stops asking once the period is arranged.
        notes = f"/api/me/notifications?company_id={shop['company'].pk}"
        api.login(ewa)
        asked = api.get(notes).json()["notifications"][0]  # asked twice: everyone, then only the missing
        assert asked["link"] == "none" and asked["month"] is None and "jest już układany" in asked["text"]
        shop["period"].status = SchedulePeriod.Status.PUBLISHED
        shop["period"].save()
        asked = api.get(notes).json()["notifications"][0]
        assert asked["link"] == "schedule" and "jest już opublikowany" in asked["text"]
        shop["period"].status = SchedulePeriod.Status.COLLECTING
        shop["period"].save()
        asked = api.get(notes).json()["notifications"][0]
        month = max(shop["period"].start, timezone.localdate()).strftime("%Y-%m")
        assert asked["link"] == "availability" and asked["month"] == month and "Zaznacz, kiedy" in asked["text"]

    def test_requests_list_and_decisions(self, api, shop):
        row = TextRequest.objects.create(employee=shop["employee"], period=shop["period"], text="Nie z Markiem")
        as_manager(api, shop)
        [listed] = api.get(f"/api/periods/{shop['period'].pk}/requests").json()
        assert listed["employee_name"] == "Pracownik" and listed["summary"] is None
        body = api.patch(f"/api/requests/{row.pk}", {"manager_priority": "higher"}).json()
        assert body["manager_priority"] == "higher" and body["manager_rejected"] is False
        api.patch(f"/api/requests/{row.pk}", {"manager_rejected": True})
        assert TextRequest.objects.get(pk=row.pk).manager_rejected is True

    def test_employee_cannot_see_the_grid_or_requests(self, api, shop):
        api.login(shop["worker"])
        assert api.get(f"/api/periods/{shop['period'].pk}/availability").status_code == 403
        assert api.get(f"/api/periods/{shop['period'].pk}/requests").status_code == 403


class TestRules:
    @pytest.fixture
    def group(self, shop):
        group = LocationGroup.objects.create(company=shop["company"], name="Piekarnie")
        shop["location"].group = group
        shop["location"].save()
        for place, code in enumerate(["min_rest_between_shifts", "target_hours", "fair_weekends"], start=1):
            RuleSetting.objects.create(group=group, rule_code=code, position=place)
        return group

    def url(self, shop):
        return f"/api/scopes/location/{shop['location'].pk}/rules"

    def test_location_list_shows_group_rules_and_catalog(self, api, shop, group):
        RuleSetting.objects.create(location=shop["location"], rule_code="fair_weekends", position=3, enabled=False)
        body = as_manager(api, shop).get(self.url(shop)).json()
        assert body["group"]["name"] == "Piekarnie"
        items = {i["code"]: i for i in body["items"]}
        assert [i["code"] for i in body["items"][:3]] == ["min_rest_between_shifts", "target_hours", "fair_weekends"]
        assert items["min_rest_between_shifts"]["source"] == "group"
        assert items["min_rest_between_shifts"]["params"] == {"hours": 11}
        assert items["fair_weekends"]["source"] == "location" and items["fair_weekends"]["enabled"] is False
        assert items["max_shifts_per_week"]["source"] == "off"
        assert items["min_position_on_closing"]["location_only"] is True
        assert items["experience_mix"]["location_only"] is False
        assert len(body["items"]) == len(RULES)

    def test_reordered_rule_is_local_until_its_original_place_is_restored(self, api, shop, group):
        as_manager(api, shop)
        original = [
            {k: i[k] for k in ("code", "enabled", "is_hard", "params")} for i in api.get(self.url(shop)).json()["items"]
        ]
        moved = [original[1], original[0], *original[2:]]
        changed = put(api, self.url(shop), {"items": moved}).json()["items"][1]
        assert changed["source"] == "location" and changed["group_value"]["position"] == 1
        restored = put(api, self.url(shop), {"items": original}).json()["items"][0]
        assert restored["source"] == "group"

    def test_editor_moves_only_the_selected_group_rule_and_can_restore_it(self, api, shop, group):
        as_manager(api, shop)
        url = self.url(shop)
        items = [
            {k: item[k] for k in ("code", "enabled", "is_hard", "params")} for item in api.get(url).json()["items"]
        ]
        reordered = [items[1], items[0], *items[2:]]
        moved = put(api, url, {"items": reordered, "local_overrides": [items[1]["code"]]}).json()["items"]
        assert [(i["code"], i["source"]) for i in moved[:2]] == [
            (items[1]["code"], "location"),
            (items[0]["code"], "group"),
        ]
        restored = put(api, url, {"items": items, "local_overrides": []}).json()["items"]
        assert [i["code"] for i in restored] == [i["code"] for i in items]
        assert not RuleSetting.objects.filter(location=shop["location"]).exists()

    def test_saving_unchanged_list_keeps_following_the_group(self, api, shop, group):
        as_manager(api, shop)
        items = api.get(self.url(shop)).json()["items"]
        payload = {"items": [{k: i[k] for k in ("code", "enabled", "is_hard", "params")} for i in items]}
        assert put(api, self.url(shop), payload).status_code == 200
        assert not RuleSetting.objects.filter(location=shop["location"]).exists()

    def test_change_order_switch_and_hard(self, api, shop, group):
        as_manager(api, shop)
        items = [
            {k: i[k] for k in ("code", "enabled", "is_hard", "params")} for i in api.get(self.url(shop)).json()["items"]
        ]
        items[1]["is_hard"] = True  # target_hours without exceptions
        shifts = next(i for i in items if i["code"] == "max_shifts_per_week")
        shifts.update(enabled=True, params={"shifts": 4})
        body = put(api, self.url(shop), {"items": items}).json()
        by_code = {i["code"]: i for i in body["items"]}
        assert by_code["target_hours"]["source"] == "location" and by_code["target_hours"]["is_hard"] is True
        assert by_code["min_rest_between_shifts"]["source"] == "group"
        assert by_code["max_shifts_per_week"]["source"] == "own"
        assert RuleSetting.objects.get(location=shop["location"], rule_code="max_shifts_per_week").params == {
            "shifts": 4
        }

    def test_bad_params_are_refused(self, api, shop, group):
        as_manager(api, shop)
        url = self.url(shop)
        assert (
            put(
                api, url, {"items": [{"code": "max_consecutive_days", "enabled": True, "params": {"days": 0}}]}
            ).status_code
            == 400
        )
        closing = {"code": "min_position_on_closing", "enabled": True, "params": {"count": 1}}
        assert put(api, url, {"items": [closing]}).status_code == 400
        closing["params"]["position"] = "invalid"
        assert api.post(f"{url}/preview", {"items": [closing]}).status_code == 400
        closing["params"]["position"] = str(shop["position"].pk)
        assert put(api, url, {"items": [closing]}).status_code == 200
        assert api.client.delete(f"/api/positions/{shop['position'].pk}").status_code == 409
        group_url = f"/api/scopes/group/{group.pk}/rules"
        assert put(api, group_url, {"items": [closing]}).status_code == 400
        mix = {"code": "experience_mix", "enabled": True, "params": {}}
        assert put(api, url, {"items": [mix]}).status_code == 200  # no position = all positions together
        assert put(api, group_url, {"items": [mix]}).status_code == 200  # a group can use it too
        mix["params"]["position"] = str(shop["position"].pk)
        assert put(api, url, {"items": [mix]}).status_code == 200
        assert put(api, group_url, {"items": [mix]}).status_code == 400
        twice = {"code": "fair_closings", "enabled": True}
        assert put(api, url, {"items": [twice, twice]}).status_code == 400

    def test_group_list_saves_for_the_group(self, api, shop, group):
        as_manager(api, shop)
        url = f"/api/scopes/group/{group.pk}/rules"
        body = put(api, url, {"items": [{"code": "fair_closings", "enabled": True}]}).json()
        assert [i["code"] for i in body["items"] if i["source"] == "group"] == ["fair_closings"]
        assert list(RuleSetting.objects.filter(group=group).values_list("rule_code", flat=True)) == ["fair_closings"]

    def test_preview_without_a_schedule(self, api, shop, group):
        as_manager(api, shop)
        body = api.post(self.url(shop) + "/preview", {"items": [{"code": "fair_closings", "enabled": True}]}).json()
        assert body == {"lines": [], "period": None, "manager_rules_before": None, "manager_rules_after": None}

    def test_preview_counts_breaks_in_the_last_schedule(self, api, shop, group):
        period = shop["period"]
        version = ScheduleVersion.objects.create(period=period, number=1)
        for offset in range(6):  # six days in a row for one person
            day = period.start + timedelta(days=offset)
            start = datetime.combine(day, time(6), WARSAW)
            shift = Shift.objects.create(
                version=version,
                location=shop["location"],
                date=day,
                shift_type=shop["shift_type"],
                position=shop["position"],
                start_at=start,
                end_at=start + timedelta(hours=8),
                slot_key=f"{day}/{shop['shift_type'].pk}/{shop['position'].pk}/1",
            )
            Assignment.objects.create(shift=shift, employee=shop["employee"])
        as_manager(api, shop)
        items = [{"code": "max_consecutive_days", "enabled": True, "is_hard": True, "params": {"days": 4}}]
        body = api.post(self.url(shop) + "/preview", {"items": items}).json()
        assert body["period"].startswith(period.start.strftime("%d.%m"))
        assert any("„Dni pracy z rzędu” bez wyjątków" in line for line in body["lines"])
        assert any("przestanie się liczyć" in line for line in body["lines"])  # the group's rules left out


class TestIsolation:
    def test_other_company_gets_404(self, api, shop, make_company):
        other = make_company("Obca")
        api.login(other["manager"])
        location = shop["location"].pk
        for path in [
            f"/api/locations/{location}",
            f"/api/locations/{location}/setup",
            f"/api/locations/{location}/employees",
            f"/api/periods/{shop['period'].pk}/availability",
            f"/api/periods/{shop['period'].pk}/requests",
            f"/api/scopes/location/{location}/rules",
            f"/api/manager/overview?company_id={shop['company'].pk}",
        ]:
            assert api.get(path).status_code == 404, path
        assert api.patch(f"/api/employees/{shop['employee'].pk}", {"is_active": False}).status_code == 404
        assert api.patch(f"/api/positions/{shop['position'].pk}", {"name": "X"}).status_code == 404
        assert (
            api.patch(
                f"/api/shift-types/{shop['shift_type'].pk}", {"name": "X", "start_time": "06:00", "end_time": "14:00"}
            ).status_code
            == 404
        )
        assert api.patch(f"/api/locations/{location}", {"name": "X"}).status_code == 404
        assert api.post(f"/api/periods/{shop['period'].pk}/ask-availability", {}).status_code == 404
        assert put(api, f"/api/scopes/location/{location}/rules", {"items": []}).status_code == 404
        assert put(api, f"/api/locations/{location}/staffing", {"cells": []}).status_code == 404
        assert api.post(f"/api/locations/{location}/closures", {"date": str(shop["period"].start)}).status_code == 404
        closure = LocationClosure.objects.create(location=shop["location"], date=shop["period"].start)
        assert api.client.delete(f"/api/closures/{closure.pk}").status_code == 404

    def test_read_only_company_cannot_change_settings(self, api, shop, subscribe):
        subscribe(shop["company"], days=-1)
        as_manager(api, shop)
        assert api.post(f"/api/locations/{shop['location'].pk}/positions", {"name": "Piekarz"}).status_code == 402
        assert api.patch(f"/api/employees/{shop['employee'].pk}", {"is_active": False}).status_code == 402
        assert put(api, f"/api/scopes/location/{shop['location'].pk}/rules", {"items": []}).status_code == 402
        assert api.get(f"/api/locations/{shop['location'].pk}/setup").status_code == 200


def test_every_numeric_rule_parameter_has_an_allowed_range():
    from apps.rules.services import LOCATION_ONLY_PARAMS, NUMBER_PARAMS

    names = {name for rule in RULES for name in rule.params}
    assert names - LOCATION_ONLY_PARAMS - set(NUMBER_PARAMS) == set()
