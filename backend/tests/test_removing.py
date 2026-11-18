"""Removing things for good: people from a location, notifications, groups, locations and periods."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.assistant.models import ManagerInstruction
from apps.notifications.models import Notification
from apps.rules.models import RuleSetting
from apps.scheduling.models import Assignment, SchedulePeriod, ScheduleVersion, Shift
from apps.staffing.models import EmployeeProfile
from apps.tenancy.models import Invitation, Location, LocationGroup, Membership, Role
from tests.conftest import next_phone

WARSAW = ZoneInfo("Europe/Warsaw")


@pytest.fixture
def shop(make_company, subscribe):
    data = make_company("Złoty Kłos")
    subscribe(data["company"])
    today = timezone.localdate()
    start = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    data["period"] = SchedulePeriod.objects.create(
        location=data["location"], start=start, end=start + timedelta(days=27)
    )
    data["employee"].positions.add(data["position"])
    return data


def schedule(shop, *, published: bool) -> Assignment:
    """One shift of the employee in a version of the period."""
    version = ScheduleVersion.objects.create(
        period=shop["period"],
        number=1,
        status=ScheduleVersion.Status.PUBLISHED if published else ScheduleVersion.Status.DRAFT,
        published_at=timezone.now() if published else None,
    )
    start = datetime.combine(shop["period"].start, time(6), WARSAW)
    shift = Shift.objects.create(
        version=version,
        location=shop["location"],
        date=shop["period"].start,
        shift_type=shop["shift_type"],
        position=shop["position"],
        start_at=start,
        end_at=start + timedelta(hours=8),
        slot_key="x",
    )
    return Assignment.objects.create(shift=shift, employee=shop["employee"])


def me_companies(api, user) -> list:
    return [c["id"] for c in api.login(user).get("/api/me").json()["companies"]]


class TestRemoveEmployee:
    def test_person_without_shifts_is_deleted_and_can_be_invited_again(self, api, shop):
        api.login(shop["manager"])
        employees = f"/api/locations/{shop['location'].pk}/employees"
        assert api.client.delete(f"/api/employees/{shop['employee'].pk}").status_code == 204
        assert api.get(employees).json() == []
        assert not EmployeeProfile.objects.filter(pk=shop["employee"].pk).exists()
        assert not Membership.objects.filter(user=shop["worker"]).exists()
        assert api.client.delete(f"/api/employees/{shop['employee'].pk}").status_code == 404

        invited = api.post(f"/api/locations/{shop['location'].pk}/invitations", {"phone": shop["worker"].phone_e164})
        assert invited.status_code == 201
        assert api.login(shop["worker"]).post(f"/api/invitations/{invited.json()['id']}/accept").status_code == 200
        assert len(api.login(shop["manager"]).get(employees).json()) == 1

    def test_person_with_shifts_is_hidden_and_loses_access(self, api, shop):
        assignment = schedule(shop, published=True)
        ManagerInstruction.objects.create(
            location=shop["location"], employee=shop["employee"], data={"type": "inne"}, position=1
        )
        company = str(shop["company"].pk)
        assert me_companies(api, shop["worker"]) == [company]

        api.login(shop["manager"])
        assert api.client.delete(f"/api/employees/{shop['employee'].pk}").status_code == 204
        assert api.get(f"/api/locations/{shop['location'].pk}/employees").json() == []
        overview = api.get(f"/api/manager/overview?company_id={company}").json()
        assert overview["locations"][0]["employees"] == 0
        # History stays: the shift still belongs to the person.
        assignment.refresh_from_db()
        profile = EmployeeProfile.objects.get(pk=shop["employee"].pk)
        assert assignment.employee_id == profile.pk
        assert profile.removed_at is not None and not profile.is_active and not profile.positions.exists()
        assert not ManagerInstruction.objects.filter(employee=profile).exists()
        assert api.patch(f"/api/employees/{profile.pk}", {"is_active": True}).status_code == 404

        assert me_companies(api, shop["worker"]) == []
        assert api.get(f"/api/me/schedule?company_id={company}").status_code == 404
        assert api.get(f"/api/me/notifications?company_id={company}").status_code == 404

    def test_removed_person_comes_back_through_an_invitation(self, api, shop):
        schedule(shop, published=True)
        api.login(shop["manager"])
        api.client.delete(f"/api/employees/{shop['employee'].pk}")
        invited = api.post(f"/api/locations/{shop['location'].pk}/invitations", {"phone": shop["worker"].phone_e164})
        assert invited.status_code == 201
        assert api.login(shop["worker"]).post(f"/api/invitations/{invited.json()['id']}/accept").status_code == 200
        profile = EmployeeProfile.objects.get(pk=shop["employee"].pk)
        assert profile.removed_at is None and profile.is_active
        assert me_companies(api, shop["worker"]) == [str(shop["company"].pk)]
        [row] = api.login(shop["manager"]).get(f"/api/locations/{shop['location'].pk}/employees").json()
        assert row["id"] == str(profile.pk)

    def test_manager_who_worked_shifts_keeps_managing(self, api, shop):
        api.login(shop["manager"])
        added = api.post(f"/api/locations/{shop['location'].pk}/employees/me")
        assert added.status_code == 200
        assert api.client.delete(f"/api/employees/{added.json()['id']}").status_code == 204
        assert Membership.objects.filter(user=shop["manager"], role=Role.OWNER).exists()
        assert api.get(f"/api/locations/{shop['location'].pk}/employees").status_code == 200

    def test_only_the_locations_manager_in_a_writable_company(self, api, shop, make_company, subscribe):
        url = f"/api/employees/{shop['employee'].pk}"
        assert api.login(make_company("Obca")["manager"]).client.delete(url).status_code == 404
        colleague = User.objects.create_user(next_phone())
        membership = Membership.objects.create(company=shop["company"], user=colleague)
        EmployeeProfile.objects.create(membership=membership, home_location=shop["location"])
        assert api.login(colleague).client.delete(url).status_code == 403
        subscribe(shop["company"], days=-1)
        assert api.login(shop["manager"]).client.delete(url).status_code == 402
        assert EmployeeProfile.objects.filter(pk=shop["employee"].pk).exists()


class TestDismissNotifications:
    def test_dismiss_one_and_all(self, api, shop, make_company):
        company = shop["company"]
        mine = [
            Notification.objects.create(company=company, user=shop["worker"], kind="schedule_published")
            for _ in range(3)
        ]
        theirs = Notification.objects.create(company=company, user=shop["manager"], kind="schedule_published")
        api.login(shop["worker"])
        assert api.client.delete(f"/api/me/notifications/{mine[0].pk}").status_code == 204
        assert api.client.delete(f"/api/me/notifications/{mine[0].pk}").status_code == 404
        # Someone else's notification, in my company or another one, does not exist for me.
        assert api.client.delete(f"/api/me/notifications/{theirs.pk}").status_code == 404
        other = make_company("Obca")
        foreign = Notification.objects.create(company=other["company"], user=other["worker"], kind="x")
        assert api.client.delete(f"/api/me/notifications/{foreign.pk}").status_code == 404
        body = api.get(f"/api/me/notifications?company_id={company.pk}").json()
        assert len(body["notifications"]) == 2

        assert api.client.delete(f"/api/me/notifications?company_id={company.pk}").status_code == 204
        assert api.get(f"/api/me/notifications?company_id={company.pk}").json()["notifications"] == []
        assert Notification.objects.filter(pk__in=[theirs.pk, foreign.pk]).count() == 2
        assert api.client.delete(f"/api/me/notifications?company_id={other['company'].pk}").status_code == 404

    def test_works_in_read_only_mode(self, api, shop, subscribe):
        subscribe(shop["company"], days=-1)
        row = Notification.objects.create(company=shop["company"], user=shop["worker"], kind="schedule_published")
        assert api.login(shop["worker"]).client.delete(f"/api/me/notifications/{row.pk}").status_code == 204


class TestDeleteGroup:
    def test_locations_keep_the_groups_rules_as_their_own(self, api, shop):
        group = LocationGroup.objects.create(company=shop["company"], name="Piekarnie")
        location = shop["location"]
        location.group = group
        location.save()
        RuleSetting.objects.create(group=group, rule_code="min_rest_between_shifts", position=1, params={"hours": 12})
        RuleSetting.objects.create(group=group, rule_code="fair_weekends", position=1, enabled=False)
        RuleSetting.objects.create(group=group, rule_code="max_consecutive_days", position=2, params={"days": 5})
        RuleSetting.objects.create(location=location, rule_code="max_consecutive_days", position=1, params={"days": 3})
        rules = f"/api/scopes/location/{location.pk}/rules"
        api.login(shop["manager"])
        before = [(i["code"], i["enabled"], i["params"]) for i in api.get(rules).json()["items"]]

        assert api.client.delete(f"/api/groups/{group.pk}").status_code == 204
        assert not LocationGroup.objects.filter(pk=group.pk).exists()
        location.refresh_from_db()
        assert location.group_id is None
        after = [(i["code"], i["enabled"], i["params"]) for i in api.get(rules).json()["items"]]
        assert after == before
        assert RuleSetting.objects.get(location=location, rule_code="max_consecutive_days").params == {"days": 3}
        overview = api.get(f"/api/manager/overview?company_id={shop['company'].pk}").json()
        assert overview["groups"] == []

    def test_owner_only(self, api, shop, make_company):
        group = LocationGroup.objects.create(company=shop["company"], name="Piekarnie")
        url = f"/api/groups/{group.pk}"
        assert api.login(make_company("Obca")["manager"]).client.delete(url).status_code == 404
        boss = User.objects.create_user(next_phone())
        membership = Membership.objects.create(company=shop["company"], user=boss, role=Role.MANAGER)
        membership.locations.add(shop["location"])
        assert api.login(boss).client.delete(url).status_code == 403
        assert LocationGroup.objects.filter(pk=group.pk).exists()


class TestDeleteLocation:
    def test_empty_location_is_deleted(self, api, shop):
        spare = Location.objects.create(company=shop["company"], name="Pomyłka")
        Invitation.objects.create(location=spare, phone_e164=next_phone())
        api.login(shop["manager"])
        assert api.client.delete(f"/api/locations/{spare.pk}").status_code == 204
        assert not Location.objects.filter(pk=spare.pk).exists()

    def test_location_with_people_or_schedules_stays(self, api, shop):
        api.login(shop["manager"])
        url = f"/api/locations/{shop['location'].pk}"
        response = api.client.delete(url)
        assert response.status_code == 409 and "archiwum" in response.json()["detail"]
        shop["period"].delete()
        response = api.client.delete(url)
        assert response.status_code == 409 and "pracowników" in response.json()["detail"]
        assert api.client.delete(f"/api/employees/{shop['employee'].pk}").status_code == 204
        assert api.client.delete(url).status_code == 204

    def test_owner_only(self, api, shop, make_company):
        spare = Location.objects.create(company=shop["company"], name="Pomyłka")
        url = f"/api/locations/{spare.pk}"
        assert api.login(make_company("Obca")["manager"]).client.delete(url).status_code == 404
        boss = User.objects.create_user(next_phone())
        membership = Membership.objects.create(company=shop["company"], user=boss, role=Role.MANAGER)
        membership.locations.add(spare)
        assert api.login(boss).client.delete(url).status_code == 403
        assert Location.objects.filter(pk=spare.pk).exists()


class TestDeletePeriod:
    def test_period_with_only_drafts_is_deleted(self, api, shop):
        schedule(shop, published=False)
        api.login(shop["manager"])
        assert api.client.delete(f"/api/periods/{shop['period'].pk}").status_code == 204
        assert not SchedulePeriod.objects.filter(pk=shop["period"].pk).exists()
        assert not Shift.objects.exists()
        assert api.get(f"/api/locations/{shop['location'].pk}/periods").json() == []

    def test_published_period_stays(self, api, shop):
        schedule(shop, published=True)
        response = api.login(shop["manager"]).client.delete(f"/api/periods/{shop['period'].pk}")
        assert response.status_code == 409 and "opublikowany" in response.json()["detail"]
        assert SchedulePeriod.objects.filter(pk=shop["period"].pk).exists()

    def test_other_company_and_employee(self, api, shop, make_company):
        url = f"/api/periods/{shop['period'].pk}"
        assert api.login(make_company("Obca")["manager"]).client.delete(url).status_code == 404
        assert api.login(shop["worker"]).client.delete(url).status_code == 403
