"""Login with an SMS code, logout and the logged-in person's own data."""

from typing import Literal
from uuid import UUID

from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.middleware.csrf import get_token
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.accounts.login import request_login_code, verify_login_code
from apps.billing.services import subscription_state
from apps.core.http import client_ip, require_csrf
from apps.core.schemas import ErrorOut
from apps.tenancy.models import Invitation, InvitationStatus, Membership

router = Router(tags=["auth"])


class RequestCodeIn(Schema):
    phone: str = Field(max_length=32)
    # "register" is used by the "załóż firmę" screen: a new manager has no account and no invitation yet.
    purpose: Literal["login", "register"] = "login"


class RequestCodeOut(Schema):
    phone: str
    expires_in_s: int
    resend_after_s: int


class VerifyCodeIn(Schema):
    phone: str = Field(max_length=32)
    code: str = Field(max_length=16)


class MyCompanyOut(Schema):
    id: UUID
    name: str
    role: Literal["owner", "manager", "employee"]
    read_only: bool


class MeOut(Schema):
    id: UUID
    phone: str
    first_name: str
    last_name: str
    companies: list[MyCompanyOut]
    pending_invitations: int


class MeIn(Schema):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=120)


def build_me(user) -> MeOut:
    memberships = Membership.objects.filter(user=user)  # tenant-ok: the person's own memberships
    memberships = memberships.select_related("company").order_by("company__name")
    pending = Invitation.objects.filter(  # tenant-ok: invitations addressed to my phone number
        phone_e164=user.phone_e164, status=InvitationStatus.PENDING
    ).count()
    return MeOut(
        id=user.id,
        phone=user.phone_e164,
        first_name=user.first_name,
        last_name=user.last_name,
        companies=[
            MyCompanyOut(
                id=m.company_id,
                name=m.company.name,
                role=m.role,
                read_only=subscription_state(m.company_id).read_only,
            )
            for m in memberships
        ],
        pending_invitations=pending,
    )


@router.post(
    "/auth/request-code", response={200: RequestCodeOut, 400: ErrorOut, 404: ErrorOut, 429: ErrorOut}, auth=None
)
def request_code(request, payload: RequestCodeIn):
    """Send a 6-digit login code by SMS (locally: written to the server console)."""
    require_csrf(request)
    issued = request_login_code(payload.phone, payload.purpose, client_ip(request))
    return RequestCodeOut(
        phone=issued.phone_e164, expires_in_s=issued.expires_in_s, resend_after_s=issued.resend_after_s
    )


@router.post("/auth/verify-code", response={200: MeOut, 400: ErrorOut, 429: ErrorOut}, auth=None)
def verify_code(request, payload: VerifyCodeIn):
    """Check the code and start a session (about 60 days). The account is created on first login."""
    require_csrf(request)
    user = verify_login_code(payload.phone, payload.code)
    django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return build_me(user)


@router.post("/auth/logout", response={204: None})
def logout(request):
    django_logout(request)
    return Status(204, None)


@router.get("/me", response={200: MeOut, 401: ErrorOut}, auth=None)
def me(request):
    """Who is logged in. Also sets the CSRF cookie, so the app calls it first, before the login form."""
    get_token(request)
    if not request.user.is_authenticated:
        raise HttpError(401, "Zaloguj się.")
    return build_me(request.user)


@router.patch("/me", response=MeOut)
def update_me(request, payload: MeIn):
    user = request.user
    first_name, last_name = payload.first_name.strip(), payload.last_name.strip()
    if not first_name or not last_name:
        raise HttpError(400, "Podaj imię i nazwisko.")
    user.first_name, user.last_name = first_name, last_name
    user.save(update_fields=["first_name", "last_name"])
    return build_me(user)
