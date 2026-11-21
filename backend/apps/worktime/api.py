"""Other hours of a published shift: the employee's report, the manager's decision and the manager's own change
(logic in services.py)."""

from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone
from ninja import Field, Router, Schema
from ninja.responses import Status

from apps.availability.models import TextRequest
from apps.core.schemas import ErrorOut
from apps.scheduling.models import Assignment
from apps.staffing.me import employee_context
from apps.tenancy.context import TenantContext, context_for, tenant_context
from apps.worktime import services
from apps.worktime.models import HoursChange
from apps.worktime.schemas import WorkedOut, worked_out

router = Router(tags=["worktime"])

HoursStatus = Literal["pending", "approved", "rejected", "cancelled", "replaced", "expired"]
ERRORS = {400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut}

# How long decided changes stay on the manager's list.
RECENT_DAYS = 14

TIME_FIELD = Field(min_length=3, max_length=5, description="GG:MM w czasie lokalu, np. 14:30")


class HoursChangeOut(Schema):
    id: UUID
    status: HoursStatus
    employee_id: UUID
    employee_name: str
    location_id: UUID
    location_name: str
    position_name: str
    date: date
    # The schedule's hours (the published shift now, or as it was when the change was written).
    planned_start_time: str
    planned_end_time: str
    planned_hours: float
    start_time: str
    end_time: str
    hours: float
    # Minutes more (+) or less (−) than the schedule.
    difference_minutes: int
    reason: str
    # The manager set the hours alone (not the employee's report).
    by_manager: bool
    created_at: datetime
    decided_at: datetime | None
    decided_by_name: str
    # The published shift it is about while the person still has it; None after a correction gave it to another.
    assignment_id: UUID | None


class ManagerHoursChangesOut(Schema):
    # Reports waiting for a decision in my locations (oldest first).
    pending: list[HoursChangeOut]
    # Decided in the last two weeks, and the manager's own changes (newest first).
    recent: list[HoursChangeOut]
    # How many wait (for the badge in the menu).
    waiting: int


class ReportHoursIn(Schema):
    assignment_id: UUID
    start_time: str = TIME_FIELD
    end_time: str = TIME_FIELD
    reason: str = Field(default="", max_length=services.REASON_MAX)
    # The chat message whose proposal this is ("Wyślij kierownikowi" under the assistant's answer).
    request_id: UUID | None = None


class SetHoursIn(Schema):
    # The person the manager sees on the shift: 409 when someone else got it meanwhile.
    employee_id: UUID
    start_time: str = TIME_FIELD
    end_time: str = TIME_FIELD
    reason: str = Field(default="", max_length=services.REASON_MAX)


def _name(user) -> str:
    return user.full_name if user else ""


def _changes_out(changes: list[HoursChange]) -> list[HoursChangeOut]:
    """Read the published shift of each change once, so the plan shown is the current one."""
    current = services.current_assignments(changes)
    result = []
    for change in changes:
        tz = ZoneInfo(change.location.timezone)
        found = current.get(change.pk)
        shift = found.shift if found else None
        planned_start = shift.start_at if shift else change.planned_start_at
        planned_end = shift.end_at if shift else change.planned_end_at
        planned_minutes = (planned_end - planned_start).total_seconds() / 60
        result.append(
            HoursChangeOut(
                id=change.pk,
                status=change.status,
                employee_id=change.employee_id,
                employee_name=change.employee.membership.user.full_name or "Pracownik bez imienia",
                location_id=change.location_id,
                location_name=change.location.name,
                position_name=shift.position.name if shift else "",
                date=change.date,
                planned_start_time=services.local_time(planned_start, tz),
                planned_end_time=services.local_time(planned_end, tz),
                planned_hours=services.hours_between(planned_start, planned_end),
                start_time=services.local_time(change.start_at, tz),
                end_time=services.local_time(change.end_at, tz),
                hours=services.hours_between(change.start_at, change.end_at),
                difference_minutes=round((change.end_at - change.start_at).total_seconds() / 60 - planned_minutes),
                reason=change.reason,
                by_manager=change.by_manager,
                created_at=change.created_at,
                decided_at=change.decided_at,
                decided_by_name=_name(change.decided_by),
                assignment_id=found.pk if found else None,
            )
        )
    return result


def _query(ctx: TenantContext):
    return ctx.qs(HoursChange).select_related("location", "employee__membership__user", "decided_by")


# --- The employee --------------------------------------------------------------------------------------------


