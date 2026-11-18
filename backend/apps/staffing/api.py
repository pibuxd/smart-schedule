"""Location settings for the manager: positions, shifts and their hours, staffing per weekday with date
exceptions, and the location's employees (positions, hours, switched off)."""

import hashlib
import json
from datetime import date, time
from typing import Literal
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Count, ProtectedError, RestrictedError
from django.utils import timezone
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.core.schemas import ErrorOut
from apps.rules.models import RuleSetting
from apps.scheduling.models import Assignment, SchedulePeriod, ScheduleVersion
from apps.staffing import day_staffing
from apps.staffing.models import (
    EmployeeProfile,
    LocationClosure,
    Position,
    PositionExperience,
    ShiftType,
    StaffingException,
    StaffingRule,
)
from apps.tenancy.context import TenantContext, context_for
from apps.tenancy.models import Location

router = Router(tags=["staffing"])

TOO_MANY_EXPERIENCED = "Doświadczonych nie może być więcej niż wszystkich osób na zmianie."

ShiftKind = Literal["fixed", "flexible"]
# 1 = początkujący, 2 = samodzielny, 3 = doświadczony. Only managers see it (never in employee endpoints).
ExperienceLevel = Literal[1, 2, 3]


class PositionIn(Schema):
    name: str = Field(min_length=1, max_length=100)


class PositionOut(Schema):
    id: UUID
    name: str
    employees: int


class ShiftTypeIn(Schema):
    name: str = Field(min_length=1, max_length=100)
    kind: ShiftKind = "fixed"
    # Fixed shifts need both; an end before the start means the shift ends the next morning.
    start_time: time | None = None
    end_time: time | None = None
    is_closing: bool = False


class ShiftTypeOut(Schema):
    id: UUID
    name: str
    kind: ShiftKind
    start_time: time | None
    end_time: time | None
    is_closing: bool


class StaffingCellIn(Schema):
    weekday: int = Field(ge=0, le=6)  # 0 = Monday
    shift_type_id: UUID
    position_id: UUID
    count: int = Field(ge=0, le=50)
    # How many of `count` must be experienced on this position.
    experienced: int = Field(0, ge=0, le=50)
    # Only for shifts with flexible hours.
    start_time: time | None = None
    end_time: time | None = None


class StaffingIn(Schema):
    cells: list[StaffingCellIn] = Field(max_length=2000)


class StaffingCellOut(Schema):
    weekday: int
    shift_type_id: UUID
    position_id: UUID
    count: int
    experienced: int
    start_time: time | None
    end_time: time | None


class DayCellIn(Schema):
    shift_type_id: UUID
    position_id: UUID
    count: int = Field(ge=0, le=50)  # 0 = nobody on that date
    experienced: int = Field(0, ge=0, le=50)
    # Other hours on that date only (required for a flexible shift that has none on that weekday).
    start_time: time | None = None
    end_time: time | None = None


class DayStaffingIn(Schema):
    """What one date needs. A shift and position left out goes back to the weekday's usual staffing."""

    cells: list[DayCellIn] = Field(max_length=500)
    note: str = Field("", max_length=200)


class StaffingExceptionOut(Schema):
    id: UUID
    date: date
    shift_type_id: UUID
    position_id: UUID
    count: int
    experienced: int
    start_time: time | None
    end_time: time | None
    note: str


class ClosureIn(Schema):
    date: date
    note: str = Field("", max_length=200)


class ClosureOut(Schema):
    id: UUID
    date: date
    note: str
    in_draft: bool = Field(
        False, description="An unpublished draft still has people on this day; arrange again to clear it."
    )
    in_published: bool = Field(False, description="The published schedule still has people on this day.")


class ArrangedOut(Schema):
    start: date
    end: date


class LocationSetupOut(Schema):
    positions: list[PositionOut]
    shift_types: list[ShiftTypeOut]
    staffing: list[StaffingCellOut]
    exceptions: list[StaffingExceptionOut]
    closures: list[ClosureOut]
    # Periods (not over yet) that already have a schedule: staffing changed there works after arranging again.
    arranged: list[ArrangedOut]


