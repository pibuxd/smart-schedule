"""Giving away a shift: an employee offers a published shift, others say "Biorę", the manager approves one.

- `offer_shift`: only my own shift in a published schedule that has not started yet. Everyone in the company who
  could take it (same position name, no "nie mogę", no other shift at that time, no "no exceptions" rule broken;
  checked by the validator) gets an in-app notification.
- `claim_offer` / `withdraw_claim` / `cancel_offer`: the person is checked again when they say "Biorę"; the
  managers of the location get a notification.
- `approve_claim`: checked once more against the published schedule as it is now, then the published shift (and
  the newest draft, if it still has the giver there) moves to the new person, pinned, with a history row
  (`AssignmentEvent`, reason "offer"). The giver, the taker and the other volunteers are told.
- `refresh_after_publish`: a newly published version keeps open offers whose giver still has the shift and
  ends the others.

Full swaps (two people exchange shifts) can be added later on the same history (`AssignmentEvent.Reason.SWAP`).
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from apps.marketplace.models import ShiftClaim, ShiftOffer
from apps.notifications.services import location_manager_ids, notify
from apps.scheduling.editing import save_scores
from apps.scheduling.models import Assignment, AssignmentEvent, SchedulePeriod, ScheduleVersion
from apps.scheduling.problem_builder import build_problem_for_version
from apps.staffing.models import EmployeeProfile, Position
from engine.explain import without_pin
from engine.scoring import score
from engine.validator import validate

ACTIVE = (ShiftOffer.Status.OPEN, ShiftOffer.Status.CLAIMED)
GONE = "Tej zmiany nie można już wziąć: oddanie jest zakończone albo grafik się zmienił."


def person_name(profile: EmployeeProfile) -> str:
    return profile.membership.user.full_name or "Pracownik bez imienia"


def offer_payload(offer: ShiftOffer) -> dict:
    shift = offer.assignment.shift
    tz = ZoneInfo(shift.location.timezone)
    return {
        "offer_id": str(offer.pk),
        "date": shift.date.isoformat(),
        "start_time": f"{shift.start_at.astimezone(tz):%H:%M}",
        "end_time": f"{shift.end_at.astimezone(tz):%H:%M}",
        "position_name": shift.position.name,
        "location_name": shift.location.name,
        "offered_by_name": person_name(offer.offered_by),
    }


def offer_query(company_id):
    return ShiftOffer.objects.for_company(company_id).select_related(
        "assignment__shift__location",
        "assignment__shift__position",
        "assignment__shift__shift_type",
        "assignment__shift__version",
        "offered_by__membership__user",
    )


def expire_started(company_id) -> None:
    """Offers of shifts that have already started cannot be taken any more."""
    ShiftOffer.objects.for_company(company_id).filter(
        status__in=ACTIVE, assignment__shift__start_at__lte=timezone.now()
    ).update(status=ShiftOffer.Status.EXPIRED, decided_at=timezone.now())


# ----------------------------------------------------------------------------------------------- who can take it


@dataclass(frozen=True)
class Verdict:
    employee: EmployeeProfile
    problems: tuple[str, ...]  # hard problems (Polish sentences); empty = can take the shift

    @property
    def possible(self) -> bool:
        return not self.problems


def _people_with_position(offer: ShiftOffer, among=None):
    """Active people of the company (but the giver) who have the shift's position, here or by name elsewhere."""
    shift = offer.assignment.shift
    names = Position.objects.for_company(offer.company_id).filter(name__iexact=shift.position.name)
    people = (
        EmployeeProfile.objects.for_company(offer.company_id)
        .filter(is_active=True, positions__in=names)
        .exclude(pk=offer.offered_by_id)
        .select_related("membership__user", "home_location")
        .distinct()
    )
    if among is not None:
        people = people.filter(pk__in=[p.pk for p in among])
    return list(people)


def check_people(offer: ShiftOffer, people=None) -> list[Verdict]:
    """For each person (default: everyone with the position), the hard problems if they took the offered shift
    instead of the giver, in the published schedule as it is now. Problems the schedule already had do not count."""
    candidates = _people_with_position(offer, people)
    if not candidates:
        return []
    version = offer.assignment.shift.version
    built, schedule = build_problem_for_version(version, extra_employees=[str(p.pk) for p in candidates])
    key = offer.assignment.shift.slot_key
    problem = without_pin(built.problem, key)
    known = {v.message for v in validate(problem, schedule).hard}
    verdicts = []
    for person in candidates:
        report = validate(problem, {**schedule, key: str(person.pk)})
        problems = tuple(v.message for v in report.hard if v.message not in known)
        verdicts.append(Verdict(person, problems))
    return verdicts


