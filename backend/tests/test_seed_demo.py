from collections import Counter
from datetime import date

import pytest
from django.core.management import CommandError, call_command

from apps.availability.models import AvailabilityDay, AvailabilitySubmission, TextRequest
from apps.core.demo_data import BAKERY_COMPANY_ID, CAFE_COMPANY_ID, create_demo_data
from apps.rules.models import RuleSetting
from apps.scheduling.models import SchedulePeriod
from apps.staffing.models import Contract, EmployeeProfile, StaffingException
from apps.tenancy.models import Location, Membership, Role


@pytest.fixture
def demo(db):
    return create_demo_data(today=date(2026, 11, 12))


def test_bakery_matches_the_spec(demo):
    locations = Location.objects.for_company(BAKERY_COMPANY_ID)
    assert locations.count() == 4
    assert {loc.group.name for loc in locations} == {"Piekarnie pod Krakowem"}

    managers = Membership.objects.for_company(BAKERY_COMPANY_ID).filter(role__in=[Role.OWNER, Role.MANAGER])
    assert managers.count() == 1
    assert managers.get().locations.count() == 4

    for location in locations:
        staff = EmployeeProfile.objects.filter(home_location=location)
        assert 15 <= staff.count() <= 25
        contracts = Counter(staff.values_list("contract", flat=True))
        assert contracts[Contract.EMPLOYMENT] >= 1
        assert contracts[Contract.CIVIL] > contracts[Contract.EMPLOYMENT]

    requests = TextRequest.objects.for_company(BAKERY_COMPANY_ID).count()
    requests += TextRequest.objects.for_company(CAFE_COMPANY_ID).count()
    assert 20 <= requests <= 30

    rules = RuleSetting.objects.for_company(BAKERY_COMPANY_ID)
    assert rules.filter(group__isnull=False).count() >= 5
    assert rules.filter(location__isnull=False, is_hard=True).exists()


def test_availability_is_for_next_month_and_some_people_are_missing(demo):
    periods = SchedulePeriod.objects.for_company(BAKERY_COMPANY_ID)
    assert {(p.start, p.end) for p in periods} == {(date(2026, 12, 1), date(2026, 12, 31))}
    days = AvailabilityDay.objects.for_company(BAKERY_COMPANY_ID)
    assert days.filter(date__lt=date(2026, 12, 1)).count() == 0
    assert set(days.values_list("state", flat=True)) == {"cannot", "prefer_not", "neutral", "prefer"}

    employees = EmployeeProfile.objects.for_company(BAKERY_COMPANY_ID).count()
    submitted = AvailabilitySubmission.objects.for_company(BAKERY_COMPANY_ID).count()
    assert 0 < submitted < employees


def test_holidays_close_the_bakery(demo):
    christmas = StaffingException.objects.for_company(BAKERY_COMPANY_ID).filter(date=date(2026, 12, 25))
    assert christmas.exists()
    assert set(christmas.values_list("count", flat=True)) == {0}


def test_cafe_is_a_separate_company(demo):
    assert Location.objects.for_company(CAFE_COMPANY_ID).count() == 1
    assert EmployeeProfile.objects.for_company(CAFE_COMPANY_ID).count() == 7
    cafe_users = set(Membership.objects.for_company(CAFE_COMPANY_ID).values_list("user_id", flat=True))
    bakery_users = set(Membership.objects.for_company(BAKERY_COMPANY_ID).values_list("user_id", flat=True))
    assert not cafe_users & bakery_users


def test_data_is_deterministic(db):
    create_demo_data(today=date(2026, 11, 12))
    first = sorted(TextRequest.objects.values_list("text", flat=True))
    call_command("seed_demo", "--reset")
    assert sorted(TextRequest.objects.values_list("text", flat=True)) == first


def test_command_refuses_to_duplicate_and_resets(db):
    call_command("seed_demo")
    employees = EmployeeProfile.objects.count()
    with pytest.raises(CommandError):
        call_command("seed_demo")
    call_command("seed_demo", "--reset")
    assert EmployeeProfile.objects.count() == employees


def test_requests_for_the_manager_have_no_interpretation(demo):
    requests = TextRequest.objects.for_company(BAKERY_COMPANY_ID)
    assert requests.filter(status=TextRequest.Status.NEEDS_MANAGER).exists()
    for status in (TextRequest.Status.NEW, TextRequest.Status.NEEDS_MANAGER):
        assert not requests.filter(status=status, interpretation__isnull=False).exists()
    assert not requests.filter(status=TextRequest.Status.INTERPRETED, interpretation__isnull=True).exists()