class PositionLevel(Schema):
    position_id: UUID
    experience: ExperienceLevel


class EmployeeOut(Schema):
    revision: str
    id: UUID
    first_name: str
    last_name: str
    phone: str
    position_ids: list[UUID]
    experience: ExperienceLevel
    # The level on each of the person's positions (the default `experience` unless set otherwise).
    position_experience: list[PositionLevel]
    max_hours_month: int | None
    target_hours_month: int | None
    is_active: bool
    # True for the owner or a manager who also works shifts.
    is_manager: bool
    # Shifts from today on in drafts not published yet: switching the person off leaves them to be moved.
    draft_shifts: int = 0


class EmployeeIn(Schema):
    revision: str | None = Field(None, max_length=64)
    # The name belongs to the person's account: changed only when the account is in this company alone. The phone
    # number is the login, so only the superadmin changes it (docs/spec.md, "Zmiana numeru telefonu").
    first_name: str | None = Field(None, max_length=80)
    last_name: str | None = Field(None, max_length=80)
    position_ids: list[UUID] | None = None
    experience: ExperienceLevel | None = None
    # Levels for single positions; replaces what was set before. A position left out gets the default level.
    position_experience: list[PositionLevel] | None = None
    # Send null to clear a limit.
    max_hours_month: int | None = Field(None, ge=1, le=400)
    target_hours_month: int | None = Field(None, ge=1, le=400)
    is_active: bool | None = None


# --------------------------------------------------------------------------------------------- helpers


def _manage(request, model, object_id) -> tuple[TenantContext, object, Location]:
    """Context for a location-owned object; only the location's managers may touch it."""
    ctx, obj = context_for(request, model, object_id)
    location = obj if isinstance(obj, Location) else obj.location
    ctx.require_manager_of(location)
    return ctx, obj, location


def _change(request, model, object_id):
    ctx, obj, location = _manage(request, model, object_id)
    ctx.require_writable()
    return ctx, obj, location


def _position_out(position: Position, counts: dict) -> PositionOut:
    return PositionOut(id=position.pk, name=position.name, employees=counts.get(position.pk, 0))


def _shift_type_out(st: ShiftType) -> ShiftTypeOut:
    return ShiftTypeOut(
        id=st.pk, name=st.name, kind=st.kind, start_time=st.start_time, end_time=st.end_time, is_closing=st.is_closing
    )


def _exception_out(exc: StaffingException) -> StaffingExceptionOut:
    return StaffingExceptionOut(
        id=exc.pk,
        date=exc.date,
        shift_type_id=exc.shift_type_id,
        position_id=exc.position_id,
        count=exc.count,
        experienced=exc.experienced,
        start_time=exc.start_time,
        end_time=exc.end_time,
        note=exc.note,
    )


def _setup_out(ctx: TenantContext, location: Location) -> LocationSetupOut:
    positions = list(ctx.qs(Position).filter(location=location).order_by("name"))
    counts: dict = {}
    links = EmployeeProfile.positions.through.objects.filter(  # tenant-ok: links of this location's positions
        position__in=positions, employeeprofile__is_active=True
    )
    for position_id in links.values_list("position_id", flat=True):
        counts[position_id] = counts.get(position_id, 0) + 1
    return LocationSetupOut(
        positions=[_position_out(p, counts) for p in positions],
        shift_types=[_shift_type_out(s) for s in ctx.qs(ShiftType).filter(location=location).order_by("start_time")],
        staffing=[
            StaffingCellOut(
                weekday=r.weekday,
                shift_type_id=r.shift_type_id,
                position_id=r.position_id,
                count=r.count,
                experienced=r.experienced,
                start_time=r.start_time,
                end_time=r.end_time,
            )
            for r in ctx.qs(StaffingRule).filter(location=location).order_by("weekday")
        ],
        exceptions=[
            _exception_out(e) for e in ctx.qs(StaffingException).filter(location=location).order_by("date", "pk")
        ],
        closures=_closures_out(ctx, location),
        arranged=[
            ArrangedOut(start=start, end=end)
            for start, end in ctx.qs(SchedulePeriod)
            .filter(
                location=location,
                end__gte=timezone.localdate(),
                versions__status__in=[ScheduleVersion.Status.DRAFT, ScheduleVersion.Status.PUBLISHED],
            )
            .values_list("start", "end")
            .distinct()
            .order_by("start")
        ],
    )