def _require_current(offer: ShiftOffer) -> None:
    """The offer still stands: active, not started, and the giver still has the shift in the published schedule."""
    assignment = offer.assignment
    if offer.status not in ACTIVE:
        raise HttpError(409, GONE)
    if assignment.shift.start_at <= timezone.now():
        raise HttpError(409, "Ta zmiana już się zaczęła, więc nie można jej oddać ani wziąć.")
    if assignment.shift.version.status != ScheduleVersion.Status.PUBLISHED or (
        assignment.employee_id != offer.offered_by_id
    ):
        raise HttpError(409, GONE)


# ----------------------------------------------------------------------------------------------- the giver


def offer_shift(assignment: Assignment, profile: EmployeeProfile) -> tuple[ShiftOffer, int]:
    """'Oddaj zmianę': returns the offer and how many people were told about it."""
    with transaction.atomic():
        assignment = (
            Assignment.objects.for_company(profile.company_id)
            .select_for_update()
            .select_related("shift__version", "shift__location", "shift__position")
            .get(pk=assignment.pk)
        )
        if assignment.employee_id != profile.pk:
            raise HttpError(404, "Nie znaleziono.")
        if assignment.shift.version.status != ScheduleVersion.Status.PUBLISHED:
            raise HttpError(409, "Oddać można tylko zmianę z opublikowanego grafiku.")
        if assignment.shift.start_at <= timezone.now():
            raise HttpError(409, "Ta zmiana już się zaczęła, więc nie można jej oddać.")
        if ShiftOffer.objects.for_company(profile.company_id).filter(assignment=assignment, status__in=ACTIVE).exists():
            raise HttpError(409, "Ta zmiana jest już oddawana.")
        offer = ShiftOffer.objects.create(assignment=assignment, offered_by=profile)
        offer = offer_query(profile.company_id).get(pk=offer.pk)
        able = [v.employee for v in check_people(offer) if v.possible]
        payload = offer_payload(offer)
        told = notify(offer.company_id, [p.membership.user_id for p in able], "shift_offered", payload)
        # The managers know early, especially when nobody can take it (the giver still has to come).
        managers = set(location_manager_ids(assignment.shift.location)) - {profile.membership.user_id}
        notify(offer.company_id, managers, "offer_made", {**payload, "able": told})
    return offer, told


def cancel_offer(offer: ShiftOffer, profile: EmployeeProfile) -> ShiftOffer:
    """The giver keeps the shift after all (only before the manager approves someone)."""
    with transaction.atomic():
        offer = offer_query(offer.company_id).select_for_update(of=("self",)).get(pk=offer.pk)
        if offer.offered_by_id != profile.pk:
            raise HttpError(404, "Nie znaleziono.")
        if offer.status not in ACTIVE:
            raise HttpError(409, "Tego oddania nie można już cofnąć.")
        offer.status = ShiftOffer.Status.CANCELLED
        offer.decided_at = timezone.now()
        offer.save(update_fields=["status", "decided_at"])
        pending = offer.claims.filter(status=ShiftClaim.Status.PENDING)
        users = list(pending.values_list("employee__membership__user_id", flat=True))
        pending.update(status=ShiftClaim.Status.WITHDRAWN, decided_at=timezone.now())
        notify(offer.company_id, users, "offer_cancelled", offer_payload(offer))
    return offer


# ----------------------------------------------------------------------------------------------- the taker


