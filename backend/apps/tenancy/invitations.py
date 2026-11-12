"""Inviting people to a location by phone number, and what happens when they accept.

No SMS is sent: the invited person sees the invitation after logging in with that number.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone
from ninja.errors import HttpError

from apps.staffing.models import EmployeeProfile
from apps.tenancy.models import Invitation, InvitationStatus, Location, Membership, Role

ALREADY_DECIDED = "To zaproszenie nie jest już aktualne."


def create_invitation(
    location: Location, phone_e164: str, role: str, invited_by, first_name: str = "", last_name: str = ""
) -> Invitation:
    membership = (
        Membership.objects.for_company(location.company_id)
        .filter(user__phone_e164=phone_e164)
        .select_related("employee_profile")
        .first()
    )
    if membership is not None:
        if role == Role.EMPLOYEE and hasattr(membership, "employee_profile"):
            raise HttpError(409, "Ta osoba jest już pracownikiem tej firmy.")
        if role == Role.MANAGER and (
            membership.role == Role.OWNER
            or (membership.role == Role.MANAGER and membership.locations.filter(pk=location.pk).exists())
        ):
            raise HttpError(409, "Ta osoba już zarządza tym lokalem.")
    try:
        with transaction.atomic():
            return Invitation.objects.create(
                location=location,
                phone_e164=phone_e164,
                role=role,
                invited_by=invited_by,
                first_name=first_name.strip(),
                last_name=last_name.strip(),
            )
    except IntegrityError as exc:
        # The partial unique index: one pending invitation per (location, phone).
        raise HttpError(409, "Ten numer ma już oczekujące zaproszenie do tego lokalu.") from exc


def _decide(invitation_id, status: str, **lookup) -> Invitation:
    """Lock the invitation and move it out of `pending`. Call inside a transaction."""
    invitation = (
        Invitation.objects.select_for_update(of=("self",))
        .select_related("location", "company")
        .filter(pk=invitation_id, **lookup)
        .first()
    )
    if invitation is None:
        raise HttpError(404, "Nie znaleziono.")
    if invitation.status != InvitationStatus.PENDING:
        raise HttpError(409, ALREADY_DECIDED)
    invitation.status = status
    invitation.decided_at = timezone.now()
    invitation.save(update_fields=["status", "decided_at"])
    return invitation


@transaction.atomic
def accept_invitation(invitation_id, user) -> Invitation:
    """Join the company in one transaction: membership, and for an employee the profile in the invited location."""
    invitation = _decide(invitation_id, InvitationStatus.ACCEPTED, phone_e164=user.phone_e164)
    location = invitation.location

    membership, _ = Membership.objects.get_or_create(
        company_id=invitation.company_id, user=user, defaults={"role": invitation.role}
    )
    if invitation.role == Role.MANAGER:
        if membership.role == Role.EMPLOYEE:
            membership.role = Role.MANAGER
            membership.save(update_fields=["role"])
        if membership.role == Role.MANAGER:
            membership.locations.add(location)
    elif not EmployeeProfile.objects.for_company(invitation.company_id).filter(membership=membership).exists():
        # A person who already works in another location of this company keeps their home location;
        # work elsewhere stays an exception arranged by the manager.
        EmployeeProfile.objects.create(membership=membership, home_location=location)

    changed = []
    if not user.first_name and invitation.first_name:
        user.first_name = invitation.first_name
        changed.append("first_name")
    if not user.last_name and invitation.last_name:
        user.last_name = invitation.last_name
        changed.append("last_name")
    if changed:
        user.save(update_fields=changed)
    return invitation


@transaction.atomic
def decline_invitation(invitation_id, user) -> Invitation:
    return _decide(invitation_id, InvitationStatus.DECLINED, phone_e164=user.phone_e164)


@transaction.atomic
def cancel_invitation(invitation: Invitation) -> Invitation:
    return _decide(invitation.pk, InvitationStatus.CANCELLED)
