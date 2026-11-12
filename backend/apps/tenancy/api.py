"""Registering a company and invitations (the manager's side and the invited person's side)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from django.db import transaction
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
from apps.tenancy.context import context_for
from apps.tenancy.models import Company, Invitation, InvitationStatus, Location, Membership, Role

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
