"""Giving away shifts: the employee's "Oddaj zmianę" / "Biorę" and the manager's approval (logic in services.py)."""

from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.core.schemas import ErrorOut
from apps.marketplace import services
from apps.marketplace.models import ShiftClaim, ShiftOffer
from apps.scheduling.models import Assignment, ScheduleVersion, Shift
from apps.staffing.me import employee_context
from apps.staffing.models import EmployeeProfile
from apps.tenancy.context import TenantContext, context_for, tenant_context
from apps.tenancy.models import Location
from apps.worktime.schemas import WaitingHoursOut, WorkedOut, report_out, worked_out
from apps.worktime.services import pending_reports, worked_hours

router = Router(tags=["marketplace"])

OfferStatus = Literal["open", "claimed", "approved", "rejected", "cancelled", "expired"]
ClaimStatus = Literal["pending", "approved", "rejected", "withdrawn"]

# How long decided offers stay on the manager's list.
RECENT_DAYS = 14


class OfferShiftOut(Schema):
    date: date
    start_time: str
    end_time: str
    hours: float
    location_id: UUID
    location_name: str
    position_name: str
    shift_type_name: str


class OfferMadeOut(Schema):
    id: UUID
    status: OfferStatus
    # How many people were told that they can take it.
    notified: int
    # Of them, people whose home is the shift's location.
    notified_here: int = 0
    # The location hands given-away shifts over without the manager: the first person who takes it gets it.
    at_once: bool = False


class AvailableOfferOut(Schema):
    id: UUID
    shift: OfferShiftOut
    offered_by_name: str
    # True: the shift is in another location than my home one.
    away: bool
    # My "Biorę", if I said it: waiting for the manager.
    my_claim_id: UUID | None
    my_claim_status: ClaimStatus | None
    # "Weź zmianę" makes the shift mine at once (the location's rule "bez zatwierdzania"); my_claim_status is then
    # "approved" right after taking it.
    at_once: bool = False


class ClaimOut(Schema):
    id: UUID
    employee_id: UUID
    name: str
    home_location_name: str
    status: ClaimStatus
    created_at: datetime
    # Hard problems if this person took the shift now (empty: they can); only for waiting claims.
    problems: list[str]


class ManagerOfferOut(Schema):
    id: UUID
    # The published shift being given away (for "Wybierz osobę").
    assignment_id: UUID
    status: OfferStatus
    shift: OfferShiftOut
    offered_by_name: str
    created_at: datetime
    decided_at: datetime | None
    claims: list[ClaimOut]
    # Taken without the manager's approval (the location's rule).
    auto_approved: bool = False


class ManagerOffersOut(Schema):
    offers: list[ManagerOfferOut]
    # Volunteers waiting for a decision (for the badge in the header).
    waiting: int


def _shift_out(offer: ShiftOffer | Shift) -> OfferShiftOut:
    shift = offer if isinstance(offer, Shift) else offer.assignment.shift
    tz = ZoneInfo(shift.location.timezone)
    return OfferShiftOut(
        date=shift.date,
        start_time=f"{shift.start_at.astimezone(tz):%H:%M}",
        end_time=f"{shift.end_at.astimezone(tz):%H:%M}",
        hours=round((shift.end_at - shift.start_at).total_seconds() / 3600, 2),
        location_id=shift.location_id,
        location_name=shift.location.name,
        position_name=shift.position.name,
        shift_type_name=shift.shift_type.name if shift.shift_type else "",
    )


def _my_offer(request, offer_id: UUID) -> tuple[TenantContext, ShiftOffer, EmployeeProfile]:
    ctx, offer = context_for(request, ShiftOffer, offer_id)
    _, profile = employee_context(request, ctx.company.pk)
    return ctx, offer, profile


# --- The employee --------------------------------------------------------------------------------------------


