"""The employee's "Kiedy mogę" screen: availability for a period, weekly repeats, copying, requests in words.

Every endpoint works on the logged-in person's own employee profile in one company (`company_id`).
The calendar (`/me/calendar`) is always open: days can be marked ahead of time, also before the manager asks.
Only past days and days of a period whose schedule is already arranged are closed.
"""

from datetime import date, datetime, time, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.assistant import llm
from apps.assistant.context import MAX_CONVERSATION
from apps.assistant.services import queue_request
from apps.availability.models import (
    AvailabilityDay,
    AvailabilityPattern,
    AvailabilityState,
    AvailabilitySubmission,
    TextRequest,
)
from apps.core.schemas import ErrorOut
from apps.notifications.services import notify
from apps.scheduling.models import Assignment, SchedulePeriod, ScheduleVersion
from apps.staffing.me import employee_context
from apps.staffing.models import EmployeeProfile, works_in_q
from apps.tenancy.context import TenantContext, context_for

router = Router(tags=["availability"])

StateName = Literal["cannot", "neutral", "prefer"]
PeriodStatusName = Literal["collecting", "draft", "published"]
RequestStatusName = Literal["new", "interpreted", "needs_manager", "rejected", "answered", "superseded"]

# "Repeat every week until ..." reaches at most this far ahead.
MAX_REPEAT_DAYS = 366
CLOSED = "Termin zaznaczania dla tego okresu minął. Jeśli coś się zmieniło, powiedz kierownikowi."
# The always-open calendar: how far ahead days can be marked and how many days one request may cover.
MAX_AHEAD_DAYS = 366
MAX_CALENDAR_DAYS = 62
ARRANGED = "Grafik na te dni jest już ułożony. Jeśli coś się zmieniło, powiedz kierownikowi."


class AvailabilityPeriodOut(Schema):
    id: UUID
    location_name: str
    start: date
    end: date
    status: PeriodStatusName
    # Last day to mark availability (the location's setting: days before the period starts).
    deadline: date
    editable: bool
    # True when text requests are also read by the assistant (an outside AI service); the screen says so.
    assistant_reads: bool


class AvailabilityDayOut(Schema):
    date: date
    state: StateName
    # Optional hours: with "cannot" they say when; with "neutral"/"prefer" they mean "only then".
    # An end at or before the start means the next morning.
    from_time: time | None = None
    to_time: time | None = None
    # A second window ("lub"); `one_shift` ("albo"): at most one shift that day, in one of the windows.
    from_time_2: time | None = None
    to_time_2: time | None = None
    one_shift: bool = False


class MyAvailabilityOut(Schema):
    # None when the manager has not opened a period yet.
    period: AvailabilityPeriodOut | None
    days: list[AvailabilityDayOut]
    submitted_at: datetime | None
    # The assistant (an outside AI service) also reads requests: the request form must say so.
    assistant_reads: bool = False


class MyCalendarOut(Schema):
    start: date
    end: date
    days: list[AvailabilityDayOut]
    # Days of this range that cannot be changed: past days and days whose schedule is already arranged.
    locked: list[date]
    # The nearest period the manager is collecting availability for (None: no request is open now).
    period: AvailabilityPeriodOut | None
    submitted_at: datetime | None
    # My locations, the main one first: with more than one the screen says that availability is shared by all.
    location_names: list[str]


class CalendarIn(Schema):
    company_id: UUID
    days: list["DayIn"] = Field(min_length=1, max_length=62)


class DayIn(Schema):
    date: date
    state: StateName
    from_time: time | None = None
    to_time: time | None = None
    from_time_2: time | None = None
    to_time_2: time | None = None
    one_shift: bool = False


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
    # The period the manager asked for, or (with no period) any day of the month the request is about.
    period_id: UUID | None = None
    month: date | None = None
    text: str = Field(min_length=1, max_length=1000)


class RequestChangeIn(Schema):
    # New wording (read again by the assistant), or `understood: false` = "that is not what I meant".
    text: str | None = Field(default=None, min_length=1, max_length=1000)
    understood: bool | None = None


class HoursProposalOut(Schema):
    """A report of other hours of my published shift, prepared by the assistant (nothing is sent by itself)."""

    # My published shift now (None: the schedule changed and I no longer have it: nothing to send).
    assignment_id: UUID | None
    date: date
    start_time: str
    end_time: str
    planned_start_time: str
    planned_end_time: str
    # Minutes more (+) or less (−) than the schedule.
    difference_minutes: int
    location_name: str
    position_name: str
    reason: str
    # The report sent from this message: its status; None = not sent yet.
    sent_status: Literal["pending", "approved", "rejected", "cancelled", "replaced", "expired"] | None


