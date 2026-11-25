"""Inviting people to a location by phone number, and what happens when they accept.

No SMS is sent: the invited person sees the invitation after logging in with that number.
"""

from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from ninja.errors import HttpError

from apps.accounts.models import NOT_MOBILE, User, normalize_phone
from apps.staffing.models import EmployeeProfile, Position
from apps.staffing.removal import restore_employee
from apps.tenancy.models import Invitation, InvitationStatus, Location, Membership, Role

ALREADY_DECIDED = "To zaproszenie nie jest już aktualne."
ALREADY_PENDING = "Ten numer ma już oczekujące zaproszenie do tego lokalu."
# People invited at once from one list (the screen and the assistant).
MAX_PEOPLE = 300


def invitable_phone(raw: str, region: str = "PL") -> str:
    """The number to invite in E.164, or ValidationError. Without a country code it is from `region` (Poland unless
    the manager says a list is from elsewhere). A foreign number must be a mobile, since the code comes by SMS, unless
    it already has an account: the superadmin may add a real mobile that the number data calls something else."""
    try:
        return normalize_phone(raw, region=region)
    except ValidationError as exc:
        if exc.messages != [NOT_MOBILE]:
            raise
        phone = normalize_phone(raw, region=region, mobile=False)
        if User.objects.filter(phone_e164=phone).exists():
            return phone
        raise


def invitation_problem(location: Location, phone_e164: str, role: str) -> str | None:
    """Why this number cannot be invited to this location, or None."""
    membership = (
        Membership.objects.for_company(location.company_id)
        .filter(user__phone_e164=phone_e164)
        .select_related("employee_profile")
        .first()
    )
    if membership is not None:
        # Someone working in another location of the company can work here too (an extra location); a removed
        # person can be invited back.
        profile = getattr(membership, "employee_profile", None)
        if role == Role.EMPLOYEE and profile is not None and profile.removed_at is None and profile.works_in(location):
            return "Ta osoba już pracuje w tym lokalu."
        if role == Role.MANAGER and (
            membership.role == Role.OWNER
            or (membership.role == Role.MANAGER and membership.locations.filter(pk=location.pk).exists())
        ):
            return "Ta osoba już zarządza tym lokalem."
    pending = Invitation.objects.for_company(location.company_id).filter(
        location=location, phone_e164=phone_e164, status=InvitationStatus.PENDING
    )
    if pending.exists():
        return ALREADY_PENDING
    return None


def live_positions(location: Location, position_ids) -> list[Position]:
    """The given positions that belong to this location and are not removed (others are dropped)."""
    if not position_ids:
        return []
    return list(
        Position.objects.for_company(location.company_id).filter(
            location=location, removed_at__isnull=True, pk__in=[str(pk) for pk in position_ids]
        )
    )


def create_invitation(
    location: Location,
    phone_e164: str,
    role: str,
    invited_by,
    first_name: str = "",
    last_name: str = "",
    position_ids=(),
) -> Invitation:
    problem = invitation_problem(location, phone_e164, role)
    if problem is not None:
        raise HttpError(409, problem)
    try:
        with transaction.atomic():
            invitation = Invitation.objects.create(
                location=location,
                phone_e164=phone_e164,
                role=role,
                invited_by=invited_by,
                first_name=first_name.strip()[:80],
                last_name=last_name.strip()[:120],
            )
            if role == Role.EMPLOYEE:
                invitation.positions.set(live_positions(location, position_ids))
            return invitation
    except IntegrityError as exc:
        # The partial unique index: one pending invitation per (location, phone).
        raise HttpError(409, ALREADY_PENDING) from exc


