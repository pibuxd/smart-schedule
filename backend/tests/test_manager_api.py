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
from apps.staffing.models import EmployeeProfile, Position, ShiftType, StaffingException, StaffingRule
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

    def test_create_location_starts_with_good_practice_rules(self, api, shop):
        response = as_manager(api, shop).post(
            "/api/locations", {"company_id": str(shop["company"].pk), "name": "Skawina", "schedule_period": "week"}
        )
        assert response.status_code == 201
        location = Location.objects.get(pk=response.json()["id"])
        codes = list(
            RuleSetting.objects.filter(location=location).order_by("position").values_list("rule_code", flat=True)
        )
        assert codes == ["min_rest_between_shifts", "max_consecutive_days", "fair_weekends", "fair_closings"]
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

    def test_position_used_in_a_schedule_cannot_be_deleted(self, api, shop):
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
        response = as_manager(api, shop).client.delete(f"/api/positions/{shop['position'].pk}")
        assert response.status_code == 409 and "w ułożonym grafiku" in response.json()["detail"]

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

    def test_exceptions(self, api, shop):
        as_manager(api, shop)
        url = f"/api/locations/{shop['location'].pk}/staffing-exceptions"
        payload = {
            "date": str(date(2026, 12, 24)),
            "shift_type_id": str(shop["shift_type"].pk),
            "position_id": str(shop["position"].pk),
            "count": 0,
            "note": "Wigilia",
        }
        created = api.post(url, payload)
        assert created.status_code == 201
        assert api.post(url, payload).status_code == 409
        assert api.client.delete(f"/api/staffing-exceptions/{created.json()['id']}").status_code == 204
        assert not StaffingException.objects.exists()


class TestEmployees:
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
        assert len(body["items"]) == len(RULES)

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
        closing["params"]["position"] = str(shop["position"].pk)
        assert put(api, url, {"items": [closing]}).status_code == 200
        group_url = f"/api/scopes/group/{group.pk}/rules"
        assert put(api, group_url, {"items": [closing]}).status_code == 400
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