class MyRequestOut(Schema):
    id: UUID
    text: str
    status: RequestStatusName
    # How the assistant understood the request (only when it was sure enough); the person can say it is wrong.
    summary: str | None
    # What the assistant said to the person: an answer to a question, or a word about the request.
    reply: str | None
    # Days the request says the person cannot work that the calendar still shows as "mogę"/"chętnie" (and that can
    # still change): the screen offers to mark them "nie mogę" through `PUT /me/calendar`.
    unmarked_days: list[date]
    # Things to know: the calendar says the opposite of the request, or the request is about a shift the person's
    # position never has.
    notes: list[str]
    created_at: datetime
    # Reports of other hours the assistant prepared from this message, to send with "Wyślij kierownikowi".
    hours_reports: list[HoursProposalOut] = Field(default_factory=list)
    # The assistant was not sure what the person meant and asks them this (nothing is saved until they answer).
    question: str | None = None
    # The question has no answer yet: "Twoje prośby" lists the message as not saved, so it is not lost quietly.
    waiting: bool = False
    # The assistant still remembers the question (it is among the last messages it reads), so the next message
    # in the chat can answer it; an older one is written again instead.
    can_answer: bool = False


def _period_out(period: SchedulePeriod) -> AvailabilityPeriodOut:
    return AvailabilityPeriodOut(
        id=period.id,
        location_name=period.location.name,
        start=period.start,
        end=period.end,
        status=period.status,
        deadline=period.deadline,
        editable=period.status == SchedulePeriod.Status.COLLECTING,
        assistant_reads=llm.is_enabled(),
    )


def _my_period(ctx: TenantContext, profile: EmployeeProfile, period_id: UUID) -> SchedulePeriod:
    """A period of one of my locations (main or extra); 404 for any other."""
    period = ctx.qs(SchedulePeriod).filter(pk=period_id, location__in=profile.location_ids()).select_related("location")
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
        return MyAvailabilityOut(period=None, days=[], submitted_at=None, assistant_reads=llm.is_enabled())
    days = ctx.qs(AvailabilityDay).filter(employee=profile, date__gte=period.start, date__lte=period.end)
    submission = ctx.qs(AvailabilitySubmission).filter(employee=profile, period=period).first()
    return MyAvailabilityOut(
        period=_period_out(period),
        days=[_day_out(d) for d in days.order_by("date")],
        submitted_at=submission.submitted_at if submission else None,
        assistant_reads=llm.is_enabled(),
    )


# from, to, second from, second to, one shift ("albo")
Hours = tuple[time | None, time | None, time | None, time | None, bool]
NO_HOURS: Hours = (None, None, None, None, False)
HOUR_FIELDS = ("from_time", "to_time", "from_time_2", "to_time_2", "one_shift")


def _day_out(day: AvailabilityDay) -> AvailabilityDayOut:
    return AvailabilityDayOut(date=day.date, state=day.state, **{f: getattr(day, f) for f in HOUR_FIELDS})


def _hours_in(day: DayIn) -> Hours:
    """The hours of one marked day, checked; a day without hours has no second window and no "albo"."""
    if day.from_time is not None and day.from_time == day.to_time:
        raise HttpError(400, "Godzina początku i końca nie mogą być takie same.")
    first = day.from_time is not None or day.to_time is not None
    if (day.from_time_2 is None) != (day.to_time_2 is None):
        raise HttpError(400, "Drugi przedział godzin potrzebuje początku i końca.")
    if day.from_time_2 is not None:
        if not first:
            raise HttpError(400, "Najpierw wpisz pierwszy przedział godzin.")
        if day.from_time_2 == day.to_time_2:
            raise HttpError(400, "Godzina początku i końca nie mogą być takie same.")
    two = day.from_time_2 is not None
    return (day.from_time, day.to_time, day.from_time_2, day.to_time_2, two and day.one_shift)


