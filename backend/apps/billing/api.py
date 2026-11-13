"""Subscription of a company: its state and entering a free-access code."""

from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.db import transaction
from ninja import Field, Router, Schema
from ninja.errors import HttpError

from apps.billing.services import (
    CodeRejected,
    check_code_attempt_limit,
    generations_used_this_month,
    record_code_attempt,
    redeem_code,
    subscription_state,
)
from apps.core.http import client_ip
from apps.core.schemas import ErrorOut
from apps.tenancy.context import TenantContext, tenant_context

router = Router(tags=["billing"])


class SubscriptionOut(Schema):
    is_active: bool
    read_only: bool
    ends_at: datetime | None
    days_left: int
    # True in the last 7 days of access: the manager's panel shows a banner.
    expiring_soon: bool
    # Access comes from the free trial (no code entered yet).
    trial: bool
    generations_used: int
    generations_limit: int


class RedeemIn(Schema):
    code: str = Field(min_length=1, max_length=40)


def _subscription_out(ctx: TenantContext) -> SubscriptionOut:
    state = subscription_state(ctx.company.pk)
    return SubscriptionOut(
        is_active=state.is_active,
        read_only=state.read_only,
        ends_at=state.ends_at,
        days_left=state.days_left,
        expiring_soon=state.expiring_soon,
        trial=state.trial,
        generations_used=generations_used_this_month(ctx.company.pk),
        generations_limit=settings.GENERATION_MONTHLY_LIMIT,
    )


@router.get("/companies/{company_id}/subscription", response={200: SubscriptionOut, 403: ErrorOut, 404: ErrorOut})
def subscription(request, company_id: UUID):
    ctx = tenant_context(request, company_id)
    ctx.require_manager()
    return _subscription_out(ctx)


@router.post(
    "/companies/{company_id}/subscription/redeem",
    response={200: SubscriptionOut, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut, 429: ErrorOut},
)
def redeem_subscription_code(request, company_id: UUID, payload: RedeemIn):
    """Enter a free-access code. Extends access from its current end date; works also after it has expired."""
    ctx = tenant_context(request, company_id)
    ctx.require_manager()
    ip = client_ip(request)
    check_code_attempt_limit(ctx.user, ip)
    try:
        with transaction.atomic():
            redeem_code(ctx.company, ctx.user, payload.code)
    except CodeRejected as exc:
        record_code_attempt(ctx.user, ip, success=False)
        raise HttpError(400, str(exc)) from exc
    record_code_attempt(ctx.user, ip, success=True)
    return _subscription_out(ctx)
