"""Giving away a shift: an employee offers a published shift, others say "Biorę", the manager approves one.

- `offer_shift`: only my own shift in a published schedule that has not started yet. Everyone in the company who
  could take it (same position name, no "nie mogę", no other shift at that time, no "no exceptions" rule broken;
  checked by the validator) gets an in-app notification.
- `claim_offer` / `withdraw_claim` / `cancel_offer`: the person is checked again when they say "Biorę"; the
  managers of the location get a notification.
- `approve_claim`: checked once more against the published schedule as it is now, then the published shift (and
  the newest draft, if it still has the giver there) moves to the new person, pinned, with a history row
  (`AssignmentEvent`, reason "offer"). The giver, the taker and the other volunteers are told.
- With the location rule "przejęcie oddanej zmiany bez zatwierdzania" (`Location.handover_without_approval`),
  "Biorę" hands the shift over at once in the same way (`_hand_over`), when nobody else is already waiting for
  the manager. The giver, the taker and the managers are told.
- `refresh_after_publish`: a newly published version keeps open offers whose giver still has the shift and
  ends the others.

- The manager can also act alone ("the manager's own changes" below): `manager_reassign` puts another person on a
  published shift, `manager_swap` exchanges two people (`AssignmentEvent.Reason.SWAP`), `offer_shift(by_manager=)`
  looks for someone on an employee's behalf, `manager_close_offer` ends an offer.
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from ninja.errors import HttpError

from apps.marketplace.models import ShiftClaim, ShiftOffer
from apps.notifications.services import location_manager_ids, notify
from apps.scheduling.editing import save_scores
from apps.scheduling.models import Assignment, AssignmentEvent, SchedulePeriod, ScheduleVersion, Shift
from apps.scheduling.problem_builder import build_problem_for_version
from apps.staffing.models import EmployeeProfile, Position
from engine.explain import without_pin
from engine.scoring import score
from engine.validator import validate

ACTIVE = (ShiftOffer.Status.OPEN, ShiftOffer.Status.CLAIMED)
GONE = "Tej zmiany nie można już wziąć: oddanie jest zakończone albo grafik się zmienił."


def person_name(profile: EmployeeProfile) -> str:
    return profile.membership.user.full_name or "Pracownik bez imienia"


def shift_payload(shift: Shift) -> dict:
    tz = ZoneInfo(shift.location.timezone)
    return {
        "date": shift.date.isoformat(),
        "start_time": f"{shift.start_at.astimezone(tz):%H:%M}",
        "end_time": f"{shift.end_at.astimezone(tz):%H:%M}",
        "position_name": shift.position.name,
        "location_name": shift.location.name,
    }


def offer_payload(offer: ShiftOffer) -> dict:
    return {
        "offer_id": str(offer.pk),
        **shift_payload(offer.assignment.shift),
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


def _people_with_position(assignment: Assignment, among=None, also_location: bool = False):
    """Active people of the company (but the one who has the shift) with the shift's position, here or by name
    elsewhere. `also_location`: plus everyone of the shift's own location (for the manager, who may overrule)."""
    shift = assignment.shift
    names = Position.objects.for_company(assignment.company_id).filter(name__iexact=shift.position.name)
    wanted = Q(positions__in=names)
    if also_location:
        wanted |= Q(home_location_id=shift.location_id)
    people = (
        EmployeeProfile.objects.for_company(assignment.company_id)
        .filter(wanted, is_active=True)
        .select_related("membership__user", "home_location")
        .distinct()
    )
    if assignment.employee_id:
        people = people.exclude(pk=assignment.employee_id)
    if among is not None:
        people = people.filter(pk__in=[p.pk for p in among])
    return list(people)


def check_assignment(assignment: Assignment, people=None, also_location: bool = False) -> list[Verdict]:
    """For each person (default: everyone with the position), the hard problems if they took this shift instead
    of the person who has it, in its schedule as it is now. Problems the schedule already had do not count."""
    candidates = _people_with_position(assignment, people, also_location)
    if not candidates:
        return []
    version = assignment.shift.version
    built, schedule = build_problem_for_version(version, extra_employees=[str(p.pk) for p in candidates])
    key = assignment.shift.slot_key
    problem = without_pin(built.problem, key)
    known = {v.message for v in validate(problem, schedule).hard}
    verdicts = []
    for person in candidates:
        report = validate(problem, {**schedule, key: str(person.pk)})
        problems = tuple(v.message for v in report.hard if v.message not in known)
        verdicts.append(Verdict(person, problems))
    return verdicts