def _save_days(
    ctx: TenantContext, profile: EmployeeProfile, states: dict[date, tuple[str, Hours]], source: str
) -> None:
    if states:
        ctx.qs(EmployeeProfile).select_for_update().get(pk=profile.pk)
        if _published_dates(ctx, profile, min(states), max(states)).intersection(states):
            raise HttpError(409, ARRANGED)
    rows = [
        AvailabilityDay(
            company_id=ctx.company.pk,
            employee=profile,
            date=day,
            state=state,
            **dict(zip(HOUR_FIELDS, hours, strict=True)),
            source=source,
        )
        for day, (state, hours) in states.items()
    ]
    AvailabilityDay.objects.for_company(ctx.company).bulk_create(
        rows,
        update_conflicts=True,
        unique_fields=["employee", "date"],
        update_fields=["state", "source", *HOUR_FIELDS, "updated_at"],
    )


@router.get("/me/availability", response={200: MyAvailabilityOut, 404: ErrorOut})
def my_availability(request, company_id: UUID, period_id: UUID | None = None):
    """My availability for a period; without `period_id`, the nearest period that is collecting availability."""
    ctx, profile = employee_context(request, company_id)
    if period_id is not None:
        period = _my_period(ctx, profile, period_id)
    else:
        today = timezone.localdate()
        period = _first_open_period(
            ctx,
            profile,
            ctx.qs(SchedulePeriod).filter(
                location__in=profile.location_ids(), status=SchedulePeriod.Status.COLLECTING, end__gte=today
            ),
        )
    return _availability_out(ctx, profile, period)


def _first_open_period(ctx: TenantContext, profile: EmployeeProfile, periods) -> SchedulePeriod | None:
    """The earliest period that still waits for my "Gotowe" (someone working in several locations can be asked
    by each of them); the earliest one when all are done."""
    periods = list(periods.select_related("location").order_by("start", "location__name"))
    done = set(
        ctx.qs(AvailabilitySubmission).filter(employee=profile, period__in=periods).values_list("period_id", flat=True)
    )
    return next((p for p in periods if p.pk not in done), periods[0] if periods else None)


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
        states[day.date] = (day.state, _hours_in(day))
    with transaction.atomic():
        _save_days(ctx, profile, states, AvailabilityDay.Source.MANUAL)
    return _availability_out(ctx, profile, period)


def _published_dates(ctx: TenantContext, profile: EmployeeProfile, start: date, end: date) -> set[date]:
    return set(
        ctx.qs(Assignment)
        .filter(
            employee=profile, shift__date__range=(start, end), shift__version__status=ScheduleVersion.Status.PUBLISHED
        )
        .values_list("shift__date", flat=True)
    )


def _locked_days(ctx: TenantContext, profile: EmployeeProfile, start: date, end: date) -> set[date]:
    """Days between `start` and `end` that the employee cannot change any more."""
    today = timezone.localdate()
    locked = {start + timedelta(days=i) for i in range(max(0, min((today - start).days, (end - start).days + 1)))}
    # Availability is shared by all my locations, so a day arranged in any of them is closed for all of them: a change
    # would silently differ from what that schedule used, even while another location still collects these days.
    arranged = (
        ctx.qs(SchedulePeriod)
        .filter(location__in=profile.location_ids(), start__lte=end, end__gte=start)
        .exclude(status=SchedulePeriod.Status.COLLECTING)
    )
    for period_start, period_end in arranged.values_list("start", "end"):
        day = max(period_start, start)
        while day <= min(period_end, end):
            locked.add(day)
            day += timedelta(days=1)
    return locked | _published_dates(ctx, profile, start, end)


@router.get("/me/calendar", response={200: MyCalendarOut, 400: ErrorOut, 404: ErrorOut})
def my_calendar(request, company_id: UUID, start: date, end: date):
    """My availability between two dates (a month on the screen). Open all the time: no period is needed."""
    ctx, profile = employee_context(request, company_id)
    if end < start or (end - start).days >= MAX_CALENDAR_DAYS:
        raise HttpError(400, f"Kalendarz pokazuje najwyżej {MAX_CALENDAR_DAYS} dni naraz.")
    period = _first_open_period(
        ctx,
        profile,
        ctx.qs(SchedulePeriod).filter(
            location__in=profile.location_ids(),
            status=SchedulePeriod.Status.COLLECTING,
            end__gte=max(start, timezone.localdate()),
            start__lte=end,
        ),
    )
    submission = ctx.qs(AvailabilitySubmission).filter(employee=profile, period=period).first() if period else None
    days = ctx.qs(AvailabilityDay).filter(employee=profile, date__gte=start, date__lte=end).order_by("date")
    return MyCalendarOut(
        start=start,
        end=end,
        days=[_day_out(d) for d in days],
        locked=sorted(_locked_days(ctx, profile, start, end)),
        period=_period_out(period) if period else None,
        submitted_at=submission.submitted_at if submission else None,
        location_names=[
            profile.home_location.name,
            *profile.extra_locations.order_by("name").values_list("name", flat=True),
        ],
    )


