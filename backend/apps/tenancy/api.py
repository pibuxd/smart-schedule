"""Registering a company and invitations (the manager's side and the invited person's side)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from django.db import IntegrityError, transaction
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.accounts.login import parse_phone
from apps.billing.services import (
    CodeRejected,
    check_code_attempt_limit,
    record_code_attempt,
    redeem_code,
)
from apps.core.http import client_ip
from apps.core.schemas import ErrorOut
from apps.tenancy import invitations
from apps.tenancy.context import context_for, tenant_context
from apps.tenancy.models import Company, Invitation, InvitationStatus, Location, LocationGroup, Membership, Role

router = Router(tags=["tenancy"])

InvitationRole = Literal["manager", "employee"]
InvitationStatusName = Literal["pending", "accepted", "declined", "cancelled"]


class CompanyIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    first_name: str = Field("", max_length=80)
    last_name: str = Field("", max_length=120)
    # Optional free-access code; without it the company starts read-only until a code is entered.
    code: str = Field("", max_length=40)


class CompanyOut(Schema):
    id: UUID
    name: str
    read_only: bool
    subscription_ends_at: datetime | None


class MyInvitationOut(Schema):
    id: UUID
    company_name: str
    location_name: str
    location_address: str
    role: InvitationRole
    # Who sent it, e.g. "Teresa Gawlik", so the person recognises the invitation ("" when unknown).
    invited_by_name: str
    created_at: datetime


class InvitationIn(Schema):
    phone: str = Field(max_length=32)
    role: InvitationRole = "employee"
    first_name: str = Field("", max_length=80)
    last_name: str = Field("", max_length=120)


class InvitationOut(Schema):
    id: UUID
    location_id: UUID
    phone: str
    first_name: str
    last_name: str
    role: InvitationRole
    status: InvitationStatusName
    created_at: datetime
    decided_at: datetime | None


def _my_invitation_out(invitation: Invitation) -> MyInvitationOut:
    return MyInvitationOut(
        id=invitation.id,
        company_name=invitation.company.name,
        location_name=invitation.location.name,
        location_address=invitation.location.address,
        role=invitation.role,
        invited_by_name=invitation.invited_by.full_name if invitation.invited_by else "",
        created_at=invitation.created_at,
    )


def _invitation_out(invitation: Invitation) -> InvitationOut:
    return InvitationOut(
        id=invitation.id,
        location_id=invitation.location_id,
        phone=invitation.phone_e164,
        first_name=invitation.first_name,
        last_name=invitation.last_name,
        role=invitation.role,
        status=invitation.status,
        created_at=invitation.created_at,
        decided_at=invitation.decided_at,
    )


@router.post("/companies", response={201: CompanyOut, 400: ErrorOut, 429: ErrorOut})
def create_company(request, payload: CompanyIn):
    """Register a company; the logged-in person becomes its owner. A wrong code creates nothing."""
    user = request.user
    name = payload.name.strip()
    if not name:
        raise HttpError(400, "Podaj nazwę firmy.")
    code = payload.code.strip()
    ip = client_ip(request)
    if code:
        check_code_attempt_limit(user, ip)

    subscription = None
    try:
        with transaction.atomic():
            company = Company.objects.create(name=name, created_by=user)  # tenant-ok: a new company
            Membership.objects.create(company=company, user=user, role=Role.OWNER)  # tenant-ok: its first member
            if code:
                subscription = redeem_code(company, user, code)
            changed = []
            if payload.first_name.strip() and not user.first_name:
                user.first_name = payload.first_name.strip()
                changed.append("first_name")
            if payload.last_name.strip() and not user.last_name:
                user.last_name = payload.last_name.strip()
                changed.append("last_name")
            if changed:
                user.save(update_fields=changed)
    except CodeRejected as exc:
        record_code_attempt(user, ip, success=False)
        raise HttpError(400, str(exc)) from exc
    if code:
        record_code_attempt(user, ip, success=True)

    out = CompanyOut(
        id=company.id,
        name=company.name,
        read_only=subscription is None,
        subscription_ends_at=subscription.ends_at if subscription else None,
    )
    return Status(201, out)


@router.get("/me/invitations", response=list[MyInvitationOut])
def my_invitations(request):
    """Pending invitations for the logged-in phone number, from any company."""
    pending = (
        Invitation.objects.filter(  # tenant-ok: invitations addressed to my phone number
            phone_e164=request.user.phone_e164, status=InvitationStatus.PENDING
        )
        .select_related("company", "location", "invited_by")
        .order_by("created_at")
    )
    return [_my_invitation_out(invitation) for invitation in pending]


@router.post("/invitations/{invitation_id}/accept", response={200: MyInvitationOut, 404: ErrorOut, 409: ErrorOut})
def accept_invitation(request, invitation_id: UUID):
    """Join the location. Works only for the invited phone number; anyone else gets 404."""
    return _my_invitation_out(invitations.accept_invitation(invitation_id, request.user))


@router.post("/invitations/{invitation_id}/decline", response={200: MyInvitationOut, 404: ErrorOut, 409: ErrorOut})
def decline_invitation(request, invitation_id: UUID):
    return _my_invitation_out(invitations.decline_invitation(invitation_id, request.user))


@router.get("/locations/{location_id}/invitations", response={200: list[InvitationOut], 404: ErrorOut})
def location_invitations(request, location_id: UUID):
    """All invitations of a location, newest first (the manager sees who has not answered yet)."""
    ctx, location = context_for(request, Location, location_id)
    ctx.require_manager_of(location)
    rows = ctx.qs(Invitation).filter(location=location).order_by("-created_at")
    return [_invitation_out(invitation) for invitation in rows]


@router.post(
    "/locations/{location_id}/invitations",
    response={201: InvitationOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def invite_to_location(request, location_id: UUID, payload: InvitationIn):
    """Invite a person by phone number. No SMS is sent; they see the invitation after logging in."""
    ctx, location = context_for(request, Location, location_id)
    ctx.require_manager_of(location)
    ctx.require_writable()
    if payload.role == Role.MANAGER and ctx.role != Role.OWNER:
        raise HttpError(403, "Menedżera może zaprosić tylko właściciel firmy.")
    invitation = invitations.create_invitation(
        location, parse_phone(payload.phone), payload.role, ctx.user, payload.first_name, payload.last_name
    )
    return Status(201, _invitation_out(invitation))


@router.post(
    "/invitations/{invitation_id}/cancel",
    response={200: InvitationOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def cancel_invitation(request, invitation_id: UUID):
    ctx, invitation = context_for(request, Invitation, invitation_id)
    ctx.require_manager_of(invitation.location)
    ctx.require_writable()
    return _invitation_out(invitations.cancel_invitation(invitation))


# --- The manager's panel: locations at a glance, adding and changing locations and groups ---------------------

PeriodKind = Literal["week", "month"]
PeriodStatusName = Literal["collecting", "draft", "published"]


class GroupOut(Schema):
    id: UUID
    name: str


class GroupIn(Schema):
    company_id: UUID
    name: str = Field(min_length=1, max_length=200)


class LocationIn(Schema):
    company_id: UUID
    name: str = Field(min_length=1, max_length=200)
    address: str = Field("", max_length=300)
    group_id: UUID | None = None
    schedule_period: PeriodKind = "month"
    availability_deadline_days: int = Field(7, ge=0, le=60)


class LocationUpdateIn(Schema):
    name: str | None = Field(None, min_length=1, max_length=200)
    address: str | None = Field(None, max_length=300)
    group_id: UUID | None = None
    schedule_period: PeriodKind | None = None
    availability_deadline_days: int | None = Field(None, ge=0, le=60)
    # True archives the location (it keeps its history), False brings it back.
    archived: bool | None = None


class LocationOut(Schema):
    id: UUID
    name: str
    address: str
    group_id: UUID | None
    group_name: str | None
    schedule_period: PeriodKind
    availability_deadline_days: int
    archived: bool


class PeriodSummaryOut(Schema):
    id: UUID
    start: date
    end: date
    status: PeriodStatusName
    deadline: date
    availability_requested_at: datetime | None
    # Active employees who pressed "Gotowe" / have not yet.
    submitted: int
    missing: list[str]
    late_days: int


class LocationSummaryOut(LocationOut):
    employees: int
    pending_invitations: int
    # The current or next period (the latest one when every period has ended); None: no period yet.
    period: PeriodSummaryOut | None


class SubscriptionSummaryOut(Schema):
    read_only: bool
    # Why it is read-only, in words for the manager ("" when it is not).
    read_only_message: str
    never_started: bool
    days_left: int
    expiring_soon: bool


class ManagerOverviewOut(Schema):
    company_id: UUID
    company_name: str
    role: Literal["owner", "manager"]
    subscription: SubscriptionSummaryOut
    groups: list[GroupOut]
    locations: list[LocationSummaryOut]
    archived: list[LocationOut]


def _location_out(location: Location) -> LocationOut:
    return LocationOut(
        id=location.pk,
        name=location.name,
        address=location.address,
        group_id=location.group_id,
        group_name=location.group.name if location.group_id else None,
        schedule_period=location.schedule_period,
        availability_deadline_days=location.availability_deadline_days,
        archived=location.archived_at is not None,
    )


def _period_summary(ctx, location: Location, today: date) -> PeriodSummaryOut | None:
    from apps.availability.api import late_after
    from apps.availability.models import AvailabilityDay, AvailabilitySubmission
    from apps.scheduling.models import SchedulePeriod
    from apps.staffing.models import EmployeeProfile

    periods = ctx.qs(SchedulePeriod).filter(location=location).select_related("location")
    period = periods.filter(end__gte=today).order_by("start").first() or periods.order_by("-start").first()
    if period is None:
        return None
    people = list(
        ctx.qs(EmployeeProfile)
        .filter(home_location=location, is_active=True)
        .select_related("membership__user")
        .order_by("membership__user__last_name", "membership__user__first_name")
    )
    done = set(ctx.qs(AvailabilitySubmission).filter(period=period).values_list("employee_id", flat=True))
    late = (
        ctx.qs(AvailabilityDay)
        .filter(employee__in=people, date__gte=period.start, date__lte=period.end, updated_at__gte=late_after(period))
        .count()
    )
    return PeriodSummaryOut(
        id=period.pk,
        start=period.start,
        end=period.end,
        status=period.status,
        deadline=period.deadline,
        availability_requested_at=period.availability_requested_at,
        submitted=sum(1 for p in people if p.pk in done),
        missing=[p.membership.user.full_name or "Bez imienia" for p in people if p.pk not in done],
        late_days=late,
    )


@router.get("/manager/overview", response={200: ManagerOverviewOut, 403: ErrorOut, 404: ErrorOut})
def manager_overview(request, company_id: UUID):
    """The manager's start screen: every location they run, the state of its current period and who is missing."""
    from django.utils import timezone

    from apps.billing.services import subscription_state
    from apps.staffing.models import EmployeeProfile

    ctx = tenant_context(request, company_id)
    ctx.require_manager()
    today = timezone.localdate()
    managed = ctx.managed_locations().select_related("group")
    active = [loc for loc in managed if loc.archived_at is None]
    state = subscription_state(ctx.company.pk)
    summaries = []
    for location in active:
        summaries.append(
            LocationSummaryOut(
                **_location_out(location).dict(),
                employees=ctx.qs(EmployeeProfile).filter(home_location=location, is_active=True).count(),
                pending_invitations=ctx.qs(Invitation)
                .filter(location=location, status=InvitationStatus.PENDING)
                .count(),
                period=_period_summary(ctx, location, today),
            )
        )
    return ManagerOverviewOut(
        company_id=ctx.company.pk,
        company_name=ctx.company.name,
        role=ctx.role,
        subscription=SubscriptionSummaryOut(
            read_only=state.read_only,
            read_only_message=state.read_only_message if state.read_only else "",
            never_started=state.ends_at is None,
            days_left=state.days_left,
            expiring_soon=state.expiring_soon,
        ),
        groups=[GroupOut(id=g.pk, name=g.name) for g in ctx.qs(LocationGroup).order_by("name")],
        locations=summaries,
        archived=[_location_out(loc) for loc in managed if loc.archived_at is not None],
    )


