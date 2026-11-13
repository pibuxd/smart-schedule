"""The employee's "Kiedy mogę" screen: availability for a period, weekly repeats, copying, requests in words.

Every endpoint works on the logged-in person's own employee profile in one company (`company_id`).
Availability can be changed only while the period is collecting availability.
"""

from datetime import date, datetime, time, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.availability.models import (
    AvailabilityDay,
    AvailabilityPattern,
    AvailabilitySubmission,
    TextRequest,
)
from apps.core.schemas import ErrorOut
from apps.scheduling.models import SchedulePeriod
from apps.staffing.me import employee_context
from apps.staffing.models import EmployeeProfile
from apps.tenancy.context import TenantContext, context_for

router = Router(tags=["availability"])

StateName = Literal["cannot", "neutral", "prefer"]
PeriodStatusName = Literal["collecting", "draft", "published"]
RequestStatusName = Literal["new", "interpreted", "needs_manager", "rejected"]

# "Repeat every week until ..." reaches at most this far ahead.
MAX_REPEAT_DAYS = 366
CLOSED = "Termin zaznaczania dla tego okresu minął. Jeśli coś się zmieniło, powiedz kierownikowi."


class AvailabilityPeriodOut(Schema):
    id: UUID
    location_name: str
    start: date
    end: date
    status: PeriodStatusName
    # Last day to mark availability (the location's setting: days before the period starts).
    deadline: date
    editable: bool


class AvailabilityDayOut(Schema):
    date: date
    state: StateName
    # Optional hours: with "cannot" they say when; with "neutral"/"prefer" they mean "only then".
    # An end at or before the start means the next morning.
    from_time: time | None = None
    to_time: time | None = None


class MyAvailabilityOut(Schema):
    # None when the manager has not opened a period yet.
    period: AvailabilityPeriodOut | None
    days: list[AvailabilityDayOut]
    submitted_at: datetime | None


class DayIn(Schema):
    date: date
    state: StateName
    from_time: time | None = None
    to_time: time | None = None


class AvailabilityIn(Schema):
    company_id: UUID
    period_id: UUID
    days: list[DayIn] = Field(min_length=1, max_length=62)


class PeriodRefIn(Schema):
    company_id: UUID
    period_id: UUID


class PatternIn(Schema):
    company_id: UUID
    period_id: UUID
    weekdays: list[int] = Field(min_length=1, max_length=7)  # 0 = Monday
    state: StateName
    repeat_until: date


class RequestIn(Schema):
    company_id: UUID
    period_id: UUID
    text: str = Field(min_length=1, max_length=1000)


class MyRequestOut(Schema):
    id: UUID
    text: str
    status: RequestStatusName
    created_at: datetime


def _period_out(period: SchedulePeriod) -> AvailabilityPeriodOut:
    return AvailabilityPeriodOut(
        id=period.id,
        location_name=period.location.name,
        start=period.start,
        end=period.end,
        status=period.status,
        deadline=period.deadline,
        editable=period.status == SchedulePeriod.Status.COLLECTING,
    )


def _my_period(ctx: TenantContext, profile: EmployeeProfile, period_id: UUID) -> SchedulePeriod:
    """A period of my home location; 404 for any other."""
    period = ctx.qs(SchedulePeriod).filter(pk=period_id, location=profile.home_location).select_related("location")
    period = period.first()
    if period is None:
        raise HttpError(404, "Nie znaleziono tego okresu grafiku.")
    return period


def _editable_period(ctx: TenantContext, profile: EmployeeProfile, period_id: UUID) -> SchedulePeriod:
    ctx.require_writable()
    period = _my_period(ctx, profile, period_id)
    if period.status != SchedulePeriod.Status.COLLECTING:
        raise HttpError(409, CLOSED)
    return period


def _availability_out(ctx: TenantContext, profile: EmployeeProfile, period: SchedulePeriod | None) -> MyAvailabilityOut:
    if period is None:
        return MyAvailabilityOut(period=None, days=[], submitted_at=None)
    days = ctx.qs(AvailabilityDay).filter(employee=profile, date__gte=period.start, date__lte=period.end)
    submission = ctx.qs(AvailabilitySubmission).filter(employee=profile, period=period).first()
    return MyAvailabilityOut(
        period=_period_out(period),
        days=[
            AvailabilityDayOut(date=d.date, state=d.state, from_time=d.from_time, to_time=d.to_time)
            for d in days.order_by("date")
        ],
        submitted_at=submission.submitted_at if submission else None,
    )


