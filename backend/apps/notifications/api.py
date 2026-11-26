"""The person's in-app notifications in one company (also for managers)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from django.utils import timezone
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.core.schemas import ErrorOut
from apps.notifications.models import Notification
from apps.notifications.services import LINKS, notification_text
from apps.scheduling.models import SchedulePeriod
from apps.tenancy.context import context_for, tenant_context

router = Router(tags=["notifications"])

# The newest notifications shown on the screen.
LIMIT = 50

Link = Literal["schedule", "availability", "offers", "hours", "none"]


class NotificationOut(Schema):
    id: UUID
    kind: str
    text: str
    # Which screen the notification is about.
    link: Link
    # The month the screen should open on ("2026-12"), for a request for availability: "Kiedy mogę" shows one
    # month, and the request may be for a later one than today's.
    month: str | None = None
    created_at: datetime
    read: bool


class NotificationsOut(Schema):
    notifications: list[NotificationOut]
    unread: int


class MarkReadIn(Schema):
    company_id: UUID
    # Left out: all of my notifications in this company.
    ids: list[UUID] | None = Field(default=None, max_length=200)


@router.get("/me/notifications", response={200: NotificationsOut, 404: ErrorOut})
def my_notifications(request, company_id: UUID):
    """My newest notifications, newest first, and how many I have not seen. Works in read-only mode."""
    ctx = tenant_context(request, company_id)
    mine = ctx.qs(Notification).filter(user=ctx.user)
    rows = list(mine.order_by("-created_at")[:LIMIT])
    # A request for availability of a period that is already being arranged asks for what cannot be done any more.
    asked = {str(n.payload.get("period_id")) for n in rows if n.kind == "availability_requested" and n.payload}
    statuses = {
        str(pk): status
        for pk, status in ctx.qs(SchedulePeriod).filter(pk__in=_uuids(asked)).values_list("pk", "status")
    }
    result = []
    for n in rows:
        payload, link, month = n.payload or {}, LINKS.get(n.kind, "none"), None
        if n.kind == "availability_requested":
            status = statuses.get(str(payload.get("period_id")))
            if status is not None and status != SchedulePeriod.Status.COLLECTING:
                published = status == SchedulePeriod.Status.PUBLISHED
                payload = {**payload, "closed": "published" if published else "arranging"}
                link = "schedule" if published else "none"
            else:
                month = _month(payload.get("start"))
        result.append(
            NotificationOut(
                id=n.pk,
                kind=n.kind,
                text=notification_text(n.kind, payload),
                link=link,
                month=month,
                created_at=n.created_at,
                read=n.read_at is not None,
            )
        )
    return NotificationsOut(notifications=result, unread=mine.filter(read_at__isnull=True).count())


def _uuids(values: set[str]) -> list[UUID]:
    result = []
    for value in values:
        try:
            result.append(UUID(value))
        except ValueError:
            continue
    return result


def _month(day) -> str | None:
    """ "2026-12-01" -> "2026-12"; the month "Kiedy mogę" opens on (today's when the period has started)."""
    try:
        start = date.fromisoformat(str(day))
    except ValueError:
        return None
    return max(start, timezone.localdate()).strftime("%Y-%m")


@router.post("/me/notifications/read", response={204: None, 404: ErrorOut})
def mark_notifications_read(request, payload: MarkReadIn):
    """Mark my notifications as seen (not company data, so allowed in read-only mode too)."""
    ctx = tenant_context(request, payload.company_id)
    rows = ctx.qs(Notification).filter(user=ctx.user, read_at__isnull=True)
    if payload.ids is not None:
        rows = rows.filter(pk__in=payload.ids)
    rows.update(read_at=timezone.now())
    return Status(204, None)


@router.delete("/me/notifications/{notification_id}", response={204: None, 404: ErrorOut})
def dismiss_notification(request, notification_id: UUID):
    """Remove one of my notifications for good (the "X" on it). Allowed in read-only mode, like marking as seen."""
    ctx, notification = context_for(request, Notification, notification_id)
    if notification.user_id != ctx.user.pk:
        raise HttpError(404, "Nie znaleziono.")
    notification.delete()
    return Status(204, None)


@router.delete("/me/notifications", response={204: None, 404: ErrorOut})
def dismiss_all_notifications(request, company_id: UUID):
    """Remove all of my notifications in this company."""
    ctx = tenant_context(request, company_id)
    ctx.qs(Notification).filter(user=ctx.user).delete()
    return Status(204, None)