def _require_owner(ctx) -> None:
    if ctx.role != Role.OWNER:
        raise HttpError(403, "To może zrobić tylko właściciel firmy.")


def _group_or_400(ctx, group_id: UUID | None) -> LocationGroup | None:
    if group_id is None:
        return None
    group = ctx.qs(LocationGroup).filter(pk=group_id).first()
    if group is None:
        raise HttpError(400, "Wybierz grupę z tej firmy.")
    return group


def _save_unique(obj, message: str) -> None:
    try:
        with transaction.atomic():
            obj.save()
    except IntegrityError as exc:
        raise HttpError(409, message) from exc


@router.post(
    "/groups", response={201: GroupOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut}
)
def create_group(request, payload: GroupIn):
    ctx = tenant_context(request, payload.company_id)
    _require_owner(ctx)
    ctx.require_writable()
    group = LocationGroup(company=ctx.company, name=payload.name.strip())
    if not group.name:
        raise HttpError(400, "Podaj nazwę grupy.")
    _save_unique(group, "Grupa o tej nazwie już jest.")
    return Status(201, GroupOut(id=group.pk, name=group.name))


@router.post(
    "/locations", response={201: LocationOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut}
)
def create_location(request, payload: LocationIn):
    """A new location starts with the good-practice rules switched on (or follows its group's rules)."""
    from apps.rules.models import RuleSetting
    from engine.rules_catalog import RULES

    ctx = tenant_context(request, payload.company_id)
    _require_owner(ctx)
    ctx.require_writable()
    name = payload.name.strip()
    if not name:
        raise HttpError(400, "Podaj nazwę lokalu.")
    location = Location(
        company=ctx.company,
        name=name,
        address=payload.address.strip(),
        group=_group_or_400(ctx, payload.group_id),
        schedule_period=payload.schedule_period,
        availability_deadline_days=payload.availability_deadline_days,
    )
    with transaction.atomic():
        _save_unique(location, "Lokal o tej nazwie już jest w firmie.")
        if location.group_id is None:
            good = [rule for rule in RULES if rule.good_practice]
            RuleSetting.objects.for_company(ctx.company).bulk_create(
                RuleSetting(company=ctx.company, location=location, rule_code=rule.code, position=place)
                for place, rule in enumerate(good, start=1)
            )
    return Status(201, _location_out(location))