# The reasons in a few words, for a list in a sentence ("Anna Kowalska (już pracuje w tym lokalu)").
SHORT_PROBLEMS = {
    "Ta osoba już pracuje w tym lokalu.": "już pracuje w tym lokalu",
    "Ta osoba już zarządza tym lokalem.": "już zarządza tym lokalem",
    ALREADY_PENDING: "ma już zaproszenie",
    "Brak numeru telefonu.": "brak numeru",
    "Ten numer jest już wyżej na liście.": "numer powtarza się na liście",
    "Nie zarządzasz tym lokalem.": "nie zarządzasz tym lokalem",
    "Kierownika zaprasza tylko właściciel firmy.": "kierownika zaprasza tylko właściciel firmy",
}


def short_problem(problem: str) -> str:
    """A wrong number has several messages; all of them are "zły numer" in a list. Already short words (no full stop)
    stay as they are."""
    if not problem.endswith("."):
        return problem
    return SHORT_PROBLEMS.get(problem, "zły numer" if "numer" in problem else problem.rstrip(".").lower())


@dataclass
class Person:
    """One row of a list of people to invite. `location` None = the location the list was sent for."""

    phone: str
    first_name: str = ""
    last_name: str = ""
    position_ids: list = field(default_factory=list)
    location_id: object = None
    role: str = Role.EMPLOYEE
    # Filled by `check_people`.
    location: Location | None = None
    phone_e164: str = ""
    problem: str | None = None


def check_people(ctx, default: Location, people: list[Person], region: str = "PL") -> list[Person]:
    """Find what stands in the way of each invitation (`problem`); nothing is saved. `ctx` is the TenantContext of
    the manager who sends the list: only locations they manage, only the owner invites managers. Numbers without a
    country code are from `region`."""
    managed = {str(loc.pk): loc for loc in ctx.managed_locations()}
    seen: set[tuple] = set()
    for person in people:
        person.location = managed.get(str(person.location_id or default.pk))
        person.problem = None
        person.phone_e164 = ""
        if person.location is None:
            person.problem = "Nie zarządzasz tym lokalem."
            continue
        person.position_ids = [p.pk for p in live_positions(person.location, person.position_ids)]
        if not person.phone.strip():
            person.problem = "Brak numeru telefonu."
            continue
        try:
            person.phone_e164 = invitable_phone(person.phone, region)
        except ValidationError as exc:
            person.problem = exc.messages[0]
            continue
        if person.role == Role.MANAGER and ctx.role != Role.OWNER:
            person.problem = "Kierownika zaprasza tylko właściciel firmy."
            continue
        key = (person.location.pk, person.phone_e164)
        if key in seen:
            person.problem = "Ten numer jest już wyżej na liście."
            continue
        seen.add(key)
        person.problem = invitation_problem(person.location, person.phone_e164, person.role)
    return people


@transaction.atomic
def invite_people(
    ctx, default: Location, people: list[Person], region: str = "PL"
) -> tuple[list[Invitation], list[Person]]:
    """Invite everyone on the list who can be invited; the rest come back with their `problem`."""
    invited, skipped = [], []
    for person in check_people(ctx, default, people, region):
        if person.problem is None:
            try:
                invited.append(
                    create_invitation(
                        person.location,
                        person.phone_e164,
                        person.role,
                        ctx.user,
                        person.first_name,
                        person.last_name,
                        person.position_ids,
                    )
                )
                continue
            except HttpError as exc:
                person.problem = exc.message
        skipped.append(person)
    return invited, skipped


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
    else:
        profile = EmployeeProfile.objects.for_company(invitation.company_id).filter(membership=membership).first()
        if profile is None:
            profile = EmployeeProfile.objects.create(membership=membership, home_location=location)
        elif profile.removed_at is not None:
            restore_employee(profile, location)
        elif not profile.works_in(location):
            # A person who already works in another location of this company keeps their main location and gets
            # this one as an extra location (docs/plan.md, section 27).
            profile.extra_locations.add(location)
        # Positions the manager chose when inviting (only live positions of this location).
        positions = invitation.positions.filter(location=location, removed_at__isnull=True)
        if positions:
            profile.positions.add(*positions)

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