@router.put("/me/calendar", response={204: None, 400: ErrorOut, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut})
def save_my_calendar(request, payload: CalendarIn):
    """Save marked days, with or without a request from the manager (saved at once after every tap or drag)."""
    ctx, profile = employee_context(request, payload.company_id)
    ctx.require_writable()
    today = timezone.localdate()
    dates = [day.date for day in payload.days]
    if min(dates) < today:
        raise HttpError(409, "Dni, które już minęły, nie da się zmienić.")
    if max(dates) > today + timedelta(days=MAX_AHEAD_DAYS):
        raise HttpError(400, "Można zaznaczać najwyżej rok naprzód.")
    if _locked_days(ctx, profile, min(dates), max(dates)) & set(dates):
        raise HttpError(409, ARRANGED)
    states = {}
    for day in payload.days:
        states[day.date] = (day.state, _hours_in(day))
    with transaction.atomic():
        _save_days(ctx, profile, states, AvailabilityDay.Source.MANUAL)
    return Status(204, None)


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
    earlier = {d: (state, tuple(hours)) for d, state, *hours in rows.values_list("date", "state", *HOUR_FIELDS)}
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
    # Availability is shared by all my locations, so "Gotowe" also answers their periods within the same days.
    covered = ctx.qs(SchedulePeriod).filter(
        location__in=profile.location_ids(),
        status=SchedulePeriod.Status.COLLECTING,
        start__gte=period.start,
        end__lte=period.end,
    )
    for each in {period, *covered}:
        AvailabilitySubmission.objects.for_company(ctx.company).get_or_create(
            company=ctx.company, employee=profile, period=each
        )
    return _availability_out(ctx, profile, period)


class _Calendar:
    """My marked days and the days I cannot change any more, read once for a list of requests."""

    def __init__(self, ctx: TenantContext, profile: EmployeeProfile, start: date, end: date) -> None:
        rows = ctx.qs(AvailabilityDay).filter(employee=profile, date__gte=start, date__lte=end)
        self.states = dict(rows.values_list("date", "state"))
        self.locked = _locked_days(ctx, profile, start, end)


def _request_out(text_request: TextRequest, calendar: _Calendar | None = None, later: int = 0) -> MyRequestOut:
    """`later`: how many messages of the same chat came after this one (the assistant reads the last few)."""
    unmarked, notes = _calendar_facts(text_request, calendar) if calendar is not None else ([], [])
    interpreted = text_request.status == TextRequest.Status.INTERPRETED
    question = (text_request.question or None) if text_request.status == TextRequest.Status.ANSWERED else None
    waiting = bool(question) and not text_request.answers.all()
    return MyRequestOut(
        id=text_request.id,
        text=text_request.text,
        status=text_request.status,
        summary=_summary(text_request),
        reply=text_request.reply or None,
        unmarked_days=unmarked,
        notes=[*((text_request.interpretation or {}).get("notes") or [] if interpreted else []), *notes],
        created_at=text_request.created_at,
        hours_reports=_hours_proposals(text_request),
        question=question,
        waiting=waiting,
        can_answer=waiting and later < MAX_CONVERSATION,
    )


def _hours_proposals(row: TextRequest) -> list[HoursProposalOut]:
    """The assistant's reports of other hours in this message, with what became of the one sent from it."""
    if not row.hours_reports:
        return []
    from apps.scheduling.models import Assignment, ScheduleVersion

    sent = {
        (str(change.period_id), change.slot_key): change.status
        for change in row.hours_changes.order_by("created_at")  # the newest wins
    }
    result = []
    for item in row.hours_reports:
        key = (item.get("period_id"), item.get("slot_key"))
        current = (
            Assignment.objects.for_company(row.company_id)
            .filter(
                employee_id=row.employee_id,
                shift__slot_key=item.get("slot_key"),
                shift__version__period_id=item.get("period_id"),
                shift__version__status=ScheduleVersion.Status.PUBLISHED,
            )
            .values_list("pk", flat=True)
            .first()
        )
        result.append(
            HoursProposalOut(
                assignment_id=current,
                date=item["date"],
                start_time=item["start_time"],
                end_time=item["end_time"],
                planned_start_time=item["planned_start_time"],
                planned_end_time=item["planned_end_time"],
                difference_minutes=item.get("difference", 0),
                location_name=item.get("location_name", ""),
                position_name=item.get("position_name", ""),
                reason=item.get("reason", ""),
                sent_status=sent.get(key),
            )
        )
    return result


