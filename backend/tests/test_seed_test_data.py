from datetime import date, timedelta

import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.availability.models import TextRequest
from apps.billing.models import AccessCode
from apps.core import test_data as td
from apps.core.demo_data import BAKERY_COMPANY_ID, create_demo_data
from apps.marketplace.models import ShiftOffer
from apps.scheduling.models import SchedulePeriod
from apps.scheduling.problem_builder import build_problem
from apps.tenancy.models import Company, Invitation
from engine.problem import RequestType

pytestmark = pytest.mark.django_db(transaction=True)


def test_periods_around_today():
    p = td.Periods.around(date(2026, 11, 17))
    assert p.published == (date(2026, 11, 1), date(2026, 11, 30))
    assert p.next == (date(2026, 12, 1), date(2026, 12, 31))
    assert p.later_month == date(2027, 1, 1)
    assert p.week0 == (date(2026, 11, 16), date(2026, 11, 22))
    # Fewer than 10 days left: the published period also covers next month, so there are shifts to give away.
    late = td.Periods.around(date(2026, 11, 25))
    assert late.published == (date(2026, 11, 1), date(2026, 12, 31))
    assert late.next == (date(2027, 1, 1), date(2027, 1, 31))


def test_seed_reset_and_delete_keep_other_data():
    create_demo_data()
    call_command("seed_test_data", seconds=2)

    assert Company.objects.filter(id__in=td.TEST_COMPANY_IDS).count() == 3
    assert SchedulePeriod.objects.filter(company_id=td.COMPANY_A, status="published").count() == 3
    assert ShiftOffer.objects.filter(company_id=td.COMPANY_A).exists()
    assert TextRequest.objects.filter(company_id=td.COMPANY_A, period__isnull=True).exists()
    assert Invitation.objects.filter(phone_e164=td.INVITED_ONLY_PHONES[2], status="pending").count() == 2
    assert AccessCode.objects.filter(note__startswith="Dane testowe").count() == 4
    # Natalia and Roman (Piotr's test, 20.11): "not with Zuzanna on closing" and "at most three nights a week".
    natalia = TextRequest.objects.get(company_id=td.COMPANY_A, text__startswith="Nie stawiajcie mnie z Zuzanną")
    roman = TextRequest.objects.get(company_id=td.COMPANY_A, text__startswith="Mogę brać nocki")
    requests = {r.id: r for r in build_problem([natalia.period]).problem.requests}
    closing = requests[str(natalia.pk)]
    assert closing.type == RequestType.AVOID_PERSON and closing.shift_type is not None
    nights = requests[str(roman.pk)]
    assert nights.type == RequestType.SHIFTS_LIMIT and nights.max_shifts == 3 and nights.weekly_hours
    # Celina (Piotr's test, 26.11): 30 hours in one week and 10 in the next, rather at the end of the week.
    celina = TextRequest.objects.get(company_id=td.COMPANY_A, text__contains="chcę wyrobić 30 godzin")
    requests = {r.id: r for r in build_problem([celina.period]).problem.requests}
    first, second = requests[str(celina.pk)], requests[f"{celina.pk}:2"]
    assert (first.type, first.target_hours, second.target_hours) == (RequestType.HOURS_TARGET, 30, 10)
    assert first.weekly_hours and len(first.dates) == 7 and min(second.dates) == max(first.dates) + timedelta(days=1)
    assert {d.weekday() for d in first.preferred_dates} == {3, 4, 5, 6}

    # A company the tester registered from a test number goes away with --reset; the demo stays.
    tester = User.objects.create_user(td.REGISTER_PHONES[0])
    Company.objects.create(name="Firma testera", created_by=tester)
    call_command("seed_test_data", reset=True, seconds=2)
    assert not Company.objects.filter(name="Firma testera").exists()
    assert not User.objects.filter(phone_e164=td.REGISTER_PHONES[0]).exists()
    assert Company.objects.filter(id__in=td.TEST_COMPANY_IDS).count() == 3

    call_command("seed_test_data", delete=True)
    assert not Company.objects.filter(id__in=td.TEST_COMPANY_IDS).exists()
    assert not User.objects.filter(phone_e164__in=td.all_account_phones()).exists()
    assert Company.objects.filter(id=BAKERY_COMPANY_ID).exists()


def test_refuses_numbers_of_real_accounts():
    User.objects.create_user(td.OWNER_A)
    with pytest.raises(Exception, match="mają już konta"):
        call_command("seed_test_data", seconds=2)
    assert not Company.objects.filter(id__in=td.TEST_COMPANY_IDS).exists()
