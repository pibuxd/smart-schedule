"""Location settings for the manager: positions, shifts and their hours, staffing per weekday with date
exceptions, and the location's employees (positions, hours, switched off)."""

from datetime import date, time
from typing import Literal
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError, RestrictedError
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.core.schemas import ErrorOut
from apps.staffing.models import (
    EmployeeProfile,
    Position,
    ShiftType,
    StaffingException,
    StaffingRule,
)
from apps.tenancy.context import TenantContext, context_for
from apps.tenancy.models import Location

router = Router(tags=["staffing"])

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
    start_time: time | None
    end_time: time | None


class StaffingExceptionIn(Schema):
    date: date
    shift_type_id: UUID
    position_id: UUID
    count: int = Field(ge=0, le=50)  # 0 = nobody that day (e.g. closed)
    start_time: time | None = None
    end_time: time | None = None
    note: str = Field("", max_length=200)


class StaffingExceptionOut(Schema):
    id: UUID
    date: date
    shift_type_id: UUID
    position_id: UUID
    count: int
    start_time: time | None
    end_time: time | None
    note: str


class LocationSetupOut(Schema):
    positions: list[PositionOut]
    shift_types: list[ShiftTypeOut]
    staffing: list[StaffingCellOut]
    exceptions: list[StaffingExceptionOut]


class EmployeeOut(Schema):
    id: UUID
    first_name: str
    last_name: str
    phone: str
    position_ids: list[UUID]
    experience: ExperienceLevel
    max_hours_month: int | None
    target_hours_month: int | None
    is_active: bool
    # True for the owner or a manager who also works shifts.
    is_manager: bool


class EmployeeIn(Schema):
    position_ids: list[UUID] | None = None
    experience: ExperienceLevel | None = None
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
                start_time=r.start_time,
                end_time=r.end_time,
            )
            for r in ctx.qs(StaffingRule).filter(location=location).order_by("weekday")
        ],
        exceptions=[
            _exception_out(e) for e in ctx.qs(StaffingException).filter(location=location).order_by("date", "pk")
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


def _in_location(ctx: TenantContext, model, pk, location: Location, what: str):
    obj = ctx.qs(model).filter(pk=pk, location=location).first()
    if obj is None:
        raise HttpError(400, f"Wybierz {what} z tego lokalu.")
    return obj


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


@router.delete(
    "/positions/{position_id}", response={204: None, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut}
)
def delete_position(request, position_id: UUID):
    """Also removes its staffing; refused when a schedule already uses it (history stays intact)."""
    _, position, _ = _change(request, Position, position_id)
    try:
        with transaction.atomic():
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
    _, st, _ = _change(request, ShiftType, shift_type_id)
    try:
        with transaction.atomic():
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
            start_time=start,
            end_time=end,
        )
    with transaction.atomic():
        ctx.qs(StaffingRule).filter(location=location).delete()
        for row in rows.values():
            row.save()
    return _setup_out(ctx, location)


@router.post(
    "/locations/{location_id}/staffing-exceptions",
    response={201: StaffingExceptionOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def create_staffing_exception(request, location_id: UUID, payload: StaffingExceptionIn):
    """A different staffing on one date (e.g. Christmas Eve), replacing the weekday's for that shift and position."""
    ctx, location, _ = _change(request, Location, location_id)
    st = _in_location(ctx, ShiftType, payload.shift_type_id, location, "zmianę")
    position = _in_location(ctx, Position, payload.position_id, location, "stanowisko")
    _check_hours(payload.start_time, payload.end_time, False, f"Zmiana „{st.name}”")
    exc = StaffingException(
        company=ctx.company,
        location=location,
        date=payload.date,
        shift_type=st,
        position=position,
        count=payload.count,
        start_time=payload.start_time,
        end_time=payload.end_time,
        note=payload.note.strip(),
    )
    _unique(exc.save, "Ten dzień ma już wyjątek dla tej zmiany i stanowiska. Usuń go i dodaj nowy.")
    return Status(201, _exception_out(exc))


@router.delete("/staffing-exceptions/{exception_id}", response={204: None, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut})
def delete_staffing_exception(request, exception_id: UUID):
    _, exc, _ = _change(request, StaffingException, exception_id)
    exc.delete()
    return Status(204, None)


# --------------------------------------------------------------------------------------------- employees


def _employee_out(profile: EmployeeProfile, position_ids: list) -> EmployeeOut:
    user = profile.membership.user
    return EmployeeOut(
        id=profile.pk,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone_e164,
        position_ids=position_ids,
        experience=profile.experience,
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
    return [_employee_out(p, positions[p.pk]) for p in profiles]


@router.patch(
    "/employees/{employee_id}",
    response={200: EmployeeOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut},
)
def update_employee(request, employee_id: UUID, payload: EmployeeIn):
    """Positions, experience level, monthly maximum and target, or switching the person off (history stays)."""
    ctx, profile = context_for(request, EmployeeProfile, employee_id)
    ctx.require_manager_of(profile.home_location)
    ctx.require_writable()
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
    with transaction.atomic():
        profile.save()
        if "position_ids" in sent and payload.position_ids is not None:
            positions = list(ctx.qs(Position).filter(pk__in=payload.position_ids, location=profile.home_location))
            if len(positions) != len(set(payload.position_ids)):
                raise HttpError(400, "Wybierz stanowiska z lokalu tej osoby.")
            profile.positions.set(positions)
    profile = ctx.qs(EmployeeProfile).select_related("membership__user").get(pk=profile.pk)
    return _employee_out(profile, _position_ids([profile])[profile.pk])