def check_people(offer: ShiftOffer, people=None) -> list[Verdict]:
    """Who can take the offered shift instead of the giver (see `check_assignment`)."""
    return check_assignment(offer.assignment, people)


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


def offer_shift(assignment: Assignment, profile: EmployeeProfile, by_manager=None) -> tuple[ShiftOffer, int, int]:
    """'Oddaj zmianę': returns the offer, how many people were told about it, and how many of them work
    in the shift's own location (the giver wants to know whether colleagues or people from elsewhere can come).
    `by_manager`: the manager's user who looks for someone on the employee's behalf (the employee is told)."""
    with transaction.atomic():
        assignment = (
            Assignment.objects.for_company(profile.company_id)
            .select_for_update(of=("self",))
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
        told_here = len({p.membership.user_id for p in able if p.home_location_id == assignment.shift.location_id})
        # The managers know early, especially when nobody can take it (the giver still has to come).
        acting = by_manager.pk if by_manager is not None else profile.membership.user_id
        managers = set(location_manager_ids(assignment.shift.location)) - {acting}
        notify(offer.company_id, managers, "offer_made", {**payload, "able": told})
        if by_manager is not None and profile.membership.user_id != by_manager.pk:
            notify(offer.company_id, [profile.membership.user_id], "offer_opened_for_you", {**payload, "able": told})
    return offer, told, told_here


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
    """'Biorę': allowed only to someone who can take the shift now; the managers decide, or with the location's
    rule "bez zatwierdzania" the shift is the taker's at once (the returned claim is then approved)."""
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
        auto = takes_without_approval(offer)
        if auto:
            # Same lock as the manager's approval: no schedule edit or publication between the check and the move.
            SchedulePeriod.objects.select_for_update().filter(pk=offer.assignment.shift.version.period_id).first()
            profile = EmployeeProfile.objects.for_company(offer.company_id).select_for_update().get(pk=profile.pk)
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
        if auto:
            # The location's rule: the first person who can take it gets it, no manager in between.
            _hand_over(offer, claim, profile, by=profile.membership.user, auto=True)
            return claim
        offer.status = ShiftOffer.Status.CLAIMED
        offer.save(update_fields=["status"])
        payload = {**offer_payload(offer), "claimed_by_name": person_name(profile)}
        notify(offer.company_id, location_manager_ids(offer.assignment.shift.location), "shift_claimed", payload)
        notify(offer.company_id, [offer.offered_by.membership.user_id], "offer_claimed", payload)
    return claim


def takes_without_approval(offer: ShiftOffer) -> bool:
    """'Weź zmianę' moves the shift at once: the location says so and nobody is already waiting for the manager
    (someone who said 'Biorę' before the rule was switched on keeps their place in the queue)."""
    if not offer.assignment.shift.location.handover_without_approval:
        return False
    return not offer.claims.filter(status=ShiftClaim.Status.PENDING).exists()


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


def _move(assignment: Assignment, to: EmployeeProfile, pinned: bool = True) -> None:
    assignment.employee = to
    assignment.borrowed = to.home_location_id != assignment.shift.location_id
    assignment.manual = True
    # The new person was agreed on: arranging the period again keeps them there.
    assignment.pinned = pinned
    assignment.forced = False  # an earlier override was about the person who had the shift
    assignment.save(update_fields=["employee", "borrowed", "manual", "pinned", "forced"])


def _transfer(published: Assignment, taker: EmployeeProfile, reason: str, by, now, pinned: bool = True) -> None:
    """Move a published shift (and the newest draft's copy, when it still has the same person) to `taker`, with
    a history row. The caller holds the locks and saves the scores afterwards (`_rescore`)."""
    shift = published.shift
    before = published.employee_id
    _move(published, taker, pinned)
    newest = (
        ScheduleVersion.objects.for_company(published.company_id)
        .filter(period_id=shift.version.period_id)
        .order_by("-number")
        .first()
    )
    if newest is not None and newest.status == ScheduleVersion.Status.DRAFT:
        draft_row = (
            Assignment.objects.for_company(published.company_id)
            .filter(shift__version=newest, shift__slot_key=shift.slot_key, employee_id=before)
            .select_related("shift")
            .first()
        )
        if draft_row is not None:
            _move(draft_row, taker, pinned)
    AssignmentEvent.objects.create(
        company_id=published.company_id,
        location_id=shift.location_id,
        period_id=shift.version.period_id,
        slot_key=shift.slot_key,
        from_employee_id=before,
        to_employee=taker,
        reason=reason,
        by=by,
        at=now,
    )


def _rescore(version: ScheduleVersion) -> None:
    built, schedule = build_problem_for_version(version)
    report = validate(built.problem, schedule)
    save_scores(version, score(built.problem, report, location=str(version.period.location_id)))


def _tell_home_managers(taker: EmployeeProfile, shift: Shift, payload: dict, auto: bool) -> None:
    """The taker's own manager learns that they work elsewhere that day."""
    if taker.home_location_id != shift.location_id:
        home = set(location_manager_ids(taker.home_location)) - set(location_manager_ids(shift.location))
        notify(taker.company_id, home, "borrowed", {**payload, "auto": auto})


def _hand_over(offer: ShiftOffer, claim: ShiftClaim, taker: EmployeeProfile, by, auto: bool) -> None:
    """Move the published shift (and the newest draft's copy) to the taker, pinned, with a history row; close the
    offer and tell everyone. The caller holds the locks and has checked the taker with the validator.
    `auto`: the location's rule approved it ("bez zatwierdzania"); `by` is then the taker's own user."""
    now = timezone.now()
    shift = offer.assignment.shift
    _transfer(offer.assignment, taker, AssignmentEvent.Reason.OFFER, by, now)
    _rescore(shift.version)

    claim.status = ShiftClaim.Status.APPROVED
    claim.auto_approved = auto
    claim.decided_by = None if auto else by
    claim.decided_at = now
    claim.save(update_fields=["status", "auto_approved", "decided_by", "decided_at"])
    others = offer.claims.filter(status=ShiftClaim.Status.PENDING).exclude(pk=claim.pk)
    other_users = list(others.values_list("employee__membership__user_id", flat=True))
    others.update(status=ShiftClaim.Status.REJECTED, decided_by=None if auto else by, decided_at=now)
    offer.status = ShiftOffer.Status.APPROVED
    offer.decided_at = now
    offer.save(update_fields=["status", "decided_at"])

    payload = {**offer_payload(offer), "claimed_by_name": person_name(taker)}
    managers = set(location_manager_ids(shift.location))
    if auto:
        notify(offer.company_id, [taker.membership.user_id], "claim_taken", payload)
        notify(offer.company_id, [offer.offered_by.membership.user_id], "offer_taken_auto", payload)
        notify(offer.company_id, managers - {taker.membership.user_id}, "handover_done", payload)
    else:
        notify(offer.company_id, [taker.membership.user_id], "claim_approved", payload)
        notify(offer.company_id, [offer.offered_by.membership.user_id], "offer_taken", payload)
    notify(offer.company_id, other_users, "claim_rejected", payload)
    _tell_home_managers(taker, shift, payload, auto)


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
            .select_for_update(of=("self",))
            .select_related("membership__user", "home_location")
            .get(pk=claim.employee_id)
        )
        verdicts = check_people(offer, [taker]) if taker.is_active else []
        if not verdicts or not verdicts[0].possible:
            reasons = " ".join(verdicts[0].problems) if verdicts else "Ta osoba nie pracuje już na tym stanowisku."
            raise HttpError(409, "Tej osoby nie można wpisać na tę zmianę: " + reasons)

        _hand_over(offer, claim, taker, by=user, auto=False)
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


