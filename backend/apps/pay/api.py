"""Rates and supplements for the manager (docs/plan.md, section 35): position rates and people's own rates on a
position, each from a day on, and supplements for hours at a time of day. Only the location's managers read or
change them; the pay itself is in "Mój grafik" and "Godziny" (`apps.pay.services`)."""

from datetime import date, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from uuid import UUID

from django.db import transaction
from django.db.models import F
from ninja import Field, Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from apps.core.schemas import ErrorOut
from apps.pay.models import PaySupplement, PersonalRate, PositionRate
from apps.staffing.models import EmployeeProfile, Position
from apps.tenancy.context import TenantContext, context_for
from apps.tenancy.models import Location

router = Router(tags=["pay"])

GROSZ = Decimal("0.01")
MAX_AMOUNT = Decimal(10_000)
BAD_RATE = "Stawka za godzinę to kwota w złotych większa od zera, np. 31,40."
BAD_AMOUNT = "Dodatek to kwota w złotych większa od zera, np. 6,00."
BAD_PERCENT = "Dodatek w procentach to liczba od 1 do 1000, np. 20."
NOT_THEIR_POSITION = "Własną stawkę można ustawić tylko na stanowisku, na którym ta osoba pracuje."
FIRST = F("valid_from").asc(nulls_first=True)


class RateIn(Schema):
    # Złoty an hour; null = no rate from that day (a position) or the position's rate again (a person).
    hourly_rate: float | None = None
    # The first day the rate counts; null = from the start (the first rate, for every shift).
    valid_from: date | None = None


class PersonalRateIn(RateIn):
    position_id: UUID


class RateStepOut(Schema):
    id: UUID
    valid_from: date | None
    hourly_rate: float | None


class PositionRatesOut(Schema):
    position_id: UUID
    name: str
    rates: list[RateStepOut]


class PersonalRateOut(RateStepOut):
    employee_id: UUID
    position_id: UUID


SupplementKind = Literal["amount", "percent"]


class SupplementIn(Schema):
    name: str = Field(min_length=1, max_length=60)
    start_time: time
    # At or before `start_time` = past midnight; the same time = the whole day.
    end_time: time
    weekdays: list[int]  # 0 = Monday … 6 = Sunday
    kind: SupplementKind = "amount"
    # Złoty an hour (`amount`) or percent of the shift's rate (`percent`).
    value: float
    all_positions: bool = True
    position_ids: list[UUID] = Field(default_factory=list)
    # Only when adding: the first day it counts; null = for every shift.
    valid_from: date | None = None


class SupplementChangeIn(SupplementIn):
    # A new amount, hours, days or positions count from this day; the supplement keeps the old ones before it.
    change_from: date | None = None


class SupplementOut(Schema):
    id: UUID
    name: str
    start_time: time
    end_time: time
    weekdays: list[int]
    kind: SupplementKind
    value: float
    all_positions: bool
    position_ids: list[UUID]
    valid_from: date | None
    valid_until: date | None


class PaySettingsOut(Schema):
    positions: list[PositionRatesOut]
    supplements: list[SupplementOut]


# ------------------------------------------------------------------------------------------------ helpers


def _manage(request, model, object_id) -> tuple[TenantContext, object, Location]:
    ctx, obj = context_for(request, model, object_id)
    location = obj if isinstance(obj, Location) else obj.location
    ctx.require_manager_of(location)
    return ctx, obj, location