@router.get("/locations/{location_id}", response={200: LocationOut, 403: ErrorOut, 404: ErrorOut})
def location_detail(request, location_id: UUID):
    ctx, location = context_for(request, Location, location_id)
    ctx.require_manager_of(location)
    return _location_out(location)


@router.patch(
    "/locations/{location_id}",
    response={200: LocationOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def update_location(request, location_id: UUID, payload: LocationUpdateIn):
    """Name, address, group, period length, default deadline; archiving (owner only) instead of deleting."""
    from django.utils import timezone

    ctx, location = context_for(request, Location, location_id)
    ctx.require_manager_of(location)
    ctx.require_writable()
    sent = payload.model_fields_set
    if payload.name is not None:
        location.name = payload.name.strip()
        if not location.name:
            raise HttpError(400, "Podaj nazwę lokalu.")
    if payload.address is not None:
        location.address = payload.address.strip()
    if "group_id" in sent:
        _require_owner(ctx)
        location.group = _group_or_400(ctx, payload.group_id)
    if payload.schedule_period is not None:
        location.schedule_period = payload.schedule_period
    if payload.availability_deadline_days is not None:
        location.availability_deadline_days = payload.availability_deadline_days
    if payload.archived is not None:
        _require_owner(ctx)
        if payload.archived and location.archived_at is None:
            location.archived_at = timezone.now()
        elif not payload.archived:
            location.archived_at = None
    _save_unique(location, "Lokal o tej nazwie już jest w firmie.")
    return _location_out(location)