# ----------------------------------------------------------------------------------- the manager's own changes
#
# The manager decides alone, without anyone's "Biorę": puts another person on a published shift, swaps two
# people, looks for someone on an employee's behalf, or ends an offer. The validator still checks every change,
# but the manager may overrule it (`force`): the change is then saved unpinned, because a pinned shift that
# breaks a hard rule would make arranging the period again impossible. Shifts that have already started can be
# changed too, so that the schedule (and the hours counted from it) says who really worked.

NOT_PUBLISHED = "Tak można zmieniać tylko opublikowany grafik. Szkic popraw w „Grafik”."


def _locked_published(company_id, assignment_ids) -> list[Assignment]:
    """Published assignments locked for a change, in the order given, with their period locked like an edit."""
    rows = {
        a.pk: a
        for a in Assignment.objects.for_company(company_id)
        .select_for_update(of=("self",))
        .select_related("shift__version__period", "shift__location", "shift__position", "shift__shift_type")
        .filter(pk__in=assignment_ids)
        .order_by("pk")
    }
    found = [rows[pk] for pk in assignment_ids if pk in rows]
    if len(found) != len(assignment_ids):
        raise HttpError(404, "Nie znaleziono.")
    for period_id in sorted({a.shift.version.period_id for a in found}):
        SchedulePeriod.objects.select_for_update().filter(pk=period_id).first()
    if any(a.shift.version.status != ScheduleVersion.Status.PUBLISHED for a in found):
        raise HttpError(409, NOT_PUBLISHED)
    return found