def _calendar_facts(row: TextRequest, calendar: _Calendar) -> tuple[list[date], list[str]]:
    from apps.assistant.readings import dates_in
    from apps.assistant.services import request_span

    if row.status != TextRequest.Status.INTERPRETED or not row.interpretation:
        return [], []
    start, end = request_span(row)
    unmarked: set[date] = set()
    notes = []
    for part in [row.interpretation, *(row.interpretation.get("more") or [])]:
        days = sorted(dates_in(part, start, end))
        if part.get("type") == "wolne_dni":
            if part.get("cannot"):
                unmarked |= {
                    d for d in days if calendar.states.get(d) != AvailabilityState.CANNOT and d not in calendar.locked
                }
            eager = [d for d in days if calendar.states.get(d) == AvailabilityState.PREFER]
            if eager:
                notes.append(
                    f"W kalendarzu masz „Chętnie” w dni, w które prośba mówi o wolnym: {_dates_words(eager)}. "
                    "Popraw kalendarz, jeśli prośba jest aktualna."
                )
        elif part.get("type") == "chce_pracowac":
            blocked = [d for d in days if calendar.states.get(d) == AvailabilityState.CANNOT]
            if blocked:
                notes.append(
                    f"W kalendarzu masz „Nie mogę” w dni, w które prośba mówi o pracy: {_dates_words(blocked)}. "
                    "Tych dni generator Ci nie da."
                )
    return sorted(unmarked), notes


def _dates_words(days: list[date]) -> str:
    return ", ".join(f"{d.day}.{d.month:02d}" for d in days[:8]) + (" i inne" if len(days) > 8 else "")


def _summary(row: TextRequest) -> str | None:
    from apps.assistant.readings import legacy_hours_notice

    summary = (
        (row.interpretation or {}).get("summary")
        if row.status in (TextRequest.Status.INTERPRETED, TextRequest.Status.ANSWERED, TextRequest.Status.REJECTED)
        else None
    )
    return str(summary) + legacy_hours_notice(row.interpretation, row.text) if summary else None


def _request_month(day: date) -> date:
    """A month for a request without a period: from this month up to a year ahead (its first day)."""
    month = day.replace(day=1)
    today = timezone.localdate()
    if month < today.replace(day=1):
        raise HttpError(400, "Ten miesiąc już minął. Napisz prośbę na ten albo kolejny miesiąc.")
    if month > today + timedelta(days=MAX_AHEAD_DAYS):
        raise HttpError(400, "Prośbę można napisać najwyżej rok naprzód.")
    return month


@router.get("/me/requests", response={200: list[MyRequestOut], 400: ErrorOut, 404: ErrorOut})
def my_requests(request, company_id: UUID, period_id: UUID | None = None, month: date | None = None):
    """My requests for a period, or (without `period_id`) the ones I wrote for a month with no period yet."""
    ctx, profile = employee_context(request, company_id)
    if period_id is not None:
        # Also the ones I wrote for its months before the manager asked: they count here too.
        scope = TextRequest.for_periods([_my_period(ctx, profile, period_id)])
    elif month is not None:
        scope = Q(period=None, month=month.replace(day=1))
    else:
        raise HttpError(400, "Wybierz miesiąc.")
    requests = list(
        ctx.qs(TextRequest)
        .filter(scope, employee=profile)
        .select_related("period")
        .prefetch_related("answers")
        .order_by("created_at")
    )
    calendar = None
    if requests:
        from apps.assistant.services import request_span

        spans = [request_span(r) for r in requests]
        calendar = _Calendar(ctx, profile, min(s for s, _ in spans), max(e for _, e in spans))
    # Messages after each one in its own chat (a period, or a month without one): see `context.MAX_CONVERSATION`.
    later, seen = [], {}
    for r in reversed(requests):
        chat = (r.period_id, r.month)
        later.append(seen.get(chat, 0))
        seen[chat] = seen.get(chat, 0) + 1
    return [_request_out(r, calendar, n) for r, n in zip(requests, reversed(later), strict=True)]


LIMIT_FULL = "Masz już tyle próśb, ile można wysłać na jeden okres. Usuń albo popraw którąś."