def claim_offer(offer: ShiftOffer, profile: EmployeeProfile) -> ShiftClaim:
    """'Biorę': allowed only to someone who can take the shift now; the managers decide."""
    with transaction.atomic():
        offer = offer_query(offer.company_id).select_for_update(of=("self",)).get(pk=offer.pk)
        _require_current(offer)
        if offer.offered_by_id == profile.pk:
            raise HttpError(409, "To Twoja zmiana.")
        claim = offer.claims.filter(employee=profile).first()
        if claim is not None and claim.status == ShiftClaim.Status.PENDING:
            return claim
        if claim is not None and claim.status == ShiftClaim.Status.REJECTED:
            raise HttpError(409, "Kierownik już nie zatwierdził Ci tej zmiany.")
        verdicts = check_people(offer, [profile])
        if not verdicts:
            raise HttpError(409, "Nie pracujesz na tym stanowisku, więc nie możesz wziąć tej zmiany.")
        if not verdicts[0].possible:
            raise HttpError(409, "Nie możesz wziąć tej zmiany: " + " ".join(verdicts[0].problems))
        if claim is None:
            claim = ShiftClaim.objects.create(offer=offer, employee=profile)
        else:  # withdrawn before, now again
            claim.status = ShiftClaim.Status.PENDING
            claim.created_at = timezone.now()
            claim.decided_at = None
            claim.save(update_fields=["status", "created_at", "decided_at"])
        offer.status = ShiftOffer.Status.CLAIMED
        offer.save(update_fields=["status"])
        payload = {**offer_payload(offer), "claimed_by_name": person_name(profile)}
        notify(offer.company_id, location_manager_ids(offer.assignment.shift.location), "shift_claimed", payload)
    return claim


def _reopen_if_nobody_waits(offer: ShiftOffer) -> None:
    if offer.status == ShiftOffer.Status.CLAIMED and not offer.claims.filter(status=ShiftClaim.Status.PENDING).exists():
        offer.status = ShiftOffer.Status.OPEN
        offer.save(update_fields=["status"])


def withdraw_claim(claim: ShiftClaim, profile: EmployeeProfile) -> ShiftClaim:
    with transaction.atomic():
        claim = ShiftClaim.objects.for_company(claim.company_id).select_for_update().get(pk=claim.pk)
        if claim.employee_id != profile.pk:
            raise HttpError(404, "Nie znaleziono.")
        if claim.status != ShiftClaim.Status.PENDING:
            raise HttpError(409, "Kierownik już zdecydował, więc nie można się wycofać.")
        claim.status = ShiftClaim.Status.WITHDRAWN
        claim.decided_at = timezone.now()
        claim.save(update_fields=["status", "decided_at"])
        offer = ShiftOffer.objects.for_company(claim.company_id).select_for_update().get(pk=claim.offer_id)
        _reopen_if_nobody_waits(offer)
    return claim


# ----------------------------------------------------------------------------------------------- the manager


def _move(assignment: Assignment, to: EmployeeProfile) -> None:
    assignment.employee = to
    assignment.borrowed = to.home_location_id != assignment.shift.location_id
    assignment.manual = True
    # The new person was agreed on: arranging the period again keeps them there.
    assignment.pinned = True
    assignment.save(update_fields=["employee", "borrowed", "manual", "pinned"])


def approve_claim(claim: ShiftClaim, user) -> ShiftOffer:
    """The taker gets the shift in the published schedule (checked again now)."""
    with transaction.atomic():
        claim = ShiftClaim.objects.for_company(claim.company_id).select_for_update().get(pk=claim.pk)
        offer = offer_query(claim.company_id).select_for_update(of=("self",)).get(pk=claim.offer_id)
        SchedulePeriod.objects.select_for_update().filter(pk=offer.assignment.shift.version.period_id).first()
        if claim.status != ShiftClaim.Status.PENDING:
            raise HttpError(409, "O tej osobie już zdecydowano.")
        _require_current(offer)
        taker = (
            EmployeeProfile.objects.for_company(claim.company_id)
            .select_related("membership__user")
            .get(pk=claim.employee_id)
        )
        verdicts = check_people(offer, [taker]) if taker.is_active else []
        if not verdicts or not verdicts[0].possible:
            reasons = " ".join(verdicts[0].problems) if verdicts else "Ta osoba nie pracuje już na tym stanowisku."
            raise HttpError(409, "Tej osoby nie można wpisać na tę zmianę: " + reasons)

        now = timezone.now()
        published = offer.assignment
        shift = published.shift
        _move(published, taker)
        newest = (
            ScheduleVersion.objects.for_company(offer.company_id)
            .filter(period_id=shift.version.period_id)
            .order_by("-number")
            .first()
        )
        if newest is not None and newest.status == ScheduleVersion.Status.DRAFT:
            draft_row = (
                Assignment.objects.for_company(offer.company_id)
                .filter(shift__version=newest, shift__slot_key=shift.slot_key, employee_id=offer.offered_by_id)
                .select_related("shift")
                .first()
            )
            if draft_row is not None:
                _move(draft_row, taker)
        AssignmentEvent.objects.create(
            company_id=offer.company_id,
            location_id=shift.location_id,
            period_id=shift.version.period_id,
            slot_key=shift.slot_key,
            from_employee_id=offer.offered_by_id,
            to_employee=taker,
            reason=AssignmentEvent.Reason.OFFER,
            by=user,
            at=now,
        )
        built, schedule = build_problem_for_version(shift.version)
        report = validate(built.problem, schedule)
        save_scores(shift.version, score(built.problem, report, location=str(shift.location_id)))

        claim.status = ShiftClaim.Status.APPROVED
        claim.decided_by = user
        claim.decided_at = now
        claim.save(update_fields=["status", "decided_by", "decided_at"])
        others = offer.claims.filter(status=ShiftClaim.Status.PENDING).exclude(pk=claim.pk)
        other_users = list(others.values_list("employee__membership__user_id", flat=True))
        others.update(status=ShiftClaim.Status.REJECTED, decided_by=user, decided_at=now)
        offer.status = ShiftOffer.Status.APPROVED
        offer.decided_at = now
        offer.save(update_fields=["status", "decided_at"])

        payload = {**offer_payload(offer), "claimed_by_name": person_name(taker)}
        notify(offer.company_id, [taker.membership.user_id], "claim_approved", payload)
        notify(offer.company_id, [offer.offered_by.membership.user_id], "offer_taken", payload)
        notify(offer.company_id, other_users, "claim_rejected", payload)
    return offer


