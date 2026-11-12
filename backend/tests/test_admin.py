"""Every admin list and form opens for the superadmin (smoke test on demo data)."""

from datetime import date

import pytest
from django.contrib import admin
from django.urls import reverse

from apps.accounts.models import User
from apps.core.demo_data import create_demo_data


@pytest.fixture
def superadmin_client(client, db):
    create_demo_data(today=date(2026, 11, 12))
    client.force_login(User.objects.create_superuser("+48500999999", "haslo-testowe-123"))
    return client


def test_all_admin_pages_open(superadmin_client):
    for model in admin.site._registry:
        meta = model._meta
        changelist = reverse(f"admin:{meta.app_label}_{meta.model_name}_changelist")
        assert superadmin_client.get(changelist).status_code == 200, changelist
        obj = model._default_manager.first()
        if obj is not None:
            change = reverse(f"admin:{meta.app_label}_{meta.model_name}_change", args=[obj.pk])
            assert superadmin_client.get(change).status_code == 200, change


def test_superadmin_can_add_user_with_normalized_phone(superadmin_client):
    response = superadmin_client.post(
        reverse("admin:accounts_user_add"),
        {"phone_e164": "601 222 333", "first_name": "Ola", "last_name": "Nowak", "usable_password": "false"},
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    assert User.objects.filter(phone_e164="+48601222333").exists()


def test_location_added_in_admin_gets_company_from_form(superadmin_client):
    from apps.core.demo_data import CAFE_COMPANY_ID
    from apps.tenancy.models import Location

    response = superadmin_client.post(
        reverse("admin:tenancy_location_add"),
        {
            "company": str(CAFE_COMPANY_ID),
            "name": "Kraków – Podgórze",
            "address": "",
            "timezone": "Europe/Warsaw",
            "schedule_period": "week",
            "availability_deadline_days": 3,
        },
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    assert Location.objects.for_company(CAFE_COMPANY_ID).filter(name="Kraków – Podgórze").exists()
