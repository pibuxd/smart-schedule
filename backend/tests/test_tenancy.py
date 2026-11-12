"""Tenant isolation: queries are limited to one company and rows of two companies cannot be linked."""

from datetime import date

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import RequestFactory
from ninja.errors import HttpError

from apps.availability.models import AvailabilityDay, AvailabilityState
from apps.scheduling.models import SchedulePeriod
from apps.staffing.models import EmployeeProfile, Position, StaffingRule
from apps.tenancy.base import CompanyOwnedModel
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Location, Membership

COMPANY_OWNED = sorted((m for m in apps.get_models() if issubclass(m, CompanyOwnedModel)), key=lambda m: m._meta.label)


def test_all_company_owned_tables_have_indexed_non_null_company():
    assert len(COMPANY_OWNED) >= 25
    for model in COMPANY_OWNED:
        field = model._meta.get_field("company")
        assert not field.null, model
        assert field.db_index, model


@pytest.mark.django_db
def test_seeded_companies_do_not_see_each_others_rows():
    from apps.core.demo_data import BAKERY_COMPANY_ID, CAFE_COMPANY_ID, create_demo_data

    create_demo_data(today=date(2026, 11, 12))

    checked = 0
    for model in COMPANY_OWNED:
        for own, other in [(BAKERY_COMPANY_ID, CAFE_COMPANY_ID), (CAFE_COMPANY_ID, BAKERY_COMPANY_ID)]:
            rows = model.objects.for_company(own)
            assert not rows.filter(company_id=other).exists()
            if rows.exists():
                checked += 1
    # Both companies have rows in the main tables, so the check above is not vacuous.
    assert checked >= 20


@pytest.mark.django_db
def test_for_company_requires_a_company():
    with pytest.raises(ValueError):
        Location.objects.for_company(None)


@pytest.mark.django_db
def test_tenant_context_returns_404_for_other_company(make_company):
    a, b = make_company("A"), make_company("B")
    request = RequestFactory().get("/")
    request.user = a["manager"]

    ctx = tenant_context(request, a["company"].id)
    assert ctx.is_manager
    assert list(ctx.qs(Location)) == [a["location"]]
    assert ctx.get(Location, id=a["location"].id) == a["location"]

    # An object of company B looked up through company A's context does not exist.
    with pytest.raises(HttpError) as err:
        ctx.get(Location, id=b["location"].id)
    assert err.value.status_code == 404

    # Asking for company B's context as a non-member is also a 404 (no hint that it exists).
    with pytest.raises(HttpError) as err:
        tenant_context(request, b["company"].id)
    assert err.value.status_code == 404


@pytest.mark.django_db
def test_tenant_context_requires_login(make_company):
    from django.contrib.auth.models import AnonymousUser

    a = make_company("A")
    request = RequestFactory().get("/")
    request.user = AnonymousUser()
    with pytest.raises(HttpError) as err:
        tenant_context(request, a["company"].id)
    assert err.value.status_code == 401


@pytest.mark.django_db
def test_employee_manages_no_locations_and_manager_only_assigned(make_company):
    a = make_company("A")
    request = RequestFactory().get("/")
    request.user = a["worker"]
    ctx = tenant_context(request, a["company"].id)
    assert not ctx.is_manager
    assert not ctx.managed_locations().exists()
    with pytest.raises(HttpError) as err:
        ctx.require_manager()
    assert err.value.status_code == 403

    second = Location.objects.create(company=a["company"], name="Drugi lokal")
    membership = Membership.objects.get(user=a["worker"])
    membership.role = "manager"
    membership.save()
    membership.locations.add(second)
    ctx = tenant_context(request, a["company"].id)
    assert list(ctx.managed_locations()) == [second]


@pytest.mark.django_db
def test_qs_rejects_models_without_company(make_company):
    from apps.accounts.models import User

    a = make_company("A")
    request = RequestFactory().get("/")
    request.user = a["manager"]
    with pytest.raises(TypeError):
        tenant_context(request, a["company"].id).qs(User)


@pytest.mark.django_db
def test_company_is_copied_from_parent(make_company):
    a = make_company("A")
    position = Position.objects.create(location=a["location"], name="Piekarz")
    assert position.company_id == a["company"].id


@pytest.mark.django_db
def test_foreign_key_to_other_company_is_rejected(make_company):
    a, b = make_company("A"), make_company("B")
    with pytest.raises(ValidationError) as err:
        StaffingRule.objects.create(
            location=a["location"], weekday=0, shift_type=a["shift_type"], position=b["position"], count=1
        )
    assert "position" in err.value.message_dict

    # Explicit company that does not match the parent row.
    with pytest.raises(ValidationError):
        Position.objects.create(company=b["company"], location=a["location"], name="Piekarz")

    # Also when the related object is given only by id (not loaded).
    with pytest.raises(ValidationError):
        AvailabilityDay.objects.create(
            company=a["company"],
            employee_id=b["employee"].id,
            date=date(2026, 12, 1),
            state=AvailabilityState.PREFER,
        )


@pytest.mark.django_db
def test_many_to_many_link_to_other_company_is_rejected(make_company):
    a, b = make_company("A"), make_company("B")
    employee: EmployeeProfile = a["employee"]

    employee.positions.add(a["position"])
    with pytest.raises(ValidationError), transaction.atomic():
        employee.positions.add(b["position"])
    with pytest.raises(ValidationError), transaction.atomic():
        b["position"].employees.add(employee)  # reverse side
    with pytest.raises(ValidationError), transaction.atomic():
        Membership.objects.get(user=a["manager"]).locations.add(b["location"])
    assert list(employee.positions.all()) == [a["position"]]


@pytest.mark.django_db
def test_admin_style_clean_reports_other_company(make_company):
    a, b = make_company("A"), make_company("B")
    period = SchedulePeriod(location=a["location"], start=date(2026, 12, 1), end=date(2026, 12, 31))
    period.full_clean()
    period.location = b["location"]
    period.company = a["company"]
    with pytest.raises(ValidationError):
        period.full_clean()