def _limit_full(ctx: TenantContext, profile: EmployeeProfile, scope: dict, exclude=None) -> bool:
    """Whether the requests that take a place in the limit per period (questions and refused messages do not) fill
    it. `TEXT_REQUESTS_PER_PERIOD = 0` (the default) means no limit."""
    limit = settings.TEXT_REQUESTS_PER_PERIOD
    if not limit:
        return False
    rows = ctx.qs(TextRequest).filter(employee=profile, status__in=TextRequest.COUNTED, **scope)
    return (rows.exclude(pk=exclude) if exclude else rows).count() >= limit


def _tell_managers(ctx: TenantContext, text_request: TextRequest) -> None:
    """A message handed to the manager to read: the managers of its location get a notification."""
    from apps.notifications.services import location_manager_ids

    location = text_request.location
    notify(
        ctx.company.pk,
        location_manager_ids(location),
        "request_for_manager",
        {
            "employee_name": text_request.employee.membership.user.full_name or "Pracownik",
            "text": text_request.text[:80],
            "location_name": location.name,
        },
    )


def _require_request_open(text_request: TextRequest) -> None:
    """A request can change while its period collects availability, or until its month (no period) has passed."""
    if text_request.period_id:
        if text_request.period.status != SchedulePeriod.Status.COLLECTING:
            raise HttpError(409, CLOSED)
    elif text_request.month < timezone.localdate().replace(day=1):
        raise HttpError(409, "Ten miesiąc już minął. Jeśli coś się zmieniło, powiedz kierownikowi.")


@router.post("/me/requests", response={201: MyRequestOut, 400: ErrorOut, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut})
def create_my_request(request, payload: RequestIn):
    """ "Coś jeszcze?": a request in words for things the calendar cannot say. Only managers read it."""
    ctx, profile = employee_context(request, payload.company_id)
    if payload.period_id is not None:
        period, month = _editable_period(ctx, profile, payload.period_id), None
        scope = {"period": period}
    else:
        ctx.require_writable()
        if payload.month is None:
            raise HttpError(400, "Wybierz miesiąc.")
        period, month = None, _request_month(payload.month)
        scope = {"period": None, "month": month}
    text = payload.text.strip()
    if not text:
        raise HttpError(400, "Napisz, o co chodzi.")
    if llm.is_enabled():
        # Questions are free: the worker checks the limit of requests once it knows the message is a request.
        # This only bounds the cost of messages (0 = no limit).
        per_day = settings.ASSISTANT_MESSAGES_PER_DAY
        since = timezone.now() - timedelta(days=1)
        if per_day and ctx.qs(TextRequest).filter(employee=profile, created_at__gte=since).count() >= per_day:
            raise HttpError(429, "To już dużo wiadomości jak na jeden dzień. Napisz jutro albo powiedz kierownikowi.")
    elif _limit_full(ctx, profile, scope):
        raise HttpError(400, LIMIT_FULL)
    with transaction.atomic():
        text_request = TextRequest.objects.for_company(ctx.company).create(
            company=ctx.company, employee=profile, period=period, month=month, text=text
        )
        queue_request(text_request)  # the assistant reads it in the worker; without a key the manager does
    return Status(201, _request_out(text_request))


