"""Schedule history cannot be lost by deleting one location, period, position or person.

Locations and people are archived in the app instead (stage 7). Deleting a whole company (superadmin only,
e.g. a test company) still removes everything, because every company-owned row also cascades from it.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from django.apps import apps
from django.db import transaction
from django.db.models import RestrictedError

from apps.scheduling.models import Assignment, SchedulePeriod, ScheduleVersion, Shift
from apps.staffing.models import EmployeeProfile, Position
from apps.tenancy.base import CompanyOwnedModel
from apps.tenancy.models import Company, Location


@pytest.fixture
def published(make_company):
    a = make_company()
    period = SchedulePeriod.objects.create(location=a["location"], start=date(2026, 12, 1), end=date(2026, 12, 31))
    version = ScheduleVersion.objects.create(period=period, number=1, status=ScheduleVersion.Status.PUBLISHED)
    start = datetime(2026, 12, 1, 5, tzinfo=UTC)
    shift = Shift.objects.create(
        version=version,
        location=a["location"],
        date=date(2026, 12, 1),
        shift_type=a["shift_type"],
        position=a["position"],
        start_at=start,
        end_at=start + timedelta(hours=8),
        slot_key="2026-12-01|ranna|1",
    )
    Assignment.objects.create(shift=shift, employee=a["employee"])
    return {**a, "period": period}


@pytest.mark.parametrize("target", ["location", "period", "position", "employee"])
@pytest.mark.django_db
def test_history_blocks_deleting_a_single_object(published, target):
    with pytest.raises(RestrictedError), transaction.atomic():
        published[target].delete()
    assert Assignment.objects.filter(employee=published["employee"]).exists()


@pytest.mark.django_db
def test_location_without_history_can_be_deleted(make_company):
    a = make_company()
    spare = Location.objects.create(company=a["company"], name="Pusty lokal")
    spare.delete()
    assert not Location.objects.filter(pk=spare.pk).exists()


@pytest.mark.django_db
def test_deleting_the_company_removes_all_its_rows(published):
    other = Company.objects.create(name="Inna")
    company_id = published["company"].id
    published["company"].delete()

    for model in apps.get_models():
        if issubclass(model, CompanyOwnedModel):
            assert not model.objects.for_company(company_id).exists(), model
    assert Company.objects.filter(pk=other.pk).exists()
    assert not EmployeeProfile.objects.filter(pk=published["employee"].pk).exists()
    assert not Position.objects.filter(pk=published["position"].pk).exists()