Hours = tuple[time | None, time | None]
NO_HOURS: Hours = (None, None)


def _save_days(
    ctx: TenantContext, profile: EmployeeProfile, states: dict[date, tuple[str, Hours]], source: str
) -> None:
    rows = [
        AvailabilityDay(
            company_id=ctx.company.pk,
            employee=profile,
            date=day,
            state=state,
            from_time=hours[0],
            to_time=hours[1],
            source=source,
        )
        for day, (state, hours) in states.items()
    ]
    AvailabilityDay.objects.for_company(ctx.company).bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=["employee", "date"],
        update_fields=["state", "source", "from_time", "to_time", "updated_at"],
    )


@router.get("/me/availability", response={200: MyAvailabilityOut, 404: ErrorOut})
def my_availability(request, company_id: UUID, period_id: UUID | None = None):
    """My availability for a period; without `period_id`, the nearest period that is collecting availability."""
    ctx, profile = employee_context(request, company_id)
    if period_id is not None:
        period = _my_period(ctx, profile, period_id)
    else:
        today = timezone.localdate()
        period = (
            ctx.qs(SchedulePeriod)
            .filter(location=profile.home_location, status=SchedulePeriod.Status.COLLECTING, end__gte=today)
            .select_related("location")
            .order_by("start")
            .first()
        )
    return _availability_out(ctx, profile, period)


@router.put(
    "/me/availability", response={200: MyAvailabilityOut, 400: ErrorOut, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut}
)
def save_my_availability(request, payload: AvailabilityIn):
    """Save the marked days (saved at once after every tap or drag; "Cofnij" sends the previous states)."""
    ctx, profile = employee_context(request, payload.company_id)
    period = _editable_period(ctx, profile, payload.period_id)
    states = {}
    for day in payload.days:
        if not period.start <= day.date <= period.end:
            raise HttpError(400, "Można zaznaczać tylko dni z tego okresu.")
        if day.from_time is not None and day.from_time == day.to_time:
            raise HttpError(400, "Godzina początku i końca nie mogą być takie same.")
        states[day.date] = (day.state, (day.from_time, day.to_time))
    with transaction.atomic():
        _save_days(ctx, profile, states, AvailabilityDay.Source.MANUAL)
    return _availability_out(ctx, profile, period)


