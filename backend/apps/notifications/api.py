"""The person's in-app notifications in one company (also for managers)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from django.utils import timezone
from ninja import Field, Router, Schema
from ninja.responses import Status

from apps.core.schemas import ErrorOut
from apps.notifications.models import Notification
from apps.notifications.services import LINKS, notification_text
from apps.tenancy.context import tenant_context

router = Router(tags=["notifications"])

# The newest notifications shown on the screen.
LIMIT = 50

Link = Literal["schedule", "availability", "offers", "none"]


class NotificationOut(Schema):
    id: UUID
    kind: str
    text: str
    # Which screen the notification is about.
    link: Link
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
    rows = mine.order_by("-created_at")[:LIMIT]
    return NotificationsOut(
        notifications=[
            NotificationOut(
                id=n.pk,
                kind=n.kind,
                text=notification_text(n.kind, n.payload),
                link=LINKS.get(n.kind, "none"),
                created_at=n.created_at,
                read=n.read_at is not None,
            )
            for n in rows
        ],
        unread=mine.filter(read_at__isnull=True).count(),
    )


@router.post("/me/notifications/read", response={204: None, 404: ErrorOut})
def mark_notifications_read(request, payload: MarkReadIn):
    """Mark my notifications as seen (not company data, so allowed in read-only mode too)."""
    ctx = tenant_context(request, payload.company_id)
    rows = ctx.qs(Notification).filter(user=ctx.user, read_at__isnull=True)
    if payload.ids is not None:
        rows = rows.filter(pk__in=payload.ids)
    rows.update(read_at=timezone.now())
    return Status(204, None)