@router.patch(
    "/me/requests/{request_id}",
    response={200: MyRequestOut, 400: ErrorOut, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def update_my_request(request, request_id: UUID, payload: RequestChangeIn):
    """Correct how my request was understood: write it again, or say "that is not what I meant" (then the
    manager reads it as written). The same hands a request the assistant refused over to the manager."""
    ctx, text_request = context_for(request, TextRequest, request_id)
    if text_request.employee.membership_id != ctx.membership.pk:
        raise HttpError(404, "Nie znaleziono.")
    ctx.require_writable()
    _require_request_open(text_request)
    text = (payload.text or "").strip()
    if payload.text is not None and not text:
        raise HttpError(400, "Napisz, o co chodzi.")
    with transaction.atomic():
        text_request = ctx.qs(TextRequest).select_for_update().get(pk=text_request.pk)
        _require_request_open(text_request)
        if text_request.status == TextRequest.Status.SUPERSEDED:
            raise HttpError(409, "Ta prośba została zastąpiona. Edytuj jej nowszą wersję.")
        if text and text != text_request.text:
            text_request.text = text
            text_request.text_edited_at = timezone.now()
            text_request.status = TextRequest.Status.NEW
            text_request.interpretation = None
            text_request.question = ""
            text_request.employee_corrected = True
            text_request.save(
                update_fields=[
                    "text",
                    "text_edited_at",
                    "status",
                    "interpretation",
                    "question",
                    "employee_corrected",
                    "updated_at",
                ]
            )
            queue_request(text_request)
        elif payload.understood is False and text_request.status in (
            TextRequest.Status.INTERPRETED,
            TextRequest.Status.ANSWERED,
            TextRequest.Status.REJECTED,
        ):
            if text_request.status != TextRequest.Status.INTERPRETED:
                # An answer or a refusal becomes a request the manager reads: it takes a place in the limit.
                scope = (
                    {"period_id": text_request.period_id}
                    if text_request.period_id
                    else {"period__isnull": True, "month": text_request.month}
                )
                if _limit_full(ctx, text_request.employee, scope, exclude=text_request.pk):
                    raise HttpError(409, LIMIT_FULL)
            if text_request.status == TextRequest.Status.REJECTED:
                # The person thinks the refusal was wrong: the manager reads the text as written and decides by
                # hand. Without an interpretation the request is never scored by the generator.
                text_request.interpretation = None
                text_request.unread_reason = TextRequest.UnreadReason.REJECTED
            text_request.status = TextRequest.Status.NEEDS_MANAGER
            text_request.employee_corrected = True
            text_request.save(
                update_fields=["status", "interpretation", "unread_reason", "employee_corrected", "updated_at"]
            )
            _tell_managers(ctx, text_request)
    return _request_out(text_request)


@router.delete("/me/requests/{request_id}", response={204: None, 402: ErrorOut, 404: ErrorOut, 409: ErrorOut})
def delete_my_request(request, request_id: UUID):
    """Take back my own request while the period is still collecting availability."""
    ctx, text_request = context_for(request, TextRequest, request_id)
    if text_request.employee.membership_id != ctx.membership.pk:
        raise HttpError(404, "Nie znaleziono.")
    ctx.require_writable()
    _require_request_open(text_request)
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


class AskedOut(Schema):
    """The person's earlier message and the assistant's question on it, which this request answers."""

    text: str
    question: str


class ManagerRequestOut(Schema):
    id: UUID
    employee_id: UUID
    employee_name: str
    text: str
    status: RequestStatusName
    # How the assistant understood it; None when it was not sure, is switched off, or has not read it yet.
    summary: str | None
    # The person said the assistant got it wrong, or rewrote the request.
    employee_corrected: bool
    # Why there is no summary: "off" = the assistant was switched off when the request came, "unsure" = it read
    # the request but could not turn it into a setting, "failed" = the call failed, "rejected" = the assistant
    # refused it as off-topic and the person handed it over for a manual decision; "" otherwise.
    unread_reason: Literal["", "off", "unsure", "failed", "rejected"]
    # The assistant is on now and has not really read this request yet: the manager can hand it over again.
    can_reread: bool
    manager_priority: PriorityName
    manager_rejected: bool
    created_at: datetime
    # This message answers the assistant's question on an earlier one: the earlier text and the question.
    asked: AskedOut | None = None


class RequestDecisionIn(Schema):
    manager_priority: PriorityName | None = None
    manager_rejected: bool | None = None


def _managed_period(request, period_id: UUID) -> tuple[TenantContext, SchedulePeriod]:
    ctx, period = context_for(request, SchedulePeriod, period_id)
    ctx.require_manager_of(period.location)
    return ctx, period


def late_after(period: SchedulePeriod) -> datetime:
    """Changes from this moment on are "after the deadline": the day after the deadline, midnight local time, but
    never before the deadline was set (a day in the past does not make everything entered so far late)."""
    tz = ZoneInfo(period.location.timezone)
    after = datetime.combine(period.deadline + timedelta(days=1), time(0), tzinfo=tz)
    return max(after, period.deadline_set_at) if period.deadline_set_at else after


@router.get("/periods/{period_id}/availability", response={200: AvailabilityGridOut, 403: ErrorOut, 404: ErrorOut})
def availability_grid(request, period_id: UUID):
    """Employees × days of the period: what each person marked, who finished, what changed after the deadline."""
    ctx, period = _managed_period(request, period_id)
    profiles = list(
        ctx.qs(EmployeeProfile)
        .filter(works_in_q(period.location), is_active=True)
        .select_related("membership__user")
        .prefetch_related("positions")
        .order_by("membership__user__last_name", "membership__user__first_name")
    )
    days: dict = {p.pk: [] for p in profiles}
    cutoff = late_after(period)
    rows = ctx.qs(AvailabilityDay).filter(employee__in=profiles, date__gte=period.start, date__lte=period.end)
    for row in rows.order_by("date"):
        days[row.employee_id].append(GridDayOut(**_day_out(row).dict(), late=row.updated_at >= cutoff))
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
                positions=sorted(pos.name for pos in p.positions.all() if pos.location_id == period.location_id),
                submitted_at=submitted.get(p.pk),
                days=days[p.pk],
                late_days=sum(1 for d in days[p.pk] if d.late),
            )
            for p in profiles
        ],
    )