@router.post("/me/hours-changes", response={201: HoursChangeOut, **ERRORS})
def report_my_hours(request, payload: ReportHoursIn):
    """Report other hours of my published shift (overtime or leaving early); the manager approves or rejects."""
    ctx, assignment = context_for(request, Assignment, payload.assignment_id)
    ctx, profile = employee_context(request, ctx.company.pk)
    ctx.require_writable()
    source = None
    if payload.request_id is not None:
        source = ctx.get(TextRequest, pk=payload.request_id, employee=profile)
    change = services.report(
        profile,
        assignment.pk,
        services.parse_time(payload.start_time),
        services.parse_time(payload.end_time),
        payload.reason,
        ctx.user,
        source_request=source,
    )
    return Status(201, _changes_out([_query(ctx).get(pk=change.pk)])[0])


@router.post("/hours-changes/{change_id}/cancel", response={200: HoursChangeOut, **ERRORS})
def cancel_my_hours_change(request, change_id: UUID):
    """Take back my report while it waits for the manager."""
    ctx, change = context_for(request, HoursChange, change_id)
    ctx, profile = employee_context(request, ctx.company.pk)
    ctx.require_writable()
    services.cancel(change, profile)
    return _changes_out([_query(ctx).get(pk=change.pk)])[0]


# --- The manager ---------------------------------------------------------------------------------------------


@router.get("/manager/hours-changes", response={200: ManagerHoursChangesOut, 403: ErrorOut, 404: ErrorOut})
def manager_hours_changes(request, company_id: UUID):
    """Reports of other hours in my locations: waiting ones, and what was decided in the last two weeks."""
    ctx = tenant_context(request, company_id)
    ctx.require_manager()
    locations = list(ctx.managed_locations())
    since = timezone.now() - timedelta(days=RECENT_DAYS)
    rows = list(
        _query(ctx)
        .filter(location__in=locations)
        .filter(
            Q(status=HoursChange.Status.PENDING)
            | Q(status__in=[HoursChange.Status.APPROVED, HoursChange.Status.REJECTED], decided_at__gte=since)
        )
        .order_by("created_at")
    )
    out = _changes_out(rows)
    # A waiting report of a shift the person no longer has is not the manager's to decide (it ends on publishing).
    pending = [c for c in out if c.status == "pending" and c.assignment_id is not None]
    recent = sorted((c for c in out if c.status != "pending"), key=lambda c: c.decided_at or c.created_at, reverse=True)
    return ManagerHoursChangesOut(pending=pending, recent=recent, waiting=len(pending))


def _managed_change(request, change_id: UUID) -> tuple[TenantContext, HoursChange]:
    ctx, change = context_for(request, HoursChange, change_id)
    ctx.require_manager_of(change.location)
    ctx.require_writable()
    return ctx, change


@router.post("/hours-changes/{change_id}/approve", response={200: HoursChangeOut, **ERRORS})
def approve_hours_change(request, change_id: UUID):
    """The reported hours count instead of the schedule's; the employee is told."""
    ctx, change = _managed_change(request, change_id)
    services.decide(change, ctx.user, approve=True)
    return _changes_out([_query(ctx).get(pk=change.pk)])[0]


@router.post("/hours-changes/{change_id}/reject", response={200: HoursChangeOut, **ERRORS})
def reject_hours_change(request, change_id: UUID):
    """The reported hours do not count; the employee is told."""
    ctx, change = _managed_change(request, change_id)
    services.decide(change, ctx.user, approve=False)
    return _changes_out([_query(ctx).get(pk=change.pk)])[0]


class ShiftHoursOut(Schema):
    assignment_id: UUID
    planned_start_time: str
    planned_end_time: str
    # The hours that count now; None: the schedule's own hours count again.
    worked: WorkedOut | None


@router.post("/assignments/{assignment_id}/hours", response={200: ShiftHoursOut, **ERRORS})
def set_shift_hours(request, assignment_id: UUID, payload: SetHoursIn):
    """The manager sets the hours one person really works on a published shift, at once (also after the fact).
    The schedule's own hours bring the plan back; a waiting report of the shift is answered by this."""
    ctx, assignment = context_for(request, Assignment, assignment_id)
    ctx.require_manager_of(assignment.shift.location)
    ctx.require_writable()
    worked = services.set_hours(
        assignment,
        services.parse_time(payload.start_time),
        services.parse_time(payload.end_time),
        payload.reason,
        ctx.user,
        employee_id=payload.employee_id,
    )
    shift = assignment.shift
    tz = ZoneInfo(shift.location.timezone)
    return ShiftHoursOut(
        assignment_id=assignment.pk,
        planned_start_time=services.local_time(shift.start_at, tz),
        planned_end_time=services.local_time(shift.end_at, tz),
        worked=worked_out(worked, shift),
    )
