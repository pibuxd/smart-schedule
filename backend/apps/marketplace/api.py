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
from apps.scheduling.models import Assignment
from apps.staffing.me import employee_context
from apps.staffing.models import EmployeeProfile
from apps.tenancy.context import TenantContext, context_for, tenant_context

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


class AvailableOfferOut(Schema):
    id: UUID
    shift: OfferShiftOut
    offered_by_name: str
    # True: the shift is in another location than my home one.
    away: bool
    # My "Biorę", if I said it: waiting for the manager.
    my_claim_id: UUID | None
    my_claim_status: ClaimStatus | None


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
    status: OfferStatus
    shift: OfferShiftOut
    offered_by_name: str
    created_at: datetime
    decided_at: datetime | None
    claims: list[ClaimOut]


class ManagerOffersOut(Schema):
    offers: list[ManagerOfferOut]
    # Volunteers waiting for a decision (for the badge in the header).
    waiting: int


def _shift_out(offer: ShiftOffer) -> OfferShiftOut:
    shift = offer.assignment.shift
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
    offer, notified = services.offer_shift(assignment, profile)
    return Status(201, OfferMadeOut(id=offer.pk, status=offer.status, notified=notified))


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
            )
        )
    return result


@router.post("/offers/{offer_id}/claim", response={201: AvailableOfferOut, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut})
def claim_offer(request, offer_id: UUID):
    """'Biorę': the managers of the location decide; the shift is not mine until they approve."""
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
            status=o.status,
            shift=_shift_out(o),
            offered_by_name=services.person_name(o.offered_by),
            created_at=o.created_at,
            decided_at=o.decided_at,
            claims=_claims_out(o, check=o.status == ShiftOffer.Status.CLAIMED),
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
