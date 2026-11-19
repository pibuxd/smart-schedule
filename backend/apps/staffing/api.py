"""Location settings for the manager: positions, shifts and their hours, staffing per weekday with date
exceptions, and the location's employees (positions, hours, switched off)."""

import hashlib
import json
from datetime import date, time
from typing import Literal
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.core.schemas import ErrorOut
from apps.rules.models import RuleSetting
from apps.scheduling.models import Assignment, SchedulePeriod, ScheduleVersion, Shift
from apps.staffing import day_staffing, removal
from apps.staffing.models import (
    EmployeeProfile,
    LocationClosure,
    Position,
    PositionExperience,
    ShiftType,
    StaffingException,
    StaffingRule,
    works_in_q,
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
    # The person's main location. In the list of another location the person works there as an extra location
    # (`is_home` false); `position_ids` are then their positions in the listed location only.
    home_location_id: UUID | None = None
    home_location_name: str = ""
    is_home: bool = True
    # Shifts from today on in published schedules: removing the person leaves them on these shifts.
    published_shifts: int = 0
    # The person's other locations (main and extra, without the listed one): removing them from the listed location
    # keeps them there.
    other_location_names: list[str] = Field(default_factory=list)


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
    # The location whose list the manager edits the person in: positions and their levels change only there.
    # Left out: the person's main location.
    location_id: UUID | None = None


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
    if isinstance(obj, Position) and obj.removed_at is not None:
        raise HttpError(404, "Nie znaleziono.")
    return ctx, obj, location


def _positions(ctx: TenantContext, location: Location):
    """The location's positions without the removed ones (those live on only in old schedules)."""
    return ctx.qs(Position).filter(location=location, removed_at__isnull=True)


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
    positions = list(_positions(ctx, location).order_by("name"))
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
    """Also removes its staffing and takes it from people. A position that a saved schedule uses is kept hidden
    (old schedules still show its name), so the manager can always get rid of it."""
    ctx, position, _ = _change(request, Position, position_id)
    with transaction.atomic():
        _check_rule_references(ctx, position, "position")
        if not ctx.qs(Shift).filter(position=position).exists():
            position.delete()
        else:
            ctx.qs(StaffingRule).filter(position=position).delete()
            ctx.qs(StaffingException).filter(position=position).delete()
            ctx.qs(PositionExperience).filter(position=position).delete()
            position.employees.clear()
            position.removed_at = timezone.now()
            position.save(update_fields=["removed_at"])
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
    with transaction.atomic():
        _check_rule_references(ctx, st, "shift_type")
        st.delete()
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
    positions = {p.pk: p for p in _positions(ctx, location)}
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


def _employee_out(
    profile: EmployeeProfile,
    position_ids: list,
    levels: dict | None = None,
    location: Location | None = None,
    here: set | None = None,
) -> EmployeeOut:
    """`position_ids`: all of the person's positions (the revision covers them all). With `location`, only that
    location's positions are shown."""
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
    home = profile.home_location
    if location is not None:
        if here is None:
            positions = Position.objects.for_company(profile.company_id).filter(
                location=location, removed_at__isnull=True
            )
            here = set(positions.values_list("pk", flat=True))
        position_ids = [pid for pid in position_ids if pid in here]
    listed = location or home
    others = sorted(loc.name for loc in [home, *profile.extra_locations.all()] if loc.pk != listed.pk)
    return EmployeeOut(
        home_location_id=home.pk,
        home_location_name=home.name,
        is_home=location is None or location.pk == home.pk,
        other_location_names=others,
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
    """People who work in this location (as their main location or an extra one): active first, then switched
    off; by surname."""
    ctx, location, _ = _manage(request, Location, location_id)
    profiles = list(
        ctx.qs(EmployeeProfile)
        .filter(works_in_q(location), removed_at__isnull=True)
        .select_related("membership__user", "home_location")
        .prefetch_related("extra_locations")
        .order_by("-is_active", "membership__user__last_name", "membership__user__first_name")
    )
    positions = _position_ids(profiles)
    levels = _position_levels(profiles)
    drafts = _upcoming_shifts(ctx, profiles, ScheduleVersion.Status.DRAFT)
    published = _upcoming_shifts(ctx, profiles, ScheduleVersion.Status.PUBLISHED)
    here = set(_positions(ctx, location).values_list("pk", flat=True))
    return [
        _employee_out(p, positions[p.pk], levels[p.pk], location, here).model_copy(
            update={"draft_shifts": drafts.get(p.pk, 0), "published_shifts": published.get(p.pk, 0)}
        )
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


def _upcoming_shifts(ctx: TenantContext, profiles, status: str) -> dict:
    """profile id -> number of shifts from today on in drafts (not yet published) or in published schedules."""
    rows = (
        ctx.qs(Assignment)
        .filter(
            employee__in=profiles,
            shift__version__status=status,
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
            profile.positions.set(_positions(ctx, location))
        elif profile.removed_at is not None:
            removal.restore_employee(profile, location)
            profile.positions.set(_positions(ctx, location))
        elif not profile.works_in(location):
            # Working in another location already: this one becomes an extra location (docs/plan.md, section 27).
            profile.extra_locations.add(location)
            profile.positions.add(*_positions(ctx, location))
        elif profile.is_active:
            raise HttpError(409, "Jesteś już na liście pracowników tego lokalu.")
        else:
            profile.is_active = True
            profile.save(update_fields=["is_active"])
    profile = ctx.qs(EmployeeProfile).select_related("membership__user", "home_location").get(pk=profile.pk)
    return _employee_out(
        profile, _position_ids([profile])[profile.pk], _position_levels([profile])[profile.pk], location
    )


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
    profile = ctx.qs(EmployeeProfile).select_for_update().select_related("home_location").get(pk=profile.pk)
    location = profile.home_location
    if payload.location_id is not None and payload.location_id != location.pk:
        location = ctx.get(Location, pk=payload.location_id)
        if not profile.works_in(location):
            raise HttpError(404, "Ta osoba nie pracuje w tym lokalu.")
    ctx.require_manager_of(location)
    ctx.require_writable()
    if profile.removed_at is not None:
        raise HttpError(404, "Nie znaleziono.")
    if payload.revision is not None:
        current = _employee_out(profile, _position_ids([profile])[profile.pk], _position_levels([profile])[profile.pk])
        if current.revision != payload.revision:
            raise HttpError(409, "Ktoś zmienił dane tej osoby. Zamknij formularz i otwórz go ponownie.")
    sent = payload.model_fields_set
    # Experience, monthly hours and switching off are shared by all the person's locations: only the manager of
    # the main location changes them (the other locations' schedules depend on them too).
    shared = {
        "experience": payload.experience if payload.experience is not None else profile.experience,
        "max_hours_month": payload.max_hours_month,
        "target_hours_month": payload.target_hours_month,
        "is_active": payload.is_active if payload.is_active is not None else profile.is_active,
    }
    changed = {f for f, value in shared.items() if f in sent and value != getattr(profile, f)}
    if changed and location.pk != profile.home_location_id:
        raise HttpError(
            409,
            "Doświadczenie, godziny i wyłączenie z grafiku ustawia kierownik lokalu głównego tej osoby "
            f"({profile.home_location.name}).",
        )
    for field_name in changed:
        setattr(profile, field_name, shared[field_name])
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
        here = set(_positions(ctx, location).values_list("pk", flat=True))
        if "position_ids" in sent and payload.position_ids is not None:
            # Only this location's positions change; the person keeps their positions in other locations.
            positions = list(_positions(ctx, location).filter(pk__in=payload.position_ids))
            if len(positions) != len(set(payload.position_ids)):
                raise HttpError(400, "Wybierz stanowiska z lokalu tej osoby.")
            elsewhere = list(profile.positions.exclude(location=location))
            profile.positions.set([*elsewhere, *positions])
        own = set(profile.positions.values_list("pk", flat=True))
        if "position_experience" in sent and payload.position_experience is not None:
            wanted = {item.position_id: item.experience for item in payload.position_experience}
            if not set(wanted) <= own & here:
                raise HttpError(400, "Stopień można ustawić tylko na stanowisku, na którym ta osoba pracuje.")
            ctx.qs(PositionExperience).filter(employee=profile, position__location=location).delete()
            for position_id, level in wanted.items():
                if level != profile.experience:  # only what differs from the default is kept
                    PositionExperience(employee=profile, position_id=position_id, level=level).save()
        # A level equal to the (possibly new) default, or for a position just taken away, is not kept.
        stale = ctx.qs(PositionExperience).filter(employee=profile)
        stale.exclude(position_id__in=own).delete()
        stale.filter(level=profile.experience).delete()
    profile = ctx.qs(EmployeeProfile).select_related("membership__user", "home_location").get(pk=profile.pk)
    return _employee_out(
        profile, _position_ids([profile])[profile.pk], _position_levels([profile])[profile.pk], location
    )


@router.delete(
    "/employees/{employee_id}", response={204: None, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut}
)
def remove_employee(request, employee_id: UUID, location_id: UUID | None = None):
    """Remove the person from a location (`location_id`, by default their main one). From their only location
    it is for good: shifts in saved schedules and their hours stay; a plain employee loses access to the company
    and can come back only through a new invitation. From one of several locations only that location goes; the
    person keeps working in the others (docs/plan.md, section 27)."""
    ctx, profile = context_for(request, EmployeeProfile, employee_id)
    location = ctx.get(Location, pk=location_id) if location_id else profile.home_location
    ctx.require_manager_of(location)
    ctx.require_writable()
    if profile.removed_at is not None or not profile.works_in(location):
        raise HttpError(404, "Nie znaleziono.")
    if profile.extra_locations.exists():
        removal.leave_location(profile, location)
    else:
        removal.remove_employee(profile)
    return Status(204, None)