def _check_hours(start: time | None, end: time | None, required: bool, what: str) -> None:
    if (start is None) != (end is None):
        raise HttpError(400, f"{what}: podaj godzinę początku i końca albo żadnej.")
    if required and start is None:
        raise HttpError(400, f"{what}: podaj godziny zmiany.")
    if start is not None and start == end:
        raise HttpError(400, f"{what}: początek i koniec nie mogą być o tej samej godzinie.")


def _unique(save, message: str):
    try:
        with transaction.atomic():
            return save()
    except IntegrityError as exc:
        raise HttpError(409, message) from exc


# --------------------------------------------------------------------------------------------- setup


@router.get("/locations/{location_id}/setup", response={200: LocationSetupOut, 403: ErrorOut, 404: ErrorOut})
def location_setup(request, location_id: UUID):
    """Everything the location settings screen shows."""
    ctx, location, _ = _manage(request, Location, location_id)
    return _setup_out(ctx, location)


@router.post(
    "/locations/{location_id}/positions",
    response={201: PositionOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def create_position(request, location_id: UUID, payload: PositionIn):
    ctx, location, _ = _change(request, Location, location_id)
    name = payload.name.strip()
    if not name:
        raise HttpError(400, "Podaj nazwę stanowiska.")
    position = _unique(
        lambda: Position.objects.for_company(ctx.company).create(company=ctx.company, location=location, name=name),
        "Takie stanowisko już jest w tym lokalu.",
    )
    return Status(201, _position_out(position, {}))


@router.patch(
    "/positions/{position_id}",
    response={200: PositionOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def update_position(request, position_id: UUID, payload: PositionIn):
    _, position, _ = _change(request, Position, position_id)
    name = payload.name.strip()
    if not name:
        raise HttpError(400, "Podaj nazwę stanowiska.")
    position.name = name
    _unique(lambda: position.save(update_fields=["name"]), "Takie stanowisko już jest w tym lokalu.")
    return _position_out(position, {})


IN_USE = "{what} jest już w ułożonym grafiku, więc nie można go usunąć. Możesz zmienić jego nazwę."


def _check_rule_references(ctx: TenantContext, obj: Position | ShiftType, param: str) -> None:
    # Serialize against saving the location's rules, which store these references in JSON.
    ctx.qs(Location).select_for_update().get(pk=obj.location_id)
    references = ctx.qs(RuleSetting).filter(location_id=obj.location_id, **{f"params__{param}": str(obj.pk)})
    if references.filter(enabled=True).exists():
        what = "tego stanowiska" if param == "position" else "tej zmiany"
        raise HttpError(409, f"Najpierw zmień lub wyłącz zasadę lokalu, która używa {what}.")
    for rule in references:
        del rule.params[param]
        rule.save(update_fields=["params"])


@router.delete(
    "/positions/{position_id}", response={204: None, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut}
)
def delete_position(request, position_id: UUID):
    """Also removes its staffing; refused when a schedule already uses it (history stays intact)."""
    ctx, position, _ = _change(request, Position, position_id)
    try:
        with transaction.atomic():
            _check_rule_references(ctx, position, "position")
            position.delete()
    except (ProtectedError, RestrictedError) as exc:
        raise HttpError(409, IN_USE.format(what="To stanowisko")) from exc
    return Status(204, None)


def _apply_shift_type(st: ShiftType, payload: ShiftTypeIn) -> None:
    name = payload.name.strip()
    if not name:
        raise HttpError(400, "Podaj nazwę zmiany.")
    fixed = payload.kind == ShiftType.Kind.FIXED
    _check_hours(payload.start_time, payload.end_time, fixed, f"Zmiana „{name}”")
    st.name, st.kind, st.is_closing = name, payload.kind, payload.is_closing
    st.start_time, st.end_time = payload.start_time, payload.end_time


@router.post(
    "/locations/{location_id}/shift-types",
    response={201: ShiftTypeOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def create_shift_type(request, location_id: UUID, payload: ShiftTypeIn):
    ctx, location, _ = _change(request, Location, location_id)
    st = ShiftType(company=ctx.company, location=location)
    _apply_shift_type(st, payload)
    _unique(st.save, "Zmiana o tej nazwie już jest w tym lokalu.")
    return Status(201, _shift_type_out(st))


@router.patch(
    "/shift-types/{shift_type_id}",
    response={200: ShiftTypeOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def update_shift_type(request, shift_type_id: UUID, payload: ShiftTypeIn):
    """New hours apply to schedules arranged from now on; saved schedules keep the hours they had."""
    _, st, _ = _change(request, ShiftType, shift_type_id)
    _apply_shift_type(st, payload)
    _unique(st.save, "Zmiana o tej nazwie już jest w tym lokalu.")
    return _shift_type_out(st)


@router.delete(
    "/shift-types/{shift_type_id}", response={204: None, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut}
)
def delete_shift_type(request, shift_type_id: UUID):
    """Removes its staffing too. Saved schedules keep their shifts (with the hours copied)."""
    ctx, st, _ = _change(request, ShiftType, shift_type_id)
    try:
        with transaction.atomic():
            _check_rule_references(ctx, st, "shift_type")
            st.delete()
    except (ProtectedError, RestrictedError) as exc:
        raise HttpError(409, IN_USE.format(what="Ta zmiana")) from exc
    return Status(204, None)


@router.put(
    "/locations/{location_id}/staffing",
    response={200: LocationSetupOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut},
)
def save_staffing(request, location_id: UUID, payload: StaffingIn):
    """The whole weekly table at once: how many people of each position every shift needs on each weekday.
    Cells with 0 (or left out) mean nobody."""
    ctx, location, _ = _change(request, Location, location_id)
    shift_types = {st.pk: st for st in ctx.qs(ShiftType).filter(location=location)}
    positions = {p.pk: p for p in ctx.qs(Position).filter(location=location)}
    rows: dict[tuple, StaffingRule] = {}
    for cell in payload.cells:
        st, position = shift_types.get(cell.shift_type_id), positions.get(cell.position_id)
        if st is None or position is None:
            raise HttpError(400, "Obsada może dotyczyć tylko zmian i stanowisk tego lokalu.")
        if not cell.count:
            continue
        if cell.experienced > cell.count:
            raise HttpError(400, TOO_MANY_EXPERIENCED)
        flexible = st.kind == ShiftType.Kind.FLEXIBLE
        start, end = (cell.start_time, cell.end_time) if flexible else (None, None)
        _check_hours(start, end, False, f"Zmiana „{st.name}”")
        rows[(cell.weekday, st.pk, position.pk)] = StaffingRule(
            company=ctx.company,
            location=location,
            weekday=cell.weekday,
            shift_type=st,
            position=position,
            count=cell.count,
            experienced=cell.experienced,
            start_time=start,
            end_time=end,
        )
    with transaction.atomic():
        ctx.qs(StaffingRule).filter(location=location).delete()
        for row in rows.values():
            row.save()
    return _setup_out(ctx, location)


@router.put(
    "/locations/{location_id}/staffing-days/{day}",
    response={200: LocationSetupOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut},
)
def save_day_staffing(request, location_id: UUID, day: date, payload: DayStaffingIn):
    """Staffing of one date (e.g. Christmas Eve), set from the calendar. It replaces the weekday's staffing for the
    shifts and positions that differ; everything left out, or equal to the usual, follows the weekday again."""
    ctx, location, _ = _change(request, Location, location_id)
    if abs((day - timezone.localdate()).days) > 2 * 366:
        raise HttpError(400, "Obsadę można ustawić na dzień najwyżej dwa lata od dziś. Sprawdź rok.")
    shift_types = {st.pk: st for st in ctx.qs(ShiftType).filter(location=location)}
    positions = {p.pk: p for p in ctx.qs(Position).filter(location=location)}
    cells = {}
    for cell in payload.cells:
        st, position = shift_types.get(cell.shift_type_id), positions.get(cell.position_id)
        if st is None or position is None:
            raise HttpError(400, "Obsada może dotyczyć tylko zmian i stanowisk tego lokalu.")
        if cell.experienced > cell.count:
            raise HttpError(400, TOO_MANY_EXPERIENCED)
        _check_hours(cell.start_time, cell.end_time, False, f"Zmiana „{st.name}”")
        cells[(st.pk, position.pk)] = cell
    note = payload.note.strip()
    with transaction.atomic():
        for exc in ctx.qs(StaffingException).filter(location=location, date=day):
            if (exc.shift_type_id, exc.position_id) not in cells:
                exc.delete()
        for (st_id, position_id), cell in cells.items():
            st, position = shift_types[st_id], positions[position_id]
            day_staffing.save_day_cell(
                location,
                day,
                st,
                position,
                count=cell.count,
                experienced=cell.experienced,
                start=cell.start_time,
                end=cell.end_time,
                note=note,
            )
            if cell.count and None in day_staffing.day_hours(location, day, st, position):
                raise HttpError(400, f"Zmiana „{st.name}” ma dowolne godziny. Podaj, od której do której.")
    return _setup_out(ctx, location)


@router.post(
    "/locations/{location_id}/closures",
    response={201: ClosureOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def create_closure(request, location_id: UUID, payload: ClosureIn):
    """A day the location is closed: the generator schedules nobody there that day."""
    ctx, location, _ = _change(request, Location, location_id)
    if abs((payload.date - timezone.localdate()).days) > 2 * 366:
        raise HttpError(400, "Dzień zamknięcia może być najwyżej dwa lata od dziś. Sprawdź rok.")
    closure = LocationClosure(company=ctx.company, location=location, date=payload.date, note=payload.note.strip())
    _unique(closure.save, "Ten dzień jest już na liście dni zamknięcia.")
    return Status(201, _closures_out(ctx, location, [closure])[0])


@router.delete("/closures/{closure_id}", response={204: None, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut})
def delete_closure(request, closure_id: UUID):
    _, closure, _ = _change(request, LocationClosure, closure_id)
    closure.delete()
    return Status(204, None)


# --------------------------------------------------------------------------------------------- employees


def _employee_out(profile: EmployeeProfile, position_ids: list, levels: dict | None = None) -> EmployeeOut:
    levels = levels or {}
    user = profile.membership.user
    # Include settings stored on the account and position links as well as the profile row.
    snapshot = (
        user.first_name,
        user.last_name,
        profile.experience,
        profile.is_active,
        profile.max_hours_month,
        profile.target_hours_month,
        sorted((str(pid), levels.get(pid, profile.experience)) for pid in position_ids),
    )
    return EmployeeOut(
        revision=hashlib.sha256(json.dumps(snapshot).encode()).hexdigest(),
        id=profile.pk,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone_e164,
        position_ids=position_ids,
        experience=profile.experience,
        position_experience=[
            PositionLevel(position_id=pid, experience=levels.get(pid, profile.experience)) for pid in position_ids
        ],
        max_hours_month=profile.max_hours_month,
        target_hours_month=profile.target_hours_month,
        is_active=profile.is_active,
        is_manager=profile.membership.is_manager,
    )


def _position_ids(profiles) -> dict:
    result: dict = {p.pk: [] for p in profiles}
    links = EmployeeProfile.positions.through.objects.filter(  # tenant-ok: links of profiles read via ctx
        employeeprofile_id__in=list(result)
    ).order_by("position__name")
    for profile_id, position_id in links.values_list("employeeprofile_id", "position_id"):
        result[profile_id].append(position_id)
    return result


def _position_levels(profiles) -> dict:
    """profile id -> {position id -> level set for that position}."""
    result: dict = {p.pk: {} for p in profiles}
    rows = PositionExperience.objects.filter(employee_id__in=list(result))  # tenant-ok: profiles read via ctx
    for profile_id, position_id, level in rows.values_list("employee_id", "position_id", "level"):
        result[profile_id][position_id] = level
    return result


@router.get("/locations/{location_id}/employees", response={200: list[EmployeeOut], 403: ErrorOut, 404: ErrorOut})
def location_employees(request, location_id: UUID):
    """People whose home location this is: active first, then switched off; by surname."""
    ctx, location, _ = _manage(request, Location, location_id)
    profiles = list(
        ctx.qs(EmployeeProfile)
        .filter(home_location=location)
        .select_related("membership__user")
        .order_by("-is_active", "membership__user__last_name", "membership__user__first_name")
    )
    positions = _position_ids(profiles)
    levels = _position_levels(profiles)
    drafts = _draft_shifts(ctx, profiles)
    return [
        _employee_out(p, positions[p.pk], levels[p.pk]).model_copy(update={"draft_shifts": drafts.get(p.pk, 0)})
        for p in profiles
    ]


def _closures_out(ctx: TenantContext, location: Location, closures=None) -> list[ClosureOut]:
    """Closed days, each saying whether a draft or the published schedule still has someone working that day.
    Past days are frozen (arranging again keeps them), so they never get the warning."""
    if closures is None:
        closures = list(ctx.qs(LocationClosure).filter(location=location).order_by("date"))
    worked = set(
        ctx.qs(Assignment)
        .filter(
            shift__location=location,
            shift__date__in=[c.date for c in closures],
            shift__date__gte=timezone.localdate(),
            shift__version__status__in=[ScheduleVersion.Status.DRAFT, ScheduleVersion.Status.PUBLISHED],
            employee__isnull=False,
        )
        .values_list("shift__date", "shift__version__status")
        .distinct()
    )
    return [
        ClosureOut(
            id=c.pk,
            date=c.date,
            note=c.note,
            in_draft=(c.date, ScheduleVersion.Status.DRAFT) in worked,
            in_published=(c.date, ScheduleVersion.Status.PUBLISHED) in worked,
        )
        for c in closures
    ]


def _draft_shifts(ctx: TenantContext, profiles) -> dict:
    """profile id -> number of shifts from today on in drafts (not yet published)."""
    rows = (
        ctx.qs(Assignment)
        .filter(
            employee__in=profiles,
            shift__version__status=ScheduleVersion.Status.DRAFT,
            shift__date__gte=timezone.localdate(),
        )
        .values("employee")
        .annotate(n=Count("pk"))
        .order_by()
    )
    return {row["employee"]: row["n"] for row in rows}


@router.post(
    "/locations/{location_id}/employees/me",
    response={200: EmployeeOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def add_myself_as_employee(request, location_id: UUID):
    """A manager who also works shifts adds themselves to the schedule of a location they manage, with every
    position of the location (they can stand in for anyone; positions can be narrowed afterwards)."""
    ctx, location, _ = _change(request, Location, location_id)
    with transaction.atomic():
        profile = ctx.qs(EmployeeProfile).select_related("home_location").filter(membership=ctx.membership).first()
        if profile is None:
            profile = EmployeeProfile.objects.for_company(ctx.company).create(
                company=ctx.company, membership=ctx.membership, home_location=location
            )
            profile.positions.set(ctx.qs(Position).filter(location=location))
        elif profile.home_location_id != location.pk:
            raise HttpError(
                409,
                f"Jesteś już pracownikiem lokalu {profile.home_location.name}. Pracownik ma jeden lokal domowy.",
            )
        elif profile.is_active:
            raise HttpError(409, "Jesteś już na liście pracowników tego lokalu.")
        else:
            profile.is_active = True
            profile.save(update_fields=["is_active"])
    profile = ctx.qs(EmployeeProfile).select_related("membership__user").get(pk=profile.pk)
    return _employee_out(profile, _position_ids([profile])[profile.pk], _position_levels([profile])[profile.pk])


def _changed_account(ctx: TenantContext, profile: EmployeeProfile, payload: EmployeeIn):
    """The person's account with the new name applied (not saved), or None when it does not change.

    The account is shared by every company the person works for, so nothing changes when the person also has
    another company."""
    user = profile.membership.user
    first = payload.first_name.strip() if payload.first_name is not None else user.first_name
    last = payload.last_name.strip() if payload.last_name is not None else user.last_name
    if (first, last) == (user.first_name, user.last_name):
        return None
    if not first:
        raise HttpError(400, "Wpisz imię.")
    if user.memberships.exclude(company=ctx.company).exists():  # tenant-ok: only checks other companies exist
        raise HttpError(409, "Ta osoba ma konto także w innej firmie, więc imię może zmienić tylko ona sama.")
    user.first_name, user.last_name = first, last
    return user


@router.patch(
    "/employees/{employee_id}",
    response={200: EmployeeOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
@transaction.atomic
def update_employee(request, employee_id: UUID, payload: EmployeeIn):
    """Name, positions, experience level, monthly maximum and target, or switching the person off
    (history stays)."""
    ctx, profile = context_for(request, EmployeeProfile, employee_id)
    profile = ctx.qs(EmployeeProfile).select_for_update().get(pk=profile.pk)
    ctx.require_manager_of(profile.home_location)
    ctx.require_writable()
    if payload.revision is not None:
        current = _employee_out(profile, _position_ids([profile])[profile.pk], _position_levels([profile])[profile.pk])
        if current.revision != payload.revision:
            raise HttpError(409, "Ktoś zmienił dane tej osoby. Zamknij formularz i otwórz go ponownie.")
    sent = payload.model_fields_set
    if "experience" in sent and payload.experience is not None:
        profile.experience = payload.experience
    if "max_hours_month" in sent:
        profile.max_hours_month = payload.max_hours_month
    if "target_hours_month" in sent:
        profile.target_hours_month = payload.target_hours_month
    if "is_active" in sent and payload.is_active is not None:
        profile.is_active = payload.is_active
    if (
        profile.max_hours_month is not None
        and profile.target_hours_month is not None
        and profile.target_hours_month > profile.max_hours_month
    ):
        raise HttpError(400, "Cel godzin nie może być większy niż maksimum.")
    user = _changed_account(ctx, profile, payload)
    with transaction.atomic():
        if user is not None:
            user.save(update_fields=["first_name", "last_name"])
        profile.save()
        if "position_ids" in sent and payload.position_ids is not None:
            positions = list(ctx.qs(Position).filter(pk__in=payload.position_ids, location=profile.home_location))
            if len(positions) != len(set(payload.position_ids)):
                raise HttpError(400, "Wybierz stanowiska z lokalu tej osoby.")
            profile.positions.set(positions)
        own = set(profile.positions.values_list("pk", flat=True))
        if "position_experience" in sent and payload.position_experience is not None:
            wanted = {item.position_id: item.experience for item in payload.position_experience}
            if not set(wanted) <= own:
                raise HttpError(400, "Stopień można ustawić tylko na stanowisku, na którym ta osoba pracuje.")
            ctx.qs(PositionExperience).filter(employee=profile).delete()
            for position_id, level in wanted.items():
                if level != profile.experience:  # only what differs from the default is kept
                    PositionExperience(employee=profile, position_id=position_id, level=level).save()
        # A level equal to the (possibly new) default, or for a position just taken away, is not kept.
        stale = ctx.qs(PositionExperience).filter(employee=profile)
        stale.exclude(position_id__in=own).delete()
        stale.filter(level=profile.experience).delete()
    profile = ctx.qs(EmployeeProfile).select_related("membership__user").get(pk=profile.pk)
    return _employee_out(profile, _position_ids([profile])[profile.pk], _position_levels([profile])[profile.pk])
