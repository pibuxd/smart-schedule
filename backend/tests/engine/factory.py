"""Small builders for engine tests (no database)."""

from datetime import date, time

from engine.problem import Employee, Problem, Slot, shift_bounds

LOC = "loc-1"
SALES = "sales"
BAKER = "baker"


def employee(
    id: str,
    *,
    positions: tuple[str, ...] = (SALES,),
    contract: str = "civil",
    home: str = LOC,
    **kwargs,
) -> Employee:
    return Employee(
        id=id,
        name=kwargs.pop("name", id.capitalize()),
        home_location=home,
        positions=frozenset(positions),
        contract=contract,
        **kwargs,
    )


def _t(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def slot(
    id: str,
    day: date,
    start: str = "06:00",
    end: str = "14:00",
    *,
    position: str = SALES,
    shift_type: str | None = None,
    location: str = LOC,
    closing: bool = False,
) -> Slot:
    begin, finish = shift_bounds(day, _t(start), _t(end))
    return Slot(
        id=id,
        location=location,
        date=day,
        shift_type=shift_type or f"{start}-{end}",
        position=position,
        start=begin,
        end=finish,
        shift_name="Zmiana",
        is_closing=closing,
    )


def problem(employees, slots, *, start: date | None = None, end: date | None = None, **kwargs) -> Problem:
    days = [s.date for s in slots] or [date(2026, 11, 2)]
    return Problem(
        period_start=start or min(days),
        period_end=end or max(days),
        employees=tuple(employees),
        slots=tuple(slots),
        **kwargs,
    )