def _manager_request_out(row: TextRequest) -> ManagerRequestOut:
    summary = _summary(row)
    if summary and row.status == TextRequest.Status.INTERPRETED and (row.interpretation or {}).get("partial"):
        summary += " Resztę wiadomości asystent zostawił Tobie do przeczytania."
    return ManagerRequestOut(
        id=row.pk,
        employee_id=row.employee_id,
        employee_name=row.employee.membership.user.full_name or "Bez imienia",
        text=row.text,
        status=row.status,
        summary=summary,
        employee_corrected=row.employee_corrected,
        unread_reason=row.unread_reason,
        can_reread=_can_reread(row),
        manager_priority=row.manager_priority,
        manager_rejected=row.manager_rejected,
        created_at=row.created_at,
        asked=AskedOut(text=row.answer_to.text, question=row.answer_to.question) if row.answer_to else None,
    )


def _can_reread(row: TextRequest) -> bool:
    return (
        llm.is_enabled()
        and row.status == TextRequest.Status.NEEDS_MANAGER
        and row.unread_reason in (TextRequest.UnreadReason.OFF, TextRequest.UnreadReason.FAILED)
        and not row.manager_rejected
    )


@router.get("/periods/{period_id}/requests", response={200: list[ManagerRequestOut], 403: ErrorOut, 404: ErrorOut})
def period_requests(request, period_id: UUID):
    """Requests in words for this period, oldest first. Only managers see them."""
    ctx, period = _managed_period(request, period_id)
    rows = (
        ctx.qs(TextRequest)
        .filter(TextRequest.for_periods([period]))
        .exclude(status__in=[TextRequest.Status.SUPERSEDED, TextRequest.Status.ANSWERED])
        .exclude(interpretation__type="out_of_scope", interpretation__type__isnull=False)
        .select_related("employee__membership__user", "answer_to")
    )
    return [_manager_request_out(r) for r in rows.order_by("created_at")]


@router.patch(
    "/requests/{request_id}",
    response={200: ManagerRequestOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def update_request(request, request_id: UUID, payload: RequestDecisionIn):
    """The manager rejects a request, or marks it as more or less important than usual."""
    ctx, row = context_for(request, TextRequest, request_id)
    ctx.require_manager_of(row.location)
    ctx.require_writable()
    with transaction.atomic():
        row = ctx.qs(TextRequest).select_for_update().get(pk=row.pk)
        if row.status in (TextRequest.Status.SUPERSEDED, TextRequest.Status.ANSWERED):
            raise HttpError(409, "Ta wiadomość nie jest już aktywną prośbą. Odśwież listę.")
        if payload.manager_priority is not None:
            row.manager_priority = payload.manager_priority
        if payload.manager_rejected is not None:
            row.manager_rejected = payload.manager_rejected
        row.save(update_fields=["manager_priority", "manager_rejected", "updated_at"])
    return _manager_request_out(row)


@router.post(
    "/requests/{request_id}/reread",
    response={200: ManagerRequestOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def reread_request(request, request_id: UUID):
    """Hand a request to the assistant again: one that came while it was switched off, or when the call failed."""
    ctx, row = context_for(request, TextRequest, request_id)
    ctx.require_manager_of(row.location)
    ctx.require_writable()
    with transaction.atomic():
        row = ctx.qs(TextRequest).select_for_update().get(pk=row.pk)
        if not _can_reread(row):
            raise HttpError(409, "Tej prośby nie da się teraz dać asystentowi. Odśwież stronę.")
        was_off = row.unread_reason == TextRequest.UnreadReason.OFF
        row.status = TextRequest.Status.NEW
        row.interpretation = None
        row.unread_reason = TextRequest.UnreadReason.NONE
        row.save(update_fields=["status", "interpretation", "unread_reason", "updated_at"])
        queue_request(row)
        if was_off:
            # The person wrote it when the screen said only the manager reads it: tell them it went further.
            notify(ctx.company.pk, [row.employee.membership.user_id], "request_to_assistant", {"text": row.text[:80]})
    return _manager_request_out(row)