def _started(shift: Shift) -> bool:
    return shift.start_at <= timezone.now()


def _end_offer_after_change(assignment: Assignment, taker: EmployeeProfile | None, by, now) -> None:
    """The manager changed who has an offered shift: the offer is over. When the new person had said "Biorę"
    (or the manager picked them for an offered shift) it ends as approved, otherwise as out of date."""
    offer = offer_query(assignment.company_id).filter(assignment=assignment, status__in=ACTIVE).first()
    if offer is None:
        return
    pending = offer.claims.filter(status=ShiftClaim.Status.PENDING)
    if taker is not None:
        claim = offer.claims.filter(employee=taker).first() or ShiftClaim(offer=offer, employee=taker)
        claim.status = ShiftClaim.Status.APPROVED
        claim.decided_by = by
        claim.decided_at = now
        claim.save()
        pending = pending.exclude(pk=claim.pk)
        offer.status = ShiftOffer.Status.APPROVED
    else:
        offer.status = ShiftOffer.Status.EXPIRED
    users = list(pending.values_list("employee__membership__user_id", flat=True))
    pending.update(status=ShiftClaim.Status.REJECTED, decided_by=by, decided_at=now)
    offer.decided_at = now
    offer.save(update_fields=["status", "decided_at"])
    notify(offer.company_id, users, "claim_rejected", offer_payload(offer))


def manager_candidates(assignment: Assignment) -> list[Verdict]:
    """Everyone the manager can put on this shift: people with the position anywhere in the company and everyone
    of the shift's location, each with the hard problems the change would add (the manager may overrule them)."""
    return check_assignment(assignment, also_location=True)


def manager_reassign(assignment: Assignment, taker: EmployeeProfile, user, force: bool = False) -> Assignment:
    """The manager puts `taker` on a published shift instead of the person who has it (or on an empty one)."""
    with transaction.atomic():
        (assignment,) = _locked_published(assignment.company_id, [assignment.pk])
        taker = (
            EmployeeProfile.objects.for_company(assignment.company_id)
            .select_for_update(of=("self",))
            .select_related("membership__user", "home_location")
            .filter(pk=taker.pk, is_active=True)
            .first()
        )
        if taker is None:
            raise HttpError(409, "Ta osoba nie pracuje już w firmie.")
        if assignment.employee_id == taker.pk:
            raise HttpError(409, "Ta osoba już ma tę zmianę.")
        verdicts = check_assignment(assignment, [taker], also_location=True)
        problems = verdicts[0].problems if verdicts else ("Ta osoba nie pracuje na tym stanowisku.",)
        if problems and not force:
            raise HttpError(409, "Tej osoby nie można wpisać na tę zmianę: " + " ".join(problems))
        now = timezone.now()
        shift = assignment.shift
        before = assignment.employee
        _transfer(assignment, taker, AssignmentEvent.Reason.MANUAL, user, now, pinned=not problems)
        _rescore(shift.version)
        _end_offer_after_change(assignment, taker, user, now)

        payload = {**shift_payload(shift), "claimed_by_name": person_name(taker), "past": _started(shift)}
        notify(assignment.company_id, {taker.membership.user_id} - {user.pk}, "shift_assigned", payload)
        if before is not None:
            notify(assignment.company_id, {before.membership.user_id} - {user.pk}, "shift_unassigned", payload)
        _tell_home_managers(taker, shift, payload, auto=False)
    return assignment


