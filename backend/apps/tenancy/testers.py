"""The closed test of the phone apps (Piotr, 28.11.2026; docs/plan.md section 51).

Google Play lets a new personal developer account publish only after 12 testers used the app for 14 days, and testers
need someone to work with. So, while `TESTERS_LOCATION_ID` names a location, a Polish number with no account and no
invitation may log in on the plain login screen, and its first login puts the new account in that location: as
a manager or as an employee, drawn at random from the places still free (`TESTERS_MANAGERS` managers and
`TESTERS_EMPLOYEES` employees). Places count the people now in the location, so someone a tester-manager invites
takes an employee's place too, and a person removed from the location frees one. When every place is taken,
such a number hears that the test is full. The store reviewers' account (`REVIEW_LOGIN_PHONE`) is a manager of the
location and takes no place.

The joining goes through an invitation that is accepted at once (`invitations.accept_invitation`), so the location's
history shows how each tester came in. Turn the setting off before the app is open to everyone.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from apps.accounts.login import review_phone
from apps.accounts.models import User
from apps.billing.models import Subscription
from apps.staffing.models import EmployeeProfile, works_in_q
from apps.tenancy.models import Company, Invitation, InvitationStatus, Location, Membership, Role

logger = logging.getLogger(__name__)

REVIEWER_NAME = ("Recenzent", "Sklepu")


@dataclass(frozen=True)
class Places:
    managers: int
    employees: int
    free_managers: int
    free_employees: int

    @property
    def free(self) -> int:
        return self.free_managers + self.free_employees


def testers_location() -> Location | None:
    """The location new testers join, or None when the closed test is off (or the setting names no live location)."""
    raw = settings.TESTERS_LOCATION_ID
    if not raw:
        return None
    try:
        location = Location.objects.filter(pk=raw, archived_at__isnull=True).first()  # tenant-ok: set by the admin
    except ValidationError:
        location = None
    if location is None:
        logger.warning("TESTERS_LOCATION_ID does not name a live location; new numbers do not join any")
    return location


def places(location: Location) -> Places:
    """How many managers and employees the location has, and how many places are still free for testers."""
    managers = Membership.objects.for_company(location.company_id).filter(role=Role.MANAGER, locations=location)
    reviewer = review_phone()
    if reviewer:
        managers = managers.exclude(user__phone_e164=reviewer)
    employees = EmployeeProfile.objects.for_company(location.company_id).filter(
        works_in_q(location), membership__role=Role.EMPLOYEE, removed_at__isnull=True
    )
    m, e = managers.count(), employees.count()
    return Places(m, e, max(0, settings.TESTERS_MANAGERS - m), max(0, settings.TESTERS_EMPLOYEES - e))


def may_join() -> bool:
    """A new number may get a code to join the test: the test is on and a place is free (checked again on login)."""
    location = testers_location()
    return location is not None and places(location).free > 0


def is_full() -> bool:
    """The test is on but every place is taken."""
    location = testers_location()
    return location is not None and places(location).free == 0


def draw_role(location: Location) -> str | None:
    """Manager or employee, at random in proportion to the free places (so 3 + 15 places end as 3 + 15 people
    in some random order); None when nothing is free."""
    free = places(location)
    if free.free == 0:
        return None
    return Role.MANAGER if secrets.randbelow(free.free) < free.free_managers else Role.EMPLOYEE


def join(user: User) -> bool:
    """Put a new account in the test location. Call inside the transaction that created the account.

    False when the test is off or full by now (two testers logging in at the same moment are served one by one).
    A number that got an invitation in the meantime keeps it and joins nothing here.
    """
    location = testers_location()
    if location is None:
        return False
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"testers:{location.pk}"])
    if Invitation.objects.filter(phone_e164=user.phone_e164, status=InvitationStatus.PENDING).exists():
        return True
    role = draw_role(location)
    if role is None:
        return False
    from apps.tenancy.invitations import accept_invitation

    invitation = Invitation.objects.create(location=location, phone_e164=user.phone_e164, role=role, invited_by=None)
    accept_invitation(invitation.pk, user)
    logger.info("a tester joined %s as %s", location.pk, role)
    return True


@dataclass(frozen=True)
class Setup:
    location: Location
    created: bool
    access_until: object
    reviewer: User | None


@transaction.atomic
def set_up(name: str = "", days: int | None = None) -> Setup:
    """The test location: the one `TESTERS_LOCATION_ID` names, or a new empty company with one location `name`
    (good-practice rules, no positions, shifts or people). `days` gives the company access until that many days
    from now. With `REVIEW_LOGIN_PHONE` set, that account becomes a manager of the location."""
    location = testers_location()
    created = False
    if location is None:
        name = name.strip()
        if not name:
            raise ValueError("Podaj nazwę lokalu (--name).")
        # Run twice before the setting is in .env, the command finds the location it made the first time.
        location = Location.objects.filter(  # tenant-ok: the admin's command, not a request
            name=name, company__name=name, company__created_by__isnull=True, archived_at__isnull=True
        ).first()
    if location is None:
        from apps.rules.defaults import add_good_practice_rules

        created = True
        company = Company.objects.create(name=name)
        location = Location.objects.create(company=company, name=name)
        add_good_practice_rules(location)
        days = days or 90
    if days:
        ends_at = timezone.now() + timedelta(days=days)
        Subscription.objects.for_company(location.company_id).update_or_create(
            company_id=location.company_id, defaults={"ends_at": ends_at, "source": Subscription.Source.CODE}
        )
    subscription = Subscription.objects.for_company(location.company_id).first()
    return Setup(location, created, subscription.ends_at if subscription else None, _add_reviewer(location))


def _add_reviewer(location: Location) -> User | None:
    phone = review_phone()
    if phone is None:
        return None
    first, last = REVIEWER_NAME
    user = User.objects.filter(phone_e164=phone).first() or User.objects.create_user(
        phone, first_name=first, last_name=last
    )
    membership, _ = Membership.objects.get_or_create(
        company_id=location.company_id, user=user, defaults={"role": Role.MANAGER}
    )
    if membership.role == Role.MANAGER:
        membership.locations.add(location)
    return user
