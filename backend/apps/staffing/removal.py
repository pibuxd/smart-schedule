"""Removing a person from a location for good ("Usuń z lokalu"), and bringing a removed person back.

A person nobody ever scheduled is deleted with everything they entered. A person with shifts in saved schedules
cannot be deleted (hours and history would be lost), so the profile stays, hidden: `removed_at` set, switched off,
without positions, offers or manager instructions. A plain employee then loses access to the company.
"""

from django.db import transaction
from django.utils import timezone

from apps.staffing.models import EmployeeProfile, PositionExperience
from apps.tenancy.models import Location, Role


@transaction.atomic
def remove_employee(profile: EmployeeProfile) -> bool:
    """True when the person is gone entirely, False when the profile stays hidden for the schedule history."""
    from apps.assistant.models import ManagerInstruction
    from apps.marketplace.models import ShiftClaim, ShiftOffer
    from apps.marketplace.services import ACTIVE, cancel_offer, withdraw_claim
    from apps.notifications.models import Notification
    from apps.scheduling.models import Assignment

    company_id = profile.company_id
    profile = (
        EmployeeProfile.objects.for_company(company_id)
        .select_for_update(of=("self",))
        .select_related("membership")
        .get(pk=profile.pk)
    )
    membership = profile.membership
    if not Assignment.objects.for_company(company_id).filter(employee=profile).exists():
        if membership.role == Role.EMPLOYEE:
            Notification.objects.for_company(company_id).filter(user_id=membership.user_id).delete()
            membership.delete()  # takes the profile and everything the person entered with it
        else:
            profile.delete()  # a manager who worked shifts keeps managing
        return True

    for offer in ShiftOffer.objects.for_company(company_id).filter(offered_by=profile, status__in=ACTIVE):
        cancel_offer(offer, profile)
    for claim in ShiftClaim.objects.for_company(company_id).filter(employee=profile, status=ShiftClaim.Status.PENDING):
        withdraw_claim(claim, profile)
    ManagerInstruction.objects.for_company(company_id).filter(employee=profile).delete()
    PositionExperience.objects.for_company(company_id).filter(employee=profile).delete()
    profile.positions.clear()
    profile.is_active = False
    profile.removed_at = timezone.now()
    profile.save(update_fields=["is_active", "removed_at"])
    return False


def restore_employee(profile: EmployeeProfile, location: Location) -> None:
    """A removed person accepted a new invitation: back in the schedule, in the location that invited them."""
    profile.removed_at = None
    profile.is_active = True
    profile.home_location = location
    profile.save(update_fields=["removed_at", "is_active", "home_location"])