def swap_problems(first: Assignment, second: Assignment) -> tuple[str, ...]:
    """Hard problems that swapping the two people would add to their published schedule (empty: fine)."""
    if first.pk == second.pk:
        raise HttpError(409, "Wybierz dwie różne zmiany.")
    if first.shift.version_id != second.shift.version_id:
        raise HttpError(409, "Zamienić można dwie zmiany z tego samego grafiku (ten sam lokal i okres).")
    if first.employee_id is None or second.employee_id is None:
        raise HttpError(409, "Zamienić można tylko zmiany, na których ktoś jest.")
    if first.employee_id == second.employee_id:
        raise HttpError(409, "Obie zmiany ma ta sama osoba.")
    built, schedule = build_problem_for_version(first.shift.version)
    keys = (first.shift.slot_key, second.shift.slot_key)
    problem = without_pin(without_pin(built.problem, keys[0]), keys[1])
    known = {v.message for v in validate(problem, schedule).hard}
    swapped = {**schedule, keys[0]: str(second.employee_id), keys[1]: str(first.employee_id)}
    return tuple(v.message for v in validate(problem, swapped).hard if v.message not in known)


def manager_swap(first: Assignment, second: Assignment, user, force: bool = False) -> None:
    """Two people exchange their published shifts (history reason "swap"); both are told."""
    with transaction.atomic():
        first, second = _locked_published(first.company_id, [first.pk, second.pk])
        problems = swap_problems(first, second)
        if problems and not force:
            raise HttpError(409, "Tej zamiany nie można zrobić: " + " ".join(problems))
        now = timezone.now()
        people = {
            p.pk: p
            for p in EmployeeProfile.objects.for_company(first.company_id)
            .select_related("membership__user", "home_location")
            .filter(pk__in=[first.employee_id, second.employee_id])
        }
        one, two = people[first.employee_id], people[second.employee_id]
        _transfer(first, two, AssignmentEvent.Reason.SWAP, user, now, pinned=not problems)
        _transfer(second, one, AssignmentEvent.Reason.SWAP, user, now, pinned=not problems)
        _rescore(first.shift.version)
        for row in (first, second):
            _end_offer_after_change(row, None, user, now)
        for person, gave, got, other in ((one, first, second, two), (two, second, first, one)):
            payload = {**shift_payload(got.shift), "given": shift_payload(gave.shift), "with_name": person_name(other)}
            notify(first.company_id, {person.membership.user_id} - {user.pk}, "shift_swapped", payload)


def manager_close_offer(offer: ShiftOffer, user) -> ShiftOffer:
    """The manager ends an offer: the shift stays with the giver, the volunteers are turned down."""
    with transaction.atomic():
        offer = offer_query(offer.company_id).select_for_update(of=("self",)).get(pk=offer.pk)
        if offer.status not in ACTIVE:
            raise HttpError(409, "To oddanie jest już zakończone.")
        now = timezone.now()
        pending = offer.claims.filter(status=ShiftClaim.Status.PENDING)
        users = list(pending.values_list("employee__membership__user_id", flat=True))
        pending.update(status=ShiftClaim.Status.REJECTED, decided_by=user, decided_at=now)
        offer.status = ShiftOffer.Status.REJECTED
        offer.decided_at = now
        offer.save(update_fields=["status", "decided_at"])
        payload = offer_payload(offer)
        # Not a refusal of the volunteer: nobody takes the shift, the giver stays on it.
        notify(offer.company_id, users, "offer_cancelled", payload)
        notify(offer.company_id, {offer.offered_by.membership.user_id} - {user.pk}, "offer_closed", payload)
    return offer


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