@router.post(
    "/me/availability/pattern",
    response={200: MyAvailabilityOut, 400: ErrorOut, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def repeat_my_availability(request, payload: PatternIn):
    """ "Powtarzaj co tydzień do [data]": the chosen weekdays get this state from the period start until that date."""
    ctx, profile = employee_context(request, payload.company_id)
    period = _editable_period(ctx, profile, payload.period_id)
    weekdays = sorted(set(payload.weekdays))
    if any(not 0 <= w <= 6 for w in weekdays):
        raise HttpError(400, "Wybierz dni tygodnia.")
    if payload.repeat_until < period.start:
        raise HttpError(400, "Data końca powtarzania musi być w tym okresie albo później.")
    if payload.repeat_until > period.start + timedelta(days=MAX_REPEAT_DAYS):
        raise HttpError(400, "Powtarzanie może trwać najwyżej rok.")
    states = {}
    day = period.start
    while day <= payload.repeat_until:
        if day.weekday() in weekdays:
            states[day] = (payload.state, NO_HOURS)
        day += timedelta(days=1)
    with transaction.atomic():
        for weekday in weekdays:
            AvailabilityPattern.objects.for_company(ctx.company).create(
                company=ctx.company,
                employee=profile,
                weekday=weekday,
                state=payload.state,
                repeat_until=payload.repeat_until,
            )
        if states:
            _save_days(ctx, profile, states, AvailabilityDay.Source.PATTERN)
    return _availability_out(ctx, profile, period)


def previous_month_day(day: date, period_start: date) -> date:
    """The same weekday four (or five) weeks earlier, always before the period starts."""
    source = day - timedelta(days=28)
    return source if source < period_start else day - timedelta(days=35)


@router.post(
    "/me/availability/copy-previous",
    response={200: MyAvailabilityOut, 400: ErrorOut, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def copy_previous_availability(request, payload: PeriodRefIn):
    """ "Skopiuj z poprzedniego miesiąca": each day takes the state of the same weekday 4-5 weeks earlier."""
    ctx, profile = employee_context(request, payload.company_id)
    period = _editable_period(ctx, profile, payload.period_id)
    sources = {}
    day = period.start
    while day <= period.end:
        sources[day] = previous_month_day(day, period.start)
        day += timedelta(days=1)
    rows = ctx.qs(AvailabilityDay).filter(employee=profile, date__in=list(sources.values()))
    earlier = {
        d: (state, (start, end)) for d, state, start, end in rows.values_list("date", "state", "from_time", "to_time")
    }
    states = {day: earlier[source] for day, source in sources.items() if source in earlier}
    if not states:
        raise HttpError(400, "W poprzednim miesiącu nie masz nic zaznaczone, więc nie ma czego skopiować.")
    with transaction.atomic():
        _save_days(ctx, profile, states, AvailabilityDay.Source.COPY)
    return _availability_out(ctx, profile, period)


@router.post("/me/availability/submit", response={200: MyAvailabilityOut, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut})
def submit_my_availability(request, payload: PeriodRefIn):
    """ "Gotowe": tells the manager I have finished. Days left unmarked mean "mogę"."""
    ctx, profile = employee_context(request, payload.company_id)
    period = _editable_period(ctx, profile, payload.period_id)
    AvailabilitySubmission.objects.for_company(ctx.company).get_or_create(
        company=ctx.company, employee=profile, period=period
    )
    return _availability_out(ctx, profile, period)


def _request_out(text_request: TextRequest) -> MyRequestOut:
    return MyRequestOut(
        id=text_request.id, text=text_request.text, status=text_request.status, created_at=text_request.created_at
    )


@router.get("/me/requests", response={200: list[MyRequestOut], 404: ErrorOut})
def my_requests(request, company_id: UUID, period_id: UUID):
    ctx, profile = employee_context(request, company_id)
    period = _my_period(ctx, profile, period_id)
    requests = ctx.qs(TextRequest).filter(employee=profile, period=period).order_by("created_at")
    return [_request_out(r) for r in requests]


@router.post("/me/requests", response={201: MyRequestOut, 400: ErrorOut, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut})
def create_my_request(request, payload: RequestIn):
    """ "Coś jeszcze?": a request in words for things the calendar cannot say. Only managers read it."""
    ctx, profile = employee_context(request, payload.company_id)
    period = _editable_period(ctx, profile, payload.period_id)
    text = payload.text.strip()
    if not text:
        raise HttpError(400, "Napisz, o co chodzi.")
    text_request = TextRequest.objects.for_company(ctx.company).create(
        company=ctx.company, employee=profile, period=period, text=text
    )
    return Status(201, _request_out(text_request))


@router.delete("/me/requests/{request_id}", response={204: None, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut})
def delete_my_request(request, request_id: UUID):
    """Take back my own request while the period is still collecting availability."""
    ctx, text_request = context_for(request, TextRequest, request_id)
    if text_request.employee.membership_id != ctx.membership.pk:
        raise HttpError(404, "Nie znaleziono.")
    ctx.require_writable()
    if text_request.period.status != SchedulePeriod.Status.COLLECTING:
        raise HttpError(409, CLOSED)
    text_request.delete()
    return Status(204, None)


# --- The manager's side: who marked what, who has not finished, requests in words ---------------------------

PriorityName = Literal["lower", "normal", "higher"]


class GridPeriodOut(Schema):
    id: UUID
    location_id: UUID
    location_name: str
    start: date
    end: date
    status: PeriodStatusName
    deadline: date
    requested_at: datetime | None


class GridDayOut(AvailabilityDayOut):
    # Marked or changed after the deadline day (the manager decides whether to take it into account).
    late: bool


class GridEmployeeOut(Schema):
    id: UUID
    name: str
    positions: list[str]
    submitted_at: datetime | None
    days: list[GridDayOut]
    late_days: int


class AvailabilityGridOut(Schema):
    period: GridPeriodOut
    employees: list[GridEmployeeOut]


class ManagerRequestOut(Schema):
    id: UUID
    employee_id: UUID
    employee_name: str
    text: str
    status: RequestStatusName
    # How the assistant understood it (stage 10); None until then.
    summary: str | None
    manager_priority: PriorityName
    manager_rejected: bool
    created_at: datetime


class RequestDecisionIn(Schema):
    manager_priority: PriorityName | None = None
    manager_rejected: bool | None = None


def _managed_period(request, period_id: UUID) -> tuple[TenantContext, SchedulePeriod]:
    ctx, period = context_for(request, SchedulePeriod, period_id)
    ctx.require_manager_of(period.location)
    return ctx, period


def late_after(period: SchedulePeriod) -> datetime:
    """Changes from this moment on are "after the deadline": the day after the deadline, midnight local time."""
    tz = ZoneInfo(period.location.timezone)
    return datetime.combine(period.deadline + timedelta(days=1), time(0), tzinfo=tz)


@router.get("/periods/{period_id}/availability", response={200: AvailabilityGridOut, 403: ErrorOut, 404: ErrorOut})
def availability_grid(request, period_id: UUID):
    """Employees × days of the period: what each person marked, who finished, what changed after the deadline."""
    ctx, period = _managed_period(request, period_id)
    profiles = list(
        ctx.qs(EmployeeProfile)
        .filter(home_location=period.location, is_active=True)
        .select_related("membership__user")
        .prefetch_related("positions")
        .order_by("membership__user__last_name", "membership__user__first_name")
    )
    days: dict = {p.pk: [] for p in profiles}
    cutoff = late_after(period)
    rows = ctx.qs(AvailabilityDay).filter(employee__in=profiles, date__gte=period.start, date__lte=period.end)
    for row in rows.order_by("date"):
        days[row.employee_id].append(
            GridDayOut(
                date=row.date,
                state=row.state,
                from_time=row.from_time,
                to_time=row.to_time,
                late=row.updated_at >= cutoff,
            )
        )
    submitted = dict(ctx.qs(AvailabilitySubmission).filter(period=period).values_list("employee_id", "submitted_at"))
    return AvailabilityGridOut(
        period=GridPeriodOut(
            id=period.pk,
            location_id=period.location_id,
            location_name=period.location.name,
            start=period.start,
            end=period.end,
            status=period.status,
            deadline=period.deadline,
            requested_at=period.availability_requested_at,
        ),
        employees=[
            GridEmployeeOut(
                id=p.pk,
                name=p.membership.user.full_name or "Bez imienia",
                positions=sorted(pos.name for pos in p.positions.all()),
                submitted_at=submitted.get(p.pk),
                days=days[p.pk],
                late_days=sum(1 for d in days[p.pk] if d.late),
            )
            for p in profiles
        ],
    )


def _manager_request_out(row: TextRequest) -> ManagerRequestOut:
    summary = (row.interpretation or {}).get("summary") if row.status == TextRequest.Status.INTERPRETED else None
    return ManagerRequestOut(
        id=row.pk,
        employee_id=row.employee_id,
        employee_name=row.employee.membership.user.full_name or "Bez imienia",
        text=row.text,
        status=row.status,
        summary=str(summary) if summary else None,
        manager_priority=row.manager_priority,
        manager_rejected=row.manager_rejected,
        created_at=row.created_at,
    )


@router.get("/periods/{period_id}/requests", response={200: list[ManagerRequestOut], 403: ErrorOut, 404: ErrorOut})
def period_requests(request, period_id: UUID):
    """Requests in words for this period, oldest first. Only managers see them."""
    ctx, period = _managed_period(request, period_id)
    rows = ctx.qs(TextRequest).filter(period=period).select_related("employee__membership__user")
    return [_manager_request_out(r) for r in rows.order_by("created_at")]


@router.patch("/requests/{request_id}", response={200: ManagerRequestOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut})
def update_request(request, request_id: UUID, payload: RequestDecisionIn):
    """The manager rejects a request, or marks it as more or less important than usual."""
    ctx, row = context_for(request, TextRequest, request_id)
    ctx.require_manager_of(row.period.location)
    ctx.require_writable()
    if payload.manager_priority is not None:
        row.manager_priority = payload.manager_priority
    if payload.manager_rejected is not None:
        row.manager_rejected = payload.manager_rejected
    row.save(update_fields=["manager_priority", "manager_rejected", "updated_at"])
    return _manager_request_out(row)
