"""Login with an SMS code, logout and the logged-in person's own data."""

from typing import Literal
from uuid import UUID

from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.core.exceptions import ValidationError
from django.middleware.csrf import get_token
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.accounts.login import request_login_code, verify_login_code
from apps.accounts.models import normalize_bank_account
from apps.billing.services import subscription_state
from apps.core.http import client_ip, require_csrf
from apps.core.schemas import ErrorOut
from apps.tenancy.models import Invitation, InvitationStatus, Membership, Role

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
    # Works shifts in this company (has an active employee profile): only then "Mój grafik" makes sense.
    works_shifts: bool = False


class MeOut(Schema):
    id: UUID
    phone: str
    first_name: str
    last_name: str
    # My account number for pay transfers: 26 digits, "" when not given.
    bank_account: str = ""
    companies: list[MyCompanyOut]
    pending_invitations: int


class MeIn(Schema):
    # Only what is sent changes.
    first_name: str | None = Field(None, min_length=1, max_length=80)
    last_name: str | None = Field(None, min_length=1, max_length=120)
    # Spaces, dashes and "PL" are fine; "" removes the number.
    bank_account: str | None = Field(None, max_length=40)


def _works_shifts(membership) -> bool:
    try:
        return membership.employee_profile.is_active
    except Membership.employee_profile.RelatedObjectDoesNotExist:
        return False


def _removed(membership) -> bool:
    """A plain employee removed from the company by a manager (kept only for the schedule history)."""
    profile = getattr(membership, "employee_profile", None)
    return membership.role == Role.EMPLOYEE and profile is not None and profile.removed_at is not None


def build_me(user) -> MeOut:
    memberships = Membership.objects.filter(user=user)  # tenant-ok: the person's own memberships
    memberships = memberships.select_related("company", "employee_profile").order_by("company__name")
    pending = Invitation.objects.filter(  # tenant-ok: invitations addressed to my phone number
        phone_e164=user.phone_e164, status=InvitationStatus.PENDING
    ).count()
    return MeOut(
        id=user.id,
        phone=user.phone_e164,
        first_name=user.first_name,
        last_name=user.last_name,
        bank_account=user.bank_account,
        companies=[
            MyCompanyOut(
                id=m.company_id,
                name=m.company.name,
                role=m.role,
                read_only=subscription_state(m.company_id).read_only,
                works_shifts=_works_shifts(m),
            )
            for m in memberships
            if not _removed(m)
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


@router.patch("/me", response={200: MeOut, 400: ErrorOut})
def update_me(request, payload: MeIn):
    """My name and my bank account number (optional, for pay; managers of my locations see it)."""
    user = request.user
    changed = []
    for field_name in ("first_name", "last_name"):
        value = getattr(payload, field_name)
        if value is None:
            continue
        if not value.strip():
            raise HttpError(400, "Podaj imię i nazwisko.")
        setattr(user, field_name, value.strip())
        changed.append(field_name)
    if payload.bank_account is not None:
        try:
            user.bank_account = normalize_bank_account(payload.bank_account)
        except ValidationError as exc:
            raise HttpError(400, exc.messages[0]) from exc
        changed.append("bank_account")
    if changed:
        user.save(update_fields=changed)
    return build_me(user)