def _money(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _amount(value: float | None, low: Decimal, high: Decimal, message: str) -> Decimal | None:
    if value is None:
        return None
    exact = Decimal(str(value))
    if not exact.is_finite() or exact > high:
        raise HttpError(400, message)
    exact = exact.quantize(GROSZ, rounding=ROUND_HALF_UP)
    if exact < low:
        raise HttpError(400, message)
    return exact


def _rate(value: float | None) -> Decimal | None:
    return _amount(value, GROSZ, MAX_AMOUNT, BAD_RATE)


def _step_out(step) -> RateStepOut:
    return RateStepOut(id=step.pk, valid_from=step.valid_from, hourly_rate=_money(step.hourly_rate))


def _position_rates_out(ctx: TenantContext, position: Position) -> PositionRatesOut:
    steps = ctx.qs(PositionRate).filter(position=position).order_by(FIRST)
    return PositionRatesOut(position_id=position.pk, name=position.name, rates=[_step_out(s) for s in steps])


def _personal_out(step: PersonalRate) -> PersonalRateOut:
    return PersonalRateOut(
        id=step.pk,
        employee_id=step.employee_id,
        position_id=step.position_id,
        valid_from=step.valid_from,
        hourly_rate=_money(step.hourly_rate),
    )


def _supplement_out(s: PaySupplement) -> SupplementOut:
    return SupplementOut(
        id=s.pk,
        name=s.name,
        start_time=s.start_time,
        end_time=s.end_time,
        weekdays=s.weekday_list(),
        kind=s.kind,
        value=float(s.value),
        all_positions=s.all_positions,
        position_ids=[] if s.all_positions else sorted((p.pk for p in s.positions.all()), key=str),
        valid_from=s.valid_from,
        valid_until=s.valid_until,
    )


def _live_position(ctx: TenantContext, position_id) -> Position:
    return ctx.get(Position, pk=position_id, removed_at__isnull=True)


# ------------------------------------------------------------------------------------------------ settings


@router.get("/locations/{location_id}/pay-settings", response={200: PaySettingsOut, 403: ErrorOut, 404: ErrorOut})
def pay_settings(request, location_id: UUID):
    """The location's positions with their rates by day, and its supplements (also ended ones, with dates)."""
    ctx, location, _ = _manage(request, Location, location_id)
    positions = list(ctx.qs(Position).filter(location=location, removed_at__isnull=True).order_by("name"))
    steps: dict = {p.pk: [] for p in positions}
    for step in ctx.qs(PositionRate).filter(position__in=positions).order_by("position_id", FIRST):
        steps[step.position_id].append(_step_out(step))
    supplements = ctx.qs(PaySupplement).filter(location=location).prefetch_related("positions")
    return PaySettingsOut(
        positions=[PositionRatesOut(position_id=p.pk, name=p.name, rates=steps[p.pk]) for p in positions],
        supplements=[_supplement_out(s) for s in supplements.order_by(FIRST, "start_time", "name")],
    )


# ------------------------------------------------------------------------------------------------ position rates


@router.post(
    "/positions/{position_id}/rates",
    response={200: PositionRatesOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut},
)
def set_position_rate(request, position_id: UUID, payload: RateIn):
    """The position's rate from `valid_from` on (a step on the same day is replaced). Shifts before that day keep
    the rate they had."""
    ctx, position, _ = _manage(request, Position, position_id)
    ctx.require_writable()
    if position.removed_at is not None:
        raise HttpError(404, "Nie znaleziono.")
    rate = _rate(payload.hourly_rate)
    with transaction.atomic():
        ctx.qs(PositionRate).update_or_create(
            position=position,
            valid_from=payload.valid_from,
            defaults={"hourly_rate": rate},
        )
    return _position_rates_out(ctx, position)


@router.delete(
    "/position-rates/{rate_id}", response={200: PositionRatesOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut}
)
def delete_position_rate(request, rate_id: UUID):
    """Removes one step (e.g. a mistake): the step before it counts again until the next one."""
    ctx, step = context_for(request, PositionRate, rate_id)
    ctx.require_manager_of(step.position.location)
    ctx.require_writable()
    step.delete()
    return _position_rates_out(ctx, step.position)


# ------------------------------------------------------------------------------------------------ own rates


@router.get(
    "/locations/{location_id}/personal-rates", response={200: list[PersonalRateOut], 403: ErrorOut, 404: ErrorOut}
)
def personal_rates(request, location_id: UUID):
    """People's own rates on this location's positions, by day."""
    ctx, location, _ = _manage(request, Location, location_id)
    steps = ctx.qs(PersonalRate).filter(position__location=location).order_by("employee_id", "position_id", FIRST)
    return [_personal_out(s) for s in steps]


@router.post(
    "/employees/{employee_id}/rates",
    response={200: list[PersonalRateOut], 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut},
)
def set_personal_rate(request, employee_id: UUID, payload: PersonalRateIn):
    """The person's own rate on one of their positions from `valid_from` on, e.g. a raise for a longer record.
    Returns the person's steps on that position."""
    ctx, profile = context_for(request, EmployeeProfile, employee_id)
    if profile.removed_at is not None:
        raise HttpError(404, "Nie znaleziono.")
    position = _live_position(ctx, payload.position_id)
    ctx.require_manager_of(position.location)
    ctx.require_writable()
    if not profile.positions.filter(pk=position.pk).exists():
        raise HttpError(400, NOT_THEIR_POSITION)
    rate = _rate(payload.hourly_rate)
    with transaction.atomic():
        ctx.qs(PersonalRate).update_or_create(
            employee=profile,
            position=position,
            valid_from=payload.valid_from,
            defaults={"hourly_rate": rate},
        )
    steps = ctx.qs(PersonalRate).filter(employee=profile, position=position).order_by(FIRST)
    return [_personal_out(s) for s in steps]


@router.delete("/personal-rates/{rate_id}", response={204: None, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut})
def delete_personal_rate(request, rate_id: UUID):
    ctx, step = context_for(request, PersonalRate, rate_id)
    ctx.require_manager_of(step.position.location)
    ctx.require_writable()
    step.delete()
    return Status(204, None)


# ------------------------------------------------------------------------------------------------ supplements


def _supplement_values(ctx: TenantContext, location: Location, payload: SupplementIn) -> dict:
    name = payload.name.strip()
    if not name:
        raise HttpError(400, "Podaj nazwę dodatku.")
    days = set(payload.weekdays)
    if not days or not days <= set(range(7)):
        raise HttpError(400, "Wybierz co najmniej jeden dzień tygodnia.")
    if payload.kind == PaySupplement.Kind.PERCENT:
        value = _amount(payload.value, Decimal(1), Decimal(1000), BAD_PERCENT)
    else:
        value = _amount(payload.value, GROSZ, MAX_AMOUNT, BAD_AMOUNT)
    positions: list = []
    if not payload.all_positions:
        wanted = set(payload.position_ids)
        positions = list(ctx.qs(Position).filter(location=location, removed_at__isnull=True, pk__in=wanted))
        if not wanted:
            raise HttpError(400, "Wybierz stanowiska, których dotyczy dodatek.")
        if len(positions) != len(wanted):
            raise HttpError(400, "Dodatek może dotyczyć tylko stanowisk tego lokalu.")
    return {
        "name": name,
        "start_time": payload.start_time.replace(second=0, microsecond=0),
        "end_time": payload.end_time.replace(second=0, microsecond=0),
        "weekdays": sum(1 << day for day in days),
        "kind": payload.kind,
        "value": value,
        "all_positions": payload.all_positions,
        "positions": positions,
    }


def _pay_terms(values: dict) -> tuple:
    """What changes the pay (everything but the name)."""
    positions = frozenset(p.pk for p in values["positions"])
    return (values["start_time"], values["end_time"], values["weekdays"], values["kind"], values["value"],
            values["all_positions"], positions)  # fmt: skip


def _save_supplement(supplement: PaySupplement, values: dict) -> PaySupplement:
    for field, value in values.items():
        if field != "positions":
            setattr(supplement, field, value)
    supplement.save()
    supplement.positions.set(values["positions"])
    return supplement


@router.post(
    "/locations/{location_id}/supplements",
    response={201: SupplementOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut},
)
def create_supplement(request, location_id: UUID, payload: SupplementIn):
    """A new supplement, e.g. nights 22:00–06:00 +6 zł an hour, from `valid_from` (null = for every shift)."""
    ctx, location, _ = _manage(request, Location, location_id)
    ctx.require_writable()
    values = _supplement_values(ctx, location, payload)
    with transaction.atomic():
        supplement = PaySupplement(company=ctx.company, location=location, valid_from=payload.valid_from)
        _save_supplement(supplement, values)
    return Status(201, _supplement_out(supplement))


@router.patch(
    "/supplements/{supplement_id}",
    response={200: SupplementOut, 400: ErrorOut, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut},
)
def update_supplement(request, supplement_id: UUID, payload: SupplementChangeIn):
    """A new name changes in place. Other changes count from `change_from`: the supplement ends the day before and
    a new one starts with the changes, so earlier shifts keep what they had (unless it starts on that day or later,
    then it changes in place). Returns the supplement that counts from `change_from`."""
    ctx, supplement, location = _manage(request, PaySupplement, supplement_id)
    ctx.require_writable()
    values = _supplement_values(ctx, location, payload)
    now = {
        "start_time": supplement.start_time,
        "end_time": supplement.end_time,
        "weekdays": supplement.weekdays,
        "kind": supplement.kind,
        "value": supplement.value,
        "all_positions": supplement.all_positions,
        "positions": [] if supplement.all_positions else list(supplement.positions.all()),
    }
    day = payload.change_from
    with transaction.atomic():
        if _pay_terms(values) == _pay_terms(now):
            supplement.name = values["name"]
            supplement.save(update_fields=["name"])
            return _supplement_out(supplement)
        if day is None:
            raise HttpError(400, "Podaj, od którego dnia liczy się zmiana dodatku.")
        if supplement.valid_until is not None and day > supplement.valid_until:
            raise HttpError(400, "Ten dodatek kończy się przed tym dniem.")
        if supplement.valid_from is not None and day <= supplement.valid_from:
            return _supplement_out(_save_supplement(supplement, values))
        until = supplement.valid_until
        supplement.valid_until = day - timedelta(days=1)
        supplement.save(update_fields=["valid_until"])
        changed = PaySupplement(company=ctx.company, location=location, valid_from=day, valid_until=until)
        return _supplement_out(_save_supplement(changed, values))


@router.delete("/supplements/{supplement_id}", response={204: None, 402: ErrorOut, 403: ErrorOut, 404: ErrorOut})
def end_supplement(request, supplement_id: UUID, end_from: date | None = None):
    """No supplement from `end_from` on; shifts before keep it. Without a day, or when it would only start on that
    day or later, the supplement is deleted."""
    ctx, supplement, _ = _manage(request, PaySupplement, supplement_id)
    ctx.require_writable()
    if end_from is None or (supplement.valid_from is not None and end_from <= supplement.valid_from):
        supplement.delete()
    elif supplement.valid_until is None or end_from <= supplement.valid_until:
        supplement.valid_until = end_from - timedelta(days=1)
        supplement.save(update_fields=["valid_until"])
    return Status(204, None)