@router.post(
    "/me/shifts/{assignment_id}/offer",
    response={201: OfferMadeOut, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def offer_my_shift(request, assignment_id: UUID):
    """'Oddaj zmianę': everyone who could take my shift gets an in-app notification. It stays mine until the
    manager approves someone."""
    ctx, assignment = context_for(request, Assignment, assignment_id)
    _, profile = employee_context(request, ctx.company.pk)
    if assignment.employee_id != profile.pk:
        raise HttpError(404, "Nie znaleziono.")
    ctx.require_writable()
    offer, notified, here = services.offer_shift(assignment, profile)
    at_once = assignment.shift.location.handover_without_approval
    return Status(
        201, OfferMadeOut(id=offer.pk, status=offer.status, notified=notified, notified_here=here, at_once=at_once)
    )


@router.post("/offers/{offer_id}/cancel", response={200: OfferMadeOut, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut})
def cancel_my_offer(request, offer_id: UUID):
    """The giver keeps the shift after all."""
    ctx, offer, profile = _my_offer(request, offer_id)
    ctx.require_writable()
    offer = services.cancel_offer(offer, profile)
    return OfferMadeOut(id=offer.pk, status=offer.status, notified=0)


@router.get("/me/offers", response={200: list[AvailableOfferOut], 404: ErrorOut})
def available_offers(request, company_id: UUID):
    """'Zmiany do wzięcia': shifts given away in the company that I can take now (or already said 'Biorę' to)."""
    ctx, profile = employee_context(request, company_id)
    mine = {c.offer_id: c for c in ctx.qs(ShiftClaim).filter(employee=profile)}
    result = []
    for offer in services.visible_offers_for(profile):
        claim = mine.get(offer.pk)
        if claim is not None and claim.status == ShiftClaim.Status.REJECTED:
            continue
        if claim is None or claim.status != ShiftClaim.Status.PENDING:
            verdicts = services.check_people(offer, [profile])
            if not verdicts or not verdicts[0].possible:
                continue
        waiting = claim is not None and claim.status == ShiftClaim.Status.PENDING
        result.append(
            AvailableOfferOut(
                id=offer.pk,
                shift=_shift_out(offer),
                offered_by_name=services.person_name(offer.offered_by),
                away=offer.assignment.shift.location_id != profile.home_location_id,
                my_claim_id=claim.pk if waiting else None,
                my_claim_status=claim.status if waiting else None,
                at_once=services.takes_without_approval(offer) if not waiting else False,
            )
        )
    return result


@router.post("/offers/{offer_id}/claim", response={201: AvailableOfferOut, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut})
def claim_offer(request, offer_id: UUID):
    """'Biorę': the managers of the location decide; the shift is not mine until they approve. With the location's
    rule "bez zatwierdzania" it is mine at once (status "approved")."""
    ctx, offer, profile = _my_offer(request, offer_id)
    ctx.require_writable()
    claim = services.claim_offer(offer, profile)
    offer = services.offer_query(ctx.company.pk).get(pk=offer.pk)
    return Status(
        201,
        AvailableOfferOut(
            id=offer.pk,
            shift=_shift_out(offer),
            offered_by_name=services.person_name(offer.offered_by),
            away=offer.assignment.shift.location_id != profile.home_location_id,
            my_claim_id=claim.pk,
            my_claim_status=claim.status,
            at_once=claim.auto_approved,
        ),
    )


@router.post("/claims/{claim_id}/withdraw", response={204: None, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut})
def withdraw_my_claim(request, claim_id: UUID):
    ctx, claim = context_for(request, ShiftClaim, claim_id)
    _, profile = employee_context(request, ctx.company.pk)
    ctx.require_writable()
    services.withdraw_claim(claim, profile)
    return Status(204, None)


# --- The manager ---------------------------------------------------------------------------------------------


def _claims_out(offer: ShiftOffer, check: bool) -> list[ClaimOut]:
    claims = list(offer.claims.select_related("employee__membership__user", "employee__home_location"))
    pending = [c.employee for c in claims if c.status == ShiftClaim.Status.PENDING]
    problems: dict = {}
    if check and pending:
        problems = {p.pk: ["Ta osoba nie pracuje już na tym stanowisku."] for p in pending}
        problems.update({v.employee.pk: list(v.problems) for v in services.check_people(offer, pending)})
    order = {"pending": 0, "approved": 1, "rejected": 2, "withdrawn": 3}
    claims.sort(key=lambda c: (order[c.status], c.created_at))
    return [
        ClaimOut(
            id=c.pk,
            employee_id=c.employee_id,
            name=services.person_name(c.employee),
            home_location_name=c.employee.home_location.name,
            status=c.status,
            created_at=c.created_at,
            problems=problems.get(c.employee_id, []) if c.status == ShiftClaim.Status.PENDING else [],
        )
        for c in claims
    ]


@router.get("/manager/offers", response={200: ManagerOffersOut, 403: ErrorOut, 404: ErrorOut})
def manager_offers(request, company_id: UUID):
    """'Oddane zmiany' in my locations: open ones, those waiting for my decision, and the last two weeks."""
    ctx = tenant_context(request, company_id)
    ctx.require_manager()
    services.expire_started(ctx.company.pk)
    since = timezone.now() - timedelta(days=RECENT_DAYS)
    rows = services.offer_query(ctx.company.pk).filter(assignment__shift__location__in=ctx.managed_locations())
    active = list(rows.filter(status__in=services.ACTIVE).order_by("assignment__shift__start_at"))
    recent = list(rows.exclude(status__in=services.ACTIVE).filter(decided_at__gte=since).order_by("-decided_at")[:50])
    offers = [
        ManagerOfferOut(
            id=o.pk,
            assignment_id=o.assignment_id,
            status=o.status,
            shift=_shift_out(o),
            offered_by_name=services.person_name(o.offered_by),
            created_at=o.created_at,
            decided_at=o.decided_at,
            claims=_claims_out(o, check=o.status == ShiftOffer.Status.CLAIMED),
            auto_approved=any(c.auto_approved for c in o.claims.all()),
        )
        for o in active + recent
    ]
    waiting = sum(1 for o in offers for c in o.claims if c.status == "pending")
    return ManagerOffersOut(offers=offers, waiting=waiting)


def _managed_claim(request, claim_id: UUID) -> tuple[TenantContext, ShiftClaim]:
    ctx, claim = context_for(request, ShiftClaim, claim_id)
    offer = services.offer_query(ctx.company.pk).get(pk=claim.offer_id)
    ctx.require_manager_of(offer.assignment.shift.location)
    ctx.require_writable()
    return ctx, claim


DECISION_ERRORS = {402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut}


@router.post("/claims/{claim_id}/approve", response={200: OfferMadeOut, **DECISION_ERRORS})
def approve_claim(request, claim_id: UUID):
    """The volunteer gets the shift in the published schedule (checked by the validator again)."""
    ctx, claim = _managed_claim(request, claim_id)
    offer = services.approve_claim(claim, ctx.user)
    return OfferMadeOut(id=offer.pk, status=offer.status, notified=0)


@router.post("/claims/{claim_id}/reject", response={204: None, **DECISION_ERRORS})
def reject_claim(request, claim_id: UUID):
    ctx, claim = _managed_claim(request, claim_id)
    services.reject_claim(claim, ctx.user)
    return Status(204, None)


# --- The manager's own changes: another person on a shift, a swap, an offer on someone's behalf ---------------

# How far back and ahead "Zmień obsadę" lists published shifts.
PAST_DAYS = 14
AHEAD_DAYS = 62


class ManagerShiftOut(Schema):
    id: UUID  # the assignment
    version_id: UUID
    shift: OfferShiftOut
    employee_id: UUID | None
    employee_name: str  # "" = nobody on the shift
    # The shift has already started: it can still be corrected, but not offered.
    started: bool
    # An active offer of this shift ("Oddane zmiany").
    offer_id: UUID | None = None
    # Hours that count for the person instead of the schedule's ("Zmień godziny sam"); None: as planned.
    worked: WorkedOut | None = None
    # The person's report of other hours, waiting for a decision.
    hours_report: WaitingHoursOut | None = None


class HandoverCandidateOut(Schema):
    employee_id: UUID
    name: str
    home_location_name: str
    # Works in the shift's own location.
    here: bool
    # Said "Weź zmianę" for this shift and waits for a decision.
    wants: bool
    # Hard problems this person on the shift would add (empty: fine). The manager may overrule them.
    problems: list[str]


class ReassignIn(Schema):
    employee_id: UUID
    # Put the person there although the validator has objections.
    force: bool = False


class SwapIn(Schema):
    first_id: UUID
    second_id: UUID
    force: bool = False


class SwapCheckOut(Schema):
    problems: list[str]


def _managed_assignment(request, assignment_id: UUID, write: bool = True) -> tuple[TenantContext, Assignment]:
    ctx, assignment = context_for(request, Assignment, assignment_id)
    ctx.require_manager_of(assignment.shift.location)
    if write:
        ctx.require_writable()
    return ctx, assignment


@router.get("/locations/{location_id}/handover-shifts", response={200: list[ManagerShiftOut], **DECISION_ERRORS})
def handover_shifts(request, location_id: UUID):
    """Published shifts of the location (two weeks back, two months ahead) for "Zmień obsadę"."""
    ctx, location = context_for(request, Location, location_id)
    ctx.require_manager_of(location)
    today = timezone.localdate()
    rows = list(
        ctx.qs(Assignment)
        .filter(
            shift__location=location,
            shift__version__status=ScheduleVersion.Status.PUBLISHED,
            shift__date__range=(today - timedelta(days=PAST_DAYS), today + timedelta(days=AHEAD_DAYS)),
        )
        .select_related(
            "shift__location", "shift__position", "shift__shift_type", "shift__version", "employee__membership__user"
        )
        .order_by("shift__start_at", "shift__position__name", "shift__slot_key")
    )
    worked, waiting = worked_hours(rows), pending_reports(rows)
    offers = dict(
        ctx.qs(ShiftOffer)
        .filter(assignment__in=[a.pk for a in rows], status__in=services.ACTIVE)
        .values_list("assignment_id", "pk")
    )
    now = timezone.now()
    return [
        ManagerShiftOut(
            id=a.pk,
            version_id=a.shift.version_id,
            shift=_shift_out(a.shift),
            employee_id=a.employee_id,
            employee_name=services.person_name(a.employee) if a.employee else "",
            started=a.shift.start_at <= now,
            offer_id=offers.get(a.pk),
            worked=worked_out(worked.get(a.pk), a.shift),
            hours_report=report_out(waiting.get(a.pk), a.shift),
        )
        for a in rows
    ]


@router.get(
    "/assignments/{assignment_id}/handover-candidates",
    response={200: list[HandoverCandidateOut], **DECISION_ERRORS},
)
def handover_candidates(request, assignment_id: UUID):
    """Who the manager can put on this published shift: people who can come first, then those with problems."""
    ctx, assignment = _managed_assignment(request, assignment_id, write=False)
    if assignment.shift.version.status != ScheduleVersion.Status.PUBLISHED:
        raise HttpError(409, services.NOT_PUBLISHED)
    wants = set(
        ctx.qs(ShiftClaim)
        .filter(offer__assignment=assignment, offer__status__in=services.ACTIVE, status=ShiftClaim.Status.PENDING)
        .values_list("employee_id", flat=True)
    )
    location_id = assignment.shift.location_id
    result = [
        HandoverCandidateOut(
            employee_id=v.employee.pk,
            name=services.person_name(v.employee),
            home_location_name=v.employee.home_location.name,
            here=v.employee.works_in(location_id),
            wants=v.employee.pk in wants,
            problems=list(v.problems),
        )
        for v in services.manager_candidates(assignment)
    ]
    result.sort(key=lambda c: (bool(c.problems), not c.wants, not c.here, c.name))
    return result


@router.post("/assignments/{assignment_id}/reassign", response={200: ManagerShiftOut, **DECISION_ERRORS})
def reassign_shift(request, assignment_id: UUID, payload: ReassignIn):
    """The manager puts another person on a published shift, without anyone's "Weź zmianę"."""
    ctx, assignment = _managed_assignment(request, assignment_id)
    taker = ctx.get(EmployeeProfile, pk=payload.employee_id)
    row = services.manager_reassign(assignment, taker, ctx.user, force=payload.force)
    return ManagerShiftOut(
        id=row.pk,
        version_id=row.shift.version_id,
        shift=_shift_out(row.shift),
        employee_id=row.employee_id,
        employee_name=services.person_name(row.employee),
        started=row.shift.start_at <= timezone.now(),
    )


def _swap_pair(request, payload: SwapIn, write: bool) -> tuple[TenantContext, Assignment, Assignment]:
    ctx, first = _managed_assignment(request, payload.first_id, write=write)
    second = ctx.get(Assignment, pk=payload.second_id)
    ctx.require_manager_of(second.shift.location)
    return ctx, first, second


@router.post("/shift-swaps/check", response={200: SwapCheckOut, **DECISION_ERRORS})
def check_shift_swap(request, payload: SwapIn):
    """What the validator says about two people exchanging their published shifts (nothing is saved)."""
    _, first, second = _swap_pair(request, payload, write=False)
    if first.shift.version.status != ScheduleVersion.Status.PUBLISHED:
        raise HttpError(409, services.NOT_PUBLISHED)
    return SwapCheckOut(problems=list(services.swap_problems(first, second)))


@router.post("/shift-swaps", response={204: None, **DECISION_ERRORS})
def swap_shifts(request, payload: SwapIn):
    """Two people exchange their published shifts; both are told in the app."""
    ctx, first, second = _swap_pair(request, payload, write=True)
    services.manager_swap(first, second, ctx.user, force=payload.force)
    return Status(204, None)


@router.post("/assignments/{assignment_id}/offer", response={201: OfferMadeOut, **DECISION_ERRORS})
def offer_shift_for_employee(request, assignment_id: UUID):
    """The manager looks for someone to take an employee's shift: the same offer as the employee's "Oddaj zmianę"."""
    ctx, assignment = _managed_assignment(request, assignment_id)
    if assignment.employee_id is None:
        raise HttpError(409, "Na tej zmianie nikogo nie ma. Wybierz osobę sam.")
    giver = ctx.get(EmployeeProfile, pk=assignment.employee_id)
    offer, notified, here = services.offer_shift(assignment, giver, by_manager=ctx.user)
    at_once = assignment.shift.location.handover_without_approval
    return Status(
        201, OfferMadeOut(id=offer.pk, status=offer.status, notified=notified, notified_here=here, at_once=at_once)
    )


@router.post("/offers/{offer_id}/close", response={200: OfferMadeOut, **DECISION_ERRORS})
def close_offer(request, offer_id: UUID):
    """The manager ends an offer: the shift stays with the person who gave it away."""
    ctx, offer = context_for(request, ShiftOffer, offer_id)
    offer = services.offer_query(ctx.company.pk).get(pk=offer.pk)
    ctx.require_manager_of(offer.assignment.shift.location)
    ctx.require_writable()
    offer = services.manager_close_offer(offer, ctx.user)
    return OfferMadeOut(id=offer.pk, status=offer.status, notified=0)
