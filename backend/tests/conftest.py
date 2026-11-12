import os

# Tests run with DEBUG on so that a SECRET_KEY default is available locally and in CI.
os.environ.setdefault("DJANGO_DEBUG", "1")

import itertools
from datetime import time

import pytest

_phone_numbers = itertools.count(1)


def next_phone() -> str:
    return f"+48601{next(_phone_numbers):06d}"


@pytest.fixture
def make_company(db):
    """Create a company with one location, one position, one shift type and one employee."""
    from apps.accounts.models import User
    from apps.staffing.models import EmployeeProfile, Position, ShiftType
    from apps.tenancy.models import Company, Location, Membership, Role

    def factory(name: str = "Firma"):
        company = Company.objects.create(name=name)
        location = Location.objects.create(company=company, name=f"{name} – lokal")
        position = Position.objects.create(location=location, name="Sprzedawca")
        shift_type = ShiftType.objects.create(location=location, name="Ranna", start_time=time(6), end_time=time(14))
        manager = User.objects.create_user(next_phone(), first_name="Menedżer")
        Membership.objects.create(company=company, user=manager, role=Role.OWNER)
        worker = User.objects.create_user(next_phone(), first_name="Pracownik")
        membership = Membership.objects.create(company=company, user=worker)
        employee = EmployeeProfile.objects.create(membership=membership, home_location=location)
        return {
            "company": company,
            "location": location,
            "position": position,
            "shift_type": shift_type,
            "manager": manager,
            "worker": worker,
            "employee": employee,
        }

    return factory
