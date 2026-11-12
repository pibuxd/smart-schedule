"""Database constraints that keep the data consistent no matter which code writes it."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User, normalize_phone
from apps.availability.models import AvailabilityDay, AvailabilityState
from apps.billing.models import AccessCode, GenerationUsage, Subscription
from apps.rules.models import RuleSetting, WeightProfile
from apps.scheduling.models import Assignment, SchedulePeriod, ScheduleVersion, Shift
from apps.staffing.models import EmployeeProfile, ShiftType, StaffingRule
from apps.tenancy.models import Invitation, InvitationStatus, LocationGroup, Membership

from .conftest import next_phone


def violates(callable_):
    with pytest.raises(IntegrityError), transaction.atomic():
        callable_()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("600 100 200", "+48600100200"), ("+48 600-100-200", "+48600100200"), ("0048600100200", "+48600100200")],
)
def test_phone_is_normalized_to_e164(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["123", "+49 1512 3456789", "abc"])
def test_non_polish_or_invalid_phone_is_rejected(raw):
    with pytest.raises(ValidationError):
        normalize_phone(raw)


@pytest.mark.django_db
def test_one_account_per_phone():
    User.objects.create_user("600 100 999")
    violates(lambda: User.objects.create_user("+48600100999"))


@pytest.mark.django_db
def test_app_users_have_no_password():
    assert not User.objects.create_user(next_phone()).has_usable_password()


@pytest.mark.django_db
def test_one_membership_per_user_and_company(make_company):
    a = make_company()
    violates(lambda: Membership.objects.create(company=a["company"], user=a["worker"]))


@pytest.mark.django_db
def test_one_pending_invitation_per_location_and_phone(make_company):
    a = make_company()
    phone = next_phone()
    Invitation.objects.create(location=a["location"], phone_e164=phone)
    violates(lambda: Invitation.objects.create(location=a["location"], phone_e164=phone))

    # A decided invitation does not block a new pending one.
    Invitation.objects.filter(phone_e164=phone).update(status=InvitationStatus.DECLINED, decided_at=timezone.now())
    Invitation.objects.create(location=a["location"], phone_e164=phone)


@pytest.mark.django_db
def test_decided_invitation_needs_decision_time(make_company):
    a = make_company()
    violates(
        lambda: Invitation.objects.create(
            location=a["location"], phone_e164=next_phone(), status=InvitationStatus.ACCEPTED
        )
    )


@pytest.mark.django_db
def test_staffing_rule_unique_per_slot_and_valid_weekday(make_company):
    a = make_company()
    kwargs = {"location": a["location"], "shift_type": a["shift_type"], "position": a["position"]}
    StaffingRule.objects.create(weekday=0, count=2, **kwargs)
    violates(lambda: StaffingRule.objects.create(weekday=0, count=3, **kwargs))
    violates(lambda: StaffingRule.objects.create(weekday=7, count=1, **kwargs))


@pytest.mark.django_db
def test_fixed_shift_needs_hours_and_flexible_does_not(make_company):
    a = make_company()
    violates(lambda: ShiftType.objects.create(location=a["location"], name="Bez godzin"))
    violates(
        lambda: ShiftType.objects.create(location=a["location"], name="Zero", start_time=time(8), end_time=time(8))
    )
    ShiftType.objects.create(location=a["location"], name="Dowolna", kind=ShiftType.Kind.FLEXIBLE)
    overnight = ShiftType.objects.create(location=a["location"], name="Nocna", start_time=time(22), end_time=time(6))
    assert overnight.is_overnight


@pytest.mark.django_db
def test_availability_unique_per_employee_and_day(make_company):
    a = make_company()
    day = {"employee": a["employee"], "date": date(2026, 12, 1)}
    AvailabilityDay.objects.create(state=AvailabilityState.PREFER, **day)
    violates(lambda: AvailabilityDay.objects.create(state=AvailabilityState.CANNOT, **day))
    violates(
        lambda: AvailabilityDay.objects.create(
            employee=a["employee"],
            date=date(2026, 12, 2),
            state=AvailabilityState.PREFER,
            from_time=time(16),
            to_time=time(14),
        )
    )


@pytest.mark.django_db
def test_employee_target_hours_not_above_maximum(make_company):
    a = make_company()
    profile: EmployeeProfile = a["employee"]
    profile.max_hours_month, profile.target_hours_month = 100, 120
    violates(profile.save)


@pytest.mark.django_db
def test_rule_setting_belongs_to_exactly_one_scope_and_is_unique(make_company):
    a = make_company()
    group = LocationGroup.objects.create(company=a["company"], name="Grupa")
    RuleSetting.objects.create(group=group, rule_code="fair_weekends", position=1)
    RuleSetting.objects.create(location=a["location"], rule_code="fair_weekends", position=1)  # override is fine
    violates(lambda: RuleSetting.objects.create(group=group, rule_code="fair_weekends", position=2))
    violates(lambda: RuleSetting.objects.create(location=a["location"], rule_code="fair_weekends", position=2))
    violates(
        lambda: RuleSetting.objects.create(
            company=a["company"], group=group, location=a["location"], rule_code="fair_closings", position=1
        )
    )
    violates(lambda: RuleSetting.objects.create(company=a["company"], rule_code="fair_closings", position=1))


@pytest.mark.django_db
def test_rule_setting_must_come_from_catalog(make_company):
    a = make_company()
    with pytest.raises(ValidationError):
        RuleSetting(location=a["location"], rule_code="make_everyone_happy", position=1).full_clean()
    with pytest.raises(ValidationError):
        RuleSetting(
            location=a["location"], rule_code="max_consecutive_days", params={"weeks": 2}, position=1
        ).full_clean()
    RuleSetting(location=a["location"], rule_code="max_consecutive_days", params={"days": 5}, position=1).full_clean()


@pytest.mark.django_db
def test_weight_profile_keeps_manager_voice_stronger(make_company):
    a = make_company()
    violates(lambda: WeightProfile.objects.create(location=a["location"], manager_share=Decimal("0.40")))
    WeightProfile.objects.create(location=a["location"])
    violates(lambda: WeightProfile.objects.create(location=a["location"]))


@pytest.mark.django_db
def test_one_published_version_per_period_and_hole_cannot_be_pinned(make_company):
    a = make_company()
    period = SchedulePeriod.objects.create(location=a["location"], start=date(2026, 12, 1), end=date(2026, 12, 31))
    violates(
        lambda: SchedulePeriod.objects.create(location=a["location"], start=date(2026, 12, 1), end=date(2026, 11, 1))
    )
    ScheduleVersion.objects.create(period=period, number=1, status=ScheduleVersion.Status.PUBLISHED)
    violates(lambda: ScheduleVersion.objects.create(period=period, number=1))
    violates(lambda: ScheduleVersion.objects.create(period=period, number=2, status=ScheduleVersion.Status.PUBLISHED))

    version = ScheduleVersion.objects.create(period=period, number=2)
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
    assert shift.company_id == a["company"].id
    violates(lambda: Assignment.objects.create(shift=shift, employee=None, pinned=True))
    Assignment.objects.create(shift=shift, employee=a["employee"], pinned=True)


@pytest.mark.django_db
def test_subscription_and_usage_constraints(make_company):
    a = make_company()
    Subscription.objects.create(company=a["company"], ends_at=timezone.now() + timedelta(days=30))
    violates(lambda: Subscription.objects.create(company=a["company"], ends_at=timezone.now()))
    GenerationUsage.objects.create(company=a["company"], month=date(2026, 12, 1))
    violates(lambda: GenerationUsage.objects.create(company=a["company"], month=date(2026, 12, 1)))
    violates(lambda: GenerationUsage.objects.create(company=a["company"], month=date(2027, 1, 2)))


@pytest.mark.django_db
def test_access_code_limits():
    violates(lambda: AccessCode.objects.create(code_hash="a", prefix="ABCD", days=45))
    violates(lambda: AccessCode.objects.create(code_hash="b", prefix="ABCD", max_uses=1, uses=2))
    AccessCode.objects.create(code_hash="c", prefix="ABCD", days=60)
