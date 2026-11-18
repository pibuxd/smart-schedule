"""Staffing of one date: how it differs from the weekday's usual staffing.

A `StaffingException` row is kept only while the date really differs (people, experienced, or hours); setting a
date back to the usual numbers removes the row. Both the calendar in the location's settings and adding or
removing a place in the schedule editor write through here, so they always show the same thing."""

from datetime import date, time

from apps.staffing.models import Position, ShiftType, StaffingException, StaffingRule
from apps.tenancy.models import Location


def _usual(location: Location, day: date, shift_type: ShiftType, position: Position) -> StaffingRule | None:
    return (
        StaffingRule.objects.for_company(location.company_id)
        .filter(location=location, weekday=day.weekday(), shift_type=shift_type, position=position)
        .first()
    )


def _exception(location: Location, day: date, shift_type: ShiftType, position: Position) -> StaffingException | None:
    return (
        StaffingException.objects.for_company(location.company_id)
        .filter(location=location, date=day, shift_type=shift_type, position=position)
        .first()
    )


def day_hours(
    location: Location, day: date, shift_type: ShiftType, position: Position
) -> tuple[time | None, time | None]:
    """The hours this shift has on this date: the date's own, else the weekday's, else the shift type's."""
    for row in (_exception(location, day, shift_type, position), _usual(location, day, shift_type, position)):
        if row is not None and row.start_time is not None:
            return row.start_time, row.end_time
    return shift_type.start_time, shift_type.end_time


def day_experienced(location: Location, day: date, shift_type: ShiftType, position: Position) -> int:
    """How many people of this shift and position must be experienced on this date."""
    for row in (_exception(location, day, shift_type, position), _usual(location, day, shift_type, position)):
        if row is not None:
            return row.experienced
    return 0


def save_day_cell(
    location: Location,
    day: date,
    shift_type: ShiftType,
    position: Position,
    *,
    count: int,
    experienced: int,
    start: time | None = None,
    end: time | None = None,
    note: str = "",
) -> None:
    """Set what this date needs for one shift and position. Equal to the weekday's usual = no exception kept."""
    rule = _usual(location, day, shift_type, position)
    usual_count, usual_experienced = (rule.count, rule.experienced) if rule else (0, 0)
    usual_start = (rule.start_time if rule else None) or shift_type.start_time
    usual_end = (rule.end_time if rule else None) or shift_type.end_time
    if count == 0 or (start, end) == (usual_start, usual_end):
        start = end = None  # nothing to keep: nobody works, or the hours are the usual ones
    rows = StaffingException.objects.for_company(location.company_id).filter(
        location=location, date=day, shift_type=shift_type, position=position
    )
    if (count, experienced) == (usual_count, usual_experienced) and start is None:
        rows.delete()
        return
    values = {"count": count, "experienced": experienced, "start_time": start, "end_time": end, "note": note}
    if not rows.update(**values):
        StaffingException.objects.create(
            company_id=location.company_id,
            location=location,
            date=day,
            shift_type=shift_type,
            position=position,
            **values,
        )


def set_day_count(location: Location, day: date, shift_type: ShiftType, position: Position, count: int) -> None:
    """Change only the number of people on this date; hours, the note and the experienced quota stay (capped)."""
    exception = _exception(location, day, shift_type, position)
    base = exception or _usual(location, day, shift_type, position)
    save_day_cell(
        location,
        day,
        shift_type,
        position,
        count=count,
        experienced=min(base.experienced if base else 0, count),
        start=exception.start_time if exception else None,
        end=exception.end_time if exception else None,
        note=exception.note if exception else "",
    )