def reject_claim(claim: ShiftClaim, user) -> ShiftClaim:
    with transaction.atomic():
        claim = ShiftClaim.objects.for_company(claim.company_id).select_for_update().get(pk=claim.pk)
        if claim.status != ShiftClaim.Status.PENDING:
            raise HttpError(409, "O tej osobie już zdecydowano.")
        claim.status = ShiftClaim.Status.REJECTED
        claim.decided_by = user
        claim.decided_at = timezone.now()
        claim.save(update_fields=["status", "decided_by", "decided_at"])
        offer = offer_query(claim.company_id).select_for_update(of=("self",)).get(pk=claim.offer_id)
        _reopen_if_nobody_waits(offer)
        user_id = (
            EmployeeProfile.objects.for_company(claim.company_id)
            .filter(pk=claim.employee_id)
            .values_list("membership__user_id", flat=True)
            .first()
        )
        notify(claim.company_id, [user_id], "claim_rejected", offer_payload(offer))
    return claim


# ----------------------------------------------------------------------------------------------- publishing


def refresh_after_publish(version: ScheduleVersion, previous: ScheduleVersion | None) -> None:
    """Open offers of the previous published version follow the slot into the new one when the giver still has
    it there; otherwise they end and the giver and the volunteers are told."""
    if previous is None:
        return
    offers = list(offer_query(version.company_id).filter(assignment__shift__version=previous, status__in=ACTIVE))
    if not offers:
        return
    rows = {
        a.shift.slot_key: a
        for a in Assignment.objects.for_company(version.company_id)
        .filter(shift__version=version, shift__slot_key__in=[o.assignment.shift.slot_key for o in offers])
        .select_related("shift")
    }
    for offer in offers:
        row = rows.get(offer.assignment.shift.slot_key)
        if row is not None and row.employee_id == offer.offered_by_id:
            offer.assignment = row
            offer.save(update_fields=["assignment"])
            continue
        payload = offer_payload(offer)
        pending = offer.claims.filter(status=ShiftClaim.Status.PENDING)
        users = [offer.offered_by.membership.user_id, *pending.values_list("employee__membership__user_id", flat=True)]
        pending.update(status=ShiftClaim.Status.WITHDRAWN, decided_at=timezone.now())
        offer.status = ShiftOffer.Status.EXPIRED
        offer.decided_at = timezone.now()
        offer.save(update_fields=["status", "decided_at"])
        notify(version.company_id, users, "offer_expired", payload)


def visible_offers_for(profile: EmployeeProfile):
    """Active offers in the company that this person did not make (eligibility is checked per offer)."""
    expire_started(profile.company_id)
    return (
        offer_query(profile.company_id)
        .filter(status__in=ACTIVE, assignment__shift__version__status=ScheduleVersion.Status.PUBLISHED)
        .exclude(offered_by=profile)
        .filter(assignment__shift__start_at__gt=timezone.now())
        .order_by("assignment__shift__start_at")
    )
