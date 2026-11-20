"""Shapes other apps add to their shifts: the hours that count and a report waiting for the manager."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from ninja import Schema

from apps.scheduling.models import Shift
from apps.worktime.models import HoursChange
from apps.worktime.services import Worked, hours_between, local_time


class WorkedOut(Schema):
    """Hours that count instead of the schedule's (approved overtime or a shorter shift)."""

    start_at: datetime
    end_at: datetime
    start_time: str  # local wall-clock time, e.g. "06:00"
    end_time: str
    hours: float
    # Minutes more (+) or less (−) than the schedule.
    difference_minutes: int
    by_manager: bool


class WaitingHoursOut(Schema):
    """A report of other hours waiting for the manager."""

    id: UUID
    start_time: str
    end_time: str
    hours: float
    difference_minutes: int
    reason: str


def worked_out(worked: Worked | None, shift: Shift) -> WorkedOut | None:
    """None when the plan counts."""
    if worked is None or worked.change is None:
        return None
    tz = ZoneInfo(shift.location.timezone)
    return WorkedOut(
        start_at=worked.start_at.astimezone(tz),
        end_at=worked.end_at.astimezone(tz),
        start_time=local_time(worked.start_at, tz),
        end_time=local_time(worked.end_at, tz),
        hours=worked.hours,
        difference_minutes=worked.difference_minutes(shift),
        by_manager=worked.change.by_manager,
    )


def report_out(change: HoursChange | None, shift: Shift) -> WaitingHoursOut | None:
    if change is None:
        return None
    tz = ZoneInfo(shift.location.timezone)
    planned = (shift.end_at - shift.start_at).total_seconds()
    return WaitingHoursOut(
        id=change.pk,
        start_time=local_time(change.start_at, tz),
        end_time=local_time(change.end_at, tz),
        hours=hours_between(change.start_at, change.end_at),
        difference_minutes=round(((change.end_at - change.start_at).total_seconds() - planned) / 60),
        reason=change.reason,
    )
